"""The validated configuration must be reachable from the LIVE path.

Every sweep pointed the same way — the exit ladder subtracts value, the entry
score selects, expectancy sits in a right tail — and none of it was reachable
without editing source. daily_run built a default Config(), so the system kept
running the configuration that was measured as harmful. A finding that the
running system cannot be switched to is not a finding, it is a note.
"""

import pytest

from kala.config import Config, config_for_profile, forward_test_config
from kala.exits import governing_stop


def test_forward_test_profile_disables_every_price_exit():
    c = forward_test_config()
    assert c.risk.trailing_enabled is False
    # even after a large run-up the stop must stay inert
    stop, _, _ = governing_stop(1000.0, 2000.0, None, c.risk)
    assert stop < 50.0
    assert c.risk.target_profit_pct > 100.0
    assert c.risk.breakeven_trigger_pct > 100.0


def test_forward_test_profile_carries_the_validated_entry_and_hold():
    c = forward_test_config()
    assert c.backtest.score_entry_threshold == pytest.approx(80.0)
    assert c.backtest.holding_max_days == 60


def test_threshold_and_hold_are_overridable():
    c = forward_test_config(score_threshold=90.0, holding_days=40)
    assert c.backtest.score_entry_threshold == pytest.approx(90.0)
    assert c.backtest.holding_max_days == 40


def test_legacy_profile_is_untouched_defaults():
    """Existing backtest numbers were computed under this; it must not drift."""
    legacy = config_for_profile("legacy")
    d = Config()
    assert legacy.risk.hard_stop_pct == d.risk.hard_stop_pct
    assert legacy.risk.target_profit_pct == d.risk.target_profit_pct
    assert legacy.risk.trailing_enabled == d.risk.trailing_enabled
    assert legacy.backtest.score_entry_threshold == d.backtest.score_entry_threshold


@pytest.mark.parametrize("name", [None, "", "legacy", "LEGACY", "default"])
def test_absent_or_default_profile_stays_legacy(name):
    """Silence must mean the old behaviour — never a silent strategy change."""
    assert config_for_profile(name).risk.hard_stop_pct == Config().risk.hard_stop_pct


def test_forward_test_is_selectable_by_name():
    c = config_for_profile("forward_test")
    assert c.risk.trailing_enabled is False
    assert c.backtest.holding_max_days == 60


def test_a_typo_raises_rather_than_falling_back():
    """A misspelled profile must not quietly run the one you are moving away
    from — that is the failure this project keeps finding."""
    with pytest.raises(ValueError, match="unknown exit_profile"):
        config_for_profile("forwrd_test")
    with pytest.raises(ValueError, match="unknown exit_profile"):
        config_for_profile("no_exits")


def test_the_two_profiles_actually_differ():
    a, b = config_for_profile("legacy"), config_for_profile("forward_test")
    assert a.risk.hard_stop_pct != b.risk.hard_stop_pct
    assert a.backtest.holding_max_days != b.backtest.holding_max_days
