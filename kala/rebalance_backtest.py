"""
Rebalancing POLICY backtest — does periodically rebalancing a fixed basket
back to equal weight actually beat just buying and holding it?

WHY THIS IS DIFFERENT FROM THE SEVEN FAILED TESTS
-------------------------------------------------
Every strategy this project ruled out (PROJECT_STATUS.md) tried to TIME the
market — pick when to enter/exit a name to beat it. This tests no such
thing. The basket is FIXED and the same in both arms; the only difference
is a maintenance rule: arm A never touches it (buy-and-hold, weights drift),
arm B resets it to equal weight every N trading days. There is no
prediction about which stock goes up. So this can't fall into the
beta-capture trap the alpha check exists to catch — both arms hold the same
stocks; we're isolating the effect of the REBALANCING POLICY alone.

WHAT TO HONESTLY EXPECT
-----------------------
The academic "rebalancing premium" is real but small and regime-dependent:
rebalancing systematically trims what's run up and tops up what's lagged, so
in a choppy/mean-reverting, low-correlation basket it can add a little
return AND reduce volatility; in a strong one-directional trend it can DRAG
return (you keep selling the winner). After transaction costs — which this
models, because rebalancing is NOT free — any return edge often shrinks to a
wash. The reliable benefit is usually VOLATILITY / drawdown reduction and
staying diversified (not silently ending up 60% in one name), not a return
boost. Read the output with that prior: if rebalanced return < buy-and-hold
but vol is lower, that is the EXPECTED, honest result, not a bug.

COSTS
-----
``cost_rate`` is charged on every rupiah of value that changes hands at each
rebalance (one leg). The CLI derives it from ``kala.config`` so it matches
the same honest cost assumptions the rest of the project uses. Set it to 0
to see the frictionless (dishonest) upper bound on the rebalancing premium —
useful only to see how much of any edge the costs eat.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

TRADING_DAYS = 252


@dataclass(frozen=True)
class PolicyStats:
    total_return_pct: float
    cagr_pct: float
    ann_vol_pct: float
    max_drawdown_pct: float
    return_per_vol: float        # CAGR / annualized vol -- crude risk-adjusted return


@dataclass(frozen=True)
class RebalanceComparison:
    buy_hold: PolicyStats
    rebalanced: PolicyStats
    n_rebalances: int
    total_cost: float            # currency paid in rebalancing frictions
    total_cost_pct: float        # as % of starting capital
    n_names: int
    n_days: int
    note: str = ""
    dropped_short_history: tuple = ()   # tickers excluded pre-join (see _align_closes)


# A ticker whose own price history is much shorter than the rest of the
# basket (recently listed, or a truncated/partial Yahoo series for a
# soon-to-be-delisted name) is dropped BEFORE the strict multi-name inner
# join -- otherwise a SINGLE such name can silently collapse the whole join
# to only the few days everyone happens to overlap on. Round, pre-declared
# threshold: keep a name only if its own history is at least this fraction
# of the LONGEST series present (see kala.weighting_backtest, same fix).
MIN_HISTORY_FRACTION = 0.5


def _align_closes(prices: dict[str, pd.Series]) -> tuple[pd.DataFrame, list[str]]:
    """Inner-join every ticker's Close series on shared dates, after first
    dropping any name whose own history is too short to be a fair member of
    the join. A policy comparison must run both arms on the SAME calendar or
    it isn't apples-to-apples. Returns (aligned_df, dropped_tickers)."""
    frames = {t: s.dropna() for t, s in prices.items() if s is not None and len(s)}
    if not frames:
        return pd.DataFrame(), []
    max_len = max(len(s) for s in frames.values())
    floor = max_len * MIN_HISTORY_FRACTION
    kept = {t: s for t, s in frames.items() if len(s) >= floor}
    dropped = sorted(set(frames) - set(kept))
    if not kept:
        return pd.DataFrame(), dropped
    return pd.DataFrame(kept).dropna(how="any"), dropped


def _stats(equity: pd.Series) -> PolicyStats:
    equity = equity.dropna()
    if len(equity) < 2 or equity.iloc[0] <= 0:
        return PolicyStats(0.0, 0.0, 0.0, 0.0, 0.0)
    total_return = equity.iloc[-1] / equity.iloc[0] - 1.0
    years = len(equity) / TRADING_DAYS
    cagr = (equity.iloc[-1] / equity.iloc[0]) ** (1.0 / years) - 1.0 if years > 0 else 0.0
    daily = equity.pct_change().dropna()
    ann_vol = float(daily.std() * np.sqrt(TRADING_DAYS)) if len(daily) else 0.0
    running_max = equity.cummax()
    max_dd = float((equity / running_max - 1.0).min())
    rpv = (cagr / ann_vol) if ann_vol > 0 else 0.0
    return PolicyStats(total_return * 100, cagr * 100, ann_vol * 100, max_dd * 100, rpv)


