#!/usr/bin/env python3
"""A mistyped --benchmark used to delete the alpha check and leave the verdict.

Run:  python repro_missing_benchmark.py

THE FAILURE (fixed; this script is the regression demonstration)
---------------------------------------------------------------
`--benchmark` accepts any string. If the ticker does not resolve on yfinance,
`run_walkforward.py` prints a WARNING **to stderr** and carries on. What used
to land on stdout was a complete-looking report:

    VERDICT: EDGE CONFIRMED OOS — positive EV, statistically distinguishable...

...and NO ALPHA CHECK section at all, because `summary_text()` gates that whole
block on `pooled_excess_baseline["n"] > 0` and had no else branch.

The alpha check is what distinguishes stock-picking from market exposure — it
is the measurement that overturned the exit-ladder result. Its absence was
silent, and a missing section is far harder to notice than a wrong number.
Redirect stdout to a log (`> run.log`) and the stderr warning is gone too,
leaving a saved report that reads as a clean confirmed edge.

A test asserted this silence was correct (`assert "ALPHA" not in text`,
"additive and opt-in"), so the suite was holding the behaviour in place.

THE FIX
-------
The raw verdict is still printed — it is a real measurement — but it is
labelled `VERDICT (raw, vs cash)`, and an explicit `ALPHA CHECK: NOT RUN`
block names the reason it is missing and the usual cause.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
# Works whether this script sits beside the package or one level below it
# (the shipped tree puts it in Kala/repro/ with the package at Kala/kala/).
for _cand in (ROOT, ROOT.parent, ROOT.parent / "aug"):
    if (_cand / "kala").is_dir():
        sys.path.insert(0, str(_cand))
        break
else:
    raise SystemExit(
        f"cannot find the kala package near {ROOT}. Run this from inside "
        f"the project tree.")

from kala.walkforward import WalkForwardReport  # noqa: E402


def stats(n, ev, t):
    return {"n": n, "ev_pct": ev, "median_pct": ev / 2, "win_rate_pct": 40.0,
            "profit_factor": 1.4, "t_stat": t}


def build(with_benchmark: bool) -> WalkForwardReport:
    r = WalkForwardReport(folds=[], baseline_threshold=80.0)
    r.pooled_chosen = stats(5600, 4.70, 5.1)
    r.pooled_baseline = stats(5241, 4.31, 4.8)
    if with_benchmark:
        r.pooled_excess_chosen = stats(5600, 2.90, 4.3)
        r.pooled_excess_baseline = stats(5241, 2.71, 4.1)
        r.pooled_excess_clustered_t = 4.31
    return r


print(__doc__)
for label, flag in (("BENCHMARK RESOLVED (healthy)", True),
                    ("BENCHMARK MISTYPED / DELISTED (the bug)", False)):
    print("=" * 72)
    print(label)
    print("=" * 72)
    text = build(flag).summary_text()
    print(text)
    print()
    ran_alpha = "ALPHA VERDICT" in text
    said_skipped = "ALPHA CHECK: NOT RUN" in text
    raw_labelled = "VERDICT (raw, vs cash)" in text
    print(f"  -> alpha check actually ran        : {ran_alpha}")
    print(f"  -> says explicitly it was SKIPPED  : {said_skipped}")
    print(f"  -> raw verdict labelled as raw     : {raw_labelled}")
    assert raw_labelled, "the raw verdict must say it is raw"
    assert ran_alpha != said_skipped, (
        "exactly one of 'ran' / 'skipped' must be true — otherwise the report "
        "is either silent about a skip or claiming a skip that did not happen")
    print()

print("=" * 72)
print("""WHAT TO LOOK FOR
  Before the fix, the two reports differed only by a MISSING section: both
  ended on a confident VERDICT line, and nothing on stdout said that one of
  them had never checked whether its edge was alpha or beta.

  After the fix, the second report says so in the report itself, so a saved
  log carries the reason the alpha check is not there.

  The assertions above fail if either half regresses: if the skip goes silent
  again, or if the notice starts firing on runs that did compute excess.""")
