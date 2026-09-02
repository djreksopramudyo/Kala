"""The daily log printed one entry threshold; the scanner used another.

``daily_run`` logs, off the profile-resolved config, on every single run::

    exit profile: FORWARD_TEST — no stop/target/trailing,
    entry score >= 80, hold 60d.

``kala_daily_trader`` decided the BUY cutoff with a bare
``Config().backtest.score_entry_threshold`` — the LEGACY default, 60, always,
never reading runner_config.json. The paper trader buys everything labelled
BUY or STRONG BUY, so under ``forward_test`` every entry scoring 60-79 was a
trade the profile says should not happen — and the +1.71%/trade measurement
that justifies the profile was made at baseline 80 over 5,241 trades. Those
entries are not in it.

The comment above that log line says a strategy change this large must never
be something you have to read the source to discover. It was printed, and it
was not what ran.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kala.config import Config, config_for_profile, live_config  # noqa: E402

LEGACY_CUTOFF = 60.0
FORWARD_TEST_CUTOFF = 80.0


def cfg_file(tmp_path, **settings) -> Path:
    p = tmp_path / "runner_config.json"
    p.write_text(json.dumps(settings), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# the two numbers that disagreed
# ---------------------------------------------------------------------------

def test_the_profiles_really_do_specify_different_cutoffs():
    """If these were equal the whole finding would be moot. They are not."""
    assert Config().backtest.score_entry_threshold == LEGACY_CUTOFF
    got = config_for_profile("forward_test").backtest.score_entry_threshold
    assert got == FORWARD_TEST_CUTOFF
    assert got != LEGACY_CUTOFF


def test_the_live_cutoff_follows_the_configured_profile(tmp_path):
    p = cfg_file(tmp_path, exit_profile="forward_test")
    assert live_config(p).backtest.score_entry_threshold == FORWARD_TEST_CUTOFF
    assert live_config(p).backtest.holding_max_days == 60


def test_no_profile_is_the_historical_behaviour(tmp_path):
    """Nothing changes for anyone who has not opted in — that is the point.

    The old code was a hardcoded ``Config()``. With no exit_profile set, this
    must produce exactly that, or the fix would silently move a live bot's
    entry cutoff.
    """
    p = cfg_file(tmp_path, daily_capital_idr=5_000_000)
    assert live_config(p).backtest.score_entry_threshold == LEGACY_CUTOFF
    assert live_config(p).backtest.holding_max_days == Config().backtest.holding_max_days


@pytest.mark.parametrize("content", ["", "{not json", "[]", "null", '"hello"'])
def test_an_unusable_config_falls_back_to_legacy_not_to_a_crash(tmp_path, content):
    """The live scanner must not stop scanning over a malformed config."""
    p = tmp_path / "runner_config.json"
    p.write_text(content, encoding="utf-8")
    assert live_config(p).backtest.score_entry_threshold == LEGACY_CUTOFF


def test_a_missing_config_falls_back_to_legacy(tmp_path):
    assert live_config(tmp_path / "nope.json").backtest.score_entry_threshold \
        == LEGACY_CUTOFF


def test_an_unknown_profile_still_raises(tmp_path):
    """A typo must not quietly run the profile you were moving away from."""
    p = cfg_file(tmp_path, exit_profile="forwardtest")
    with pytest.raises(ValueError, match="unknown exit_profile"):
        live_config(p)


# ---------------------------------------------------------------------------
# the log and the decision must now be the same number
# ---------------------------------------------------------------------------

def test_the_logged_threshold_is_the_one_the_scanner_would_use(tmp_path):
    """The finding, stated as an equality.

    daily_run logs ``trade_cfg.backtest.score_entry_threshold`` where
    trade_cfg = config_for_profile(cfg["exit_profile"]). The scanner now
    resolves the same way from the same file, so the two cannot drift.
    """
    for profile, expected in (("forward_test", FORWARD_TEST_CUTOFF),
                              ("legacy", LEGACY_CUTOFF),
                              (None, LEGACY_CUTOFF)):
        settings = {} if profile is None else {"exit_profile": profile}
        p = cfg_file(tmp_path, **settings)
        logged = config_for_profile(settings.get("exit_profile")) \
            .backtest.score_entry_threshold
        decided = live_config(p).backtest.score_entry_threshold
        assert logged == decided == expected, profile


def test_the_scanner_reads_the_resolved_config(tmp_path):
    """Ties the resolver to the call site without grepping the source.

    ``co_names`` comes off the COMPILED function, so this cannot pass on a
    call that was deleted or commented out. Its honest limit: it would still
    pass if the call became unreachable, and exercising the real one means
    running the whole networked scan.
    """
    import kala_daily_trader as dt
    names = dt.get_live_signal.__code__.co_names
    assert "live_config" in names
    assert "Config" not in names, (
        "a bare Config() is back in the live signal path")


# ---------------------------------------------------------------------------
# the band ladder itself — the live buy decision, now testable
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("score,expected", [
    (95, "STRONG BUY"), (80, "STRONG BUY"), (79.9, "BUY"), (60, "BUY"),
    (59.9, "HOLD"), (50, "HOLD"), (49.9, "SELL"), (35, "SELL"),
    (34.9, "STRONG SELL"), (0, "STRONG SELL"),
])
def test_the_legacy_bands_are_unchanged(score, expected):
    from kala_daily_trader import signal_for_score
    assert signal_for_score(score, LEGACY_CUTOFF) == expected


@pytest.mark.parametrize("score,expected", [
    (95, "STRONG BUY"), (80, "STRONG BUY"),
    (79.9, "HOLD"), (60, "HOLD"),      # NOT a buy under this profile
    (49.9, "SELL"), (34.9, "STRONG SELL"),
])
def test_a_higher_cutoff_stops_labelling_60_to_79_as_buy(score, expected):
    """The trades the measurement never included, no longer entered."""
    from kala_daily_trader import signal_for_score
    assert signal_for_score(score, FORWARD_TEST_CUTOFF) == expected


def test_an_unsafe_stock_is_avoided_at_any_score():
    from kala_daily_trader import signal_for_score
    assert signal_for_score(99, LEGACY_CUTOFF, is_safe=False) == "AVOID"
    assert signal_for_score(0, LEGACY_CUTOFF, is_safe=False) == "AVOID"


def test_strong_never_sits_below_the_buy_cutoff():
    """A cutoff above STRONG would make STRONG BUY the weaker label.

    With buy_threshold 90 and STRONG hardcoded at 80, an unguarded ladder
    labels a score of 85 STRONG BUY — above the strong line, below the line
    that decides whether to buy at all.
    """
    from kala_daily_trader import signal_for_score
    assert signal_for_score(85, 90.0) == "HOLD"
    assert signal_for_score(90, 90.0) == "STRONG BUY"


def test_the_plain_buy_band_is_empty_when_the_cutoff_equals_strong():
    """Not a bug — the paper trader buys both labels — but it must be a
    consequence of the numbers, not an ordering accident."""
    from kala_daily_trader import signal_for_score
    labels = {signal_for_score(s, FORWARD_TEST_CUTOFF) for s in range(80, 101)}
    assert labels == {"STRONG BUY"}
