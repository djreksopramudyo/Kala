"""The daily screen must say what a BUY has been measured to be worth — or say
that it has not been measured, in those words, and never as +0.00%.

Every test here calls the renderer and reads what a user would read. None of
them greps a source file: the defect this whole module exists to prevent is a
number that is present, precise, and about something else.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kala.expectation import (  # noqa: E402
    DEFAULT_PATH,
    STALE_DAYS,
    LiveSetup,
    block,
    describe,
    excess_excluding_largest_fold,
    live_lines,
    load,
    measured_vetoes_off,
    mismatches,
)

TODAY = date(2026, 8, 23)
LIVE = LiveSetup(holding_max_days=60, baseline_threshold=60.0,
                 disabled_vetoes=(), exit_profile="forward_test")


def _table(**over):
    """A saved fold table that MATCHES ``LIVE`` unless overridden."""
    t = {
        "strategy": "momentum",
        "exit_profile": "forward_test",
        "baseline_threshold": 60.0,
        "holding_max_days": 60,
        "benchmark": "EQUAL_WEIGHT",
        "apply_entry_vetoes": True,
        "disabled_vetoes": [],
        "n_tickers": 615,
        "measured_at": "2026-08-21",
        "threshold_grid_size": 6,
        "spread_mode": "flat",   # matches LIVE; overridden per-test

        # Both arms. The CHOSEN column is deliberately 100 points higher on
        # every fold so a decomposition that reads the wrong arm cannot land
        # on the right answer by accident.
        "folds": [
            {"fold": 0, "n": 200, "excess_pct": 99.0,
             "n_baseline": 100, "excess_baseline_pct": -1.0},
            {"fold": 1, "n": 240, "excess_pct": 100.5,
             "n_baseline": 120, "excess_baseline_pct": 0.5},
            {"fold": 2, "n": 180, "excess_pct": 108.0,
             "n_baseline": 90, "excess_baseline_pct": 8.0},
        ],
        "pooled_excess_chosen": {"n": 620, "ev_pct": 101.3},
        "pooled_excess_baseline": {"n": 310, "ev_pct": 1.71, "t_stat": 2.4},
        "pooled_excess_baseline_clustered_t": 1.92,
        "pooled_excess_baseline_dsr": 0.766,
    }
    t.update(over)
    return t


def _write(tmp_path, **over):
    p = tmp_path / "expectation.json"
    p.write_text(json.dumps(_table(**over)), encoding="utf-8")
    return p


def _text(lines):
    return "\n".join(lines)


def _has_per_trade_figure(lines):
    """Is a '%/trade' number on screen at all?

    The non-vacuity guard for every withholding test below: it is not enough
    that a warning appears, the number must be ABSENT. A block that printed
    both the refusal and the figure would pass a 'warning present' assertion
    while doing exactly the thing the refusal exists to prevent.
    """
    return any("%/trade" in ln for ln in lines)


# ---------------------------------------------------------------------------
# no measurement is not a measurement of zero
# ---------------------------------------------------------------------------

def test_a_missing_file_reads_as_not_measured_not_as_zero(tmp_path):
    lines = block(LIVE, path=tmp_path / "nope.json", today=TODAY)
    text = _text(lines)
    assert "NOT MEASURED" in text
    assert "not the same as an expectation of zero" in text.lower()
    assert not _has_per_trade_figure(lines), text
    assert "0.00" not in text, "a missing measurement rendered as a number"


def test_unreadable_and_malformed_tables_are_treated_as_absent(tmp_path):
    bad = tmp_path / "expectation.json"
    bad.write_text("{not json", encoding="utf-8")
    assert load(bad) is None
    assert "NOT MEASURED" in _text(block(LIVE, path=bad, today=TODAY))


def test_a_json_array_is_not_accepted_as_a_measurement(tmp_path):
    """A partial read must not present as a table with everything missing."""
    p = tmp_path / "expectation.json"
    p.write_text("[]", encoding="utf-8")
    assert load(p) is None


def test_the_not_measured_block_says_how_to_measure_it(tmp_path):
    text = _text(block(LIVE, path=tmp_path / "nope.json", today=TODAY))
    assert "run_walkforward.py" in text
    assert "--save-folds" in text
    assert "--benchmark" in text


def test_the_default_path_is_where_the_daily_run_looks():
    assert DEFAULT_PATH.endswith(".json")


# ---------------------------------------------------------------------------
# a matching measurement is reported in full
# ---------------------------------------------------------------------------

def test_a_matching_measurement_puts_the_numbers_on_screen(tmp_path):
    lines = block(LIVE, path=_write(tmp_path), today=TODAY)
    text = _text(lines)
    assert "+1.71%/trade" in text
    assert "clustered t +1.92" in text
    assert "0.766" in text
    assert "NOT APPLICABLE" not in text
    assert "NOT MEASURED" not in text


def test_it_names_what_was_measured(tmp_path):
    text = _text(block(LIVE, path=_write(tmp_path), today=TODAY))
    for token in ("momentum", "forward_test", "hold 60d", "EQUAL_WEIGHT",
                  "615 tickers", "3 folds", "310 pooled OOS trades"):
        assert token in text, f"{token} missing from the provenance line"


def test_it_reports_the_concentration_alongside_the_headline(tmp_path):
    """+1.71% without 'and -0.44% minus one fold' is half a measurement."""
    lines = block(LIVE, path=_write(tmp_path), today=TODAY)
    text = _text(lines)
    assert "excluding the biggest single fold (#2)" in text
    # (100*-1.0 + 120*0.5) / 220 = -0.1818...
    assert "-0.18%/trade" in text
    assert "1 of 3 folds negative" in text


def test_the_headline_and_the_ex_best_figure_are_not_the_same_number(tmp_path):
    """Guards the case where the concentration line silently echoes the
    headline — which is what a broken exclusion would look like."""
    text = _text(block(LIVE, path=_write(tmp_path), today=TODAY))
    assert text.count("+1.71%/trade") == 1


# ---------------------------------------------------------------------------
# a measurement of a different configuration is withheld
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("over,field", [
    ({"holding_max_days": 90}, "holding_max_days"),
    ({"baseline_threshold": 80.0}, "baseline_threshold"),
    ({"disabled_vetoes": ["rsi"]}, "vetoes disabled"),
    ({"exit_profile": "legacy"}, "exit_profile"),
])
def test_a_binding_difference_withholds_the_number(tmp_path, over, field):
    lines = block(LIVE, path=_write(tmp_path, **over), today=TODAY)
    text = _text(lines)
    assert "NOT APPLICABLE" in text
    assert field in text, "the block must name WHICH field differs"
    assert not _has_per_trade_figure(lines), (
        "the excess figure was printed beside signals it does not describe")


def test_the_no_veto_arm_does_not_pass_as_the_all_veto_live_setting(tmp_path):
    """The trap every fold table on disk is sitting in.

    A run made WITHOUT --apply-entry-vetoes applied no vetoes at all and
    records ``disabled_vetoes: []`` — byte-identical to a full-veto run's
    record. Compared on that field alone the no-veto arm matches a live bot
    running all five, and those two arms differ by 4.23%/trade: +1.71 against
    -2.52. It is the single most misleading number this module could print.
    """
    lines = block(LIVE, path=_write(tmp_path, apply_entry_vetoes=False),
                  today=TODAY)
    text = _text(lines)
    assert "NOT APPLICABLE" in text
    assert not _has_per_trade_figure(lines)
    m = load(_write(tmp_path, apply_entry_vetoes=False))
    assert measured_vetoes_off(m) == ("bear", "obv", "parabolic", "rsi",
                                      "thin_volume")


def test_a_no_veto_run_does_match_a_no_veto_live_setting(tmp_path):
    """Non-vacuity: the check above must not refuse everything.

    Applying the measured-best configuration is the whole point of having
    measured it, and a block that withheld the number afterwards would make
    the good setting look unmeasured.
    """
    live_off = LiveSetup(60, 60.0, ("bear", "obv", "parabolic", "rsi",
                                    "thin_volume"), exit_profile="forward_test")
    lines = block(live_off, path=_write(tmp_path, apply_entry_vetoes=False),
                  today=TODAY)
    assert "NOT APPLICABLE" not in _text(lines)
    assert _has_per_trade_figure(lines)


def test_a_table_that_never_recorded_the_veto_arm_is_not_assumed_to_match(tmp_path):
    t = _table()
    del t["apply_entry_vetoes"]
    p = tmp_path / "expectation.json"
    p.write_text(json.dumps(t), encoding="utf-8")
    lines = block(LIVE, path=p, today=TODAY)
    assert "not recorded" in _text(lines)
    assert not _has_per_trade_figure(lines)


def test_a_matching_setup_reports_no_mismatches(tmp_path):
    assert mismatches(load(_write(tmp_path)), LIVE) == []


def test_the_threshold_comparison_tolerates_float_representation(tmp_path):
    """60 and 60.0 are the same threshold; a spurious refusal is also a bug."""
    assert mismatches(load(_write(tmp_path, baseline_threshold=60)), LIVE) == []


# ---------------------------------------------------------------------------
# a run with no benchmark has no excess column
# ---------------------------------------------------------------------------

def test_a_run_without_a_benchmark_says_so_instead_of_showing_zero(tmp_path):
    p = _write(tmp_path, benchmark=None, pooled_excess_baseline={},
               pooled_excess_baseline_clustered_t=None,
               pooled_excess_baseline_dsr=None)
    lines = block(LIVE, path=p, today=TODAY)
    text = _text(lines)
    assert "NOT MEASURED in this run" in text
    assert "0.00" not in text
    assert not _has_per_trade_figure(lines)


def test_zero_trades_is_not_reported_as_a_zero_edge(tmp_path):
    p = _write(tmp_path, pooled_excess_baseline={"n": 0, "ev_pct": 0.0})
    assert load(p).excess_pct is None


# ---------------------------------------------------------------------------
# staleness, from the recorded stamp and nothing else
# ---------------------------------------------------------------------------

def test_a_recent_measurement_shows_its_age_and_is_not_called_stale(tmp_path):
    text = _text(block(LIVE, path=_write(tmp_path), today=TODAY))
    assert "measured 2026-08-21 (2d ago)" in text
    assert "STALE" not in text


def test_an_old_measurement_is_called_stale(tmp_path):
    text = _text(block(LIVE, path=_write(tmp_path, measured_at="2025-01-01"),
                       today=TODAY))
    assert "STALE" in text
    assert str(STALE_DAYS) in text


def test_a_table_with_no_stamp_says_the_date_is_not_recorded(tmp_path):
    t = _table()
    del t["measured_at"]
    p = tmp_path / "expectation.json"
    p.write_text(json.dumps(t), encoding="utf-8")
    text = _text(block(LIVE, path=p, today=TODAY))
    assert "date not recorded" in text
    assert "ago" not in text, "an unknown age must not be rendered as an age"


def test_the_age_is_not_taken_from_the_file_mtime(tmp_path):
    """Copying a fold table rewrites mtime. A staleness check that reports a
    two-year-old measurement as fresh is worse than no staleness check."""
    import os
    p = _write(tmp_path, measured_at="2024-01-01")
    os.utime(p, (0, 0))          # ancient mtime
    text = _text(block(LIVE, path=p, today=TODAY))
    assert "measured 2024-01-01" in text
    assert "STALE" in text
    os.utime(p, None)            # fresh mtime, same stamp
    assert "STALE" in _text(block(LIVE, path=p, today=TODAY))


def test_a_stamp_in_the_future_is_flagged_not_shown_as_negative_age(tmp_path):
    text = _text(block(LIVE, path=_write(tmp_path, measured_at="2027-01-01"),
                       today=TODAY))
    assert "FUTURE" in text
    import re
    assert not re.search(r"\(-\d+d ago\)", text), text


def test_an_unparseable_stamp_is_not_an_age(tmp_path):
    text = _text(block(LIVE, path=_write(tmp_path, measured_at="last Tuesday"),
                       today=TODAY))
    assert "measured last Tuesday" in text
    assert "ago" not in text


# ---------------------------------------------------------------------------
# the verdict may not contradict the evidence printed above it
# ---------------------------------------------------------------------------

def _confident(**over):
    """Stats that clear EV and the clustered t but not the deflated Sharpe."""
    base = {"pooled_excess_baseline": {"n": 400, "ev_pct": 2.0, "t_stat": 3.0},
            "pooled_excess_baseline_clustered_t": 2.6,
            "pooled_excess_baseline_dsr": 0.70}
    base.update(over)
    return base


def test_a_sub_bar_deflated_sharpe_is_deflated_for_when_the_grid_is_known(tmp_path):
    text = _text(block(LIVE, path=_write(tmp_path, **_confident()), today=TODAY))
    assert "DEFLATED SHARPE" in text
    assert "6 thresholds tried" in text
    assert "predates" not in text, (
        "the fallback caveat fired even though the grid size was recorded")


def test_an_old_table_cannot_report_edge_confirmed_over_a_sub_bar_dsr(tmp_path):
    """Tables written before threshold_grid_size exists cannot deflate.

    Left alone, edge_verdict skips its deflation clause when the trial count
    is 0 and returns EDGE CONFIRMED OOS — printed directly under a deflated
    Sharpe of 0.70. That contradiction between a headline and its own evidence
    is the exact bug edge_verdict's extra arguments were added to fix; it must
    not come back through a different door.
    """
    text = _text(block(LIVE, path=_write(tmp_path, threshold_grid_size=0,
                                         **_confident()), today=TODAY))
    assert "0.700" in text
    assert "governing" in text, "EDGE CONFIRMED was left standing unqualified"


def test_a_clean_result_still_reads_as_confirmed(tmp_path):
    """Non-vacuity: the caveat must not attach itself to everything."""
    text = _text(block(LIVE, path=_write(tmp_path, threshold_grid_size=0,
                                         **_confident(
                                             pooled_excess_baseline_dsr=0.99)),
                       today=TODAY))
    assert "EDGE CONFIRMED OOS" in text
    assert "governing" not in text


def test_a_negative_edge_is_not_dressed_up(tmp_path):
    text = _text(block(LIVE, path=_write(
        tmp_path, pooled_excess_baseline={"n": 400, "ev_pct": -2.52,
                                          "t_stat": -3.0},
        pooled_excess_baseline_clustered_t=-3.10), today=TODAY))
    assert "NO OOS EDGE" in text
    assert "-2.52%/trade" in text


def test_too_few_trades_reads_as_inconclusive(tmp_path):
    text = _text(block(LIVE, path=_write(
        tmp_path, pooled_excess_baseline={"n": 12, "ev_pct": 5.0,
                                          "t_stat": 1.0}), today=TODAY))
    assert "INCONCLUSIVE" in text


# ---------------------------------------------------------------------------
# the concentration arithmetic
# ---------------------------------------------------------------------------

def test_the_biggest_fold_is_chosen_by_contribution_not_percentage():
    """A 3-trade fold at +40% is not what a pooled average is made of.

    Picking by percentage would remove it, change the pooled number by almost
    nothing, and let a genuinely concentrated result pass the check.
    """
    folds = [{"fold": 0, "n": 3, "excess_pct": 40.0},
             {"fold": 1, "n": 300, "excess_pct": 6.0},
             {"fold": 2, "n": 200, "excess_pct": -3.0}]
    value, fold_id = excess_excluding_largest_fold(folds)
    assert fold_id == 1
    assert value == pytest.approx((3 * 40.0 + 200 * -3.0) / 203)


def test_folds_without_an_excess_are_skipped_not_counted_as_zero():
    folds = [{"fold": 0, "n": 100, "excess_pct": None},
             {"fold": 1, "n": 100, "excess_pct": 4.0},
             {"fold": 2, "n": 100, "excess_pct": 2.0}]
    value, fold_id = excess_excluding_largest_fold(folds)
    assert fold_id == 1
    assert value == pytest.approx(2.0)


def test_a_single_usable_fold_has_nothing_to_exclude():
    assert excess_excluding_largest_fold(
        [{"fold": 0, "n": 100, "excess_pct": 4.0}]) == (None, None)
    assert excess_excluding_largest_fold([]) == (None, None)


def test_zero_trade_folds_do_not_divide_by_zero():
    folds = [{"fold": 0, "n": 0, "excess_pct": 4.0},
             {"fold": 1, "n": 100, "excess_pct": 2.0}]
    assert excess_excluding_largest_fold(folds) == (None, None)


def test_the_concentration_line_is_absent_when_there_is_one_fold(tmp_path):
    p = _write(tmp_path, folds=[{"fold": 0, "n_baseline": 310,
                                 "excess_baseline_pct": 1.71}])
    text = _text(block(LIVE, path=p, today=TODAY))
    assert "excluding the biggest" not in text
    assert "+1.71%/trade" in text


# ---------------------------------------------------------------------------
# LiveSetup reads the same fields the runner recorded
# ---------------------------------------------------------------------------

def test_live_setup_from_config_matches_a_table_made_with_that_config(tmp_path):
    from kala.config import Config
    cfg = Config()
    cfg.backtest.holding_max_days = 45
    cfg.backtest.score_entry_threshold = 70.0
    live = LiveSetup.from_config(cfg, disabled_vetoes=["rsi", "bear"],
                                 exit_profile="forward_test")
    assert live.disabled_vetoes == ("bear", "rsi"), "must be sorted for diffing"
    p = _write(tmp_path, holding_max_days=45, baseline_threshold=70.0,
               disabled_vetoes=["bear", "rsi"])
    assert mismatches(load(p), live) == []


def test_describe_accepts_a_measurement_directly(tmp_path):
    m = load(_write(tmp_path))
    assert "+1.71%/trade" in _text(describe(m, LIVE, today=TODAY))


# ---------------------------------------------------------------------------
# what the daily run actually logs
# ---------------------------------------------------------------------------

def test_the_live_block_names_the_veto_setting_that_is_running(tmp_path):
    """entry_settings.describe() was called by nothing but its own tests.

    Its docstring says a setting that cannot be seen from the output is a
    setting nobody can verify took effect — and it was in no output. This
    audit's own written instruction was to apply disabled_entry_vetoes and
    then check the log for "entry vetoes: ALL OFF", a line no code printed.
    """
    from kala.config import forward_test_config
    cfg = {"exit_profile": "forward_test",
           "disabled_entry_vetoes": ["rsi", "parabolic", "obv", "thin_volume",
                                     "bear"]}
    lines = live_lines(cfg, forward_test_config(score_threshold=60.0),
                       path=tmp_path / "none.json", today=TODAY)
    assert "entry vetoes: ALL OFF" in lines[0]


def test_the_live_block_defaults_to_reporting_every_veto_on(tmp_path):
    """Non-vacuity: the line must track the config, not always say ALL OFF."""
    from kala.config import Config
    lines = live_lines({}, Config(), path=tmp_path / "none.json", today=TODAY)
    assert "entry vetoes: ALL ON" in lines[0]


def test_the_live_block_compares_against_the_running_configuration(tmp_path):
    """A legacy-profile bot must not be handed a forward_test measurement.

    This is the live system's actual state: runner_config.json names no
    exit_profile, so the ladder is ON and holding_max_days is 20, while every
    saved measurement was made under forward_test at 60 days. Those are not
    the same strategy, and the difference has to be on screen rather than
    resolved silently in favour of the number that exists.
    """
    from kala.config import Config
    text = _text(live_lines({}, Config(), path=_write(tmp_path), today=TODAY))
    assert "NOT APPLICABLE" in text
    assert "exit_profile" in text and "legacy" in text
    assert "%/trade" not in text


def test_the_live_block_reports_the_number_when_the_setup_does_match(tmp_path):
    """Non-vacuity again: matching configurations must produce the figure."""
    from kala.config import forward_test_config
    cfg = {"exit_profile": "forward_test"}
    text = _text(live_lines(cfg, forward_test_config(score_threshold=60.0),
                            path=_write(tmp_path), today=TODAY))
    assert "NOT APPLICABLE" not in text
    assert "+1.71%/trade" in text


def test_an_unknown_veto_name_in_the_config_still_raises(tmp_path):
    """The live block must not become a place where a typo is tolerated."""
    from kala.config import Config
    from kala.entry_settings import UnknownVetoName
    with pytest.raises(UnknownVetoName):
        live_lines({"disabled_entry_vetoes": ["rsii"]}, Config(),
                   path=tmp_path / "none.json", today=TODAY)


# ---------------------------------------------------------------------------
# the daily run has to actually emit it
# ---------------------------------------------------------------------------

def test_the_daily_run_logs_the_expectation():
    import daily_run
    from kala.config import Config

    logged: list[str] = []
    daily_run.report_measured_expectation({}, Config(), emit=logged.append)
    assert any("MEASURED EXPECTATION" in ln for ln in logged), logged
    assert any("entry vetoes" in ln for ln in logged), logged


def test_a_broken_expectation_report_is_logged_not_swallowed(monkeypatch):
    """A reporting bug must not leave the run looking like a quiet one.

    Silently dropping the block produces a screen identical to a run with
    nothing to report — the exact substitution of a failure for a normal
    outcome that this module exists to prevent.
    """
    import daily_run
    from kala.config import Config

    def boom(*a, **k):
        raise RuntimeError("fold table is a directory")

    monkeypatch.setattr(daily_run.expectation, "live_lines", boom)
    logged: list[str] = []
    daily_run.report_measured_expectation({}, Config(), emit=logged.append)
    text = _text(logged)
    assert "could not be reported" in text
    assert "fold table is a directory" in text
    assert "not a measurement of zero" in text


def test_main_still_reports_the_expectation():
    """Ties the reporter to the orchestrator without grepping the source.

    ``co_names`` is read off the COMPILED function, so this cannot pass on a
    call that was commented out or deleted — the realistic drift. Its honest
    limit: it would still pass if the call became unreachable, which no cheap
    check can see, and running main() means running the whole live scan.
    """
    import daily_run
    assert "report_measured_expectation" in daily_run.main.__code__.co_names


# ---------------------------------------------------------------------------
# the decomposition must decompose the number printed above it
# ---------------------------------------------------------------------------

def test_the_concentration_uses_the_same_arm_as_the_headline(tmp_path):
    """The defect this file shipped in its own first version.

    The headline is the FIXED-BASELINE arm — that is the arm the clustered t,
    the deflated Sharpe and the VERDICT are all computed on. The only per-fold
    excess the saved tables carried was the WALK-FORWARD-CHOSEN arm's. Pooled,
    those two arms are +1.71% over 5,241 trades and +1.27% over 6,082; the
    -0.44%/trade concentration figure quoted throughout this audit belongs to
    the second one. Subtracting a fold of one from the total of the other is
    not a decomposition of either.

    The fixture's chosen column is 100 points higher on every fold, so reading
    the wrong arm cannot produce the right answer.
    """
    m = load(_write(tmp_path))
    value, fold_id, arm = m.concentration
    assert arm == "baseline"
    assert fold_id == 2
    assert value == pytest.approx((100 * -1.0 + 120 * 0.5) / 220)


def test_an_old_table_says_which_arm_its_concentration_belongs_to(tmp_path):
    """Fifteen tables on disk have no baseline fold column.

    Refusing outright would drop the only concentration evidence they hold, so
    the chosen arm is used — and labelled, with ITS pooled figure beside it, so
    the two numbers a reader compares come from the same measurement.
    """
    t = _table()
    for f in t["folds"]:
        del f["excess_baseline_pct"]
        del f["n_baseline"]
    p = tmp_path / "expectation.json"
    p.write_text(json.dumps(t), encoding="utf-8")
    text = _text(block(LIVE, path=p, today=TODAY))
    assert "WALK-FORWARD-CHOSEN" in text
    assert "chosen arm pooled: +101.30%/trade" in text
    assert "excluding the biggest single fold" not in text, (
        "the unlabelled line implies it decomposes the headline")


def test_the_negative_fold_count_follows_the_same_arm(tmp_path):
    """Counting one arm's negative folds under another arm's headline.

    Non-vacuity: the fixture's chosen column is positive on all three folds,
    so a count read off it says 0 of 3 while the baseline column has one.
    """
    assert load(_write(tmp_path)).negative_folds == (1, 3, "baseline")
    t = _table()
    for f in t["folds"]:
        del f["excess_baseline_pct"]
        del f["n_baseline"]
    p = tmp_path / "expectation.json"
    p.write_text(json.dumps(t), encoding="utf-8")
    assert load(p).negative_folds == (0, 3, "chosen")
    assert "(chosen arm)" in _text(block(LIVE, path=p, today=TODAY))


def test_the_arm_keys_are_explicit_not_defaulted():
    """No default that silently mixes arms — the caller names the columns."""
    folds = [{"fold": 0, "n": 10, "excess_pct": 90.0,
              "n_baseline": 100, "excess_baseline_pct": -1.0},
             {"fold": 1, "n": 10, "excess_pct": 90.0,
              "n_baseline": 100, "excess_baseline_pct": 5.0}]
    assert excess_excluding_largest_fold(
        folds, "n_baseline", "excess_baseline_pct")[0] == pytest.approx(-1.0)
    assert excess_excluding_largest_fold(folds)[0] == pytest.approx(90.0)


# ---------------------------------------------------------------------------
# the instruction has to produce a table this block will accept
# ---------------------------------------------------------------------------

def _round_trip(settings: dict):
    """Generate the printed command, parse it with the REAL CLI, build the
    provenance it would save, and compare that back against the live setup."""
    import shlex

    from kala.config import CostModel, config_from_settings
    from kala.expectation import Measurement, measure_command
    from run_walkforward import build_parser, build_run_config, run_provenance

    cfg = config_from_settings(settings)
    live = LiveSetup.from_config(
        cfg, sorted(settings.get("disabled_entry_vetoes") or []),
        exit_profile=settings.get("exit_profile"))

    printed = " ".join(ln.strip().rstrip("\\").strip()
                       for ln in measure_command(live, "x.json"))
    argv = shlex.split(printed)[2:]          # drop "python run_walkforward.py"
    args = build_parser().parse_args(argv)   # the real parser, not a stand-in

    costs = CostModel(spread_mode="tick_floor" if args.tick_spread else "flat")
    run_cfg = build_run_config(args.exit_profile, costs, args.apply_entry_vetoes,
                               False, disabled_vetoes=tuple(args.disable_veto),
                               holding_days=args.holding_days,
                               baseline_threshold=args.baseline_threshold)

    class _S:
        name = "momentum"

    prov = run_provenance(args, _S(), run_cfg, 615, measured_at="2026-08-23")
    return live, prov, mismatches(Measurement(path=Path("x.json"), raw=prov), live)


RECOMMENDED = {
    "exit_profile": "forward_test",
    "disabled_entry_vetoes": ["rsi", "parabolic", "obv", "thin_volume", "bear"],
    "costs_spread_mode": "tick_floor",
}


@pytest.mark.parametrize("settings,label", [
    (RECOMMENDED, "the audit's recommended configuration"),
    ({}, "the configuration as shipped"),
    ({"exit_profile": "forward_test"}, "profile only, vetoes still on"),
    ({"costs_spread_mode": "tick_floor"}, "costs only, legacy profile"),
])
def test_the_printed_command_produces_a_table_this_block_accepts(settings, label):
    """The loop this module is built around, closed.

    The instruction used to be a fixed string: `--strategy momentum
    --exit-profile forward_test --benchmark EQUAL_WEIGHT --save-folds ...`.
    Followed literally against a tick-floored book it produces a table
    recording `spread_mode: flat` — which this same block then REFUSES. It
    printed a command and rejected the command's own output.

    Nothing short of parsing the real CLI catches that, because the defect is
    a disagreement between two pieces of code that never met.
    """
    live, prov, bad = _round_trip(settings)
    assert bad == [], f"{label}: the command's own output is rejected — {bad}"


def test_the_command_tracks_the_settings_rather_than_being_fixed(tmp_path):
    """Non-vacuity: it must actually differ between configurations."""
    from kala.config import config_from_settings  # noqa: I001
    from kala.expectation import measure_command
    def cmd(settings):
        cfg = config_from_settings(settings)
        return " ".join(measure_command(LiveSetup.from_config(
            cfg, sorted(settings.get("disabled_entry_vetoes") or []),
            exit_profile=settings.get("exit_profile")), "x.json"))

    rec, shipped = cmd(RECOMMENDED), cmd({})
    assert rec != shipped
    assert "--tick-spread" in rec and "--tick-spread" not in shipped
    assert "--holding-days 60" in rec and "--holding-days 20" in shipped
    assert "--baseline-threshold 80" in rec
    assert "--disable-veto" in rec and "--disable-veto" not in shipped


def test_the_command_always_asks_for_the_honest_benchmark():
    """IHSG is the default and it is the wrong yardstick for this universe."""
    from kala.expectation import measure_command
    text = " ".join(measure_command(LIVE, "x.json"))
    assert "--benchmark EQUAL_WEIGHT" in text
    assert "--save-folds x.json" in text
