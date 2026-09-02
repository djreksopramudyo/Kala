"""The holding sweep must refuse the mistakes a sweep invites.

`holding_max_days` is 60, tuned while the exit ladder was in place. The ladder
was later measured significantly negative and removed, and nobody has swept the
holding period since — it is the last parameter still carrying a value chosen
under conditions that no longer hold.

Running five walk-forwards by hand and reading five terminal outputs is exactly
the loop that produced two misreadings earlier in this audit. This driver
exists so the comparison is mechanical; these tests exist so it refuses the
comparisons that are not valid.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sweep_holding_walkforward import (  # noqa: E402
    calendar,
    excess_excluding_best_fold,
    tabulate,
)

SCRIPT = ROOT / "sweep_holding_walkforward.py"


def _run(*args, cwd=None):
    return subprocess.run([sys.executable, str(SCRIPT), *args],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", cwd=str(cwd or ROOT), timeout=300)


def _table(tmp_path, hold, start_shift=0, ev=1.0, ct=2.5, dsr=0.99, n=5000,
           prefix="f_hold"):
    folds = [{"fold": i,
              "start": f"2022-11-{22 + start_shift:02d}",
              "end": f"2023-0{1 + (i % 8)}-17",
              "n": 600, "ev_pct": 1.0, "benchmark_pct": 2.0,
              "excess_pct": ev + 100.0,
              "n_baseline": 300,
              "excess_baseline_pct": ev - (2.0 if i % 3 == 0 else 0.0)}
             for i in range(14)]
    p = tmp_path / f"{prefix}_{hold}.json"
    p.write_text(json.dumps({
        "strategy": "momentum", "exit_profile": "forward_test",
        "baseline_threshold": 80, "benchmark": "EQUAL_WEIGHT",
        "apply_entry_vetoes": False, "disabled_vetoes": [],
        "holding_max_days": hold, "n_tickers": 569, "folds": folds,
        "pooled_excess_baseline": {"n": n, "ev_pct": ev},
        "pooled_excess_baseline_clustered_t": ct,
        "pooled_excess_baseline_dsr": dsr,
    }), encoding="utf-8")
    return p


# ---- argument validation, before anything expensive runs -----------------

def test_duplicate_holds_are_rejected():
    """A duplicate would run the same measurement twice and tabulate it twice."""
    out = _run("--holds", "30", "30")
    assert out.returncode == 1
    assert "duplicates" in out.stderr


def test_nonsensical_holds_are_rejected():
    out = _run("--holds", "0")
    assert out.returncode == 1
    assert ">= 1" in out.stderr


def test_it_refuses_a_passthrough_that_would_fight_it():
    """--holding-days is what this script varies; accepting one is ambiguous."""
    out = _run("--holds", "30", "--holding-days", "60")
    assert out.returncode == 1
    assert "set per run by this script" in out.stderr

    out = _run("--holds", "30", "--save-folds", "x.json")
    assert out.returncode == 1
    assert "set per run by this script" in out.stderr


# ---- the calendar guard --------------------------------------------------

def test_calendar_reads_the_fold_windows(tmp_path):
    p = _table(tmp_path, 30)
    run = json.loads(p.read_text(encoding="utf-8"))
    cal = calendar(run)
    assert len(cal) == 14
    assert cal[0] == ("2022-11-22", "2023-01-17")   # matches the fixture above
    assert all(len(w) == 2 for w in cal)


def test_misaligned_calendars_are_refused(tmp_path):
    """A warehouse refresh mid-sweep shifts boundaries. That is not a holding
    effect, and tabulating it would attribute a quarter to a parameter."""
    _table(tmp_path, 30, start_shift=0)
    _table(tmp_path, 60, start_shift=2)          # boundaries moved
    out = _run("--holds", "30", "60", "--out-dir", str(tmp_path), "--reuse")
    assert out.returncode == 1
    assert "FOLD CALENDARS DIFFER" in out.stderr
    assert "60" in out.stderr
    assert "Refusing to tabulate" in out.stderr


def test_aligned_calendars_tabulate(tmp_path):
    """Non-vacuity: refusing everything would satisfy the test above."""
    _table(tmp_path, 30, ev=1.0)
    _table(tmp_path, 60, ev=2.0)
    out = _run("--holds", "30", "60", "--out-dir", str(tmp_path), "--reuse")
    assert out.returncode == 0, out.stderr
    assert "HOLDING-PERIOD SWEEP" in out.stdout
    assert "Best excess: 60d" in out.stdout


def test_the_override_exists_and_still_warns(tmp_path):
    _table(tmp_path, 30, start_shift=0)
    _table(tmp_path, 60, start_shift=2)
    out = _run("--holds", "30", "60", "--out-dir", str(tmp_path), "--reuse",
               "--allow-misaligned")
    assert out.returncode == 0
    assert "Read with care" in out.stdout or "Read with care" in out.stderr


# ---- the table itself ----------------------------------------------------

def test_the_table_reports_the_baseline_arms_statistics(capsys, tmp_path):
    """The verdict is judged on the BASELINE arm, so the table must show it."""
    runs = [(30, json.loads(_table(tmp_path, 30, ev=1.0, ct=1.4, dsr=0.55)
                            .read_text(encoding="utf-8"))),
            (60, json.loads(_table(tmp_path, 60, ev=3.0, ct=4.1, dsr=0.99)
                            .read_text(encoding="utf-8")))]
    tabulate(runs)
    out = capsys.readouterr().out
    assert "+1.00%" in out and "+3.00%" in out
    assert "+1.40" in out and "+4.10" in out      # clustered t, both arms' rows
    assert "0.550" in out and "0.990" in out      # deflated Sharpe
    assert "clustered t" in out and "defl. Sharpe" in out


def test_the_table_warns_when_the_best_value_is_at_the_edge(capsys, tmp_path):
    """A peak at the boundary means the optimum may be outside the sweep."""
    runs = [(20, json.loads(_table(tmp_path, 20, ev=5.0).read_text(encoding="utf-8"))),
            (40, json.loads(_table(tmp_path, 40, ev=3.0).read_text(encoding="utf-8"))),
            (60, json.loads(_table(tmp_path, 60, ev=1.0).read_text(encoding="utf-8")))]
    tabulate(runs)
    out = capsys.readouterr().out
    assert "EDGE of the swept range" in out
    assert "20d" in out


def test_no_edge_warning_when_the_peak_is_interior(capsys, tmp_path):
    """Non-vacuity: warning always would satisfy the test above."""
    runs = [(20, json.loads(_table(tmp_path, 20, ev=1.0).read_text(encoding="utf-8"))),
            (40, json.loads(_table(tmp_path, 40, ev=5.0).read_text(encoding="utf-8"))),
            (60, json.loads(_table(tmp_path, 60, ev=1.0).read_text(encoding="utf-8")))]
    tabulate(runs)
    out = capsys.readouterr().out
    assert "EDGE of the swept range" not in out


def test_the_table_says_a_pick_is_multiple_testing(capsys, tmp_path):
    """Choosing the best of N is the move the deflated Sharpe discounts.

    Printing a winner without saying that invites exactly the overfit this
    project already retracted once.
    """
    runs = [(30, json.loads(_table(tmp_path, 30).read_text(encoding="utf-8"))),
            (60, json.loads(_table(tmp_path, 60).read_text(encoding="utf-8")))]
    tabulate(runs)
    out = capsys.readouterr().out
    assert "SHAPE, not a pick" in out
    assert "multiple-testing" in out


def test_a_run_without_a_benchmark_says_so_rather_than_printing_zeros(capsys):
    """No excess computed must not render as a sweep full of 0.00%.

    The first version of this test only checked that "n/a" appeared SOMEWHERE.
    A mutation that rendered the EV column as `+0.00%` survived it, because the
    clustered-t and Sharpe columns still said n/a. Zero-versus-missing, in the
    tool built to compare measurements — assert on the EV cell itself.
    """
    runs = [(30, {"folds": [], "pooled_excess_baseline": {"n": 0}})]
    tabulate(runs)
    out = capsys.readouterr().out
    row = [ln for ln in out.splitlines() if ln.strip().startswith("30")]
    assert row, f"no data row rendered:\n{out}"
    assert "n/a" in row[0], f"the EV cell did not say n/a: {row[0]!r}"
    assert "0.00%" not in row[0], (
        f"a missing excess rendered as a measured zero: {row[0]!r}")
    assert "No excess figures" in out


# ---- the runner is reused, not reimplemented -----------------------------

def test_it_shells_out_to_run_walkforward():
    """A second implementation of the measurement could drift from the first.

    Every number this project has published came from run_walkforward.py; a
    sweep computed some other way would not be comparable with any of them.
    """
    src = SCRIPT.read_text(encoding="utf-8")
    assert 'RUNNER = ROOT / "run_walkforward.py"' in src
    assert "subprocess.run(cmd" in src
    assert "walk_forward_strategy" not in src, "the measurement was reimplemented"


def test_the_saved_table_carries_the_baseline_arm_statistics():
    """The sweep reads these; run_walkforward must write them."""
    src = (ROOT / "run_walkforward.py").read_text(encoding="utf-8")
    assert '"pooled_excess_baseline_clustered_t":' in src
    assert '"pooled_excess_baseline_dsr":' in src


@pytest.mark.parametrize("flag", ["--holds", "--out-dir", "--reuse",
                                  "--allow-misaligned"])
def test_the_flags_are_documented(flag):
    out = _run("--help")
    assert out.returncode == 0
    assert flag in out.stdout


# ---- concentration: the column that turned the real sweep inside out ------

def _run_with_folds(rows, n=5000, ev=None, ct=2.0, dsr=0.9, baseline=True):
    """rows = [(n_trades, excess_pct), ...] in fold order.

    ``baseline=True`` writes the per-fold BASELINE excess column, which is the
    arm the headline comes from. ``baseline=False`` reproduces a table written
    before that column existed — the state all fifteen tables on disk are in.
    The chosen-arm column is deliberately given DIFFERENT values so a test
    cannot pass by reading the wrong one.
    """
    folds = [{"fold": i, "start": "2022-11-22", "end": "2023-01-17",
              "n": nn * 2, "ev_pct": 1.0, "benchmark_pct": 2.0,
              "excess_pct": ee + 100.0,
              **({"n_baseline": nn, "excess_baseline_pct": ee} if baseline else {})}
             for i, (nn, ee) in enumerate(rows)]
    pooled = (sum(nn * ee for nn, ee in rows) / sum(nn for nn, _ in rows)) if rows else 0.0
    return {"folds": folds,
            "pooled_excess_baseline": {"n": n, "ev_pct": ev if ev is not None else pooled},
            "pooled_excess_baseline_clustered_t": ct,
            "pooled_excess_baseline_dsr": dsr}


def test_excess_excluding_best_fold_removes_the_biggest_contributor():
    """The real sweep's finding: the ramp was one fold, not the parameter."""

    # Four flat-negative folds and one enormous winner.
    run = _run_with_folds([(100, -1.0), (100, -1.0), (100, -1.0), (100, -1.0),
                           (100, 20.0)])
    xb, fold = excess_excluding_best_fold(run)
    assert fold == 4, "the wrong fold was identified as the biggest contributor"
    assert xb == pytest.approx(-1.0), "removing it must leave the rest, not the total"


