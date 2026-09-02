"""Discipline tracker: separating 'the strategy failed' from 'it never ran'."""

import numpy as np
import pandas as pd
import pytest

from kala.config import CostModel
from kala.discipline import (
    ENGINE,
    HOLDING_LIMIT,
    MANUAL,
    UNKNOWN,
    classify_exit,
    counterfactual_hold,
    format_report,
    summarise_discipline,
)

# ---- classification --------------------------------------------------------

def test_holding_limit_is_recognised():
    assert classify_exit("[CONSIDER] max holding period (60 bars >= 60)") == HOLDING_LIMIT


@pytest.mark.parametrize("reason", [
    "[URGENT] governing stop hit: 950.00 <= 960.00 (initial, phase 1)",
    "[CONSIDER] target profit reached (+8.2%)",
    "[URGENT] DEATH CROSS today (fast crossed below slow)",
])
def test_engine_exits_are_recognised(reason):
    assert classify_exit(reason) == ENGINE


def test_manual_is_the_default_reading():
    assert classify_exit("manual sell") == MANUAL
    assert classify_exit("took profit, felt toppy") == MANUAL


def test_missing_reason_is_unknown_not_manual():
    assert classify_exit(None) == UNKNOWN
    assert classify_exit("") == UNKNOWN
    assert classify_exit("   ") == UNKNOWN


def test_unrecognised_text_counts_as_manual_not_engine():
    """Over-crediting the engine would hide exactly what this module exists to
    surface, so anything unrecognised must fall to the human side."""
    assert classify_exit("SELL because chart looked bad") == MANUAL


# ---- summary ---------------------------------------------------------------

def _t(pnl, reason, entry="2026-01-05", date="2026-02-05", ticker="AAA.JK", entry_px=1000.0):
    return {"ticker": ticker, "pnl_pct": pnl, "reason": reason,
            "entry_date": entry, "date": date, "entry": entry_px, "exit": 1000.0}


def test_system_share_is_zero_when_every_close_is_manual():
    log = [_t(-4.8, "manual sell") for _ in range(10)]
    s = summarise_discipline(log)
    assert s.n_closed == 10
    assert s.by_agent[MANUAL] == 10
    assert s.system_share == 0.0


def test_system_share_counts_both_engine_and_holding_limit():
    log = ([_t(1.0, "[CONSIDER] max holding period (60 bars >= 60)")] * 3
           + [_t(-2.0, "[URGENT] governing stop hit: x")] * 1
           + [_t(-4.0, "manual sell")] * 4)
    s = summarise_discipline(log)
    assert s.system_share == pytest.approx(0.5)


def test_mean_pnl_and_hold_are_reported_per_agent():
    log = [_t(10.0, "manual sell", entry="2026-01-01", date="2026-01-11"),
           _t(-2.0, "manual sell", entry="2026-01-01", date="2026-01-21")]
    s = summarise_discipline(log)
    assert s.pnl_by_agent[MANUAL] == pytest.approx(4.0)
    assert s.hold_by_agent[MANUAL] == pytest.approx(15.0)


def test_entries_without_an_entry_date_are_counted_not_dropped():
    log = [_t(1.0, "manual sell"), {"ticker": "B.JK", "pnl_pct": 2.0,
                                    "reason": "manual sell", "date": "2026-02-01",
                                    "entry": 100.0}]
    s = summarise_discipline(log)
    assert s.n_closed == 2
    assert s.n_without_entry_date == 1


def test_empty_log_does_not_divide_by_zero():
    s = summarise_discipline([])
    assert s.n_closed == 0 and s.system_share == 0.0
    assert "No closed trades" in format_report(s)


# ---- counterfactual --------------------------------------------------------

def _hist(n=200, start="2026-01-01", drift=0.0, price=1000.0):
    idx = pd.bdate_range(start, periods=n)
    close = price * (1 + drift) ** np.arange(n)
    return pd.DataFrame({"Open": close, "High": close, "Low": close,
                         "Close": close, "Volume": np.full(n, 1e6)}, index=idx)


