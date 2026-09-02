"""A safety device that turns itself off must not do it quietly.

``load_breaker_state`` answered ``(None, False)`` for both a sidecar that does
not exist yet and one that exists but will not parse. Downstream those are the
same event, and the consequence is not symmetric:

    stored_peak=None  -> the high-water mark re-anchors to TODAY's equity
    was_halted=False  -> evaluate_breaker skips the "still halted" branch
                      -> drawdown reads 0.0%, halt threshold not met
                      -> new buys resume, having satisfied none of the
                         resume_drawdown_pct hysteresis

so an account halted at the drawdown limit starts buying again the moment the
file that remembered the halt becomes unreadable — while the report says
"First run: high-water mark anchored to today's equity".

The DEFAULT is deliberately unchanged: re-anchor, do not halt. That was a
documented choice and this module does not overrule it. What changed is that
the case is distinguishable, reported, and reversible by configuration.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kala.circuit_breaker import (  # noqa: E402
    BreakerConfig,
    evaluate_breaker,
    load_breaker_state,
    read_breaker_state,
    save_breaker_state,
)

ON = BreakerConfig(enabled=True, halt_drawdown_pct=15.0, resume_drawdown_pct=10.0)


def _halted_sidecar(tmp_path: Path) -> Path:
    """A real halt, written by the real writer: 30% below a 100k peak."""
    p = tmp_path / "breaker_state.json"
    state = evaluate_breaker(equity=70_000.0, stored_peak=100_000.0, cfg=ON)
    assert state.halted, "fixture must actually be halted or it tests nothing"
    save_breaker_state(p, state)
    return p


def test_absent_and_damaged_sidecars_are_now_distinguishable(tmp_path):
    damaged = _halted_sidecar(tmp_path)
    damaged.write_text("{not json at all", encoding="utf-8")

    absent = read_breaker_state(tmp_path / "nope.json")
    broken = read_breaker_state(damaged)

    assert absent.existed is False and absent.error is None
    assert broken.existed is True and broken.error is not None
    # Both still report no usable peak -- that part was never the problem.
    assert absent.peak is None and broken.peak is None


def test_a_clean_sidecar_round_trips_without_an_error(tmp_path):
    load = read_breaker_state(_halted_sidecar(tmp_path))
    assert load.error is None
    assert load.existed is True
    assert load.halted is True
    assert load.peak == 100_000.0


def test_the_default_still_re_anchors_rather_than_halting(tmp_path):
    """The documented long-standing behaviour, pinned so it cannot drift."""
    damaged = _halted_sidecar(tmp_path)
    damaged.write_text("{not json at all", encoding="utf-8")

    peak, halted = load_breaker_state(damaged)
    assert peak is None and halted is False
    assert evaluate_breaker(equity=70_000.0, stored_peak=peak, was_halted=halted,
                            cfg=ON).halted is False


SAFE = BreakerConfig(enabled=True, halt_drawdown_pct=15.0,
                     resume_drawdown_pct=10.0,
                     preserve_halt_when_unreadable=True)


def test_carrying_was_halted_alone_does_NOT_hold_the_halt(tmp_path):
    """Why state_lost needs its own argument, pinned as behaviour.

    This is the trap: passing was_halted=True looks like it preserves the
    halt. It does not — stored_peak is None, so the peak re-anchors to today,
    drawdown reads 0.0%, and the hysteresis branch resumes immediately.
    """
    state = evaluate_breaker(equity=70_000.0, stored_peak=None, was_halted=True,
                             cfg=SAFE)
    assert state.halted is False
    assert "RESUMED" in state.reason


def test_state_lost_halts_when_the_operator_opted_in(tmp_path):
    state = evaluate_breaker(equity=70_000.0, stored_peak=None, was_halted=False,
                             state_lost=True, cfg=SAFE)
    assert state.halted is True
    assert "unreadable" in state.reason
    # Not a stuck halt: it says how to clear it deliberately.
    assert "delete it to re-anchor" in state.reason


def test_state_lost_is_ignored_unless_the_operator_opted_in():
    state = evaluate_breaker(equity=70_000.0, stored_peak=None, was_halted=False,
                             state_lost=True, cfg=ON)
    assert state.halted is False          # default is unchanged


def test_a_genuine_first_run_never_sets_state_lost(tmp_path):
    """The flag is about state that was LOST, not state that never existed."""
    load = read_breaker_state(tmp_path / "nope.json")
    assert load.error is None
    state = evaluate_breaker(equity=70_000.0, stored_peak=load.peak,
                             was_halted=load.halted,
                             state_lost=load.error is not None, cfg=SAFE)
    assert state.halted is False


def test_opting_in_does_not_disturb_a_clean_read(tmp_path):
    p = tmp_path / "breaker_state.json"
    save_breaker_state(p, evaluate_breaker(equity=98_000.0, stored_peak=100_000.0,
                                           cfg=ON))
    load = read_breaker_state(p)
    state = evaluate_breaker(equity=98_000.0, stored_peak=load.peak,
                             was_halted=load.halted,
                             state_lost=load.error is not None, cfg=SAFE)
    assert state.halted is False and load.peak == 100_000.0


def test_the_missed_halt_is_measurable_not_just_asserted(tmp_path):
    """Show the actual before/after on the same halted account."""
    damaged = _halted_sidecar(tmp_path)
    intact = read_breaker_state(damaged)
    damaged.write_text("{not json at all", encoding="utf-8")

    load = read_breaker_state(damaged)
    lenient = evaluate_breaker(equity=70_000.0, stored_peak=load.peak,
                               was_halted=load.halted,
                               state_lost=load.error is not None, cfg=ON)
    strict = evaluate_breaker(equity=70_000.0, stored_peak=load.peak,
                              was_halted=load.halted,
                              state_lost=load.error is not None, cfg=SAFE)

    assert intact.halted is True          # the account WAS halted
    assert lenient.halted is False        # ...and silently is not, by default
    assert strict.halted is True          # ...unless the operator says otherwise
    assert lenient.drawdown_pct == 0.0    # a 30% drawdown reported as 0%


def test_daily_run_reads_the_detailed_loader():
    """The report cannot mention a lost halt if the caller never asks for one.

    A string check because the breaker call lives inline in ``main()``, and it
    covers the failure that actually happened while writing this: an earlier
    draft reported the loss but forwarded nothing, so ``evaluate_breaker``
    could not act on it and the opt-in silently did nothing.
    """
    src = (ROOT / "daily_run.py").read_text(encoding="utf-8")
    assert "read_breaker_state(BREAKER_PATH)" in src
    assert "BREAKER STATE LOST" in src
    assert "breaker_preserve_halt_when_unreadable" in src
    # The wiring, not just the reporting: without this the opt-in is inert.
    assert "state_lost=breaker_load.error is not None" in src
