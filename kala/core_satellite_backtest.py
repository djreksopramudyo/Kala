"""
Core-satellite study — does a concentrated hand-picked "satellite" sleeve
earn its keep next to a broad index "core", or would putting that money in
the core too have been better?

WHY THIS IS THE RIGHT QUESTION TO ASK NOW
-------------------------------------------
This follows directly from the holdings-count curve (see PROJECT_STATUS.md):
risk kept falling as the number of names held rose, and had NOT flattened
even at K=16. That is prior evidence that a CONCENTRATED sleeve of ~8 names
carries meaningfully more risk than a broad index — but risk alone doesn't
settle it. The satellite sleeve is only worth holding if it pays for that
extra risk with extra return. Nothing in this project has tested that, and
it is the one remaining question whose answer could actually change what the
portfolio holds (as opposed to the thirteen signal studies, which all came
back null and changed nothing).

It is also, unlike every signal hypothesis, a question with no prediction in
it: both arms are buy-and-hold, so there is no timing edge to be wrong about
and no beta-capture trap to fall into. It's a pure allocation comparison.

THE THREE ARMS
--------------
  * ``core_only``      — 100% in the broad index/ETF
  * ``blend``          — ``core_weight`` in the index, the rest equal-weight
                         across the satellite names (the real-world structure)
  * ``satellite_only`` — 100% equal-weight across the satellite names

Comparing all three separates two different things that are easy to conflate:
whether the satellites are good ON THEIR OWN (satellite_only vs core_only),
and whether adding them to a core actually improves the COMBINED portfolio
(blend vs core_only) — which is the decision actually on the table.

ROLLING WINDOWS, NOT ONE NUMBER
---------------------------------
A single full-sample CAGR comparison is one draw of luck. As with the
deployment study, the blend-vs-core comparison is also run across many
rolling sub-windows, reporting how OFTEN the blend won rather than only by
how much on one path. A sleeve that wins on the full sample but loses in
most sub-windows is riding one or two lucky episodes, and the win rate
exposes that.

THE HISTORY CAVEAT THAT MATTERS HERE
--------------------------------------
Index ETFs on IDX are relatively young. If the core ticker has much less
history than the satellite names, the comparison silently shortens to the
core's lifetime — and a short window is exactly where a concentrated sleeve
can look good or bad by luck. The comparison therefore reports the actual
overlapping window length prominently and warns when it is short, rather
than letting a confident-looking table hide a 2-year sample. (It does NOT
apply the usual short-history DROP filter to the core: the core is the
reference asset, so if it's short, the honest response is a loud caveat,
not silently excluding the thing being tested.)

HONEST PRIOR
------------
Concentration is not compensated on average. The academic default (and the
holdings-curve evidence above) is that a handful of names carries
substantial idiosyncratic risk that the market does not pay you to bear.
So the expected result is that the satellite sleeve adds volatility and
drawdown without reliably adding return — in which case the simplest
improvement available to this portfolio is to hold less of it, not to pick
different names for it (basket selection was already tested and came back
null). If the sleeve DOES add risk-adjusted return over a decent window and
a majority of sub-windows, that would be a genuine finding worth acting on.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

TRADING_DAYS = 252
SHORT_WINDOW_YEARS = 3.0      # below this, the verdict shouts about sample size


@dataclass(frozen=True)
class ArmStats:
    cagr_pct: float
    ann_vol_pct: float
    max_drawdown_pct: float
    return_per_vol: float


@dataclass(frozen=True)
class CoreSatelliteComparison:
    core_only: ArmStats
    blend: ArmStats
    satellite_only: ArmStats
    core_weight: float
    n_satellites: int
    n_days: int
    blend_win_rate_pct: float      # % of rolling sub-windows where blend beat core
    n_subwindows: int
    subwindow_days: int
    core_ticker: str = ""
    note: str = ""


def _align(core: pd.Series, satellites: dict[str, pd.Series]) -> pd.DataFrame:
    """Join the core and every satellite on shared dates. The core is NOT
    subject to a short-history drop filter — it's the reference asset, so a
    short core shortens the study and gets a loud caveat instead."""
    frames = {"__CORE__": core.dropna()}
    for t, s in satellites.items():
        if s is not None and len(s.dropna()):
            frames[t] = s.dropna()
    if len(frames) < 2:
        return pd.DataFrame()
    return pd.DataFrame(frames).dropna(how="any")


def _stats(equity: pd.Series) -> ArmStats:
    equity = equity.dropna()
    if len(equity) < 2 or equity.iloc[0] <= 0:
        return ArmStats(0.0, 0.0, 0.0, 0.0)
    years = len(equity) / TRADING_DAYS
    cagr = (equity.iloc[-1] / equity.iloc[0]) ** (1.0 / years) - 1.0 if years > 0 else 0.0
    daily = equity.pct_change().dropna()
    vol = float(daily.std() * np.sqrt(TRADING_DAYS)) if len(daily) else 0.0
    dd = float((equity / equity.cummax() - 1.0).min())
    rpv = (cagr / vol) if vol > 0 else 0.0
    return ArmStats(cagr * 100, vol * 100, dd * 100, rpv)


def _arm_returns(closes: pd.DataFrame, core_weight: float) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Daily return streams for the three arms. Satellites are equal-weight,
    daily-rebalanced (the weighting question is a separate, already-answered
    study — equal weight was the winner there, so it's the right base here)."""
    rets = closes.pct_change().fillna(0.0)
    core_ret = rets["__CORE__"]
    sat_cols = [c for c in closes.columns if c != "__CORE__"]
    sat_ret = rets[sat_cols].mean(axis=1)
    blend_ret = core_weight * core_ret + (1.0 - core_weight) * sat_ret
    return core_ret, blend_ret, sat_ret