def _simulate_buy_and_hold(closes: pd.DataFrame, capital: float) -> pd.Series:
    """Buy equal weight on day 0, never touch. Share counts are fixed, so the
    weights drift with performance — exactly the point of the comparison."""
    n = closes.shape[1]
    first = closes.iloc[0]
    shares = (capital / n) / first          # fractional shares OK for a policy study
    return closes.mul(shares, axis=1).sum(axis=1)


def _simulate_rebalanced(closes: pd.DataFrame, capital: float,
                         every_days: int, cost_rate: float) -> tuple[pd.Series, int, float]:
    """Equal weight, reset every ``every_days`` bars. At each reset, value
    that changes hands pays ``cost_rate`` (one leg), and the cost is taken
    out of the pot before re-deriving equal-weight shares — so the model
    never spends money it doesn't have. Returns (equity_series,
    n_rebalances, total_cost)."""
    n = closes.shape[1]
    dates = closes.index
    shares = (capital / n) / closes.iloc[0]
    equity = pd.Series(index=dates, dtype=float)
    total_cost = 0.0
    n_rebalances = 0

    for i, dt in enumerate(dates):
        price = closes.iloc[i]
        value = float((shares * price).sum())
        equity.iloc[i] = value
        # rebalance on the cadence, but never on day 0 (just bought equal weight)
        if i > 0 and every_days > 0 and i % every_days == 0 and value > 0:
            target_value_each = value / n
            target_shares = target_value_each / price
            turnover = float((target_shares - shares).abs().mul(price).sum())
            cost = turnover * cost_rate
            pot_after = value - cost
            shares = (pot_after / n) / price
            total_cost += cost
            n_rebalances += 1

    return equity, n_rebalances, total_cost


def compare_rebalancing(prices: dict[str, pd.Series], capital: float = 100_000_000.0,
                        every_days: int = 63, cost_rate: float = 0.003) -> RebalanceComparison:
    """Compare buy-and-hold vs periodic-rebalance on the SAME equal-weight
    basket. ``every_days`` default 63 ≈ quarterly. ``cost_rate`` is the
    one-leg transaction cost fraction (default 0.3%). Returns a
    ``RebalanceComparison``; ``note`` is empty on success or explains why the
    comparison couldn't run (too few names / too little overlapping history).
    Any ticker with much shorter history than the rest of the basket is
    dropped BEFORE alignment rather than letting it collapse the whole join
    — see ``dropped_short_history`` on the result."""
    closes, dropped = _align_closes(prices)
    if closes.shape[1] < 2:
        return RebalanceComparison(
            _stats(pd.Series(dtype=float)), _stats(pd.Series(dtype=float)),
            0, 0.0, 0.0, closes.shape[1], len(closes),
            note="Need at least 2 names with overlapping history to compare a policy.",
            dropped_short_history=tuple(dropped))
    if len(closes) < every_days * 2:
        return RebalanceComparison(
            _stats(pd.Series(dtype=float)), _stats(pd.Series(dtype=float)),
            0, 0.0, 0.0, closes.shape[1], len(closes),
            note=f"Only {len(closes)} overlapping days — need at least "
                 f"{every_days * 2} for a meaningful rebalance cadence.",
            dropped_short_history=tuple(dropped))

    bh_equity = _simulate_buy_and_hold(closes, capital)
    rb_equity, n_rb, total_cost = _simulate_rebalanced(closes, capital, every_days, cost_rate)
    return RebalanceComparison(
        buy_hold=_stats(bh_equity),
        rebalanced=_stats(rb_equity),
        n_rebalances=n_rb,
        total_cost=total_cost,
        total_cost_pct=total_cost / capital * 100 if capital else 0.0,
        n_names=closes.shape[1],
        n_days=len(closes),
        dropped_short_history=tuple(dropped))


