"""Inverted breaker thresholds must not turn the safety device into a metronome.

Hysteresis only works while resume sits BELOW halt. Inverted — an easy
mistake, both fields are "a drawdown percentage" — the breaker flips every
single day at a CONSTANT drawdown:

    halt at 10%          -> halted
    12% > 15% is False   -> resumed
    12% >= 10% is True   -> halted
    ...

and new buys are permitted on every other one of those days. Nothing warned;
the daily message just alternated between HALTED and RESUMED.
"""

import pytest

from kala.circuit_breaker import BreakerConfig, evaluate_breaker
from kala.preflight import FAIL, OK, SKIP, check_breaker_config


def _run(equities, cfg):
    """Replay a sequence the way daily_run does, carrying peak and state."""
    peak, halted, states = None, False, []
    for eq in equities:
        st = evaluate_breaker(eq, 0.0, stored_peak=peak, was_halted=halted, cfg=cfg)
        peak, halted = st.peak, st.halted
        states.append(st)
    return states


INVERTED = BreakerConfig(enabled=True, halt_drawdown_pct=10.0,
                         resume_drawdown_pct=15.0)
SANE = BreakerConfig(enabled=True, halt_drawdown_pct=10.0,
                     resume_drawdown_pct=5.0)

# Falls to a 12% drawdown and simply stays there.
FLAT_DRAWDOWN = [100, 95, 90, 88, 88, 88, 88]


def test_inverted_thresholds_do_not_chatter():
    """The regression. A constant drawdown must produce a constant state."""
    states = _run(FLAT_DRAWDOWN, INVERTED)
    settled = [s.halted for s in states[3:]]        # once past 10%
    assert all(settled), f"breaker flipped: {settled}"


def test_inverted_thresholds_are_reported_not_silently_clamped():
    states = _run(FLAT_DRAWDOWN, INVERTED)
    assert "CONFIG" in states[-1].reason
    assert "flip on and off" in states[-1].reason


def test_sane_thresholds_still_hysteresise():
    """The clamp must not flatten a correctly configured breaker: recovery
    to 7% should NOT resume when the resume line is 5%."""
    states = _run([100, 90, 89, 93], SANE)          # dd 0, 10, 11, 7
    assert states[1].halted
    assert states[3].halted, "resumed too early — hysteresis was lost"


def test_sane_thresholds_resume_below_the_resume_line():
    states = _run([100, 90, 89, 96], SANE)          # ends at dd 4% < 5%
    assert not states[-1].halted
    assert "RESUMED" in states[-1].reason


def test_no_config_warning_when_thresholds_are_sane():
    states = _run(FLAT_DRAWDOWN, SANE)
    assert all("CONFIG" not in s.reason for s in states)


# ------------------------------------------------------------- first run ---

def test_first_run_says_the_peak_starts_today():
    """Enabling the breaker while already underwater reports 0.0% drawdown,
    because the high-water mark starts now. That must not read as
    confirmation that nothing is wrong."""
    st = evaluate_breaker(70.0, 0.0, stored_peak=None, was_halted=False, cfg=SANE)
    assert st.drawdown_pct == 0.0
    assert "anchored to today" in st.reason


def test_later_runs_do_not_repeat_the_first_run_note():
    st = evaluate_breaker(95.0, 0.0, stored_peak=100.0, was_halted=False, cfg=SANE)
    assert "anchored to today" not in st.reason


# -------------------------------------------------------------- preflight ---

def test_preflight_fails_on_inverted_thresholds():
    checks = check_breaker_config({"breaker_enabled": True,
                                   "breaker_halt_drawdown_pct": 10.0,
                                   "breaker_resume_drawdown_pct": 15.0})
    assert checks[0].status == FAIL
    assert "ABOVE" in checks[0].message


def test_preflight_passes_sane_thresholds():
    checks = check_breaker_config({"breaker_enabled": True,
                                   "breaker_halt_drawdown_pct": 15.0,
                                   "breaker_resume_drawdown_pct": 10.0})
    assert checks[0].status == OK


def test_preflight_skips_when_disabled():
    assert check_breaker_config({"breaker_enabled": False})[0].status == SKIP


def test_preflight_fails_on_a_limit_that_can_never_trip():
    checks = check_breaker_config({"breaker_enabled": True,
                                   "breaker_halt_drawdown_pct": 0.0,
                                   "breaker_resume_drawdown_pct": 0.0})
    assert checks[0].status == FAIL


def test_preflight_fails_on_non_numeric_thresholds():
    checks = check_breaker_config({"breaker_enabled": True,
                                   "breaker_halt_drawdown_pct": "fifteen"})
    assert checks[0].status == FAIL


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
