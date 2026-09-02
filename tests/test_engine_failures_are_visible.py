"""`kala_engine.py`'s failures must be visible, not silent.

The engine is the legacy all-in-one research dashboard. It is NOT in deploy/,
the Dockerfile or docker-compose — nothing runs it automatically — but it is
run by hand and it prints BUY/HOLD signals and backtest statistics, so a
failure that reads as a normal result still misleads.

An AST sweep found eight handlers there that swallow. Five turned out to be
honest already and were deliberately left alone:

  * two optional-dependency guards (`pandas_ta`, `backtesting`) — documented,
    and the script is designed to run without them;
  * the SMA-parameter fallback, which prints `Status: DEFAULT` versus
    `Status: OPTIMIZED`, so the fallback is on the page;
  * two download-loop handlers, whose skipped tickers are counted in the
    `✓ (45/50 OK)` line printed immediately after.

The three fixed here each hid something that changed what a reader would
conclude.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# The engine hard-requires most of requirements.txt at import time. Guard on
# what these tests ACTUALLY need — the module itself — rather than on a
# dependency list copied from elsewhere, which skipped the whole file in an
# environment where the engine imports perfectly well.
pytest.importorskip("kala_engine",
                    reason="kala_engine.py needs the full requirements stack")


# ---- 1. a crashed veto check must not read as "no veto fired" -------------

def test_a_failed_veto_check_is_carried_in_the_veto_list():
    """An empty veto list means "nothing fired". A crash means "nothing ran".

    The handler was `except Exception: pass`, which left a BUY standing with an
    empty list — identical, to any reader or downstream filter, to a name that
    cleared every guardrail. This is the twin of the bug fixed in
    kala_daily_trader.py.
    """
    from kala.entry_settings import veto_check_failed_note

    note = veto_check_failed_note(KeyError("Close"))
    assert "VETO CHECK FAILED" in note and "did NOT run" in note

    src = (ROOT / "kala_engine.py").read_text(encoding="utf-8")
    veto_block = src[src.index("needs_veto_check"):]
    veto_block = veto_block[:veto_block.index("return result")]
    assert "except Exception:\n            pass" not in veto_block, (
        "the veto check still swallows its failure")
    assert "veto_check_failed_note(_e)" in veto_block, (
        "the engine does not record the failure")


def test_the_engine_and_the_daily_trader_report_it_the_same_way():
    """Two scanners, one failure mode; a reader should not have to learn two.

    The first version of this test grepped both files for the message and
    FAILED — not because a scanner was wrong, but because the string was split
    across two f-string literals in one of them. Correct at runtime, invisible
    to a grep. Both now call one helper, and this asserts on what that helper
    RETURNS.
    """
    from kala.entry_settings import veto_check_failed_note

    note = veto_check_failed_note(KeyError("Close"))
    assert "VETO CHECK FAILED" in note
    assert "entry guardrails did NOT run" in note
    assert "KeyError" in note, "the exception type must be named"
    assert "Close" in note, "the exception detail must survive"

    for script in ("kala_engine.py", "kala_daily_trader.py"):
        src = (ROOT / script).read_text(encoding="utf-8")
        assert "veto_check_failed_note(_e)" in src, (
            f"{script} does not use the shared note")


def test_the_note_is_distinguishable_from_a_real_veto():
    """A downstream filter must not mistake a crash for a fired guardrail."""
    from kala.entry_settings import veto_check_failed_note

    note = veto_check_failed_note(RuntimeError("boom"))
    # Real vetoes read like "overbought (RSI 78 >= 75)". This must not.
    assert note.startswith("VETO CHECK FAILED")
    assert "did NOT run" in note


# ---- 2. a missing benchmark must announce the omission -------------------

def test_an_unavailable_benchmark_is_announced_not_just_skipped():
    """A SKIPPED alpha section is not the same as a report with no alpha.

    This is exactly CHANGES.md "Finding 8" in the walk-forward: the absence of
    a section reads as a shorter report, not a broken one. The docstring here
    said "alpha lines are then skipped" and that was all the reader ever got.
    """
    import kala_engine as iq

    src = (ROOT / "kala_engine.py").read_text(encoding="utf-8")
    fn = src[src.index("def _get_ihsg_benchmark"):]
    fn = fn[:fn.index("return _BENCHMARK_CACHE['ihsg']")]
    assert "IHSG benchmark unavailable" in fn
    assert "OMITTED" in fn
    assert "not the same as 'no alpha'" in fn
    assert hasattr(iq, "_get_ihsg_benchmark")


def test_the_benchmark_failure_path_actually_runs_and_returns_none(monkeypatch, capsys):
    """Exercise it: the warning must PRINT and the function must still return."""
    import kala_engine as iq

    def _boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(iq, "download_stock_data", _boom)
    monkeypatch.setattr(iq, "_BENCHMARK_CACHE", {}, raising=False)

    got = iq._get_ihsg_benchmark()
    out = capsys.readouterr().out
    assert got is None, "a failed benchmark must return None, not raise"
    assert "IHSG benchmark unavailable" in out, "the failure printed nothing"
    assert "RuntimeError" in out and "network down" in out, (
        "the cause must be named, or the user cannot fix it")
    assert "OMITTED" in out


def test_a_working_benchmark_prints_no_warning(monkeypatch, capsys):
    """Non-vacuity: printing the warning unconditionally would pass the above."""
    import kala_engine as iq

    monkeypatch.setattr(iq, "download_stock_data", lambda *a, **k: "SENTINEL")
    monkeypatch.setattr(iq, "_BENCHMARK_CACHE", {}, raising=False)

    got = iq._get_ihsg_benchmark()
    out = capsys.readouterr().out
    assert got == "SENTINEL"
    assert "unavailable" not in out
    assert "OMITTED" not in out


def test_the_benchmark_result_is_cached_including_the_failure(monkeypatch, capsys):
    """The warning must not repeat once per call for the rest of the run."""
    import kala_engine as iq

    calls = {"n": 0}

    def _boom(*a, **k):
        calls["n"] += 1
        raise RuntimeError("down")

    monkeypatch.setattr(iq, "download_stock_data", _boom)
    monkeypatch.setattr(iq, "_BENCHMARK_CACHE", {}, raising=False)

    iq._get_ihsg_benchmark()
    iq._get_ihsg_benchmark()
    iq._get_ihsg_benchmark()
    assert calls["n"] == 1, "the failed download was retried on every call"
    assert capsys.readouterr().out.count("IHSG benchmark unavailable") == 1


# ---- 3. the survivorship warning must not be able to vanish --------------

def test_a_warning_that_cannot_be_determined_is_stated_not_dropped():
    """If the import fails the survivorship warning simply did not print.

    A biased backtest then ran looking clean. A warning that can vanish is
    worse than no warning at all, because its absence reads as "no problem".
    """
    src = (ROOT / "kala_engine.py").read_text(encoding="utf-8")
    i = src.index("UNIVERSE_IS_POINT_IN_TIME")
    block = src[i:i + 900]
    assert "except Exception:\n        pass" not in block, (
        "the survivorship warning can still vanish silently")
    assert "could not determine" in block
    assert "SURVIVORSHIP-BIASED until shown otherwise" in block


def test_the_fallback_assumes_the_pessimistic_case():
    """When it cannot tell, it must assume BIASED — not assume clean."""
    src = (ROOT / "kala_engine.py").read_text(encoding="utf-8")
    i = src.index("could not determine")
    block = src[i:i + 400]
    assert "Assume" in block
    assert "SURVIVORSHIP-BIASED" in block
    for optimistic in ("probably fine", "assume clean", "ignore"):
        assert optimistic not in block.lower()


# ---- what was deliberately NOT changed ----------------------------------

def test_the_honest_handlers_were_left_alone():
    """Five swallowing handlers are fine; changing them would be churn.

    Recorded so a future sweep does not "fix" them and call it progress.
    """
    src = (ROOT / "kala_engine.py").read_text(encoding="utf-8")
    # optional dependencies: the script is designed to run without them
    assert "ta = None" in src
    assert "Backtest = Strategy = crossover = None" in src
    # the SMA fallback announces itself
    assert "params_optimized = False" in src
    assert "'DEFAULT':>10" in src
    # the download loop counts what it skipped
    assert "OK)" in src