def format_comparison(cmp: RebalanceComparison, every_days: int, cost_rate: float) -> str:
    """Human-readable side-by-side, with the honest interpretation baked in
    rather than left for the reader to (mis)infer from raw numbers."""
    if cmp.note and cmp.n_rebalances == 0 and cmp.buy_hold.total_return_pct == 0:
        msg = f"REBALANCING STUDY — could not run: {cmp.note}"
        if cmp.dropped_short_history:
            msg += (f"\n  Dropped for short history before alignment: "
                    f"{', '.join(cmp.dropped_short_history)}")
        return msg

    bh, rb = cmp.buy_hold, cmp.rebalanced
    # Judge in ANNUAL (CAGR) terms, not 10y total-return deltas — a -4pp/yr CAGR
    # drag compounds to a huge (and misleading) total-return pp gap, so the
    # verdict must reason on the annualized number to stay honest.
    cagr_delta = rb.cagr_pct - bh.cagr_pct
    vol_delta = rb.ann_vol_pct - bh.ann_vol_pct
    lines = []
    if cmp.dropped_short_history:
        lines.append(f"  (dropped {len(cmp.dropped_short_history)} short-history "
                     f"ticker(s) before alignment: "
                     f"{', '.join(cmp.dropped_short_history)})")
    lines += [
        f"REBALANCING POLICY STUDY — {cmp.n_names} names, {cmp.n_days} trading days "
        f"(~{cmp.n_days / TRADING_DAYS:.1f}y)",
        f"  equal weight | rebalance every {every_days}d (~{every_days / 21:.0f}mo) | "
        f"cost {cost_rate * 100:.2f}%/leg",
        "  This tests a MAINTENANCE POLICY, not a timing signal — both arms hold the "
        "same basket.",
        "",
        f"  {'metric':<22}{'buy & hold':>14}{'rebalanced':>14}",
        "  " + "-" * 50,
        f"  {'total return':<22}{bh.total_return_pct:>13.1f}%{rb.total_return_pct:>13.1f}%",
        f"  {'CAGR':<22}{bh.cagr_pct:>13.2f}%{rb.cagr_pct:>13.2f}%",
        f"  {'annualized vol':<22}{bh.ann_vol_pct:>13.2f}%{rb.ann_vol_pct:>13.2f}%",
        f"  {'max drawdown':<22}{bh.max_drawdown_pct:>13.1f}%{rb.max_drawdown_pct:>13.1f}%",
        f"  {'return / vol':<22}{bh.return_per_vol:>14.2f}{rb.return_per_vol:>14.2f}",
        "  " + "-" * 50,
        f"  Rebalanced {cmp.n_rebalances}x, total friction paid: "
        f"{cmp.total_cost_pct:.2f}% of starting capital.",
        "",
    ]
    # Honest verdict, reasoned on CAGR (annual) deltas. Return drag is checked
    # BEFORE the vol-reduction case so a big drag is never mislabeled a "wash".
    vol_note = (f"and LOWERED vol {vol_delta:+.2f}pp/yr" if vol_delta < -0.1
                else f"and vol was ~unchanged ({vol_delta:+.2f}pp/yr)")
    if cagr_delta < -0.5:
        verdict = (f"Rebalancing DRAGGED return here: {cagr_delta:+.2f}pp/yr CAGR "
                   f"{vol_note}. Classic trending-basket outcome — you keep trimming "
                   f"the winner. The discipline still caps concentration risk, but on "
                   f"THIS basket/window it cost return; don't expect a return premium.")
    elif cagr_delta > 0.3 and vol_delta < -0.1:
        verdict = (f"Rebalancing helped BOTH: {cagr_delta:+.2f}pp/yr CAGR and "
                   f"{vol_delta:+.2f}pp/yr vol — a favorable (choppy, low-correlation) "
                   f"basket. Still modest; don't over-read one window.")
    elif vol_delta < -0.3:
        verdict = (f"The reliable result: rebalancing LOWERED volatility "
                   f"{vol_delta:+.2f}pp/yr for a return that's ~a wash "
                   f"({cagr_delta:+.2f}pp/yr CAGR). That's RISK CONTROL, not a return "
                   f"boost — exactly what to honestly expect.")
    else:
        verdict = (f"Return and risk both ~unchanged ({cagr_delta:+.2f}pp/yr CAGR, "
                   f"{vol_delta:+.2f}pp/yr vol) — the rebalancing premium was within "
                   f"noise / eaten by costs here. Fine: its job is keeping you "
                   f"diversified, not making money.")
    lines.append(f"  READ: {verdict}")
    return "\n".join(lines)