def compare_core_satellite(core: pd.Series, satellites: dict[str, pd.Series],
                           core_weight: float = 0.73,
                           subwindow_days: int = 504,
                           step_days: int = 21,
                           core_ticker: str = "core") -> CoreSatelliteComparison:
    """Compare holding only the core index, a core+satellite blend, and only
    the satellites. ``core_weight`` defaults to 0.73 — the user's actual
    EQUITY-sleeve split (55% XIJI vs 20% satellites normalizes to 73/27
    within the equity portion; the remaining 25% sukuk/cash is a different
    asset class and isn't part of this comparison). ``subwindow_days``
    default 504 ≈ 2y for the rolling win-rate check."""
    closes = _align(core, satellites)
    n_sat = max(0, closes.shape[1] - 1)
    if closes.empty or n_sat < 1:
        return CoreSatelliteComparison(
            _stats(pd.Series(dtype=float)), _stats(pd.Series(dtype=float)),
            _stats(pd.Series(dtype=float)), core_weight, n_sat, len(closes),
            0.0, 0, subwindow_days, core_ticker,
            note="Need the core plus at least one satellite with overlapping history.")
    if len(closes) < subwindow_days + step_days:
        return CoreSatelliteComparison(
            _stats(pd.Series(dtype=float)), _stats(pd.Series(dtype=float)),
            _stats(pd.Series(dtype=float)), core_weight, n_sat, len(closes),
            0.0, 0, subwindow_days, core_ticker,
            note=(f"Only {len(closes)} overlapping days — the core and satellites "
                  f"share too little history for a {subwindow_days}-day rolling check. "
                  f"(Is the core ETF newer than the satellite names?)"))

    core_ret, blend_ret, sat_ret = _arm_returns(closes, core_weight)
    core_stats = _stats((1.0 + core_ret).cumprod())
    blend_stats = _stats((1.0 + blend_ret).cumprod())
    sat_stats = _stats((1.0 + sat_ret).cumprod())

    # rolling sub-windows: how OFTEN does the blend beat pure core?
    wins = 0
    total = 0
    cr = core_ret.to_numpy()
    br = blend_ret.to_numpy()
    for start in range(0, len(cr) - subwindow_days, max(1, step_days)):
        c = float(np.prod(1.0 + cr[start:start + subwindow_days]))
        b = float(np.prod(1.0 + br[start:start + subwindow_days]))
        wins += int(b > c)
        total += 1
    win_rate = (wins / total * 100) if total else 0.0

    return CoreSatelliteComparison(
        core_only=core_stats, blend=blend_stats, satellite_only=sat_stats,
        core_weight=core_weight, n_satellites=n_sat, n_days=len(closes),
        blend_win_rate_pct=win_rate, n_subwindows=total,
        subwindow_days=subwindow_days, core_ticker=core_ticker)