def test_it_weights_by_trade_count_not_by_percentage():
    """A big percentage on 3 trades is not the biggest contributor."""

    run = _run_with_folds([(3, 50.0), (1000, 2.0), (100, -1.0)])
    _, fold = excess_excluding_best_fold(run)
    assert fold == 1, "a tiny fold with a huge percentage was picked"


def test_it_returns_none_when_there_is_nothing_to_exclude():

    assert excess_excluding_best_fold({"folds": []}) == (None, None)
    assert excess_excluding_best_fold(
        {"folds": [{"fold": 0, "n_baseline": 10,
                    "excess_baseline_pct": 1.0}]}) == (None, None)
    # folds present but no excess computed at all
    run = {"folds": [{"fold": i, "n_baseline": 10, "excess_baseline_pct": None}
                     for i in range(5)]}
    assert excess_excluding_best_fold(run) == (None, None)


def test_the_table_shows_the_ex_best_column(capsys):

    runs = [(60, _run_with_folds([(100, -1.0), (100, -1.0), (100, 20.0)]))]
    tabulate(runs)
    out = capsys.readouterr().out
    assert "ex-best fold" in out
    assert "-1.00%" in out, "the re-pooled figure is not shown"
    assert "measuring one quarter" in out


def test_it_warns_when_every_holding_period_collapses(capsys):
    """The real result: every hold <= +0.25% once its biggest fold goes."""

    runs = [(h, _run_with_folds([(100, -1.0), (100, -0.5), (100, 20.0 + h)]))
            for h in (30, 45, 60)]
    tabulate(runs)
    out = capsys.readouterr().out
    assert "EVERY holding period collapses" in out
    assert "not the strategy improving" in out


