"""run_walkforward must be able to validate THROUGH a chosen exit geometry.

Every historical verdict in PROJECT_STATUS — including the standing
"unvalidated" on the composite score — was measured with the stop/target/
trailing ladder active. That ladder was later measured as subtracting roughly
1.6 points per trade, which means those verdicts may describe the exits rather
than the signal. Answering that needs the harness to be runnable with the
exits off, and until now there was no flag for it: the comment claiming a run
was "with exits off" would have run the ordinary configuration and produced an
ordinary negative, looking entirely normal.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from kala.config import Config, config_for_profile

ROOT = Path(__file__).resolve().parent.parent



def _utf8_env() -> dict:
    """Environment for a subprocess whose stdout this test decodes as UTF-8.

    The parent passes encoding="utf-8"; on Windows a Python child writing to a
    pipe encodes with the locale codepage instead, so the two ends disagree and
    any non-ASCII in --help output (this project's docstrings are full of
    em-dashes) comes back mangled or raises. Setting PYTHONIOENCODING makes the
    child agree with the parent on every platform.
    """
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("PYTHONPATH", None)
    return env

def test_the_flag_exists_and_is_constrained():
    """A free-text profile would let a typo silently run the legacy ladder."""
    out = subprocess.run([sys.executable, str(ROOT / "run_walkforward.py"), "--help"],
                         capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT),
        env=_utf8_env(), errors="replace")
    assert "--exit-profile" in out.stdout
    assert "forward_test" in out.stdout
    assert "legacy" in out.stdout


def test_an_invalid_profile_is_rejected_by_the_parser():
    out = subprocess.run(
        [sys.executable, str(ROOT / "run_walkforward.py"), "--exit-profile", "no_exits"],
        capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT),
        env=_utf8_env(), errors="replace")
    assert out.returncode != 0
    assert "invalid choice" in out.stderr


def test_legacy_profile_reproduces_the_historical_risk_settings():
    """The numbers already in PROJECT_STATUS must stay reproducible."""
    legacy = config_for_profile("legacy")
    d = Config()
    assert legacy.risk == d.risk
    assert legacy.backtest.holding_max_days == d.backtest.holding_max_days


def test_forward_test_profile_disables_the_ladder():
    from kala.exits import governing_stop
    c = config_for_profile("forward_test")
    assert c.risk.trailing_enabled is False
    stop, _, _ = governing_stop(1000.0, 1800.0, None, c.risk)
    assert stop < 50.0, "a price stop could still close the position"


@pytest.mark.parametrize("profile,expected_hold", [("legacy", 20), ("forward_test", 60)])
def test_each_profile_carries_its_own_holding_limit(profile, expected_hold):
    assert config_for_profile(profile).backtest.holding_max_days == expected_hold


# ---- the wiring, not the pieces --------------------------------------------

def test_the_flag_actually_reaches_the_config_the_harness_uses():
    """NON-VACUITY GUARD.

    Testing config_for_profile() and the argparse choices proves the parts
    work; neither notices if main() ignores the flag. Pin the composed Config.
    """
    from kala.config import CostModel
    from kala.exits import governing_stop
    from run_walkforward import build_run_config

    c = build_run_config("forward_test", CostModel(), False, False)
    assert c.risk.trailing_enabled is False
    stop, _, _ = governing_stop(1000.0, 1800.0, None, c.risk)
    assert stop < 50.0
    assert c.backtest.holding_max_days == 60
    assert c.backtest.score_entry_threshold == pytest.approx(80.0)


def test_legacy_composition_matches_the_historical_settings():
    from kala.config import CostModel
    from run_walkforward import build_run_config
    c = build_run_config("legacy", CostModel(), False, False)
    d = Config()
    assert c.risk == d.risk
    assert c.backtest.holding_max_days == d.backtest.holding_max_days
    assert c.backtest.score_entry_threshold == d.backtest.score_entry_threshold


def test_other_flags_survive_the_profile_composition():
    """--apply-entry-vetoes and --veto-ranging-stock must keep working."""
    from kala.config import CostModel
    from run_walkforward import build_run_config
    c = build_run_config("forward_test", CostModel(), True, True)
    assert c.backtest.apply_entry_vetoes is True
    assert c.entries.veto_ranging_stock is True


def test_holding_days_override_wins_over_the_profile():
    from kala.config import CostModel
    from run_walkforward import build_run_config
    c = build_run_config("forward_test", CostModel(), False, False, holding_days=90)
    assert c.backtest.holding_max_days == 90