@dataclass(frozen=True)
class SizingPoint:
    core_weight: float
    cagr_pct: float
    ann_vol_pct: float
    max_drawdown_pct: float
    return_per_vol: float


@dataclass(frozen=True)
class SizingSweep:
    points: tuple = ()
    n_days: int = 0
    n_satellites: int = 0
    core_ticker: str = ""
    note: str = ""


def sweep_core_weight(core: pd.Series, satellites: dict[str, pd.Series],
                      weights=(0.0, 0.25, 0.5, 0.73, 0.9, 1.0),
                      core_ticker: str = "core") -> SizingSweep:
    """How does the whole risk/return picture move as the core share changes?
    The core-satellite study answers "is the sleeve worth holding at all";
    this answers "and how much of it", which is the natural follow-up if the
    sleeve earned its risk.

    HONEST WARNING about how to read the output: this is a sweep over ONE
    realized history, so the best-looking weight is by construction the one
    that happened to suit the past — reading the argmax off this table and
    adopting it is textbook overfitting. It is useful for seeing the SHAPE of
    the tradeoff (how fast risk rises as you concentrate), not for picking an
    optimum. The formatter says so rather than crowning a winner."""
    closes = _align(core, satellites)
    n_sat = max(0, closes.shape[1] - 1)
    if closes.empty or n_sat < 1:
        return SizingSweep(note="Need the core plus at least one satellite "
                                "with overlapping history.")
    pts = []
    for w in weights:
        _c, blend_ret, _s = _arm_returns(closes, w)
        st = _stats((1.0 + blend_ret).cumprod())
        pts.append(SizingPoint(w, st.cagr_pct, st.ann_vol_pct,
                               st.max_drawdown_pct, st.return_per_vol))
    return SizingSweep(points=tuple(pts), n_days=len(closes),
                       n_satellites=n_sat, core_ticker=core_ticker)


def format_sizing_sweep(sw: SizingSweep) -> str:
    if sw.note:
        return f"SIZING SWEEP — could not run: {sw.note}"
    lines = [
        f"SIZING SWEEP — core '{sw.core_ticker}' + {sw.n_satellites} satellites, "
        f"{sw.n_days} trading days (~{sw.n_days / TRADING_DAYS:.1f}y)",
        "  How the picture moves as the CORE share changes (0% = all satellites).",
        "",
        f"  {'core weight':<14}{'CAGR':>10}{'vol':>9}{'maxDD':>10}{'ret/vol':>10}",
        "  " + "-" * 54,
    ]
    for p in sw.points:
        lines.append(f"  {p.core_weight * 100:>6.0f}%       {p.cagr_pct:>9.2f}%"
                     f"{p.ann_vol_pct:>8.1f}%{p.max_drawdown_pct:>9.1f}%"
                     f"{p.return_per_vol:>10.2f}")
    lines.append("  " + "-" * 54)
    lines.append(
        "  READ: Use this for the SHAPE of the tradeoff, not to pick a number. "
        "The best-looking weight here is the one that happened to fit this one "
        "realized history — adopting it because it tops this table is exactly "
        "the overfitting this project spent thirteen failed studies learning to "
        "avoid. What IS safe to take from it: how steeply risk rises as you "
        "concentrate, and whether the tradeoff is gentle (weight barely matters, "
        "so pick for simplicity/cost) or sharp (weight matters, so stay near a "
        "deliberately chosen policy rather than drifting).")
    return "\n".join(lines)


