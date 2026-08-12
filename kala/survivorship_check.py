"""
Survivorship-bias check on the core-satellite finding — the test that can
INVALIDATE the strongest result this project has produced.

WHY THIS EXISTS
---------------
The core-satellite study (see PROJECT_STATUS.md) found the user's 8-name
satellite sleeve beat holding XIJI alone in 90% of rolling windows over 8
years. That looked like the one actionable, positive result in the whole
project. But there is an obvious way it could be an illusion, and it was
flagged as a caveat at the time without ever being tested:

**The 8 satellite names were chosen by an assistant, TODAY, from a list of
"well-known, long-established, sharia-verified" IDX companies.** Nobody
selected them on backtested returns — but "well-known and still prominent in
2026" is itself a filter that correlates with "did not collapse between 2016
and 2026." That is textbook survivorship bias, and it would inflate the
sleeve's measured return without any real skill being involved.

THE TEST
--------
If the satellites' edge came from hindsight in PICKING them, then a RANDOM
8-name basket drawn from the sharia universe should mostly NOT beat the core.
If instead the edge came from the core being genuinely weak, then most random
baskets should beat it too — and the hand-picked 8 would be unremarkable
within that distribution.

So: draw many random k-subsets of the universe, blend each with the core
exactly as the real allocation does, and measure what fraction beat core-only.
Then locate the hand-picked basket's PERCENTILE inside that distribution.

  * most random baskets beat core  -> the finding SURVIVES; the driver is the
    core's weakness, not stock selection, and the hand-picked names are not
    special (which is good news for robustness, and means the sleeve does not
    depend on having picked well)
  * few random baskets beat core, and the hand-picked 8 sit far up the
    distribution -> the finding is likely an ARTIFACT of how the names were
    chosen, and must not be acted on
  * in between -> partially real, partially selection; treat with caution

THE CAVEAT THIS TEST CANNOT FIX, STATED PLAINLY
-------------------------------------------------
The random draws come from ``kala.universe.ALL_SHARIA_STOCKS``, which is
TODAY's ISSI constituent list. Companies that were delisted, went bankrupt, or
fell out of the sharia screen between the start of the window and now are
simply absent from it. So the random baskets are themselves drawn from a
survivor-filtered pool — this measures whether the HAND-PICKING added bias on
top of the universe's own bias, not the total bias.

Fixing that properly needs point-in-time ISSI membership history, which this
project does not have (the same structural gap that blocks the fundamental
factors — see PROJECT_STATUS.md). So a "survives" verdict here means "the
hand-picking specifically was not the driver," NOT "there is no survivorship
bias at all." The residual universe-level bias is real, unmeasured, and biases
the result in the optimistic direction. Read any positive result with that
discount applied.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

TRADING_DAYS = 252


@dataclass(frozen=True)
class SurvivorshipResult:
    core_cagr_pct: float
    core_return_per_vol: float
    random_median_cagr_pct: float
    random_median_return_per_vol: float
    pct_random_beating_core_cagr: float      # % of random baskets whose BLEND beat core CAGR
    pct_random_beating_core_retvol: float
    handpicked_cagr_pct: float               # NaN if no hand-picked basket supplied
    handpicked_percentile_cagr: float        # NaN if none; else 0-100 within random draws
    k: int
    n_universe: int
    n_random: int
    n_days: int
    core_weight: float
    note: str = ""


def _align(core: pd.Series, universe: dict[str, pd.Series]) -> pd.DataFrame:
    """Join core + universe names on shared dates. Names with much shorter
    history than the longest are dropped (same guard as the other studies);
    the CORE is exempt, since it is the reference asset being tested."""
    frames = {t: s.dropna() for t, s in universe.items() if s is not None and len(s.dropna())}
    if not frames:
        return pd.DataFrame()
    max_len = max(len(s) for s in frames.values())
    kept = {t: s for t, s in frames.items() if len(s) >= max_len * 0.5}
    kept["__CORE__"] = core.dropna()
    return pd.DataFrame(kept).dropna(how="any")


def _blend_stats(rets: pd.DataFrame, names: list[str], core_weight: float) -> tuple[float, float]:
    """(CAGR %, return/vol) of core_weight*core + (1-core_weight)*equal-weight(names)."""
    sat = rets[names].mean(axis=1)
    blend = core_weight * rets["__CORE__"] + (1.0 - core_weight) * sat
    equity = (1.0 + blend).cumprod()
    years = len(equity) / TRADING_DAYS
    if years <= 0 or equity.iloc[-1] <= 0:
        return 0.0, 0.0
    cagr = equity.iloc[-1] ** (1.0 / years) - 1.0
    vol = float(blend.std() * np.sqrt(TRADING_DAYS))
    return cagr * 100, (cagr / vol if vol > 0 else 0.0)


def check_survivorship(core: pd.Series, universe: dict[str, pd.Series],
                       handpicked: list[str] | None = None,
                       k: int = 8, n_random: int = 300, core_weight: float = 0.73,
                       seed: int = 0) -> SurvivorshipResult:
    """Draw ``n_random`` random k-subsets of ``universe``, blend each with the
    core, and compare against core-only. If ``handpicked`` is given (and its
    names are present in the universe), report where that basket falls inside
    the random distribution."""
    closes = _align(core, universe)
    pool = [c for c in closes.columns if c != "__CORE__"]
    if closes.empty or len(pool) <= k:
        return SurvivorshipResult(
            0, 0, 0, 0, 0, 0, float("nan"), float("nan"),
            k, len(pool), 0, len(closes), core_weight,
            note=f"Need a universe larger than k={k} with overlapping history; "
                 f"have {len(pool)}.")
    if len(closes) < TRADING_DAYS:
        return SurvivorshipResult(
            0, 0, 0, 0, 0, 0, float("nan"), float("nan"),
            k, len(pool), 0, len(closes), core_weight,
            note=f"Only {len(closes)} overlapping days — need at least a year.")

    rets = closes.pct_change().fillna(0.0)

    # core-only reference (blend with core_weight=1 is exactly the core)
    core_equity = (1.0 + rets["__CORE__"]).cumprod()
    years = len(core_equity) / TRADING_DAYS
    core_cagr = (core_equity.iloc[-1] ** (1.0 / years) - 1.0) * 100 if years > 0 else 0.0
    core_vol = float(rets["__CORE__"].std() * np.sqrt(TRADING_DAYS))
    core_rv = (core_cagr / 100 / core_vol) if core_vol > 0 else 0.0

    rng = np.random.default_rng(seed)
    cagrs, rvs = [], []
    for _ in range(n_random):
        picks = list(rng.choice(pool, size=k, replace=False))
        c, rv = _blend_stats(rets, picks, core_weight)
        cagrs.append(c)
        rvs.append(rv)
    cagrs_arr = np.asarray(cagrs)
    rvs_arr = np.asarray(rvs)

    hp_cagr, hp_pct = float("nan"), float("nan")
    if handpicked:
        present = [t for t in handpicked if t in pool]
        if len(present) >= 2:
            hp_cagr, _hp_rv = _blend_stats(rets, present, core_weight)
            hp_pct = float((cagrs_arr < hp_cagr).mean() * 100)

    return SurvivorshipResult(
        core_cagr_pct=core_cagr,
        core_return_per_vol=core_rv,
        random_median_cagr_pct=float(np.median(cagrs_arr)),
        random_median_return_per_vol=float(np.median(rvs_arr)),
        pct_random_beating_core_cagr=float((cagrs_arr > core_cagr).mean() * 100),
        pct_random_beating_core_retvol=float((rvs_arr > core_rv).mean() * 100),
        handpicked_cagr_pct=hp_cagr,
        handpicked_percentile_cagr=hp_pct,
        k=k, n_universe=len(pool), n_random=n_random, n_days=len(closes),
        core_weight=core_weight)


def format_survivorship(r: SurvivorshipResult) -> str:
    """Distribution table + a verdict that says plainly whether the
    core-satellite finding survives, and repeats the bias this cannot fix."""
    if r.note:
        return f"SURVIVORSHIP CHECK — could not run: {r.note}"

    lines = [
        f"SURVIVORSHIP CHECK — {r.n_random} random {r.k}-name baskets from "
        f"{r.n_universe} sharia names, {r.n_days} trading days "
        f"(~{r.n_days / TRADING_DAYS:.1f}y)",
        f"  each blended {r.core_weight * 100:.0f}% core / "
        f"{(1 - r.core_weight) * 100:.0f}% satellites, vs core-only",
        "  Was the satellite edge REAL, or hindsight in how the 8 names were picked?",
        "",
        f"  {'arm':<34}{'CAGR':>10}{'ret/vol':>10}",
        "  " + "-" * 55,
        f"  {'core only':<34}{r.core_cagr_pct:>9.2f}%{r.core_return_per_vol:>10.2f}",
        f"  {'random basket (median draw)':<34}{r.random_median_cagr_pct:>9.2f}%"
        f"{r.random_median_return_per_vol:>10.2f}",
    ]
    if not np.isnan(r.handpicked_cagr_pct):
        lines.append(f"  {'hand-picked 8 (the real basket)':<34}"
                     f"{r.handpicked_cagr_pct:>9.2f}%{'—':>10}")
    lines += [
        "  " + "-" * 55,
        f"  {r.pct_random_beating_core_cagr:.0f}% of RANDOM baskets beat core-only on CAGR "
        f"({r.pct_random_beating_core_retvol:.0f}% on ret/vol).",
    ]
    if not np.isnan(r.handpicked_percentile_cagr):
        lines.append(f"  The hand-picked 8 sit at the "
                     f"{r.handpicked_percentile_cagr:.0f}th percentile of that "
                     f"random distribution.")
    lines.append("")

    pct = r.pct_random_beating_core_cagr
    hp = r.handpicked_percentile_cagr
    if pct >= 70.0:
        v = (f"FINDING SURVIVES. {pct:.0f}% of RANDOMLY chosen baskets also beat "
             f"core-only, so the edge is driven by the CORE BEING WEAK, not by "
             f"clever stock selection. ")
        if not np.isnan(hp) and hp >= 80.0:
            v += (f"The hand-picked 8 are still unusually good ({hp:.0f}th percentile), "
                  f"so some selection luck is present on top — size the sleeve on the "
                  f"RANDOM-basket result, not the hand-picked one, to stay honest. ")
        elif not np.isnan(hp):
            v += (f"The hand-picked 8 are unremarkable within it ({hp:.0f}th percentile) "
                  f"— reassuring: the result does not depend on having picked well. ")
    elif pct <= 40.0:
        v = (f"FINDING IS SUSPECT. Only {pct:.0f}% of random baskets beat core-only, "
             f"so a typical 8-name sleeve does NOT beat the core. ")
        if not np.isnan(hp) and hp >= 70.0:
            v += (f"The hand-picked 8 sit at the {hp:.0f}th percentile — i.e. the "
                  f"original result came mostly from WHICH names were chosen, with "
                  f"today's hindsight, not from any repeatable property. Do NOT size up "
                  f"the sleeve on that basis. ")
        else:
            v += ("Treat the earlier core-satellite result as unconfirmed. ")
    else:
        v = (f"MIXED. {pct:.0f}% of random baskets beat core-only — the core's weakness "
             f"is real but only part of the story, and selection matters too. ")
        if not np.isnan(hp):
            v += f"Hand-picked 8 at the {hp:.0f}th percentile. "
        v += "Treat the sleeve as plausibly but not robustly favourable. "

    v += ("REMEMBER what this cannot fix: the random draws come from TODAY's sharia "
          "list, so companies that died or fell out of the screen are already absent. "
          "This measures whether the hand-picking added bias ON TOP of the universe's "
          "own survivorship bias — the residual is real, unmeasured, and flatters every "
          "arm here including the core comparison.")
    lines.append(f"  READ: {v}")
    return "\n".join(lines)
