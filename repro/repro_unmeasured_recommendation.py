#!/usr/bin/env python3
"""The daily scan recommends BUY without ever saying what a BUY is worth.

Run it:  python repro/repro_unmeasured_recommendation.py

WHAT THIS SHOWS
---------------
Four states of the same screen, in order:

  1. BEFORE — the tail of a real daily run. Nine checkmarks, a score out of
     100, a risk/reward to one decimal. Nothing about the payoff.
  2. AFTER, no measurement on disk — NOT MEASURED, in those words, with the
     command that would produce one. Not "+0.00%".
  3. AFTER, with the real EQUAL_WEIGHT measurement but the LIVE config — the
     number is withheld and the differences are named. This is the system's
     actual state: runner_config.json declares no exit_profile, so the ladder
     is on, holding is 20 days and the entry cutoff is score 60 — while every
     fold table on disk was made under forward_test, holding 60, at score 80.
     They are different strategies on every axis.
  4. AFTER, config and measurement agreed — the number appears, with its
     clustered t, its deflated Sharpe, and the concentration, labelled with
     which arm it belongs to.

The pooled figures in states 3 and 4 are the real ones from the EQUAL_WEIGHT
run: momentum, forward_test, 615 tickers. See the note above RECONSTRUCTED_FOLDS
for which numbers are measured and which are reconstructed, and why the two arms
are kept apart.
"""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for candidate in (ROOT, ROOT.parent):
    if (candidate / "kala").is_dir():
        sys.path.insert(0, str(candidate))
        break
else:
    raise SystemExit(
        "cannot find the kala package next to this script — run it from "
        "the project root: python repro/repro_unmeasured_recommendation.py")

from kala.config import Config, forward_test_config  # noqa: E402
from kala.expectation import live_lines  # noqa: E402

TODAY = date(2026, 8, 23)

BEFORE = """\
TOP PICK: BRIS.JK (Score: 82/100 | ADX: 31 | R:R: 2.4:1)
WORST:    PTPW.JK (Score: 14/100)

Total analyzed: 615 | Safe: 588 | Unsafe: 27 | Suspended: 4

v2.1 FEATURES ACTIVE:
  [x] Time Series Analysis (ROC, slope, acceleration, momentum persistence)
  [x] Relative Strength vs IHSG (outperforming stocks rank higher)
  [x] OBV Smart Money Flow (accumulation vs distribution)
  [x] Momentum-aware RSI (RSI > 70 in strong trend = continuation, not sell)
  [x] Suspension detection (zero volume, price freeze, stale data)
  [x] Liquidity filter (min 100,000 avg daily volume)
  [x] Market regime check (IHSG/JCI trend = BULLISH)
  [x] ADX trend strength + Multi-timeframe confirmation
  [x] ATR-based stop-loss + Risk/Reward ratio"""

# TWO ARMS, and they must not be mixed.
#
# The BASELINE arm is what the headline, the clustered t, the deflated Sharpe
# and the VERDICT are computed on: +1.71%/trade, t 1.92, DSR 0.766.
#
# The concentration facts this audit records — -0.44%/trade excluding fold 10,
# fold 10 at 131.5% of pooled excess P&L, 8 of 14 folds negative — belong to
# the WALK-FORWARD-CHOSEN arm, which pools to +1.27%/trade over 6,082 trades.
# Pairing "-0.44% ex-fold-10" with "+1.71%" reads as one decomposition and is
# two different measurements; the first version of this script did exactly
# that, and so did the ex-best column of the v76 holding sweep.
#
# So the fold rows below reconstruct the CHOSEN arm, and the script prints the
# concentration labelled as that arm. Trade counts are the real ones; the
# per-fold excesses are chosen to reproduce the recorded facts exactly, because
# that run's per-fold excess column is not in front of me. Saying so beats
# quietly presenting invented detail as measurement — the defect this file is
# about. _check() fails the script if the reconstruction stops matching.
RECONSTRUCTED_FOLDS = [
    (348, -3.10), (307, 6.10), (370, -5.50), (471, -4.90), (530, -7.90),
    (323, 6.60), (558, 1.19), (375, 7.70), (346, -2.10), (558, -2.80),
    (542, 18.32), (607, -5.60), (428, 13.00), (182, -1.10),
]

# The chosen arm's recorded facts, which the rows above must reproduce. The
# trade counts are the fold table's and sum to 5,945; the audit quotes the
# chosen arm pooling over 6,082, so `n` is deliberately NOT among the facts
# asserted here — claiming it would be claiming a reconciliation I have not
# done.
RECORDED = {"pooled": 1.27, "ex_best": -0.44, "biggest_fold": 10,
            "negative_folds": 8}


