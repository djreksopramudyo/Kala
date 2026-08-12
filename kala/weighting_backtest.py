"""
Weighting-scheme backtest — does an OPTIMIZED weighting of a fixed basket
(min-variance, inverse-volatility) actually beat naive equal weight (1/N)
out of sample, after costs?

WHY THIS IS DIFFERENT FROM THE REBALANCING STUDY (and from the 12 nulls)
-------------------------------------------------------------------------
``kala/rebalance_backtest.py`` asks whether periodically resetting a basket
to EQUAL weight beats buy-and-hold. This asks a different question: given
that you rebalance, does the WEIGHTING RULE matter — is an
estimated-covariance weighting (classic Markowitz-style min-variance, or the
simpler inverse-volatility risk-parity proxy) worth its extra complexity and
estimation risk versus just holding 1/N? None of the twelve timing/factor
hypotheses in PROJECT_STATUS.md touch this: they were all about WHICH stock
or WHEN to trade. This is purely about HOW MUCH of each to hold in a basket
you've already chosen — a portfolio-construction question, the one that
actually fits a long-horizon buy-and-hold allocation.

THE HONEST PRIOR: 1/N IS HARD TO BEAT
---------------------------------------
This is not an open question in the literature so much as a famous cautionary
result: DeMiguel, Garlappi & Uppal (2009), "Optimal Versus Naive
Diversification," found that across many datasets NONE of the sophisticated
optimized policies reliably beat 1/N out of sample, because the estimation
error in the covariance/mean inputs overwhelms the theoretical gain. So the
EXPECTED, honest outcome here is: min-variance and inverse-vol may lower
realized VOLATILITY (that part is somewhat robust, especially inverse-vol),
but they will struggle to beat equal weight on risk-ADJUSTED return once
turnover costs and estimation noise are paid. Read the output with that
prior: if an optimized scheme lowers vol but not Sharpe, that is the textbook
result, not a bug. A scheme that beats 1/N on Sharpe OOS *after costs* would
be the surprising, noteworthy finding.

POINT-IN-TIME DISCIPLINE
------------------------
At each rebalance date the weights are estimated ONLY from the trailing
``lookback`` days of returns (data up to and including that date), then held
FORWARD to the next rebalance. No weight is ever informed by a return that
hadn't happened yet. All schemes run on the identical calendar with identical
costs, so the ONLY thing that varies between them is the weighting rule —
exactly what isolates its effect.

COSTS
-----
``cost_rate`` is charged on every unit of value that changes hands at each
rebalance (one leg), taken out of the pot before re-deriving shares — the
same honest convention as the rebalancing study. Equal weight still pays
costs (it drifts and must be reset too), so the comparison is
scheme-vs-scheme, not free-vs-costly.

SOLVER NOTE (no scipy/pypfopt in this project's runtime)
----------------------------------------------------------
Long-only min-variance is solved here WITHOUT a QP solver: the analytical
unconstrained solution ``w ∝ Σ⁻¹1`` is computed on a RIDGE-REGULARIZED
covariance (``Σ + λI``, which both stabilizes a near-singular estimate and
mimics the covariance shrinkage real min-var implementations use), then
negative weights are clipped to zero and renormalized. That clip-and-
renormalize is a standard, well-behaved HEURISTIC projection to the
long-only simplex, not the exact constrained optimum — fine for a
philosophy comparison (does covariance estimation help at all?), and
deliberately NOT presented as a production optimizer. Inverse-volatility
needs no matrix inversion and is always long-only by construction, so it's
the robust point of comparison against the fragile full-covariance route.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

TRADING_DAYS = 252
RIDGE = 1e-4          # covariance regularization (Σ + RIDGE*I) for a stable inverse


@dataclass(frozen=True)
class WeightingStats:
    total_return_pct: float
    cagr_pct: float
    ann_vol_pct: float
    max_drawdown_pct: float
    return_per_vol: float        # CAGR / annualized vol -- crude risk-adjusted return


@dataclass(frozen=True)
class WeightingComparison:
    stats: dict[str, WeightingStats]       # scheme name -> stats
    costs_pct: dict[str, float]            # scheme name -> total friction as % of start capital
    n_names: int
    n_days: int
    n_rebalances: int
    lookback: int
    every_days: int
    note: str = ""
    schemes: tuple = field(default_factory=tuple)
    dropped_short_history: tuple = field(default_factory=tuple)   # tickers excluded pre-join


# ---------------- weighting rules --------------------------------------------
# Each takes a window of daily returns (DataFrame, rows=days, cols=tickers)
# and returns a 1-D numpy array of non-negative weights summing to 1.

def _equal_weights(window_returns: pd.DataFrame) -> np.ndarray:
    n = window_returns.shape[1]
    return np.full(n, 1.0 / n)


def _inverse_vol_weights(window_returns: pd.DataFrame) -> np.ndarray:
    """Weight each name inversely to its own realized vol (diagonal risk
    parity). Needs no covariance off-diagonals, so it's numerically robust and
    always long-only. A name with zero/NaN vol falls back to equal share."""
    vol = window_returns.std().to_numpy()
    mask = (vol > 0) & np.isfinite(vol)
    # np.divide's `where` skips the division entirely on masked-out entries
    # (np.where would still evaluate 1.0/vol everywhere first, including at
    # vol==0, which is discarded but still raises a RuntimeWarning).
    inv = np.zeros_like(vol)
    np.divide(1.0, vol, out=inv, where=mask)
    if inv.sum() <= 0:
        n = window_returns.shape[1]
        return np.full(n, 1.0 / n)
    return inv / inv.sum()


def _min_variance_weights(window_returns: pd.DataFrame) -> np.ndarray:
    """Long-only min-variance via the analytical ``Σ⁻¹1`` solution on a
    ridge-regularized covariance, then clip-negatives-and-renormalize onto the
    long-only simplex (a heuristic projection, see module docstring). Falls
    back to equal weight if the estimate is degenerate."""
    n = window_returns.shape[1]
    cov = window_returns.cov().to_numpy()
    if not np.all(np.isfinite(cov)):
        return np.full(n, 1.0 / n)
    cov = cov + RIDGE * np.eye(n)
    ones = np.ones(n)
    try:
        raw = np.linalg.solve(cov, ones)       # ∝ Σ⁻¹1
    except np.linalg.LinAlgError:
        return np.full(n, 1.0 / n)
    raw = np.where(raw > 0, raw, 0.0)          # long-only projection
    if raw.sum() <= 0:
        return np.full(n, 1.0 / n)
    return raw / raw.sum()


SCHEMES = {
    "equal_weight": _equal_weights,
    "inverse_vol": _inverse_vol_weights,
    "min_variance": _min_variance_weights,
}


# ---------------- machinery --------------------------------------------------

# A ticker whose own price history is much shorter than the rest of the
# basket (recently listed, or Yahoo returning a truncated/partial series for
# a soon-to-be-delisted name) is dropped BEFORE the strict multi-name inner
# join -- otherwise a SINGLE such name silently collapses the whole join to
# only the few days everyone happens to overlap on, which can be as little
# as 1 day on a 40-name basket even though 39 of them have full 10y history.
# Round, pre-declared threshold, not tuned to any result: keep a name only if
# its own history is at least this fraction of the LONGEST series present.
MIN_HISTORY_FRACTION = 0.5


def _align_closes(prices: dict[str, pd.Series]) -> tuple[pd.DataFrame, list[str]]:
    """Inner-join every ticker's Close series on shared dates, after first
    dropping any name whose own history is too short to be a fair member of
    the join (see MIN_HISTORY_FRACTION above). Returns (aligned_df,
    dropped_short_history_tickers) so callers can report what was excluded
    instead of it silently vanishing into a near-empty join."""
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


def _stats(equity: pd.Series) -> WeightingStats:
    equity = equity.dropna()
    if len(equity) < 2 or equity.iloc[0] <= 0:
        return WeightingStats(0.0, 0.0, 0.0, 0.0, 0.0)
    total_return = equity.iloc[-1] / equity.iloc[0] - 1.0
    years = len(equity) / TRADING_DAYS
    cagr = (equity.iloc[-1] / equity.iloc[0]) ** (1.0 / years) - 1.0 if years > 0 else 0.0
    daily = equity.pct_change().dropna()
    ann_vol = float(daily.std() * np.sqrt(TRADING_DAYS)) if len(daily) else 0.0
    running_max = equity.cummax()
    max_dd = float((equity / running_max - 1.0).min())
    rpv = (cagr / ann_vol) if ann_vol > 0 else 0.0
    return WeightingStats(total_return * 100, cagr * 100, ann_vol * 100, max_dd * 100, rpv)


def _simulate_scheme(closes: pd.DataFrame, capital: float, every_days: int,
                     lookback: int, cost_rate: float, weight_fn) -> tuple[pd.Series, int, float]:
    """Walk the price panel; the equity series STARTS at bar ``lookback`` (the
    first bar with enough trailing history to estimate weights). At each
    rebalance the weights come from returns over the trailing ``lookback``
    window ending at the current bar, are held forward, and turnover pays
    ``cost_rate`` (deducted from the pot before re-deriving shares)."""
    prices = closes.to_numpy()
    dates = closes.index
    returns = closes.pct_change()

    # initial allocation at bar `lookback`, from the first full trailing window
    start = lookback
    w = weight_fn(returns.iloc[start - lookback + 1:start + 1])
    shares = (capital * w) / prices[start]
    equity = pd.Series(index=dates[start:], dtype=float)
    total_cost = 0.0
    n_rebalances = 0

    for i in range(start, len(dates)):
        price = prices[i]
        value = float((shares * price).sum())
        equity.iloc[i - start] = value
        if i > start and every_days > 0 and (i - start) % every_days == 0 and value > 0:
            w = weight_fn(returns.iloc[i - lookback + 1:i + 1])
            target_value = value * w
            target_shares = target_value / price
            turnover = float(np.abs(target_shares - shares).dot(price))
            cost = turnover * cost_rate
            pot_after = value - cost
            shares = (pot_after * w) / price
            total_cost += cost
            n_rebalances += 1

    return equity, n_rebalances, total_cost


def compare_weighting(prices: dict[str, pd.Series], capital: float = 100_000_000.0,
                      every_days: int = 63, lookback: int = 126,
                      cost_rate: float = 0.003) -> WeightingComparison:
    """Compare equal-weight vs inverse-vol vs min-variance on the SAME fixed
    basket, same rebalance cadence, same costs — isolating the weighting rule.
    ``every_days`` default 63 ≈ quarterly; ``lookback`` default 126 ≈ 6 months
    of history to estimate weights from. ``note`` is empty on success or
    explains why the comparison couldn't run. Any ticker with much shorter
    history than the rest of the basket (recently listed, or a truncated
    Yahoo series) is dropped BEFORE alignment rather than letting it collapse
    the whole join — see ``dropped_short_history`` on the result."""
    closes, dropped = _align_closes(prices)
    schemes = tuple(SCHEMES)
    if closes.shape[1] < 2:
        return WeightingComparison({}, {}, closes.shape[1], len(closes), 0,
                                   lookback, every_days,
                                   note="Need at least 2 names with overlapping history.",
                                   schemes=schemes, dropped_short_history=tuple(dropped))
    if len(closes) < lookback + every_days * 2:
        return WeightingComparison({}, {}, closes.shape[1], len(closes), 0,
                                   lookback, every_days,
                                   note=(f"Only {len(closes)} overlapping days — need at "
                                         f"least {lookback + every_days * 2} for a lookback "
                                         f"of {lookback} plus a meaningful cadence."),
                                   schemes=schemes, dropped_short_history=tuple(dropped))

    stats: dict[str, WeightingStats] = {}
    costs_pct: dict[str, float] = {}
    n_rb = 0
    for name, fn in SCHEMES.items():
        equity, n_rb, cost = _simulate_scheme(closes, capital, every_days,
                                              lookback, cost_rate, fn)
        stats[name] = _stats(equity)
        costs_pct[name] = cost / capital * 100 if capital else 0.0
    return WeightingComparison(stats, costs_pct, closes.shape[1], len(closes),
                               n_rb, lookback, every_days, schemes=schemes,
                               dropped_short_history=tuple(dropped))


def format_weighting_comparison(cmp: WeightingComparison, cost_rate: float) -> str:
    """Human-readable table + the honest DeMiguel-informed verdict."""
    if cmp.note and not cmp.stats:
        msg = f"WEIGHTING STUDY — could not run: {cmp.note}"
        if cmp.dropped_short_history:
            msg += (f"\n  Dropped for short history before alignment: "
                    f"{', '.join(cmp.dropped_short_history)}")
        return msg

    lines = []
    if cmp.dropped_short_history:
        lines.append(f"  (dropped {len(cmp.dropped_short_history)} short-history "
                     f"ticker(s) before alignment: "
                     f"{', '.join(cmp.dropped_short_history)})")
    lines += [
        f"WEIGHTING-SCHEME STUDY — {cmp.n_names} names, {cmp.n_days} trading days "
        f"(~{cmp.n_days / TRADING_DAYS:.1f}y)",
        f"  rebalance every {cmp.every_days}d (~{cmp.every_days / 21:.0f}mo) | "
        f"weights from trailing {cmp.lookback}d | cost {cost_rate * 100:.2f}%/leg",
        "  Does an OPTIMIZED weighting beat naive 1/N out of sample, after costs?",
        "",
        f"  {'scheme':<16}{'CAGR':>10}{'ann vol':>10}{'max DD':>10}{'ret/vol':>10}{'cost%':>9}",
        "  " + "-" * 65,
    ]
    for name in cmp.schemes:
        s = cmp.stats[name]
        lines.append(f"  {name:<16}{s.cagr_pct:>9.2f}%{s.ann_vol_pct:>9.2f}%"
                     f"{s.max_drawdown_pct:>9.1f}%{s.return_per_vol:>10.2f}"
                     f"{cmp.costs_pct[name]:>8.2f}%")
    lines.append("  " + "-" * 65)
    lines.append(f"  Rebalanced {cmp.n_rebalances}x each.")
    lines.append("")

    eq = cmp.stats["equal_weight"]
    # Judge each optimized scheme against 1/N on the two axes that matter:
    # risk-adjusted return (ret/vol) and raw volatility.
    beat_sharpe = [n for n in ("inverse_vol", "min_variance")
                   if cmp.stats[n].return_per_vol > eq.return_per_vol + 0.02]
    lower_vol = [n for n in ("inverse_vol", "min_variance")
                 if cmp.stats[n].ann_vol_pct < eq.ann_vol_pct - 0.1]

    if not beat_sharpe and lower_vol:
        verdict = (f"Textbook DeMiguel result: {', '.join(lower_vol)} LOWERED "
                   f"volatility vs 1/N but did NOT beat it on risk-adjusted return "
                   f"(ret/vol). Optimization bought you risk reduction, not a better "
                   f"Sharpe — exactly what to honestly expect once estimation error and "
                   f"costs are paid. If you want lower vol, inverse-vol is the robust "
                   f"choice; if you want simplicity, 1/N gives up little.")
    elif not beat_sharpe and not lower_vol:
        verdict = ("1/N was NOT beaten on either axis — neither optimized scheme "
                   "improved risk-adjusted return OR meaningfully cut volatility here. "
                   "The estimation error swamped the theoretical gain, the strong form "
                   "of the DeMiguel finding. Just hold equal weight.")
    else:
        verdict = (f"{', '.join(beat_sharpe)} beat 1/N on risk-adjusted return "
                   f"(ret/vol) here — the SURPRISING outcome DeMiguel says is rare. "
                   f"Do NOT over-read one window/basket: confirm on another period and "
                   f"check turnover/costs before trusting it, since optimized weights "
                   f"overfit the estimation window easily.")
    lines.append(f"  READ: {verdict}")
    return "\n".join(lines)