def test_counterfactual_scores_a_rising_stock_cut_early_as_a_cost():
    """Sold at -5% on a stock that kept climbing: the rule would have won."""
    hist = {"AAA.JK": _hist(drift=0.002)}
    log = [_t(-5.0, "manual sell", entry="2026-01-01", ticker="AAA.JK", entry_px=1000.0)]
    cf = counterfactual_hold(log, hist, holding_days=60, costs=CostModel())
    assert cf.n_compared == 1
    assert cf.rule_mean > cf.actual_mean
    assert cf.delta > 0


def test_counterfactual_credits_a_good_manual_exit():
    hist = {"AAA.JK": _hist(drift=-0.002)}     # kept falling after the exit
    log = [_t(-5.0, "manual sell", entry="2026-01-01", ticker="AAA.JK")]
    cf = counterfactual_hold(log, hist, holding_days=60)
    assert cf.delta < 0


def test_trades_too_recent_to_have_run_the_rule_are_skipped(): 
    """A position the rule has not finished with cannot be scored against a
    truncated window — that would flatter whichever side the market favoured."""
    hist = {"AAA.JK": _hist(n=30)}             # only 30 bars, rule needs 60
    log = [_t(-5.0, "manual sell", entry="2026-01-01", ticker="AAA.JK")]
    cf = counterfactual_hold(log, hist, holding_days=60)
    assert cf.n_compared == 0 and cf.n_skipped == 1


def test_engine_closes_are_not_second_guessed():
    hist = {"AAA.JK": _hist(drift=0.002)}
    log = [_t(-5.0, "[URGENT] governing stop hit: x", ticker="AAA.JK")]
    cf = counterfactual_hold(log, hist, holding_days=60)
    assert cf.n_compared == 0


def test_missing_history_is_skipped_not_scored_as_zero():
    log = [_t(-5.0, "manual sell", ticker="GONE.JK")]
    cf = counterfactual_hold(log, {}, holding_days=60)
    assert cf.n_compared == 0 and cf.n_skipped == 1


def test_counterfactual_applies_sell_costs_to_the_rule_leg():
    """Both sides must carry the same cost treatment or the comparison is rigged."""
    hist = {"AAA.JK": _hist(drift=0.0)}        # perfectly flat
    log = [_t(0.0, "manual sell", entry="2026-01-01", ticker="AAA.JK", entry_px=1000.0)]
    cf = counterfactual_hold(log, hist, holding_days=60, costs=CostModel())
    # flat price, but the rule's exit still pays fees/tax/spread -> negative
    assert cf.rule_mean < 0


# ---- report ----------------------------------------------------------------

def test_report_warns_when_the_engine_never_closed_anything():
    s = summarise_discipline([_t(-4.8, "manual sell") for _ in range(6)])
    assert "WARNING" in format_report(s)


def test_report_does_not_warn_on_a_small_sample():
    s = summarise_discipline([_t(-4.8, "manual sell") for _ in range(3)])
    assert "WARNING" not in format_report(s)


# ---- scheduling: it only helps if it actually runs -------------------------

def test_discipline_keys_are_registered_with_preflight():
    """A config key the typo-checker does not know about produces a warning on
    every run for everyone who copies the example config."""
    from kala.preflight import KNOWN_CONFIG_KEYS
    assert "discipline_report_enabled" in KNOWN_CONFIG_KEYS
    assert "discipline_report_weekday" in KNOWN_CONFIG_KEYS
    assert "exit_profile" in KNOWN_CONFIG_KEYS


def test_daily_run_schedules_the_discipline_check():
    """Pins that the monthly check is wired into the scheduled loop, not just
    available as a script nobody remembers to run."""
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "daily_run.py").read_text(
        encoding="utf-8")
    assert "discipline_report" in src
    assert "summarise_discipline" in src
    # first week of the month, on the configured weekday
    assert "today.day <= 7" in src