def _check() -> None:
    """Refuse to print numbers that no longer match what was recorded."""
    from kala.expectation import excess_excluding_largest_fold

    ns = [n for n, _ in RECONSTRUCTED_FOLDS]
    pooled = sum(n * e for n, e in RECONSTRUCTED_FOLDS) / sum(ns)
    rows = [{"fold": i, "n": n, "excess_pct": e}
            for i, (n, e) in enumerate(RECONSTRUCTED_FOLDS)]
    ex_best, fold_id = excess_excluding_largest_fold(rows)
    got = {"pooled": round(pooled, 2), "ex_best": round(ex_best, 2),
           "biggest_fold": fold_id,
           "negative_folds": sum(1 for _, e in RECONSTRUCTED_FOLDS if e < 0)}
    if got != RECORDED:
        raise SystemExit(
            f"the reconstructed folds no longer reproduce the recorded run:\n"
            f"  recorded {RECORDED}\n  got      {got}")


MEASUREMENT = {
    "strategy": "momentum",
    "exit_profile": "forward_test",
    # 80, because that is what the run was made at — the headline arm's
    # provenance line records "baseline 80 ... traded 5,241 times".
    "baseline_threshold": 80.0,
    "holding_max_days": 60,
    "benchmark": "EQUAL_WEIGHT",
    "apply_entry_vetoes": True,
    "disabled_vetoes": ["bear", "obv", "parabolic", "rsi", "thin_volume"],
    "n_tickers": 615,
    "measured_at": "2026-08-21",
    "threshold_grid_size": 6,
    "folds": [{"fold": i, "n": n, "excess_pct": e}
              for i, (n, e) in enumerate(RECONSTRUCTED_FOLDS)],
    "pooled_excess_baseline": {"n": 5241, "ev_pct": 1.71, "t_stat": 2.02},
    "pooled_excess_baseline_clustered_t": 1.92,
    "pooled_excess_baseline_dsr": 0.766,
    # The chosen arm, which is the one the fold rows above belong to. Note the
    # different trade count: these are two measurements, not two views of one.
    "pooled_excess_chosen": {"n": 6082, "ev_pct": 1.27, "t_stat": 1.71},
}

# No per-fold BASELINE column — that is the state of all fifteen real tables.
# The block therefore reports the concentration for the CHOSEN arm and labels
# it, rather than subtracting a chosen-arm fold from the baseline headline.

# What runner_config.json says today: no exit_profile, no disabled vetoes.
LIVE_CONFIG_AS_SHIPPED: dict = {}

# What it would say after applying the audit's recommendation.
LIVE_CONFIG_MEASURED = {
    "exit_profile": "forward_test",
    "disabled_entry_vetoes": ["rsi", "parabolic", "obv", "thin_volume", "bear"],
}


def show(title: str, lines) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")
    for line in lines:
        print(line)


def main() -> int:
    _check()
    show("1. BEFORE — what the daily run ends with today", BEFORE.split("\n"))
    print("\n  Nine ticks about what the system is DOING. Nothing about what")
    print("  any of it has been WORTH. Precision about the signal reads as")
    print("  confidence about the payoff.")

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        missing = tmp / "expectation.json"
        show("2. AFTER — nothing measured yet",
             live_lines(LIVE_CONFIG_AS_SHIPPED, Config(), path=missing,
                        today=TODAY))
        print("\n  NOT MEASURED, and it says why that is not a zero. The old")
        print("  screen said nothing at all, which reads as nothing to say.")

        saved = tmp / "expectation.json"
        saved.write_text(json.dumps(MEASUREMENT), encoding="utf-8")

        show("3. AFTER — a measurement exists, but of a DIFFERENT configuration",
             live_lines(LIVE_CONFIG_AS_SHIPPED, Config(), path=saved,
                        today=TODAY))
        print("\n  This is the live system as shipped. The number is withheld")
        print("  because +1.71%/trade describes a 60-day hold at entry score")
        print("  80 with no exit ladder, and this bot runs a 20-day hold at")
        print("  score 60 with the ladder on. Printing it here would be a")
        print("  sourced, specific, wrong figure.")

        show("4. AFTER — config and measurement agree",
             live_lines(LIVE_CONFIG_MEASURED, forward_test_config(),
                        path=saved, today=TODAY))
        print("\n  Now the figure appears — and it is not flattering. That is")
        print("  the point: the user asked why holding produced under 1k IDR,")
        print("  and the honest answer was on disk the whole time.")
        print("\n  Note which arm the concentration is labelled with. The")
        print("  headline is the fixed-baseline arm; the only per-fold excess")
        print("  this table carries is the walk-forward-chosen arm's, and those")
        print("  pool to +1.71% and +1.27% over different trade counts. Earlier")
        print("  versions of this block, and the v76 holding sweep, subtracted")
        print("  one arm's quarter from the other arm's total.")

    print(f"\n{'=' * 78}")
    print("The defect was never a wrong number. It was a screen that gave a")
    print("recommendation and no expectation, in a project whose own audit had")
    print("already measured the expectation and left it in a JSON file the")
    print("daily run does not open.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
