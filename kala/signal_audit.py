"""
Honest scorecard for any stock-signal service — including your own.

WHY THIS EXISTS
---------------
A signal service controls its own win-rate numerator AND denominator. It
decides which calls become "signals" (the confident ones) and which get
quietly parked as "watchlist" (the shaky ones — never counted). A losing
position doesn't dent the win rate until it finally stops out, so a pile of
open, underwater trades can sit invisibly behind a "100% win" headline. And
the take-profit percentages in the ad are quoted GROSS — before IDX's
asymmetric fees and the bid/ask spread you actually cross.

This module grades a signal log the same way ``walkforward`` grades your own
strategy, with none of those escape hatches:

  * EV PER TRADE is the headline, not win rate. A 90%-win book of tiny TPs
    and rare-but-huge stops is a losing book; win rate hides that, EV doesn't.
  * REAL COSTS on both legs (``CostModel``): the buy fee + spread on entry,
    the sell fee + tax + spread on exit. The +5.3% "average gain" is measured
    net, the way your wallet measures it.
  * EVERY signal counts. A call that never hit TP or SL is EXPIRED (marked to
    market) or OPEN (still running, marked to market) — not dropped. A call
    whose entry never triggered is NO_FILL — reported, because a service that
    quotes entries that rarely fill is itself a finding.
  * BENCHMARK-RELATIVE. Every resolved trade is also scored against what IHSG
    did over the same holding days (reuses the alpha idea from walkforward):
    "did this call beat just holding the index, or did it ride the index up?"
  * PESSIMISTIC on ambiguity. When a single bar's range covers BOTH the take
    profit and the stop loss, we cannot know which was touched first intraday,
    so we assume the STOP. That one rule is what stops this auditor from
    flattering a service the way the service flatters itself.

USED FORWARD, IT CANNOT BE GAMED. Log each signal when it is PUBLISHED
(ticker, date, entry, TP, SL) — before you know the outcome — then resolve it
against real price history. Because YOU own the log, the service can't pick
the denominator. Auditing a service's own curated "history" only tells you
whether their hand-picked winners survive honest costs (still useful — often
they don't); forward-logging tells you the truth.

DESIGN (mirrors the rest of the repo): pure logic, no network. Callers pass
``{ticker: OHLCV}`` and an optional benchmark frame; a thin CLI wrapper does
the fetching. Point-in-time discipline: an EOD signal is acted on the NEXT
bar, never the bar it was published on.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .config import Config
from .walkforward import trade_stats

# Signal lifecycle statuses.
_FILLED = ("TP_HIT", "SL_HIT", "EXPIRED", "OPEN")   # carry a net return
_UNFILLED = ("NO_FILL", "NO_DATA")                   # never became a position


@dataclass
class Signal:
    """One published call. ``date`` is the publication date (acted on the NEXT
    bar — no same-bar look-ahead). Entry is treated as a limit: you get in only
    if price trades down to it within ``fill_window_bars``."""
    ticker: str
    date: object
    entry: float
    take_profit: float
    stop_loss: float


@dataclass
class SignalResult:
    signal: Signal
    status: str
    entry_fill: float | None = None      # cost-inclusive price actually paid
    exit_fill: float | None = None       # cost-inclusive proceeds received
    entry_date: object = None
    exit_date: object = None
    net_return_pct: float | None = None  # net of costs; None only when unfilled
    bars_held: int = 0
    benchmark_return_pct: float | None = None

    @property
    def excess_return_pct(self) -> float | None:
        if self.net_return_pct is None or self.benchmark_return_pct is None:
            return None
        return self.net_return_pct - self.benchmark_return_pct


def resolve_signal(signal: Signal, df: pd.DataFrame, cfg: Config,
                   fill_window_bars: int = 3, max_hold_bars: int = 20,
                   benchmark: pd.DataFrame | None = None) -> SignalResult:
    """Play one signal forward through real price history, honestly.

    Entry is a limit order active for ``fill_window_bars`` bars starting the
    bar AFTER publication; it fills at ``entry`` (cost-adjusted) the first bar
    that trades at/below it, else NO_FILL. Once filled, each bar is checked
    stop-first (ties → stop). Neither hit within ``max_hold_bars`` → EXPIRED at
    that bar's close; ran out of data first → OPEN. Both marked to market.
    """
    costs = cfg.costs
    idx = df.index
    pub = pd.Timestamp(signal.date)
    start = int(idx.searchsorted(pub, side="right"))   # strictly after pub bar
    if start >= len(df):
        return SignalResult(signal, "OPEN")            # published, no data yet

    # 1) entry as a limit: first bar (within the window) whose low reaches it
    fill_i = None
    for i in range(start, min(start + fill_window_bars, len(df))):
        if float(df["Low"].iloc[i]) <= signal.entry:
            fill_i = i
            break
    if fill_i is None:
        return SignalResult(signal, "NO_FILL")

    entry_fill = signal.entry * costs.buy_multiplier(signal.entry)
    entry_date = idx[fill_i]

    # 2) resolve TP/SL, stop-first on any bar whose range covers both
    end_i = min(fill_i + max_hold_bars, len(df) - 1)
    for j in range(fill_i, end_i + 1):
        low = float(df["Low"].iloc[j])
        high = float(df["High"].iloc[j])
        if low <= signal.stop_loss:                    # pessimism: stop wins ties
            exit_fill = signal.stop_loss * costs.sell_multiplier(signal.stop_loss)
            return _finish(signal, "SL_HIT", entry_fill, exit_fill,
                           entry_date, idx[j], j - fill_i, benchmark)
        if high >= signal.take_profit:
            exit_fill = signal.take_profit * costs.sell_multiplier(signal.take_profit)
            return _finish(signal, "TP_HIT", entry_fill, exit_fill,
                           entry_date, idx[j], j - fill_i, benchmark)

    # 3) neither triggered: EXPIRED if the full window elapsed, else still OPEN
    ran_out = (fill_i + max_hold_bars) > (len(df) - 1)
    close = float(df["Close"].iloc[end_i])
    exit_fill = close * costs.sell_multiplier(close)
    return _finish(signal, "OPEN" if ran_out else "EXPIRED", entry_fill,
                   exit_fill, entry_date, idx[end_i], end_i - fill_i, benchmark)


def _finish(signal, status, entry_fill, exit_fill, entry_date, exit_date,
            bars_held, benchmark) -> SignalResult:
    net = (exit_fill / entry_fill - 1.0) * 100.0
    bench = None
    if benchmark is not None and len(benchmark) >= 2:
        b = benchmark["Close"]
        b_entry = b.asof(pd.Timestamp(entry_date))
        b_exit = b.asof(pd.Timestamp(exit_date))
        if pd.notna(b_entry) and pd.notna(b_exit) and float(b_entry) > 0:
            bench = (float(b_exit) / float(b_entry) - 1.0) * 100.0
    return SignalResult(signal, status, entry_fill, exit_fill, entry_date,
                        exit_date, net, bars_held, bench)


@dataclass
class AuditReport:
    results: list[SignalResult]
    filled: dict                      # trade_stats over net returns of filled signals
    excess: dict = field(default_factory=dict)   # trade_stats over benchmark-excess
    status_counts: dict = field(default_factory=dict)

    @property
    def n_signals(self) -> int:
        return len(self.results)

    def summary_text(self, service: str = "signal service") -> str:
        s = self.filled
        sc = self.status_counts
        n_filled = s["n"]
        lines = [f"SIGNAL AUDIT — {service}, scored net of real IDX costs",
                 "=" * 62,
                 f"signals logged: {self.n_signals}"]
        never = sc.get("NO_FILL", 0) + sc.get("NO_DATA", 0)
        if never:
            lines.append(f"  never became a position: {never} "
                         f"(NO_FILL {sc.get('NO_FILL', 0)}, NO_DATA {sc.get('NO_DATA', 0)}) "
                         f"— entry never triggered / no price data")
        lines.append(f"  resolved as positions: {n_filled} "
                     f"(TP {sc.get('TP_HIT', 0)}, SL {sc.get('SL_HIT', 0)}, "
                     f"expired {sc.get('EXPIRED', 0)}, still open {sc.get('OPEN', 0)})")
        lines.append("-" * 62)
        if n_filled == 0:
            lines.append("No positions to score.")
            return "\n".join(lines)
        lines.append(f"EV/trade (net):   {s['ev_pct']:+.2f}%   "
                     f"t={s['t_stat']:.2f}   (THE headline — beats win rate)")
        lines.append(f"win rate:         {s['win_rate_pct']:.0f}%   "
                     f"median {s['median_pct']:+.2f}%   PF {s['profit_factor']:.2f}")
        lines.append(f"compounded:       {s['total_compounded_pct']:+.1f}% "
                     f"over {n_filled} trades")
        if self.excess.get("n", 0) > 0:
            e = self.excess
            lines.append(f"vs holding IHSG:  {e['ev_pct']:+.2f}%/trade excess   "
                         f"t={e['t_stat']:.2f}   (did it beat the index, or ride it?)")
        lines.append("-" * 62)
        lines.append("VERDICT: " + _audit_verdict(s, self.excess))
        return "\n".join(lines)


def _audit_verdict(filled: dict, excess: dict) -> str:
    n, ev, t = filled.get("n", 0), filled.get("ev_pct", 0.0), filled.get("t_stat", 0.0)
    if n < 30:
        return (f"INCONCLUSIVE — only {n} resolved trade(s). A high win rate on "
                f"a handful of calls is noise; log more before believing anything.")
    exc_ev = excess.get("ev_pct", 0.0) if excess.get("n", 0) > 0 else None
    if ev <= 0:
        return ("NEGATIVE net of costs — whatever the ad's win rate, these calls "
                "lose money after real fees and spread. This is the number that matters.")
    if exc_ev is not None and exc_ev <= 0:
        return ("POSITIVE vs cash but NOT vs the index — the calls made money only "
                "because the market rose; holding IHSG would have done as well with "
                "less risk. That's beta, not skill.")
    if t >= 2.0:
        return ("POSITIVE and statistically distinguishable from 0, net of costs and "
                "vs the index. Rare. Keep logging — one clean window isn't proof, "
                "but this one earned a closer look.")
    return ("POSITIVE but WEAK (t < 2) — could be a good streak. Keep the forward "
            "log running before paying for or trading on it.")


def audit_signals(signals: list[Signal], dfs: dict[str, pd.DataFrame],
                  cfg: Config | None = None,
                  benchmark: pd.DataFrame | None = None,
                  fill_window_bars: int = 3,
                  max_hold_bars: int = 20) -> AuditReport:
    """Resolve every signal against its ticker's price history and pool the
    honest stats. ``dfs`` maps ticker -> OHLCV; a signal whose ticker is
    missing is recorded NO_DATA (counted, never silently dropped)."""
    cfg = cfg or Config()
    results: list[SignalResult] = []
    for sig in signals:
        df = dfs.get(sig.ticker)
        if df is None or len(df) < 2:
            results.append(SignalResult(sig, "NO_DATA"))
            continue
        results.append(resolve_signal(sig, df, cfg, fill_window_bars,
                                       max_hold_bars, benchmark))

    status_counts: dict[str, int] = {}
    for r in results:
        status_counts[r.status] = status_counts.get(r.status, 0) + 1

    filled_returns = [r.net_return_pct for r in results
                      if r.status in _FILLED and r.net_return_pct is not None]
    excess_returns = [r.excess_return_pct for r in results
                      if r.status in _FILLED and r.excess_return_pct is not None]

    return AuditReport(results=results,
                       filled=trade_stats(filled_returns),
                       excess=trade_stats(excess_returns),
                       status_counts=status_counts)