def test_no_collapse_warning_when_the_edge_survives_exclusion(capsys):
    """Non-vacuity: a genuinely broad edge must NOT trigger the warning."""

    runs = [(h, _run_with_folds([(100, 2.0), (100, 2.5), (100, 3.0)]))
            for h in (30, 45, 60)]
    tabulate(runs)
    out = capsys.readouterr().out
    assert "EVERY holding period collapses" not in out


def test_the_share_of_total_is_deliberately_not_reported(capsys):
    """When the total is near zero, a percentage share explodes and flips sign.

    The real 20-day run computes to a fold-10 share of -456%, which reads as a
    dramatic finding about a total that is simply near zero. The re-pooled
    average is stable; the share is not.
    """

    # total excess very near zero, one dominant fold
    runs = [(20, _run_with_folds([(100, -5.0), (100, -5.0), (100, 10.1)]))]
    tabulate(runs)
    out = capsys.readouterr().out
    assert "456" not in out
    assert "% of" not in out


# ---- the ex-best column has to decompose the column beside it -------------

def test_the_ex_best_column_uses_the_same_arm_as_the_headline():
    """v76 decomposed the BASELINE headline with the CHOSEN arm's folds.

    That was the only per-fold excess the saved tables carried. The two arms
    pool to +1.71% and +1.27% over different trade counts, so the ex-best cell
    was subtracting one arm's quarter from the other arm's total — and the
    sweep's collapse verdict was read straight off it.

    The fixture gives the chosen column values 100 points higher, so a function
    reading the wrong arm cannot land on the right answer by accident.
    """
    run = _run_with_folds([(100, -1.0), (100, -1.0), (100, 20.0)])
    value, fold_id = excess_excluding_best_fold(run)
    assert fold_id == 2
    assert value == pytest.approx(-1.0), "read the chosen arm's +100 column"


def test_a_table_without_the_baseline_column_reports_nothing():
    """No fallback. The fallback IS the bug."""
    run = _run_with_folds([(100, -1.0), (100, -1.0), (100, 20.0)], baseline=False)
    assert excess_excluding_best_fold(run) == (None, None)


def test_the_table_says_why_the_column_is_n_a(capsys):
    runs = [(60, _run_with_folds([(100, -1.0), (100, 20.0)], baseline=False))]
    tabulate(runs)
    out = capsys.readouterr().out
    assert "n/a" in out
    assert "BASELINE" in out
    assert "v76" in out, "the reader has to know the old figures were wrong"


def test_negative_fold_count_follows_the_same_arm(capsys):
    """The folds<0 cell counted the chosen arm too.

    Non-vacuity: the fixture's chosen column is +100 on every fold, so a
    count read off it is zero — a table claiming 0/3 negative while its own
    ex-best column comes from three folds, two of which are negative.
    """
    runs = [(60, _run_with_folds([(100, -1.0), (100, -1.0), (100, 20.0)]))]
    tabulate(runs)
    assert "2/3" in capsys.readouterr().out
