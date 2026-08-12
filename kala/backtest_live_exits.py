"""
Backtest arm that exits the way the LIVE system actually exits.

WHY THIS EXISTS
---------------
Every validated number in this project (walk-forward t=3.06, the portfolio
sim) exits positions through backtest.py's FOUR rules: take-profit,
governing stop, death-cross event, max holding period. The live paper
trader exits through exits.evaluate_exit + papertrade.step, and this module
reproduces that decision rule inside the backtest so the two can be compared
on identical entries — the same structural move that settled the entry-veto
question.

HISTORY: the first run of this comparison (55 tickers / 5y) caught the live
engine losing -0.21%/trade where the validated rules earned +0.37%/trade —
its four never-validated CONSIDER rules (dominated by MACD-reversal, 63% of
all exits) were churning positions out in 5.3 days average vs 12.6, and it
lacked the validated max-holding exit entirely. That led to exits.py v3.3:
the unvalidated rules were demoted to ADVISORY and papertrade gained the
max-hold rule. This module mirrors the live path as it now stands, so
re-running compare_exit_engines.py doubles as the regression proof that
live ≈ validated.

WHAT IS HELD IDENTICAL to backtest.backtest_ticker (so the ONLY difference
is the exit rule set):
  * entries: composite_score >= threshold at close t -> fill at next open,
    with the same optional evaluate_entry veto gate and regime source;
  * costs: CostModel multipliers on the same legs;
  * price basis: stops/targets measured from the RAW fill open (entry_raw),
    exactly like backtest.py — NOT the cost-inclusive basis papertrade
    stores. This is deliberate: the experiment isolates the RULE SET, not
    cost-basis bookkeeping conventions;
  * ARB realism, live-style: exits are decided on a bar's close and FILL at
    the next session's open — and if that open is limit-down locked, the
    fill CARRIES to the first tradable open, exactly like papertrade.step's
    stage-1 SELL handling. (backtest.py instead gates its stop rule at
    decision time; same intent, slightly different mechanics — the live
    semantics are the ones being measured here.);
  * end of data: a still-open position closes at the final close, tagged
    "(eod)", same as backtest.py.

Point-in-time discipline: compute_features/composite_score are causal, so a
prefix slice feats.iloc[:i+1] carries IDENTICAL values at row i to the
full-frame computation (this is the same property test_system.py proves for
the score) — evaluate_exit at bar i therefore sees exactly what the live
engine would have seen on that day, nothing from the future.
"""

from __future__ import annotations

import pandas as pd

from .backtest import BacktestResult, Trade, _is_arb_locked, _veto_category
from .config import Config
from .entries import evaluate_entry
from .exits import Urgency, evaluate_exit
from .regime import classify_market_regime, regime_at
from .scoring import composite_score, compute_features


