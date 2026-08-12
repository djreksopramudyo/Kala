"""Preflight checks — DEPLOY_CHECKLIST.md's mechanical items, automated.

The check that matters most here is the *drift* test at the bottom: it fails
when someone adds a config key to daily_run without registering it in
KNOWN_CONFIG_KEYS, which would silently weaken the typo detector.
"""

import pytest

from kala.notify import CHAT_ID_ENV, TOKEN_ENV
from kala.preflight import (
    FAIL,
    KNOWN_CONFIG_KEYS,
    OK,
    SKIP,
    WARN,
    Check,
    check_config_keys,
    check_secrets,
    check_state,
    check_timers,
    format_checks,
)


def _status(checks, name):
    return next(c.status for c in checks if c.name == name)


# --------------------------------------------------------------- secrets ---

def test_token_in_config_is_a_failure_not_a_warning():
    """A token in runner_config.json has already leaked every time that file
    was zipped or shared — which has happened in this project."""
    checks = check_secrets({"telegram_token": "12345:realtokenvalue"}, env={})
    assert _status(checks, "secrets/token") == FAIL
    msg = next(c.message for c in checks if c.name == "secrets/token")
    assert "revoke" in msg.lower()          # must tell them it's compromised


def test_placeholder_token_is_not_treated_as_a_real_credential():
    """runner_config.json.example ships SET_VIA_..._ENV_VAR_INSTEAD; copying
    it unedited must not read as 'token safely configured'."""
    checks = check_secrets(
        {"telegram_token": "SET_VIA_KALA_TELEGRAM_TOKEN_ENV_VAR_INSTEAD"},
        env={})
    assert _status(checks, "secrets/token") == FAIL


def test_env_var_token_passes():
    checks = check_secrets({}, env={TOKEN_ENV: "12345:abc",
                                    CHAT_ID_ENV: "999"})
    assert _status(checks, "secrets/token") == OK
    assert _status(checks, "secrets/chat_id") == OK


def test_missing_token_everywhere_fails():
    checks = check_secrets({}, env={})
    assert _status(checks, "secrets/token") == FAIL


def test_chat_id_in_config_warns_but_does_not_fail():
    """It identifies a chat, it does not grant access — a real distinction,
    so it must not cry wolf at the same volume as a leaked token."""
    checks = check_secrets({"telegram_chat_id": "12345"},
                           env={TOKEN_ENV: "t"})
    assert _status(checks, "secrets/chat_id") == WARN


# ---------------------------------------------------------- config keys ---

def test_typo_key_is_flagged_with_a_suggestion():
    """The silent failure nobody looks for: cfg.get() never raises, so a
    mistyped key keeps the default forever."""
    checks = check_config_keys({"scorecard_report_weekdays": 4})
    assert checks[0].status == WARN
    assert "scorecard_report_weekday" in checks[0].message


def test_unrecognised_key_with_no_near_match_still_flagged():
    checks = check_config_keys({"completely_made_up_setting": 1})
    assert checks[0].status == WARN
    assert "did you mean" not in checks[0].message


def test_clean_config_passes():
    checks = check_config_keys({"max_positions": 8, "daily_capital_idr": 1e6})
    assert checks[0].status == OK


# ---------------------------------------------------------------- state ---

def test_future_entry_date_is_caught():
    state = {"positions": {"BBCA.JK": {"entry_price": 8000, "shares": 100,
                                       "entry_date": "2099-01-01"}}}
    checks = check_state(state, today="2026-08-05")
    assert checks[0].status == FAIL
    assert "future" in checks[0].message


def test_zero_price_or_shares_is_caught():
    state = {"positions": {
        "A.JK": {"entry_price": 0, "shares": 100, "entry_date": "2026-01-02"},
        "B.JK": {"entry_price": 100, "shares": 0, "entry_date": "2026-01-02"}}}
    checks = check_state(state, today="2026-08-05")
    assert checks[0].status == FAIL
    assert "A.JK" in checks[0].message and "B.JK" in checks[0].message


def test_missing_entry_date_is_caught_because_twr_needs_it():
    state = {"positions": {"A.JK": {"entry_price": 100, "shares": 10}}}
    checks = check_state(state, today="2026-08-05")
    assert checks[0].status == FAIL
    assert "entry_date" in checks[0].message


def test_empty_book_warns_about_unrecorded_fills():
    """DEPLOY_CHECKLIST calls the unrecorded fill the most common failure
    mode, so an empty state is worth a nudge rather than a silent pass."""
    checks = check_state({}, today="2026-08-05")
    assert checks[0].status == WARN
    assert "/buy" in checks[0].message


def test_well_formed_state_passes():
    state = {"positions": {"A.JK": {"entry_price": 100, "shares": 10,
                                    "entry_date": "2026-01-02"}}, "log": []}
    checks = check_state(state, today="2026-08-05")
    assert checks[0].status == OK


# --------------------------------------------------------------- timers ---

def test_missing_fundamentals_timer_warns_about_the_blocked_lead():
    checks = check_timers(runner=lambda a: "kala-bot.service kala-daily.timer")
    assert _status(checks, "timers/kala-fundamentals.timer") == WARN
    msg = next(c.message for c in checks
               if c.name == "timers/kala-fundamentals.timer")
    assert "blocked" in msg.lower()


def test_missing_daily_timer_is_a_failure():
    checks = check_timers(runner=lambda a: "kala-bot.service")
    assert _status(checks, "timers/kala-daily.timer") == FAIL


def test_all_units_installed_passes():
    everything = ("kala-bot.service kala-daily.timer kala-fundamentals.timer")
    checks = check_timers(runner=lambda a: everything)
    assert all(c.status == OK for c in checks)


def test_systemd_query_failure_warns_rather_than_raising():
    def boom(args):
        raise OSError("systemctl exploded")
    checks = check_timers(runner=boom)
    assert checks[0].status == WARN


# ------------------------------------------------------------ formatting ---

def test_format_reports_failure_count_and_refuses_to_look_clean():
    checks = [Check("a", FAIL, "broken"), Check("b", WARN, "iffy"),
              Check("c", OK, "fine")]
    text = format_checks(checks)
    assert "1 FAILURE" in text
    assert "All checks passed" not in text


def test_format_says_all_passed_only_when_truly_clean():
    text = format_checks([Check("a", OK, "fine"), Check("b", SKIP, "n/a")])
    assert "All checks passed" in text


# ------------------------------------------------------------------ drift ---

def test_known_keys_stay_in_sync_with_daily_run_defaults():
    """The one that protects the typo check from rotting.

    Every key daily_run ships a default for must be registered here, or a
    legitimate setting would get reported as a typo the first time someone
    puts it in their config.
    """
    import daily_run

    missing = set(daily_run.DEFAULT_CONFIG) - set(KNOWN_CONFIG_KEYS)
    assert not missing, (
        f"daily_run.DEFAULT_CONFIG has keys unknown to kala.preflight: "
        f"{sorted(missing)}. Add them to KNOWN_CONFIG_KEYS.")


def test_example_config_passes_its_own_typo_check():
    """runner_config.json.example is what users copy; if it contained a key
    the code no longer reads, everyone would inherit a warning."""
    import json
    from pathlib import Path

    example = json.loads(
        (Path(__file__).resolve().parent.parent /
         "runner_config.json.example").read_text(encoding="utf-8"))
    checks = check_config_keys(example)
    assert all(c.status == OK for c in checks), [c.message for c in checks]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
