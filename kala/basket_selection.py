"""
Basket SELECTION study — the follow-up the evidence itself demanded.

WHY THIS EXISTS, AND WHY IT'S NOT ANOTHER WEIGHTING STUDY
-----------------------------------------------------------
Three separate studies in PROJECT_STATUS.md (weighting schemes, vol
targeting, and the user's real-basket runs) all landed on the SAME
explanation for why nothing helped: the user's sharia blue-chips are highly
CORRELATED — they crash together in IDX-wide selloffs, so there is little
diversifiable risk left for any overlay to reduce. Every one of those
studies took the BASKET AS GIVEN and adjusted weights or exposure.

This asks the question those results point at but never tested: if
correlation is the problem, can you fix it by CHOOSING DIFFERENT STOCKS?
That is basket SELECTION, not weighting — a genuinely different lever, and
the natural next question rather than a re-skin of a failed one.

Two things are measured:

1. ``correlation-aware selection`` — at each rebalance, pick the K names with
   the LOWEST average pairwise correlation to each other (a greedy
   min-correlation search over the trailing window), hold equal-weight until
   the next rebalance. Compared against a RANDOM-K baseline drawn from the
   same universe, repeated over many random draws so the comparison is
   against the distribution of "just pick K names," not one lucky draw.

2. ``holdings-count curve`` — portfolio volatility and max drawdown as K goes
   1, 2, 4, 8, 16, 32... Answers a question the user has a live stake in:
   is an 8-name satellite sleeve enough, or does going to 16/32 meaningfully
   cut risk? Classic finance says diversification benefit flattens fast
   (most of it by ~15-20 names, Statman 1987) and that the remaining risk is
   market risk you cannot diversify away — which, if it holds here, is
   itself the quantitative confirmation of why every overlay above failed.

THE LOOK-AHEAD TRAP THIS DELIBERATELY AVOIDS
----------------------------------------------
Picking "the historically least-correlated stocks" using the WHOLE sample is
a classic, seductive look-ahead bug: you would be selecting names using
correlation information that includes the future you then "test" on, and it
would produce a beautiful, entirely fake result. It is the same shape as the
``--min-price`` bug this project already retracted a validated result over
(see "How this was established" in PROJECT_STATUS.md).

So selection here is strictly WALK-FORWARD: at each rebalance date the
correlation matrix is estimated from the TRAILING ``lookback`` window only,
the basket is chosen from that, and it is then held FORWARD into the next
period whose returns it is judged on. The chosen names at time t never see a
return from after t.

HONEST PRIOR
------------
Correlations are notoriously UNSTABLE out of sample — the pairs that were
least correlated last year are frequently not least correlated next year,
and correlations famously converge toward 1 in exactly the crashes you most
wanted protection from. So the expected result is that correlation-aware
selection helps LESS out of sample than its in-sample appeal suggests,
possibly not at all. If it does beat random selection on realized
volatility, that is a genuine (if modest) finding; if it doesn't, that is a
clean, quantitative demonstration that the correlation problem is structural
to this market rather than a stock-picking failure — and either answer is
worth having.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

TRADING_DAYS = 252


@dataclass(frozen=True)
class BasketStats:
    cagr_pct: float
    ann_vol_pct: float
    max_drawdown_pct: float
    return_per_vol: float
    avg_pair_corr: float          # realized average pairwise correlation of the held names


@dataclass(frozen=True)
class SelectionComparison:
    low_corr: BasketStats
    random_median: BasketStats     # median across many random draws
    k: int
    n_universe: int
    n_days: int
    n_random_trials: int
    lookback: int
    every_days: int
    random_vol_pct_better_than_lowcorr: float   # % of random draws with LOWER vol
    note: str = ""


@dataclass(frozen=True)
class HoldingsCurvePoint:
    k: int
    median_ann_vol_pct: float
    median_max_drawdown_pct: float
    median_avg_pair_corr: float


@dataclass(frozen=True)
class HoldingsCurve:
    points: tuple = field(default_factory=tuple)
    n_universe: int = 0
    n_days: int = 0
    n_trials: int = 0
    note: str = ""


def _align_closes(prices: dict[str, pd.Series]) -> tuple[pd.DataFrame, list[str]]:
    frames = {t: s.dropna() for t, s in prices.items() if s is not None and len(s)}
    if not frames:
        return pd.DataFrame(), []
    max_len = max(len(s) for s in frames.values())
    kept = {t: s for t, s in frames.items() if len(s) >= max_len * 0.5}
    dropped = sorted(set(frames) - set(kept))
    if not kept:
        return pd.DataFrame(), dropped
    return pd.DataFrame(kept).dropna(how="any"), dropped


def _stats(equity: pd.Series, avg_corr: float) -> BasketStats:
    equity = equity.dropna()
    if len(equity) < 2 or equity.iloc[0] <= 0:
        return BasketStats(0.0, 0.0, 0.0, 0.0, avg_corr)
    years = len(equity) / TRADING_DAYS
    cagr = (equity.iloc[-1] / equity.iloc[0]) ** (1.0 / years) - 1.0 if years > 0 else 0.0
    daily = equity.pct_change().dropna()
    ann_vol = float(daily.std() * np.sqrt(TRADING_DAYS)) if len(daily) else 0.0
    running_max = equity.cummax()
    max_dd = float((equity / running_max - 1.0).min())
    rpv = (cagr / ann_vol) if ann_vol > 0 else 0.0
    return BasketStats(cagr * 100, ann_vol * 100, max_dd * 100, rpv, avg_corr)


def _avg_pair_corr(corr: pd.DataFrame, names: list[str]) -> float:
    """Mean of the off-diagonal entries of the correlation sub-matrix."""
    if len(names) < 2:
        return 0.0
    sub = corr.loc[names, names].to_numpy()
    iu = np.triu_indices(len(names), k=1)
    vals = sub[iu]
    vals = vals[np.isfinite(vals)]
    return float(vals.mean()) if len(vals) else 0.0


def pick_low_correlation(corr: pd.DataFrame, k: int) -> list[str]:
    """Greedy min-average-correlation basket of ``k`` names from a correlation
    matrix. Starts from the single name with the lowest average correlation to
    everything else, then repeatedly adds whichever remaining name minimizes
    the new basket's average pairwise correlation. Greedy, not the exact
    combinatorial optimum (which is intractable for realistic universes) —
    but deterministic, transparent, and good enough to answer "does choosing
    for low correlation help at all?"."""
    cols = list(corr.columns)
    if k >= len(cols):
        return cols
    mean_corr = corr.mean(axis=1)
    chosen = [str(mean_corr.idxmin())]
    while len(chosen) < k:
        best, best_score = None, np.inf
        for cand in cols:
            if cand in chosen:
                continue
            score = float(corr.loc[chosen, cand].mean())
            if score < best_score:
                best, best_score = cand, score
        if best is None:
            break
        chosen.append(best)
    return chosen