def backtest_ticker_live_exits(ticker: str, df: pd.DataFrame, benchmark=None,
                               cfg: Config | None = None):
    """backtest.backtest_ticker with the exit block swapped for the live
    engine (evaluate_exit, selling on URGENT/CONSIDER). Same signature and
    same BacktestResult shape, so every existing runner/stat helper works
    on its output unchanged."""
    cfg = cfg or Config()
    rcfg, bcfg, costs, ecfg = cfg.risk, cfg.backtest, cfg.costs, cfg.entries

    regime = None
    if benchmark is not None and len(benchmark) > 0:
        regime = classify_market_regime(benchmark)

    feats = compute_features(df)
    score = composite_score(feats)

    open_ = df["Open"].to_numpy(dtype=float)
    close = df["Close"].to_numpy(dtype=float)
    atr_arr = feats["atr"].to_numpy(dtype=float)
    score_arr = score.to_numpy(dtype=float)
    index = df.index
    n = len(df)

    result = BacktestResult(ticker=ticker)

    in_pos = False
    entry_i = -1
    entry_price = 0.0
    entry_raw = 0.0
    entry_atr = float("nan")
    peak = 0.0
    locked_bars = 0
    pending_exit_reason = None   # decided on a close, fills at next tradable open

    def close_trade(exit_i: int, raw_exit: float, reason: str):
        nonlocal in_pos
        # price-aware in tick_floor mode; == the old scalar in flat mode
        exit_price = raw_exit * costs.sell_multiplier(raw_exit)
        net = (exit_price / entry_price - 1.0) * 100.0
        result.closed.append(Trade(
            ticker=ticker, entry_date=index[entry_i], entry_price=entry_price,
            exit_date=index[exit_i], exit_price=exit_price, exit_reason=reason,
            net_return_pct=net, arb_locked_bars=locked_bars, peak_price=peak))
        in_pos = False

    for i in range(n):
        if in_pos and pending_exit_reason is not None:
            # A SELL decided on the previous close tries to fill at TODAY's
            # open. If today is limit-down locked there are no bids, so the
            # order CARRIES — exactly papertrade.step's stage-1 semantics.
            prev_close = close[i - 1] if i > 0 else None
            if _is_arb_locked(df.iloc[i], prev_close,
                              bcfg.arb_limit_pct, bcfg.arb_lock_tol_pct):
                locked_bars += 1
                peak = max(peak, close[i])
                if i == n - 1:
                    close_trade(i, close[i], pending_exit_reason + " (eod)")
                    pending_exit_reason = None
                continue
            reason = pending_exit_reason
            pending_exit_reason = None
            close_trade(i, open_[i], reason)
            # now flat at bar i: fall through so today's close can still
            # produce a new entry signal (same timing as backtest.py)

        if in_pos:
            peak = max(peak, close[i])
            status = regime_at(regime, index[i]) if regime is not None else None
            s_i = score_arr[i]
            decision = evaluate_exit(
                ticker=ticker,
                entry_price=entry_raw,           # raw-basis, same as backtest.py's math
                features=feats.iloc[: i + 1],    # causal prefix == what live saw that day
                peak_price=peak,
                entry_atr=entry_atr,
                market_status=status,
                score=float(s_i) if s_i == s_i else None,
                cfg=rcfg,
            )
            # papertrade.step queues the SELL on URGENT or CONSIDER — mirror it.
            reason = None
            if decision.exit_signal and decision.urgency >= Urgency.CONSIDER:
                reason = decision.reasons[0] if decision.reasons else "live exit"
            elif i - entry_i >= bcfg.holding_max_days:
                # max holding period — applied by the papertrade layer since
                # v3.3 (validated rule; evaluate_exit lacks bars-held context)
                reason = "max holding period"
            if reason is not None:
                if i + 1 < n:
                    pending_exit_reason = reason
                else:
                    close_trade(i, close[i], reason + " (eod)")
            elif i == n - 1:
                close_trade(i, close[i], "open at end of data (eod)")
            continue

        # flat: identical entry path to backtest.backtest_ticker ------------
        s = score_arr[i]
        if s == s and s >= bcfg.score_entry_threshold and i + 1 < n:
            result.n_signals += 1
            if bcfg.apply_entry_vetoes:
                status = regime_at(regime, index[i]) if regime is not None else None
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
            # atr_arr[i], not [i+1] — same look-ahead as backtest.py had (see
            # its history for the full explanation): Wilder's ATR at bar t
            # includes bar t's own High/Low, so the fill bar's ATR is not yet
            # known at that bar's open. This file's entire reason to exist is
            # comparing against backtest.py on IDENTICAL entries, so this
            # value must be computed the same way there too.
            entry_atr = atr_arr[i]
            peak = entry_raw
            locked_bars = 0
            pending_exit_reason = None

    if n >= 2:
        result.buy_hold_return_pct = (close[-1] / close[0] - 1.0) * 100.0
    if benchmark is not None and len(benchmark) >= 2:
        b = benchmark["Close"]
        b = b.loc[(b.index >= index[0]) & (b.index <= index[-1])]
        if len(b) >= 2:
            result.benchmark_return_pct = float((b.iloc[-1] / b.iloc[0] - 1.0) * 100.0)

    return result
