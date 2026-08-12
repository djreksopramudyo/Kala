"""
Deployment backtest — lump sum vs DCA (nyicil): given money you have RIGHT
NOW, is it better to invest it all at once or spread it over N months?

WHY THIS IS A DIFFERENT QUESTION FROM EVERYTHING ELSE TESTED
--------------------------------------------------------------
Every hypothesis in PROJECT_STATUS.md is about WHICH stock (signals) or HOW
MUCH of each (weighting) or HOW MUCH TOTAL exposure over time (vol
targeting). This is none of those. It's the DEPLOYMENT SCHEDULE question:
you have a fixed pot of cash and a basket you've already chosen — do you buy
it all today, or in equal monthly slices? No prediction about any stock is
involved, so it can't fall into the beta-capture / overfitting traps the
other studies exist to catch. It is a pure, structural comparison of two
cash-flow schedules on identical price history.

It also happens to be the single most immediately DECISION-RELEVANT question
for someone sitting on an undeployed lump sum, which is exactly the
situation this project's owner is in.

THE HONEST PRIOR — AND WHY THE VERDICT IS NOT PURELY ABOUT AVERAGE RETURN
---------------------------------------------------------------------------
The well-replicated finding (Vanguard 2012, "Dollar-cost averaging just means
taking risk later"; Constantinides 1979 much earlier) is that LUMP SUM WINS
MORE OFTEN — roughly two-thirds of historical windows in US/global data —
for a simple structural reason: markets rise more often than they fall, so
money sitting in cash waiting to be deployed is, on average, missing return.
DCA is not a return-maximizing strategy and was never claimed to be.

What DCA actually buys you is REGRET REDUCTION and sequence protection: if
you deploy everything the day before a crash, lump sum hurts far more. So
this module deliberately reports BOTH:
  * how OFTEN lump sum wins (the frequency the literature emphasizes), and
  * the WORST-CASE outcomes for each (the reason a real person might still
    choose DCA even knowing it loses on average).
A verdict that only cited average terminal wealth would be technically true
and practically misleading. The formatter states both.

WHY MANY START DATES, NOT ONE
-------------------------------
Running this on a single start date measures LUCK, not policy — a lump sum
deployed at the 2020 bottom looks brilliant and one deployed in Jan 2020
looks terrible, and neither tells you what to do today. So the comparison
rolls the start date across every point in the available history that leaves
room for the full horizon, and reports the DISTRIBUTION of outcomes. That
rolling-window discipline is the same reason ``kala.walkforward`` uses many
folds instead of one train/test split.

COSTS
-----
Lump sum pays ``cost_rate`` once, on the whole pot. DCA pays it on each of
``dca_months`` slices — same total value traded, so on a flat percentage
cost the totals are similar, but DCA's slices are smaller and IDX's
tick-floored spreads hit small orders relatively harder in reality (this
model uses a flat rate, so it is if anything GENEROUS to DCA; the real-world
edge for lump sum is likely slightly larger than reported here).

CASH YIELD
----------
``cash_yield_annual`` is the return earned on not-yet-deployed money (e.g.
a sharia deposit/money-market rate). Default 0.0 is the conservative
assumption for idle cash in a brokerage account. Setting it to a realistic
positive rate is the honest way to give DCA its best case — undeployed cash
in Indonesia CAN earn something, and ignoring that overstates lump sum's
edge. The CLI exposes it.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

TRADING_DAYS = 252
MONTH_DAYS = 21          # ~one month of trading days


@dataclass(frozen=True)
class DeploymentStats:
    """Distribution of outcomes across all rolling start dates."""
    n_windows: int
    median_terminal: float        # median terminal wealth (multiple of starting capital)
    mean_terminal: float
    p5_terminal: float            # 5th percentile -- the bad-luck case
    p95_terminal: float
    worst_terminal: float
    median_max_drawdown_pct: float
    worst_max_drawdown_pct: float


@dataclass(frozen=True)
class DeploymentComparison:
    lump: DeploymentStats
    dca: DeploymentStats
    lump_win_rate_pct: float      # % of start dates where lump sum ended richer
    median_gap_pct: float         # median (lump/dca - 1), in %
    dca_months: int
    horizon_days: int
    cash_yield_annual: float
    n_days: int
    note: str = ""


def _align_closes(prices: dict[str, pd.Series]) -> tuple[pd.DataFrame, list[str]]:
    """Inner-join Close series after dropping names whose own history is much
    shorter than the basket's longest (same guard as the other study modules —
    one thin ticker must not collapse the whole overlap)."""
    frames = {t: s.dropna() for t, s in prices.items() if s is not None and len(s)}
    if not frames:
        return pd.DataFrame(), []
    max_len = max(len(s) for s in frames.values())
    kept = {t: s for t, s in frames.items() if len(s) >= max_len * 0.5}
    dropped = sorted(set(frames) - set(kept))
    if not kept:
        return pd.DataFrame(), dropped
    return pd.DataFrame(kept).dropna(how="any"), dropped


def _basket_index(closes: pd.DataFrame) -> pd.Series:
    """Equal-weight, daily-rebalanced basket level (normalized to 1.0 at the
    start). Deployment schedules buy INTO this basket; the weighting question
    is a separate study, so equal weight is the neutral base here."""
    rets = closes.pct_change().mean(axis=1).fillna(0.0)
    return (1.0 + rets).cumprod()


def _path_stats(path: np.ndarray) -> float:
    """Max drawdown (%) of a wealth path."""
    running_max = np.maximum.accumulate(path)
    with np.errstate(divide="ignore", invalid="ignore"):
        dd = np.where(running_max > 0, path / running_max - 1.0, 0.0)
    return float(dd.min() * 100)


def _simulate_window(level: np.ndarray, dca_months: int, cost_rate: float,
                     daily_cash_rate: float) -> tuple[float, float, float, float]:
    """One start date. Returns (lump_terminal, dca_terminal, lump_maxdd,
    dca_maxdd), each terminal expressed as a multiple of starting capital.

    ``level`` is the basket's price level over the window, normalized so
    level[0] is the price at deployment start.

    LUMP: buy units at level[0] with the whole (post-cost) pot, hold.
    DCA:  hold cash (accruing ``daily_cash_rate``), deploy 1/N of the ORIGINAL
          pot every ``MONTH_DAYS`` bars, each purchase paying cost_rate.
    """
    n = len(level)
    # ---- lump sum: one purchase at t0
    lump_units = (1.0 - cost_rate) / level[0]
    lump_path = lump_units * level

    # ---- DCA: N equal slices, cash accrues in the meantime
    slice_cash = 1.0 / dca_months
    units = 0.0
    cash = 1.0
    dca_path = np.empty(n, dtype=float)
    for i in range(n):
        if i > 0:
            cash *= (1.0 + daily_cash_rate)       # idle cash earns (or doesn't)
        # deploy a slice at t=0, MONTH_DAYS, 2*MONTH_DAYS, ... while slices remain
        if i % MONTH_DAYS == 0 and i // MONTH_DAYS < dca_months:
            spend = min(slice_cash, cash)
            units += spend * (1.0 - cost_rate) / level[i]
            cash -= spend
        dca_path[i] = units * level[i] + cash

    return (float(lump_path[-1]), float(dca_path[-1]),
            _path_stats(lump_path), _path_stats(dca_path))


def _stats_from(terminals: list[float], drawdowns: list[float]) -> DeploymentStats:
    t = np.asarray(terminals, dtype=float)
    d = np.asarray(drawdowns, dtype=float)
    if not len(t):
        return DeploymentStats(0, 0, 0, 0, 0, 0, 0, 0)
    return DeploymentStats(
        n_windows=len(t),
        median_terminal=float(np.median(t)),
        mean_terminal=float(t.mean()),
        p5_terminal=float(np.percentile(t, 5)),
        p95_terminal=float(np.percentile(t, 95)),
        worst_terminal=float(t.min()),
        median_max_drawdown_pct=float(np.median(d)),
        worst_max_drawdown_pct=float(d.min()))


def compare_deployment(prices: dict[str, pd.Series], horizon_days: int = 756,
                       dca_months: int = 12, cost_rate: float = 0.003,
                       cash_yield_annual: float = 0.0,
                       step_days: int = 5) -> DeploymentComparison:
    """Roll the start date across all of history and compare lump-sum vs
    ``dca_months``-month DCA over a ``horizon_days`` holding period (default
    756 ≈ 3 years). ``step_days`` controls how finely start dates are sampled
    (5 = weekly starts; smaller is slower but denser). ``cash_yield_annual``
    is what undeployed cash earns — 0.0 is conservative toward DCA's downside;
    set it positive to give DCA its fair best case."""
    closes, _dropped = _align_closes(prices)
    if closes.shape[0] < horizon_days + MONTH_DAYS * dca_months + 10:
        return DeploymentComparison(
            _stats_from([], []), _stats_from([], []), 0.0, 0.0,
            dca_months, horizon_days, cash_yield_annual, len(closes),
            note=(f"Need at least {horizon_days + MONTH_DAYS * dca_months + 10} "
                  f"overlapping days for a {horizon_days}-day horizon with "
                  f"{dca_months} monthly slices; have {len(closes)}."))

    level = _basket_index(closes).to_numpy()
    daily_cash = (1.0 + cash_yield_annual) ** (1.0 / TRADING_DAYS) - 1.0

    lump_t, dca_t, lump_dd, dca_dd = [], [], [], []
    last_start = len(level) - horizon_days
    for start in range(0, last_start, max(1, step_days)):
        window = level[start:start + horizon_days]
        lt, dt, ld, dd = _simulate_window(window, dca_months, cost_rate, daily_cash)
        lump_t.append(lt)
        dca_t.append(dt)
        lump_dd.append(ld)
        dca_dd.append(dd)

    lump_arr = np.asarray(lump_t)
    dca_arr = np.asarray(dca_t)
    win_rate = float((lump_arr > dca_arr).mean() * 100)
    with np.errstate(divide="ignore", invalid="ignore"):
        gaps = np.where(dca_arr > 0, lump_arr / dca_arr - 1.0, 0.0)
    median_gap = float(np.median(gaps) * 100)

    return DeploymentComparison(
        lump=_stats_from(lump_t, lump_dd),
        dca=_stats_from(dca_t, dca_dd),
        lump_win_rate_pct=win_rate,
        median_gap_pct=median_gap,
        dca_months=dca_months,
        horizon_days=horizon_days,
        cash_yield_annual=cash_yield_annual,
        n_days=len(closes))


def format_deployment(cmp: DeploymentComparison, cost_rate: float) -> str:
    """Human-readable distribution table + a verdict that reports BOTH the
    average-case winner and the worst-case protection, since a
    return-only verdict would be practically misleading here."""
    if cmp.note:
        return f"DEPLOYMENT STUDY — could not run: {cmp.note}"

    L, D = cmp.lump, cmp.dca
    lines = [
        f"DEPLOYMENT STUDY (lump sum vs DCA) — {cmp.n_days} trading days of history",
        f"  horizon {cmp.horizon_days}d (~{cmp.horizon_days / TRADING_DAYS:.1f}y) | "
        f"DCA over {cmp.dca_months} monthly slices | cost {cost_rate * 100:.2f}%/buy | "
        f"idle cash earns {cmp.cash_yield_annual * 100:.1f}%/yr",
        f"  {L.n_windows} rolling start dates — a DISTRIBUTION, not one lucky path.",
        "",
        f"  {'outcome (x starting capital)':<32}{'LUMP SUM':>12}{'DCA':>12}",
        "  " + "-" * 56,
        f"  {'median terminal':<32}{L.median_terminal:>12.3f}{D.median_terminal:>12.3f}",
        f"  {'mean terminal':<32}{L.mean_terminal:>12.3f}{D.mean_terminal:>12.3f}",
        f"  {'5th pct (bad luck)':<32}{L.p5_terminal:>12.3f}{D.p5_terminal:>12.3f}",
        f"  {'worst case':<32}{L.worst_terminal:>12.3f}{D.worst_terminal:>12.3f}",
        f"  {'median max drawdown':<32}{L.median_max_drawdown_pct:>11.1f}%"
        f"{D.median_max_drawdown_pct:>11.1f}%",
        f"  {'worst max drawdown':<32}{L.worst_max_drawdown_pct:>11.1f}%"
        f"{D.worst_max_drawdown_pct:>11.1f}%",
        "  " + "-" * 56,
        f"  Lump sum ended richer in {cmp.lump_win_rate_pct:.0f}% of start dates "
        f"(median gap {cmp.median_gap_pct:+.1f}%).",
        "",
    ]

    # Verdict reports BOTH axes: frequency-of-winning AND drawdown protection.
    # Check the MEDIAN drawdown as well as the worst: an earlier version looked
    # only at the worst case, and on a basket where both schedules shared the
    # same single worst crash it wrongly announced DCA "did not buy better
    # protection" while DCA was in fact ~3pp better in the TYPICAL window --
    # which is the drawdown a user actually lives through most of the time.
    worse_worst = L.worst_max_drawdown_pct < D.worst_max_drawdown_pct - 1.0
    worse_median = L.median_max_drawdown_pct < D.median_max_drawdown_pct - 1.0
    worse_dd = worse_worst or worse_median
    dd_detail = []
    if worse_median:
        dd_detail.append(f"median {L.median_max_drawdown_pct:.1f}% vs "
                         f"{D.median_max_drawdown_pct:.1f}%")
    if worse_worst:
        dd_detail.append(f"worst {L.worst_max_drawdown_pct:.1f}% vs "
                         f"{D.worst_max_drawdown_pct:.1f}%")
    dd_txt = "; ".join(dd_detail)
    if cmp.lump_win_rate_pct >= 55.0:
        v = (f"LUMP SUM won more often ({cmp.lump_win_rate_pct:.0f}% of start dates, "
             f"median {cmp.median_gap_pct:+.1f}%) — the expected result: cash waiting "
             f"to be deployed misses the market's average upward drift. ")
        if worse_dd:
            v += (f"BUT lump sum's drawdown was deeper ({dd_txt}): DCA is buying you "
                  f"protection against deploying right before a fall, paid for with "
                  f"lower expected wealth. That trade is a preference, not a math error "
                  f"— choose on how much a bad-timing outcome would hurt you, not on "
                  f"which number is bigger.")
        else:
            v += ("DCA did not buy meaningfully better drawdown protection here (neither "
                  "median nor worst case), which is the usual reason to accept its lower "
                  "average — so on this basket there is little case for spreading the "
                  "deployment.")
    elif cmp.lump_win_rate_pct <= 45.0:
        v = (f"DCA won more often ({100 - cmp.lump_win_rate_pct:.0f}% of start dates) — "
             f"the OPPOSITE of the usual finding, which for this basket/window most "
             f"likely reflects a period that fell or chopped rather than a general truth. "
             f"Do not generalize from one market's history; re-check on a different "
             f"window before treating this as a rule.")
    else:
        v = (f"Close to a coin flip ({cmp.lump_win_rate_pct:.0f}% lump-sum wins, median "
             f"gap {cmp.median_gap_pct:+.1f}%). Neither schedule dominates on RETURN for "
             f"this basket and window. ")
        if worse_dd:
            v += (f"The tiebreaker is risk: lump sum's drawdown was deeper ({dd_txt}), so "
                  f"DCA gives up ~nothing in expected wealth here while still smoothing "
                  f"the ride — an unusually favorable setup for spreading the deployment, "
                  f"and worth noting that this is NOT the usual textbook answer.")
        else:
            v += ("Drawdowns were similar too, so pick on behavior, not numbers: DCA if a "
                  "badly-timed lump sum would make you abandon the plan, lump sum if it "
                  "wouldn't.")
    lines.append(f"  READ: {v}")
    return "\n".join(lines)
