"""A stop running on the fallback must not be labelled like the real one.

``governing_stop`` returns ``(stop, phase, label)`` and the label was
``"fixed/atr stop"`` in every phase-1 case — whether the ATR stop was
computed, whether the hard floor overrode it, or whether there was no ATR at
all and the fallback ran. Three different rules, one string.

That mattered because it was not hypothetical: every one of the 9 open
positions in the live book has ``entry_atr=None``. The volatility-scaled stop
the strategy specifies is not running on any of them, the hard floor is, and
nothing on the per-position display said so.

The fallback itself is correct and is not changed here. Only its name, and a
book-level count so the state is visible without inspecting each position.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kala.config import RiskConfig  # noqa: E402
from kala.discipline import atr_coverage, format_atr_coverage  # noqa: E402
from kala.exits import governing_stop  # noqa: E402

FLAT = RiskConfig(trailing_enabled=False, hard_stop_pct=-5.0, atr_stop_multiple=2.0)
ENTRY = 1000.0
HARD = 950.0            # entry * (1 - 5%)


def test_the_three_phase_one_outcomes_have_three_different_labels():
    no_atr = governing_stop(ENTRY, ENTRY, None, FLAT)
    tight = governing_stop(ENTRY, ENTRY, 5.0, FLAT)     # 2*5 = 10 -> stop 990
    wide = governing_stop(ENTRY, ENTRY, 50.0, FLAT)     # 2*50 = 100 -> floored

    labels = {no_atr[2], tight[2], wide[2]}
    assert len(labels) == 3, f"labels collapsed: {labels}"


def test_a_missing_atr_says_so_in_the_label():
    stop, phase, label = governing_stop(ENTRY, ENTRY, None, FLAT)
    assert stop == HARD          # behaviour unchanged: the safe fallback
    assert phase == 1
    assert "NO ATR" in label


def test_a_live_atr_stop_is_labelled_as_the_atr_stop():
    stop, _, label = governing_stop(ENTRY, ENTRY, 5.0, FLAT)
    assert stop == 990.0         # non-vacuity: the ATR stop really is governing
    assert label == "atr stop"
    assert "NO ATR" not in label


def test_the_floor_overriding_a_wide_atr_stop_is_its_own_case():
    stop, _, label = governing_stop(ENTRY, ENTRY, 50.0, FLAT)
    assert stop == HARD
    assert "floor" in label
    assert "NO ATR" not in label      # ATR existed; it was just too wide


def test_nan_atr_is_treated_as_missing_not_as_a_number():
    _, _, label = governing_stop(ENTRY, ENTRY, float("nan"), FLAT)
    assert "NO ATR" in label


def test_the_trailing_path_carries_the_same_label_when_it_is_in_phase_one():
    trailing = RiskConfig(trailing_enabled=True, hard_stop_pct=-5.0,
                          atr_stop_multiple=2.0, breakeven_trigger_pct=4.0)
    # peak == entry, so no trigger has fired: still phase 1.
    stop, phase, label = governing_stop(ENTRY, ENTRY, None, trailing)
    assert phase == 1 and stop == HARD
    assert "NO ATR" in label


def test_a_higher_phase_still_reports_its_own_label():
    """Naming phase 1 must not overwrite the trailing labels."""
    trailing = RiskConfig(trailing_enabled=True, hard_stop_pct=-5.0,
                          atr_stop_multiple=2.0, breakeven_trigger_pct=4.0,
                          trail_start_pct=10.0)
    _, phase, label = governing_stop(ENTRY, 1050.0, None, trailing)   # +5% peak
    assert phase == 2
    assert label == "breakeven"


# ---- book-level coverage --------------------------------------------------

def test_coverage_counts_positions_without_atr():
    c = atr_coverage({"A.JK": {"entry_atr": None}, "B.JK": {"entry_atr": 12.5},
                      "C.JK": {"entry_atr": float("nan")}})
    assert c.n_total == 3
    assert c.n_missing == 2
    assert c.missing == ["A.JK", "C.JK"]
    assert abs(c.pct_missing - 66.667) < 0.01


def test_coverage_reads_objects_as_well_as_dicts():
    class P:
        entry_atr = None
    c = atr_coverage({"A.JK": P()})
    assert c.n_missing == 1


def test_a_fully_covered_book_reports_no_missing_names():
    c = atr_coverage({"A.JK": {"entry_atr": 1.0}})
    assert c.n_missing == 0
    text = format_atr_coverage(c)
    assert "without entry_atr: 0" in text
    assert "hard-stop floor" not in text     # no warning when there is nothing wrong


def test_the_report_names_the_affected_tickers():
    c = atr_coverage({"AADI.JK": {"entry_atr": None}, "OK.JK": {"entry_atr": 2.0}})
    text = format_atr_coverage(c)
    assert "AADI.JK" in text
    assert "not the" in text and "rule that was tested" in text


def test_an_empty_book_says_nothing():
    assert format_atr_coverage(atr_coverage({})) == ""


def test_discipline_report_prints_atr_coverage():
    src = (ROOT / "discipline_report.py").read_text(encoding="utf-8")
    assert "format_atr_coverage(atr_coverage(positions))" in src
    assert '_state.get("positions", {})' in src