def format_core_satellite(cmp: CoreSatelliteComparison) -> str:
    """Table + a verdict that asks the only question that matters: did the
    concentrated sleeve PAY for the extra risk it carries?"""
    if cmp.note:
        return f"CORE-SATELLITE STUDY — could not run: {cmp.note}"

    c, b, s = cmp.core_only, cmp.blend, cmp.satellite_only
    years = cmp.n_days / TRADING_DAYS
    lines = [
        f"CORE-SATELLITE STUDY — core '{cmp.core_ticker}' + {cmp.n_satellites} satellite "
        f"names, {cmp.n_days} trading days (~{years:.1f}y)",
        f"  blend = {cmp.core_weight * 100:.0f}% core / "
        f"{(1 - cmp.core_weight) * 100:.0f}% satellites (equal-weight) | "
        f"rolling check: {cmp.n_subwindows} windows of {cmp.subwindow_days}d",
        "  Does the concentrated sleeve EARN the extra risk it carries?",
        "",
        f"  {'arm':<22}{'CAGR':>9}{'vol':>8}{'maxDD':>9}{'ret/vol':>9}",
        "  " + "-" * 57,
        f"  {'core only (100%)':<22}{c.cagr_pct:>8.2f}%{c.ann_vol_pct:>7.1f}%"
        f"{c.max_drawdown_pct:>8.1f}%{c.return_per_vol:>9.2f}",
        f"  {'blend (core+sat)':<22}{b.cagr_pct:>8.2f}%{b.ann_vol_pct:>7.1f}%"
        f"{b.max_drawdown_pct:>8.1f}%{b.return_per_vol:>9.2f}",
        f"  {'satellites only':<22}{s.cagr_pct:>8.2f}%{s.ann_vol_pct:>7.1f}%"
        f"{s.max_drawdown_pct:>8.1f}%{s.return_per_vol:>9.2f}",
        "  " + "-" * 57,
        f"  Blend beat core-only in {cmp.blend_win_rate_pct:.0f}% of "
        f"{cmp.subwindow_days}-day rolling windows.",
        "",
    ]

    rv_gain = b.return_per_vol - c.return_per_vol
    parts = []
    if years < SHORT_WINDOW_YEARS:
        parts.append(f"⚠ SAMPLE IS SHORT (~{years:.1f}y) — most likely the core ETF is "
                     f"younger than the satellite names, which caps the overlap. Treat "
                     f"everything below as indicative, not settled; a concentrated sleeve "
                     f"can easily look good or bad by luck over this span.")

    if rv_gain > 0.05 and cmp.blend_win_rate_pct >= 55.0:
        parts.append(f"The satellite sleeve EARNED its risk here: blend ret/vol "
                     f"{rv_gain:+.2f} vs core-only, and it won "
                     f"{cmp.blend_win_rate_pct:.0f}% of rolling windows — consistent, not "
                     f"one lucky episode. Worth keeping, though check whether the edge "
                     f"comes from a single name before scaling it up.")
    elif rv_gain < -0.05 or cmp.blend_win_rate_pct <= 45.0:
        parts.append(f"The satellite sleeve did NOT earn its risk: blend ret/vol "
                     f"{rv_gain:+.2f} vs core-only, winning only "
                     f"{cmp.blend_win_rate_pct:.0f}% of rolling windows. The concentrated "
                     f"names added volatility/drawdown without paying for it — consistent "
                     f"with the holdings-count curve, which showed risk still falling with "
                     f"MORE names. The simplest available improvement is to hold more core "
                     f"and less satellite; note that picking DIFFERENT satellite names was "
                     f"already tested (basket selection) and came back null, so 'pick "
                     f"better' is not the fix.")
    else:
        parts.append(f"A wash: blend ret/vol {rv_gain:+.2f} vs core-only, winning "
                     f"{cmp.blend_win_rate_pct:.0f}% of rolling windows. The sleeve neither "
                     f"clearly helped nor hurt on risk-adjusted terms. Since it costs real "
                     f"effort and transaction costs to maintain 8 individual positions, "
                     f"'no measurable benefit' is itself an argument for simplifying "
                     f"toward the core.")
    lines.append(f"  READ: {' '.join(parts)}")
    return "\n".join(lines)