def _run_selection(closes: pd.DataFrame, k: int, lookback: int, every_days: int,
                   picker) -> tuple[pd.Series, float]:
    """Walk forward: at each rebalance estimate correlation from the TRAILING
    ``lookback`` window, call ``picker(corr, k)`` to choose names, hold them
    equal-weight until the next rebalance. Returns (equity, avg_realized_pair_corr).
    Selection at t uses only data through t — no look-ahead."""
    rets = closes.pct_change()
    dates = closes.index
    equity_vals = [1.0]
    corrs: list[float] = []
    held: list[str] = []

    for i in range(lookback, len(dates)):
        if (i - lookback) % every_days == 0:
            window = rets.iloc[i - lookback:i]      # strictly BEFORE bar i
            corr = window.corr()
            held = picker(corr, k)
            corrs.append(_avg_pair_corr(corr, held))
        if held:
            day_ret = float(rets.iloc[i][held].mean())
            if not np.isfinite(day_ret):
                day_ret = 0.0
        else:
            day_ret = 0.0
        equity_vals.append(equity_vals[-1] * (1.0 + day_ret))

    equity = pd.Series(equity_vals[1:], index=dates[lookback:])
    return equity, (float(np.mean(corrs)) if corrs else 0.0)


def compare_selection(prices: dict[str, pd.Series], k: int = 8, lookback: int = 252,
                      every_days: int = 63, n_random_trials: int = 200,
                      seed: int = 0) -> SelectionComparison:
    """Does picking the least-correlated K names (walk-forward) beat picking K
    names at random from the same universe? Random baseline is repeated
    ``n_random_trials`` times so the comparison is against the DISTRIBUTION of
    random draws, not one lucky one."""
    closes, _dropped = _align_closes(prices)
    if closes.shape[1] <= k:
        return SelectionComparison(
            _stats(pd.Series(dtype=float), 0.0), _stats(pd.Series(dtype=float), 0.0),
            k, closes.shape[1], len(closes), 0, lookback, every_days, 0.0,
            note=f"Universe has {closes.shape[1]} usable names; need more than k={k}.")
    if len(closes) < lookback + every_days * 2:
        return SelectionComparison(
            _stats(pd.Series(dtype=float), 0.0), _stats(pd.Series(dtype=float), 0.0),
            k, closes.shape[1], len(closes), 0, lookback, every_days, 0.0,
            note=(f"Only {len(closes)} overlapping days; need at least "
                  f"{lookback + every_days * 2}."))

    lc_equity, lc_corr = _run_selection(closes, k, lookback, every_days,
                                        pick_low_correlation)
    lc_stats = _stats(lc_equity, lc_corr)

    rng = np.random.default_rng(seed)
    cols = list(closes.columns)
    rand_vols, rand_stats_list = [], []
    for _ in range(n_random_trials):
        picks = list(rng.choice(cols, size=k, replace=False))

        def _rand_picker(corr, kk, _picks=picks):
            return _picks

        eq, cr = _run_selection(closes, k, lookback, every_days, _rand_picker)
        st = _stats(eq, cr)
        rand_stats_list.append(st)
        rand_vols.append(st.ann_vol_pct)

    # median random draw, by volatility (the metric selection is aimed at)
    order = np.argsort(rand_vols)
    median_rand = rand_stats_list[order[len(order) // 2]]
    pct_random_better = float(np.mean(np.asarray(rand_vols) < lc_stats.ann_vol_pct) * 100)

    return SelectionComparison(
        low_corr=lc_stats,
        random_median=median_rand,
        k=k,
        n_universe=closes.shape[1],
        n_days=len(closes),
        n_random_trials=n_random_trials,
        lookback=lookback,
        every_days=every_days,
        random_vol_pct_better_than_lowcorr=pct_random_better)


def holdings_curve(prices: dict[str, pd.Series], ks=(1, 2, 4, 8, 16, 32),
                   n_trials: int = 100, seed: int = 0) -> HoldingsCurve:
    """How much does risk actually fall as you hold MORE names? For each K,
    draw ``n_trials`` random equal-weight baskets and report the MEDIAN
    realized vol / max drawdown / average pairwise correlation. Buy-and-hold
    over the whole window (no rebalancing) — this measures the diversification
    benefit of basket SIZE, isolated from any weighting or timing policy."""
    closes, _dropped = _align_closes(prices)
    if closes.shape[1] < 2 or len(closes) < 60:
        return HoldingsCurve(note="Need at least 2 names and 60 overlapping days.")

    rets = closes.pct_change().dropna()
    corr_full = rets.corr()
    cols = list(closes.columns)
    rng = np.random.default_rng(seed)
    points = []
    for k in ks:
        if k > len(cols):
            continue
        vols, dds, crs = [], [], []
        for _ in range(n_trials):
            picks = list(rng.choice(cols, size=k, replace=False))
            port = rets[picks].mean(axis=1)
            equity = (1.0 + port).cumprod()
            vols.append(float(port.std() * np.sqrt(TRADING_DAYS) * 100))
            dds.append(float((equity / equity.cummax() - 1.0).min() * 100))
            crs.append(_avg_pair_corr(corr_full, picks))
            if k == len(cols):
                break        # only one possible basket
        points.append(HoldingsCurvePoint(k, float(np.median(vols)),
                                         float(np.median(dds)), float(np.median(crs))))
    return HoldingsCurve(points=tuple(points), n_universe=len(cols),
                         n_days=len(closes), n_trials=n_trials)


def format_selection(cmp: SelectionComparison) -> str:
    """Selection table + a verdict that judges against the RANDOM DISTRIBUTION,
    not a single baseline, and calls out correlation instability explicitly."""
    if cmp.note:
        return f"BASKET-SELECTION STUDY — could not run: {cmp.note}"

    lc, rm = cmp.low_corr, cmp.random_median
    lines = [
        f"BASKET-SELECTION STUDY — pick K={cmp.k} from {cmp.n_universe} names, "
        f"{cmp.n_days} trading days (~{cmp.n_days / TRADING_DAYS:.1f}y)",
        f"  re-select every {cmp.every_days}d from TRAILING {cmp.lookback}d correlation "
        f"(walk-forward, no look-ahead) | {cmp.n_random_trials} random draws for baseline",
        "  Tests SELECTION (which stocks), not weighting — the follow-up to the "
        "correlation finding.",
        "",
        f"  {'basket':<28}{'CAGR':>9}{'vol':>8}{'maxDD':>9}{'ret/vol':>9}{'avgCorr':>9}",
        "  " + "-" * 72,
        f"  {'low-correlation pick':<28}{lc.cagr_pct:>8.2f}%{lc.ann_vol_pct:>7.1f}%"
        f"{lc.max_drawdown_pct:>8.1f}%{lc.return_per_vol:>9.2f}{lc.avg_pair_corr:>9.2f}",
        f"  {'random pick (median draw)':<28}{rm.cagr_pct:>8.2f}%{rm.ann_vol_pct:>7.1f}%"
        f"{rm.max_drawdown_pct:>8.1f}%{rm.return_per_vol:>9.2f}{rm.avg_pair_corr:>9.2f}",
        "  " + "-" * 72,
        f"  {cmp.random_vol_pct_better_than_lowcorr:.0f}% of random draws achieved LOWER "
        f"volatility than the low-correlation pick.",
        "",
    ]
    pct = cmp.random_vol_pct_better_than_lowcorr
    if pct <= 25.0:
        v = (f"Choosing for low correlation BEAT most random draws on volatility "
             f"(only {pct:.0f}% of random baskets did better). A real, if modest, "
             f"selection effect survived out of sample — notable, since trailing "
             f"correlations are usually unstable. Confirm on another window before "
             f"acting; and note it did NOT need to improve return to be useful.")
    elif pct >= 60.0:
        v = (f"Choosing for low correlation was WORSE than simply picking at random "
             f"({pct:.0f}% of random baskets got lower volatility). Trailing "
             f"correlations did not persist out of sample — the classic failure mode. "
             f"This is a clean, quantitative answer to 'can I fix the correlation "
             f"problem by picking different stocks': not this way.")
    else:
        v = (f"Low-correlation selection landed in the MIDDLE of the random "
             f"distribution ({pct:.0f}% of random draws did better) — i.e. "
             f"indistinguishable from picking at random. Trailing correlation carried "
             f"no reliable information about future co-movement here. The correlation "
             f"problem looks structural to this market, not fixable by selection.")
    lines.append(f"  READ: {v}")
    return "\n".join(lines)


def format_holdings_curve(curve: HoldingsCurve) -> str:
    """Diversification curve + the practical 'how many names is enough' read."""
    if curve.note:
        return f"HOLDINGS-COUNT CURVE — could not run: {curve.note}"

    lines = [
        f"HOLDINGS-COUNT CURVE — {curve.n_universe} names available, "
        f"{curve.n_days} trading days (~{curve.n_days / TRADING_DAYS:.1f}y), "
        f"{curve.n_trials} random baskets per K",
        "  How much does risk actually fall as you hold MORE stocks?",
        "",
        f"  {'K (names held)':<18}{'median vol':>13}{'median maxDD':>15}{'avg pair corr':>16}",
        "  " + "-" * 62,
    ]
    for p in curve.points:
        lines.append(f"  {p.k:<18}{p.median_ann_vol_pct:>12.1f}%"
                     f"{p.median_max_drawdown_pct:>14.1f}%{p.median_avg_pair_corr:>16.2f}")
    lines.append("  " + "-" * 62)

    if len(curve.points) >= 2:
        first, last = curve.points[0], curve.points[-1]
        vol_drop = first.median_ann_vol_pct - last.median_ann_vol_pct
        # Find where the benefit flattens: the first K within 10% of the final
        # level. NOTE the trap this avoids -- the LAST point is always within
        # 10% of itself, so a naive version reports "the knee is at K=<largest
        # tested>" even when the curve is still falling steeply there, which is
        # exactly backwards (it would tell you to stop right where more names
        # were still helping most). So a knee at the last tested K is reported
        # as NOT FLATTENED, with the still-falling step size quoted.
        knee = None
        for p in curve.points[:-1]:
            if last.median_ann_vol_pct > 0 and \
               p.median_ann_vol_pct <= last.median_ann_vol_pct * 1.10:
                knee = p.k
                break
        if knee is not None:
            knee_txt = (f"Most of the available risk reduction is captured by about "
                        f"K={knee} names; beyond that the curve is nearly flat.")
        else:
            prev = curve.points[-2]
            step = prev.median_ann_vol_pct - last.median_ann_vol_pct
            knee_txt = (f"The curve had NOT flattened by K={last.k} — the last step "
                        f"(K={prev.k}→{last.k}) still cut {step:.1f}pp of volatility, so "
                        f"more names were still helping meaningfully at the edge of the "
                        f"range tested. Re-run with larger K to find where it actually "
                        f"levels off.")
        v = (f"Going from K={first.k} to K={last.k} cut median volatility by "
             f"{vol_drop:.1f}pp (to {last.median_ann_vol_pct:.1f}%). {knee_txt} "
             f"The volatility that REMAINS at high K is market risk — undiversifiable "
             f"by holding more names, and the quantitative reason every weighting/"
             f"exposure overlay tested in this project had so little left to work with. "
             f"Reducing it further requires a different ASSET CLASS (sukuk, gold, cash), "
             f"not more stocks.")
        lines.append(f"  READ: {v}")
    return "\n".join(lines)
