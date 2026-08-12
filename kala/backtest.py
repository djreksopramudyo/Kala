"""
Event-driven, single-ticker backtest with IDX execution realism.

Three things the original got wrong and this fixes:

  * NO LOOK-AHEAD. A signal computed on bar i's close fills at bar i+1's OPEN.
    You can never trade on information you didn't have yet.
  * LIMIT-DOWN ("ARB") CARRY. When a stock is locked limit-down it cannot be
    sold — there are no bids. A naive backtest "fills" your -5% stop anyway and
    invents a loss far smaller than reality. Here a locked bar carries the
    position (counted in ``arb_locked_bars``) until the first tradable bar.
  * ASYMMETRIC COSTS. Buy fee, sell fee, sell tax and spread are all applied on
    the correct leg (see CostModel).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from . import indicators as ind
from .config import Config
from .entries import evaluate_entry
from .exits import governing_stop
from .regime import classify_market_regime, regime_at
from .scoring import composite_score, compute_features

# Coarse veto category, keyed off the (stable) prefix of entries.evaluate_entry's
# message strings — lets callers see WHICH guardrail is blocking candidates
# without entries.py having to expose a separate machine-readable code.
_VETO_CATEGORY_PREFIXES = (
    ("overbought", "overbought"),
    ("already extended", "parabolic"),
    ("OBV distribution", "distribution"),
    ("surge not confirmed", "thin_volume"),
    ("market regime is", "bear_regime"),
    ("price too low", "cheap_price"),
)


def _veto_category(msg: str) -> str:
    for prefix, cat in _VETO_CATEGORY_PREFIXES:
        if msg.startswith(prefix):
            return cat
    return "other"


@dataclass
class Trade:
    ticker: str
    entry_date: object
    entry_price: float          # cost-inclusive (what you actually paid per share)
    exit_date: object
    exit_price: float           # cost-inclusive (what you actually received)
    exit_reason: str
    net_return_pct: float
    arb_locked_bars: int = 0
    peak_price: float = 0.0


@dataclass
class BacktestResult:
    ticker: str
    closed: list[Trade] = field(default_factory=list)
    # Benchmark-relative context (None until computed by backtest_ticker):
    buy_hold_return_pct: float | None = None     # just holding this ticker
    benchmark_return_pct: float | None = None    # holding the benchmark (e.g. IHSG)
    # Entry-veto diagnostics (populated only when cfg.backtest.apply_entry_vetoes):
    n_signals: int = 0                            # bars where score cleared threshold
    n_vetoed: int = 0                              # of those, bars an entries.py veto blocked
    veto_counts: dict = field(default_factory=dict)  # category -> times it fired

    @property
    def n_trades(self) -> int:
        return len(self.closed)

    @property
    def total_return_pct(self) -> float:
        """Compounded return across sequential trades, in percent."""
        equity = 1.0
        for t in self.closed:
            equity *= (1.0 + t.net_return_pct / 100.0)
        return (equity - 1.0) * 100.0

    @property
    def alpha_vs_buy_hold_pct(self) -> float | None:
        """Strategy return minus just-holding-the-ticker. Negative means all the
        signals, stops and costs did WORSE than doing nothing."""
        if self.buy_hold_return_pct is None:
            return None
        return self.total_return_pct - self.buy_hold_return_pct

    @property
    def alpha_vs_benchmark_pct(self) -> float | None:
        """Strategy return minus the benchmark's buy-and-hold over the same
        window. This is the number people mean by "alpha": excess return over
        the passive alternative. None if no benchmark was supplied."""
        if self.benchmark_return_pct is None:
            return None
        return self.total_return_pct - self.benchmark_return_pct


def _is_arb_locked(bar, prev_close, arb_limit_pct, tol_pct: float = 1.0) -> bool:
    """True if ``bar`` is a limit-down lock: a near-limit down move that closed
    at its low (i.e. no buyers stepped in, you could not have sold).

    The tolerance accounts for locked closes that print a hair above the exact
    theoretical floor due to tick rounding.
    """
    if prev_close is None or prev_close <= 0:
        return False
    down_move_pct = (bar["Close"] - prev_close) / prev_close * 100.0
    closed_at_low = bar["Close"] <= bar["Low"] * (1.0 + 1e-9)
    near_limit = down_move_pct <= -(arb_limit_pct - tol_pct) + 1e-9
    return bool(near_limit and closed_at_low)


def backtest_ticker(ticker: str, df: pd.DataFrame, benchmark=None, cfg: Config | None = None,
                    score_override: pd.Series | None = None):
    """Run the long-only backtest for one ticker.

    ``benchmark`` (optional) is an OHLCV frame for the index (e.g. IHSG/^JKSE).
    When given, the result carries benchmark-relative fields so you can see the
    only number that matters: did the strategy beat just holding the index?

    ``score_override`` (optional) replaces composite_score's hand-tuned 0-100
    blend with a caller-supplied entry score (e.g. kala.ml_scoring's
    fitted RidgeScorer), reindexed onto ``df``'s dates. Everything else —
    ATR-based stops, the death-cross exit, entry-veto gating, cost model — is
    unchanged, so this isolates ONLY the entry-signal source. The score's
    scale need not be 0-100; ``cfg.backtest.score_entry_threshold`` must be
    supplied in whatever units the override uses."""
    cfg = cfg or Config()
    rcfg, bcfg, costs, ecfg = cfg.risk, cfg.backtest, cfg.costs, cfg.entries

    regime = None
    if bcfg.apply_entry_vetoes and benchmark is not None and len(benchmark) > 0:
        regime = classify_market_regime(benchmark)

    feats = compute_features(df)
    score = score_override.reindex(df.index) if score_override is not None else composite_score(feats)

    open_ = df["Open"].to_numpy(dtype=float)
    close = df["Close"].to_numpy(dtype=float)
    atr_arr = feats["atr"].to_numpy(dtype=float)
    score_arr = score.to_numpy(dtype=float)
    death = ind.cross_below(feats["sma_fast"], feats["sma_slow"]).to_numpy()
    index = df.index
    n = len(df)

    result = BacktestResult(ticker=ticker)

    in_pos = False
    entry_i = -1
    entry_price = 0.0       # cost-inclusive
    entry_raw = 0.0         # raw open, for stop/target math
    entry_atr = float("nan")
    peak = 0.0
    locked_bars = 0

    def close_trade(exit_i: int, raw_exit: float, reason: str):
        nonlocal in_pos
        # price-aware in tick_floor mode; == the old scalar in flat mode
        exit_price = raw_exit * costs.sell_multiplier(raw_exit)
        net = (exit_price / entry_price - 1.0) * 100.0
        result.closed.append(
            Trade(
                ticker=ticker,
                entry_date=index[entry_i],
                entry_price=entry_price,
                exit_date=index[exit_i],
                exit_price=exit_price,
                exit_reason=reason,
                net_return_pct=net,
                arb_locked_bars=locked_bars,
                peak_price=peak,
            )
        )
        in_pos = False

    for i in range(n):
        if in_pos:
            peak = max(peak, close[i])
            bars_held = i - entry_i
            stop, _phase, _label = governing_stop(entry_raw, peak, entry_atr, rcfg)

            target_price = entry_raw * (1.0 + rcfg.target_profit_pct / 100.0)
            has_next = i + 1 < n

            reason = None
            if close[i] >= target_price:
                reason = "target profit"
            elif close[i] <= stop:
                prev_close = close[i - 1] if i > 0 else None
                if _is_arb_locked(df.iloc[i], prev_close, bcfg.arb_limit_pct, bcfg.arb_lock_tol_pct):
                    locked_bars += 1  # cannot sell — carry the position
                else:
                    reason = "stop"
            elif bool(death[i]):
                reason = "death cross"
            elif bars_held >= bcfg.holding_max_days:
                reason = "max holding period"

            if reason is not None:
                if has_next:
                    close_trade(i + 1, open_[i + 1], reason)
                else:
                    close_trade(i, close[i], reason + " (eod)")
            continue

        # flat: look for an entry signal, fill at next open (no look-ahead)
        s = score_arr[i]
        if s == s and s >= bcfg.score_entry_threshold and i + 1 < n:  # s==s rejects NaN
            result.n_signals += 1
            if bcfg.apply_entry_vetoes:
                status = regime_at(regime, index[i]) if regime is not None else None
                # df.iloc[:i+1]: only price/volume history through bar i is known
                # at the moment this candidate would be scored (point-in-time).
                decision = evaluate_entry(df.iloc[: i + 1], market_status=status, cfg=ecfg)
                if not decision.allowed:
                    result.n_vetoed += 1
                    for v in decision.vetoes:
                        cat = _veto_category(v)
                        result.veto_counts[cat] = result.veto_counts.get(cat, 0) + 1
                    continue

            in_pos = True
            entry_i = i + 1
            entry_raw = open_[i + 1]
            entry_price = entry_raw * costs.buy_multiplier(entry_raw)
            # atr_arr[i], NOT [i+1]. Wilder's ATR at bar t incorporates bar t's
            # own High and Low, so atr_arr[i+1] is the fill DAY's realised
            # range — unknown when the order is placed at that day's open. It
            # feeds governing_stop() directly, so using it sized the stop with
            # one bar of future volatility: on a day that turned out wild the
            # stop came out wider, sparing the position a whipsaw exit it had
            # no way to foresee. The rest of this loop is scrupulous about
            # point-in-time (signal at i, fill at i+1, evaluate_entry fed only
            # df.iloc[:i+1]); this line was the exception.
            entry_atr = atr_arr[i]
            peak = entry_raw
            locked_bars = 0

    # ---- benchmark-relative context: is there any alpha here? ----
    if n >= 2:
        result.buy_hold_return_pct = (close[-1] / close[0] - 1.0) * 100.0
    if benchmark is not None and len(benchmark) >= 2:
        b = benchmark["Close"]
        # align to this ticker's window so the comparison is fair
        b = b.loc[(b.index >= index[0]) & (b.index <= index[-1])]
        if len(b) >= 2:
            result.benchmark_return_pct = float((b.iloc[-1] / b.iloc[0] - 1.0) * 100.0)

    return result
