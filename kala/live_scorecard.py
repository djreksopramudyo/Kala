"""
Live scorecard — the alpha check, applied to REAL trades instead of history.

WHY THIS IS DIFFERENT FROM EVERY BACKTEST IN THIS PROJECT
-----------------------------------------------------------
Fourteen hypotheses were tested here on historical data and none survived an
honest alpha check (see PROJECT_STATUS.md). This module asks the same
question of the trades that were ACTUALLY placed with real money: for each
position, did it beat simply holding the benchmark over that position's own
holding window?

That "over its own holding window" part is the whole point, and it is the
same discipline `kala.walkforward`'s ``excess_returns`` enforces. Comparing a
trade's raw return to zero flatters every trade taken in a rising market;
comparing it to what the benchmark did over exactly the same days is what
separates "I picked well" from "I was invested while everything went up."

WHAT THIS CANNOT TELL YOU — READ BEFORE ACTING ON IT
------------------------------------------------------
**A few weeks of trading is not evidence.** The backtests that found nothing
used thousands of trades; a live book of ~20 positions over ~3 weeks has no
statistical power whatsoever. A positive number here does NOT mean the
strategy works, and a negative one does not prove it is broken. Sequence luck
dominates at this sample size: one lucky or unlucky name moves the whole
figure.

What it IS good for: catching a large, obvious divergence early (e.g. every
position underwater against the benchmark), sanity-checking that recorded
trades match reality, and building the habit of judging results against a
benchmark rather than against zero. Treat it as a dashboard, not a verdict.
The formatter states this on every run rather than leaving it to be inferred.

COSTS
-----
Returns here are gross of transaction costs unless ``cost_rate`` is supplied.
Real IDX round-trip friction (commission both ways plus the sell-side final
tax plus spread) is roughly 0.5-0.8% for liquid names — material against the
kind of few-percent moves this measures, so the CLI passes the project's own
cost model rather than flattering the result with a frictionless comparison.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from kala.config import CostModel


def round_trip_cost() -> float:
    """Approximate IDR round-trip friction from the project's own cost model:
    buy commission + sell total (commission + final tax) + a full spread.

    Lives here rather than in the CLI so the weekly Telegram scorecard and the
    command line charge the SAME friction — two copies of this formula would
    quietly diverge and make the two reports disagree.
    """
    c = CostModel()
    return c.buy_commission + c.sell_total + 2 * c.half_spread


def fetch_benchmark(ticker: str, period: str = "1y") -> "pd.Series | None":
    """Download the benchmark's close history, or None if unavailable.

    yfinance hands back a single-column DataFrame for a one-ticker download
    in some versions and a Series in others; the caller wants a Series either
    way. That quirk is handled here once so the CLI and the weekly Telegram
    report cannot drift apart on it.

    Network import is function-local to keep this module importable (and its
    pure scoring logic testable) without yfinance present.
    """
    import yfinance as yf

    try:
        raw = yf.download(ticker, period=period, auto_adjust=True, progress=False)
    except Exception as e:
        from kala.logging_util import log_swallowed
        log_swallowed(f"fetch_benchmark({ticker})", e)
        return None
    if raw is None or not len(raw):
        return None
    bench = raw["Close"].dropna()
    if hasattr(bench, "columns"):          # single-ticker frame quirk
        bench = bench.iloc[:, 0]
    return bench if len(bench) else None


@dataclass(frozen=True)
class TradeScore:
    ticker: str
    entry_date: str
    shares: float
    entry_price: float
    current_price: float          # exit price for closed trades
    is_open: bool
    value_at_cost: float
    pnl_idr: float                # net of cost_rate if supplied
    return_pct: float
    benchmark_return_pct: float   # benchmark over this trade's OWN window
    excess_pct: float             # return_pct - benchmark_return_pct
    note: str = ""                # e.g. why benchmark couldn't be computed


@dataclass(frozen=True)
class Scorecard:
    trades: tuple = field(default_factory=tuple)
    benchmark: str = ""
    n_open: int = 0
    n_closed: int = 0
    total_cost_basis: float = 0.0
    total_pnl_idr: float = 0.0
    total_return_pct: float = 0.0
    benchmark_equivalent_pct: float = 0.0   # cost-weighted benchmark over the same windows
    excess_pct: float = 0.0
    n_beat_benchmark: int = 0
    cost_rate: float = 0.0
    note: str = ""
    # --- significance of the per-trade excess (see _significance) -------------
    mean_excess_per_trade: float = 0.0      # EQUAL-weighted; can disagree in sign
    excess_std: float = 0.0                 # with the cost-weighted excess_pct
    t_stat: float = 0.0
    ci_low: float = 0.0
    ci_high: float = 0.0
    is_significant: bool = False
    trades_needed: float = 0.0              # to resolve an edge of the observed size


# Two-sided 95% t critical values. Small-n values matter here: using 1.96 at
# n=21 would overstate confidence, which is the exact error this module exists
# to prevent.
_T95 = {2: 12.71, 3: 4.30, 4: 3.18, 5: 2.78, 6: 2.57, 7: 2.45, 8: 2.36, 9: 2.31,
        10: 2.26, 11: 2.23, 12: 2.20, 13: 2.18, 14: 2.16, 15: 2.14, 16: 2.13,
        17: 2.12, 18: 2.11, 19: 2.10, 20: 2.09, 21: 2.09, 22: 2.08, 25: 2.06,
        30: 2.05, 40: 2.02, 60: 2.00, 120: 1.98}


def _t_crit(n: int) -> float:
    if n < 2:
        return float("inf")
    for k in sorted(_T95):
        if n <= k:
            return _T95[k]
    return 1.96


def _significance(excesses: list[float]) -> dict:
    """One-sample t-test of per-trade excess against zero, plus the sample size
    that WOULD be needed to resolve an edge of the observed magnitude.

    This is deliberately equal-weighted, unlike the headline ``excess_pct``
    which is cost-weighted. The two can disagree in sign — and when they do,
    that is worth knowing: it means the headline is being driven by which
    positions happened to be large, not by picking skill.
    """
    n = len(excesses)
    if n < 2:
        return {"mean_excess_per_trade": excesses[0] if excesses else 0.0,
                "excess_std": 0.0, "t_stat": 0.0, "ci_low": 0.0, "ci_high": 0.0,
                "is_significant": False, "trades_needed": 0.0}
    mean = sum(excesses) / n
    var = sum((x - mean) ** 2 for x in excesses) / (n - 1)
    sd = var ** 0.5
    se = sd / (n ** 0.5) if n else 0.0
    t = mean / se if se > 0 else 0.0
    crit = _t_crit(n)
    # ~80% power at 5% two-sided needs roughly (2.8 * sd / effect)^2 samples.
    needed = (2.8 * sd / abs(mean)) ** 2 if mean else float("inf")
    return {"mean_excess_per_trade": mean, "excess_std": sd, "t_stat": t,
            "ci_low": mean - crit * se, "ci_high": mean + crit * se,
            "is_significant": abs(t) > crit, "trades_needed": needed}


def _pct(a: float, b: float) -> float:
    """Return (b/a - 1) * 100, or 0.0 when the base is unusable."""
    if a is None or b is None or a <= 0:
        return 0.0
    return (b / a - 1.0) * 100.0


def _benchmark_window_return(bench: pd.Series, start: str, end: str | None) -> tuple[float, str]:
    """Benchmark % change from the first bar on/after ``start`` to the last
    bar on/before ``end`` (or the final bar when ``end`` is None).

    Returns (pct, note). A note is set — and the pct left at 0.0 — when the
    window can't be priced, so a missing benchmark shows up as an explicit
    gap rather than silently scoring as 'benchmark did nothing', which would
    make every trade look artificially good or bad."""
    if bench is None or not len(bench):
        return 0.0, "no benchmark data"
    s = bench.dropna()
    if not len(s):
        return 0.0, "no benchmark data"
    try:
        start_ts = pd.Timestamp(start)
    except Exception:
        return 0.0, "unparseable entry date"
    at_or_after = s[s.index >= start_ts]
    if not len(at_or_after):
        return 0.0, "entry date after benchmark history"
    first = float(at_or_after.iloc[0])
    if end:
        try:
            end_ts = pd.Timestamp(end)
        except Exception:
            return 0.0, "unparseable exit date"
        upto = s[s.index <= end_ts]
        if not len(upto):
            return 0.0, "exit date before benchmark history"
        last = float(upto.iloc[-1])
    else:
        last = float(s.iloc[-1])
    return _pct(first, last), ""


def score_live(state: dict, prices: dict[str, float],
               benchmark_series: pd.Series | None = None,
               benchmark_name: str = "benchmark",
               cost_rate: float = 0.0,
               include_closed: bool = True) -> Scorecard:
    """Score real trades from a PaperTrader state dict.

    ``prices``      — latest price per ticker (open positions only need this)
    ``benchmark_series`` — benchmark close history, indexed by date
    ``cost_rate``   — round-trip friction as a fraction (e.g. 0.006 = 0.6%),
                      charged once per trade so the comparison isn't
                      flattered by pretending trading is free
    """
    positions = state.get("positions", {}) or {}
    closed = state.get("log", []) or [] if include_closed else []

    scored: list[TradeScore] = []

    for ticker, p in positions.items():
        entry = float(p.get("entry_price") or 0.0)
        shares = float(p.get("shares") or 0.0)
        entry_date = str(p.get("entry_date") or "")
        px = prices.get(ticker)
        if px is None or entry <= 0 or shares <= 0:
            continue
        cost_basis = entry * shares
        gross_ret = _pct(entry, float(px))
        net_ret = gross_ret - cost_rate * 100.0
        bench_ret, note = _benchmark_window_return(benchmark_series, entry_date, None)
        scored.append(TradeScore(
            ticker=ticker, entry_date=entry_date, shares=shares,
            entry_price=entry, current_price=float(px), is_open=True,
            value_at_cost=cost_basis,
            pnl_idr=cost_basis * net_ret / 100.0,
            return_pct=net_ret, benchmark_return_pct=bench_ret,
            excess_pct=net_ret - bench_ret, note=note))

    for e in closed:
        entry = float(e.get("entry") or 0.0)
        exit_px = float(e.get("exit") or 0.0)
        shares = float(e.get("shares") or 0.0)
        entry_date = str(e.get("entry_date") or e.get("date") or "")
        exit_date = str(e.get("date") or "")
        if entry <= 0 or shares <= 0:
            continue
        cost_basis = entry * shares
        gross_ret = _pct(entry, exit_px)
        net_ret = gross_ret - cost_rate * 100.0
        bench_ret, note = _benchmark_window_return(benchmark_series, entry_date, exit_date)
        scored.append(TradeScore(
            ticker=str(e.get("ticker") or "?"), entry_date=entry_date, shares=shares,
            entry_price=entry, current_price=exit_px, is_open=False,
            value_at_cost=cost_basis,
            pnl_idr=cost_basis * net_ret / 100.0,
            return_pct=net_ret, benchmark_return_pct=bench_ret,
            excess_pct=net_ret - bench_ret, note=note))

    if not scored:
        return Scorecard(benchmark=benchmark_name, cost_rate=cost_rate,
                         note="No priced trades found in state.")

    total_cost = sum(t.value_at_cost for t in scored)
    total_pnl = sum(t.pnl_idr for t in scored)
    total_ret = (total_pnl / total_cost * 100.0) if total_cost else 0.0
    # Cost-weighted benchmark: what the same money, deployed on the same dates
    # for the same durations, would have made in the benchmark instead.
    bench_equiv = (sum(t.value_at_cost * t.benchmark_return_pct for t in scored) / total_cost
                   if total_cost else 0.0)

    return Scorecard(
        trades=tuple(sorted(scored, key=lambda t: t.excess_pct)),
        benchmark=benchmark_name,
        n_open=sum(1 for t in scored if t.is_open),
        n_closed=sum(1 for t in scored if not t.is_open),
        total_cost_basis=total_cost,
        total_pnl_idr=total_pnl,
        total_return_pct=total_ret,
        benchmark_equivalent_pct=bench_equiv,
        excess_pct=total_ret - bench_equiv,
        n_beat_benchmark=sum(1 for t in scored if t.excess_pct > 0),
        cost_rate=cost_rate,
        **_significance([t.excess_pct for t in scored]))


def _idr(x: float) -> str:
    return f"Rp{x:,.0f}"


def format_scorecard(sc: Scorecard) -> str:
    """Per-trade table + totals, with the small-sample warning stated up front
    rather than buried, because the number is tempting to over-read."""
    if sc.note and not sc.trades:
        return f"LIVE SCORECARD — {sc.note}"

    n = len(sc.trades)
    lines = [
        f"LIVE SCORECARD — {n} real trades ({sc.n_open} open, {sc.n_closed} closed) "
        f"vs holding {sc.benchmark}",
        f"  Each trade measured against {sc.benchmark} over ITS OWN holding window "
        f"— the same alpha check that ruled out all 14 backtested hypotheses.",
        f"  Friction charged: {sc.cost_rate * 100:.2f}% round trip per trade.",
        "",
        f"  {'ticker':<10}{'entry':>10}{'now/exit':>10}{'ret%':>8}"
        f"{sc.benchmark[:6]+'%':>8}{'excess%':>9}  ",
        "  " + "-" * 60,
    ]
    for t in sc.trades:
        flag = "" if not t.note else f"  ({t.note})"
        state = "" if t.is_open else " [closed]"
        lines.append(
            f"  {t.ticker:<10}{t.entry_price:>10.1f}{t.current_price:>10.1f}"
            f"{t.return_pct:>8.1f}{t.benchmark_return_pct:>8.1f}{t.excess_pct:>9.1f}"
            f"{state}{flag}")
    gross_excess = sc.excess_pct + sc.cost_rate * 100.0
    lines += [
        "  " + "-" * 60,
        f"  Cost basis: {_idr(sc.total_cost_basis)}   P&L: {_idr(sc.total_pnl_idr)} "
        f"({sc.total_return_pct:+.2f}%)",
        f"  Same money in {sc.benchmark} over the same windows: "
        f"{sc.benchmark_equivalent_pct:+.2f}%",
        f"  EXCESS vs benchmark: {sc.excess_pct:+.2f}pp   "
        f"({sc.n_beat_benchmark}/{n} trades beat it)",
    ]
    if sc.cost_rate > 0 and gross_excess > 0:
        lines.append(
            f"  Friction took {sc.cost_rate * 100:.2f}pp of a {gross_excess:+.2f}pp "
            f"gross edge — {sc.cost_rate * 100 / gross_excess * 100:.0f}% of it.")
    lines += [
        "",
        "  SIGNIFICANCE (is this skill or noise?)",
        f"    mean excess/trade : {sc.mean_excess_per_trade:+.2f}pp "
        f"(equal-weighted; headline above is cost-weighted)",
        f"    95% CI            : [{sc.ci_low:+.2f}, {sc.ci_high:+.2f}]pp",
        f"    t-stat            : {sc.t_stat:+.2f}  -> "
        f"{'SIGNIFICANT' if sc.is_significant else 'NOT significant'}",
        f"    trades needed     : {sc.trades_needed:,.0f} to resolve an edge this size "
        f"(you have {n})",
        "",
    ]

    beat_rate = (sc.n_beat_benchmark / n * 100) if n else 0.0
    sign_flip = (sc.mean_excess_per_trade < 0) != (sc.excess_pct < 0)
    if sc.is_significant:
        verdict = (f"The per-trade excess IS statistically distinguishable from zero "
                   f"(t={sc.t_stat:+.2f}) — worth investigating properly, though "
                   f"{n} trades still can't rule out luck across many attempts. ")
    else:
        verdict = (
            f"The headline reads {sc.excess_pct:+.2f}pp with {beat_rate:.0f}% of trades "
            f"beating {sc.benchmark}, but it is INDISTINGUISHABLE FROM ZERO: t="
            f"{sc.t_stat:+.2f}, and the 95% CI [{sc.ci_low:+.2f}, {sc.ci_high:+.2f}]pp "
            f"comfortably straddles no-edge. You would need roughly "
            f"{sc.trades_needed:,.0f} trades to tell an edge this size apart from "
            f"noise; you have {n}. ")
    if sign_flip:
        verdict += (
            f"NOTE the sign disagreement: cost-weighted {sc.excess_pct:+.2f}pp vs "
            f"equal-weighted {sc.mean_excess_per_trade:+.2f}pp per trade. The headline "
            f"is being driven by WHICH POSITIONS HAPPENED TO BE LARGE, not by picking "
            f"— the typical trade landed on the other side of zero. ")
    verdict += (
        f"**{n} trades over a few weeks is NOT evidence either way.** The backtests "
        f"that found no edge used thousands of trades; at this sample size sequence "
        f"luck dominates and one name moves the whole figure. Do not size up on a "
        f"positive number here, and do not abandon a plan on a negative one.")
    lines.append(f"  READ: {verdict}")
    return "\n".join(lines)


def weekly_scorecard_text(state: dict, prices: dict[str, float],
                          benchmark_ticker: str = "XIJI.JK",
                          period: str = "1y",
                          fetch=None) -> str | None:
    """The weekly Telegram scorecard as text, or None when there is nothing
    to report (no positions and no closed trades yet).

    Kept here rather than inline in ``daily_run.main()`` so the benchmark-
    missing branch is testable offline — ``fetch`` is injectable for exactly
    that. Same reasoning as ``daily_run.quarterly_walkforward_due``.
    """
    if not state.get("positions") and not state.get("log"):
        return None
    bench = (fetch or fetch_benchmark)(benchmark_ticker, period)
    if bench is None or not len(bench):
        # Without benchmark data every excess column would compute against
        # 0.0 and the scorecard would read "exactly average" — a false
        # result, not a missing one. Report the gap instead.
        return (f"📋 SCORECARD skipped — no data for benchmark "
                f"{benchmark_ticker}, so there is nothing to compare against.")
    sc = score_live(state, prices, benchmark_series=bench,
                    benchmark_name=benchmark_ticker,
                    cost_rate=round_trip_cost())
    return format_scorecard(sc)
