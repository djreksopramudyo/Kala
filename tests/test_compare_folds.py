"""Comparing runs by eye is how two mistakes got made; this compares files.

Mistake 1: correlating the RAW per-fold EV of two strategies (+0.86) and
concluding a hidden common factor drove both. Two long-only baskets from one
universe rise together with the index — that correlation is mechanical, and
the excess column, which could have said something, was not printed at all.

Mistake 2: reading a fold table from a run whose warehouse had been refreshed
in between, so fold boundaries had moved and trade counts differed. The pasted
terminal output said nothing about it.

Both are structurally impossible here: raw and excess are reported side by
side, and misaligned fold calendars are refused rather than silently compared.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from compare_folds import corr, load  # noqa: E402


def _run(tmp_path, name, ev, excess, bench, starts=None, base=60.0):
    folds = []
    for i, (r, e, m) in enumerate(zip(ev, excess, bench)):
        start = starts[i] if starts else f"2023-{i + 1:02d}-01"
        folds.append({"fold": i, "start": start, "end": f"2024-{i + 1:02d}-01",
                      "threshold": base, "n": 100, "ev_pct": r,
                      "win_rate_pct": 30.0, "benchmark_pct": m, "excess_pct": e})
    p = tmp_path / f"{name}.json"
    p.write_text(json.dumps({"strategy": name, "exit_profile": "forward_test",
                             "baseline_threshold": base, "n_tickers": 569,
                             "folds": folds}), encoding="utf-8")
    return p


def _cli(*paths, extra=()):
    out = subprocess.run([sys.executable, str(ROOT / "compare_folds.py"),
                          *[str(p) for p in paths], *extra],
                         capture_output=True, text=True, encoding="utf-8",
                         errors="replace", cwd=ROOT)
    return out


def test_correlation_ignores_missing_excess_rather_than_scoring_it_zero():
    assert corr([1.0, 2.0, 3.0, 4.0], [1.0, 2.0, None, 4.0]) == pytest.approx(1.0)


def test_correlation_refuses_to_report_on_too_few_points():
    v = corr([1.0, 2.0], [1.0, 2.0])
    assert v != v                                  # NaN, not a confident 1.0


def test_raw_and_excess_are_reported_separately(tmp_path):
    """The whole point: identical raw series, opposite excess series."""
    ev = [1.0, 2.0, 3.0, 4.0, 5.0]
    bench = [1.0, 1.0, 1.0, 1.0, 1.0]
    a = _run(tmp_path, "aaa", ev, [1.0, 2.0, 3.0, 4.0, 5.0], bench)
    b = _run(tmp_path, "bbb", ev, [5.0, 4.0, 3.0, 2.0, 1.0], bench)

    out = _cli(a, b)
    assert out.returncode == 0, out.stdout + out.stderr
    line = next(ln for ln in out.stdout.splitlines() if "aaa / bbb" in ln)
    assert "+1.000" in line          # raw: identical
    assert "-1.000" in line          # excess: opposite


def test_misaligned_fold_calendars_are_refused(tmp_path):
    ev = [1.0, 2.0, 3.0, 4.0]
    a = _run(tmp_path, "aaa", ev, ev, ev)
    b = _run(tmp_path, "bbb", ev, ev, ev,
             starts=["2099-01-01", "2099-02-01", "2099-03-01", "2099-04-01"])

    out = _cli(a, b)
    assert out.returncode == 1
    assert "FOLD CALENDARS DIFFER" in out.stdout
    assert "Refusing to correlate" in out.stdout


def test_the_override_exists_and_still_warns(tmp_path):
    ev = [1.0, 2.0, 3.0, 4.0]
    a = _run(tmp_path, "aaa", ev, ev, ev)
    b = _run(tmp_path, "bbb", ev, ev, ev,
             starts=["2099-01-01", "2099-02-01", "2099-03-01", "2099-04-01"])

    out = _cli(a, b, extra=("--allow-misaligned",))
    assert out.returncode == 0
    assert "FOLD CALENDARS DIFFER" in out.stdout
    assert "Read with care" in out.stdout


def test_the_up_down_split_uses_the_benchmark_sign(tmp_path):
    """The regime-conditionality readout, on a case with a known answer."""
    a = _run(tmp_path, "aaa", [0.0] * 4, [10.0, 10.0, 0.0, 0.0],
             [5.0, 5.0, -5.0, -5.0])

    out = _cli(a, a)
    assert "+10.00% (2)" in out.stdout        # up folds
    assert "+0.00% (2)" in out.stdout         # down folds


def test_a_file_that_is_not_a_fold_table_is_rejected(tmp_path):
    bad = tmp_path / "nope.json"
    bad.write_text('{"hello": 1}', encoding="utf-8")
    with pytest.raises(SystemExit):
        load(str(bad))


def test_run_walkforward_can_save_a_fold_table():
    """The saved table must carry what is needed to place it later.

    This test previously asserted that run_walkforward.py contained the exact
    string `"excess_pct": (fr.oos_excess_chosen or {}).get("ev_pct")` — which
    is the BUG, not the requirement. `trade_stats([])` is a populated, truthy
    dict, so that expression returns 0.0 for a fold with no excess and writes a
    fabricated zero into the file. The test was holding the defect in place and
    would have failed the fix.

    What matters is the PROPERTY: a missing excess serialises as null.
    """
    src = (ROOT / "run_walkforward.py").read_text(encoding="utf-8")
    assert '"--save-folds"' in src
    # Without these a saved table cannot be placed later.
    for key in ('"strategy": strategy.name', '"exit_profile"', '"baseline_threshold"'):
        assert key in src

    from kala.walkforward import excess_ev, trade_stats
    assert excess_ev(trade_stats([])) is None, "a missing excess must not be 0.0"
    assert json.dumps(excess_ev(trade_stats([]))) == "null"
    # A measured zero is a different fact and must survive as a number.
    assert excess_ev(trade_stats([1.0, -1.0])) == 0.0


def test_compare_folds_cannot_tell_a_fabricated_zero_from_a_measured_one():
    """Why the fix had to be at the writer, not the reader.

    Fourteen identical zeros have zero variance, so the correlation comes back
    NaN — indistinguishable from the tool correctly declining to answer. There
    is nothing compare_folds.py can inspect to catch this; the file simply has
    to be honest.
    """
    zeros = [0.0] * 14
    real = [1.0, -2.0, 3.0, 0.5, -1.5, 2.0, 0.0, 1.0, -0.5, 2.5, -1.0, 0.5, 1.5, -2.0]
    assert corr(zeros, real) != corr(zeros, real) or True   # NaN-safe evaluation
    import math
    assert math.isnan(corr(zeros, real)), (
        "a constant series must yield NaN — if this changes, the silent "
        "corruption would start producing a confident-looking number instead")


# ---- a refusal has to say WHICH file ------------------------------------

def _fold_json(tmp_path, name, day_shift=0, strategy="momentum"):
    folds = [{"fold_id": i,
              "start": f"2022-11-{22 + day_shift:02d}",
              "end": f"2023-0{1 + (i % 8)}-17",
              "n": 100, "ev_pct": 1.0 + i,
              "benchmark_pct": 2.0 + i, "excess_pct": 0.5 + i}
             for i in range(14)]
    p = tmp_path / name
    p.write_text(json.dumps({"strategy": strategy, "exit_profile": "forward_test",
                             "baseline_threshold": 80, "n_tickers": 569,
                             "folds": folds}), encoding="utf-8")
    return str(p)


def _run_compare(*paths):
    return subprocess.run([sys.executable, str(ROOT / "compare_folds.py"), *paths],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", cwd=str(ROOT))


def test_a_misalignment_refusal_names_the_files_not_the_strategy(tmp_path):
    """Three runs of one strategy printed 'DIFFER from momentum: momentum'.

    That names neither the reference nor the offender — the one thing a reader
    needs in order to know which run to repeat. Strategy names are not unique
    across saved runs; file paths are.
    """
    a = _fold_json(tmp_path, "f_mom_ew.json", 0)
    b = _fold_json(tmp_path, "f_mom_ew_vetoes.json", 2)
    c = _fold_json(tmp_path, "f_mom_ew_gated.json", 0)
    out = _run_compare(a, b, c)

    assert out.returncode == 1, "misaligned calendars must still refuse"
    assert "f_mom_ew_vetoes.json" in out.stdout, "the offending FILE is not named"
    assert "f_mom_ew.json" in out.stdout, "the reference FILE is not named"
    # The old message, which named only the strategy three times over.
    assert "DIFFER from momentum: momentum" not in out.stdout


def test_the_refusal_shows_the_boundaries_that_differ(tmp_path):
    """Naming the file is not enough — show WHY, so the reader can judge."""
    a = _fold_json(tmp_path, "base.json", 0)
    b = _fold_json(tmp_path, "other.json", 2)
    out = _run_compare(a, b)
    assert "2022-11-22" in out.stdout and "2022-11-24" in out.stdout
    assert "the reference" in out.stdout
    assert "FIX:" in out.stdout, "the refusal must say what to do about it"


def test_aligned_runs_of_the_same_strategy_still_correlate(tmp_path):
    """Non-vacuity: identical calendars must NOT be refused."""
    a = _fold_json(tmp_path, "one.json", 0)
    b = _fold_json(tmp_path, "two.json", 0)
    out = _run_compare(a, b)
    assert out.returncode == 0, out.stdout
    assert "DIFFER" not in out.stdout
    assert "EXCESS corr" in out.stdout


def test_the_pair_labels_name_files_so_same_strategy_runs_are_distinguishable(tmp_path):
    """'momentum / momentum' identifies nothing when all three are momentum."""
    a = _fold_json(tmp_path, "base.json", 0)
    b = _fold_json(tmp_path, "vetoes.json", 0)
    out = _run_compare(a, b)
    assert "base / vetoes" in out.stdout, out.stdout
