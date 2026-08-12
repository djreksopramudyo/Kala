"""
Tests for the three maintenance guards added together:
  * daily_run.quarterly_walkforward_due — calendar/marker logic for the
    quarterly walk-forward (edge-decay alarm) that replaced the legacy
    monthly in-sample backtest.
  * universe.staleness_warning — ISSI list refresh reminder.
  * papertrade's corporate-action guard — detects a position whose stored
    entry price is inconsistent with the current adjusted history (split
    signature) and AUTO-ADJUSTS it (entry price, peak, shares) so exit
    evaluation can resume the same cycle instead of staying stuck until
    someone manually edits paper_state.json.
"""

from datetime import date

import numpy as np
import pandas as pd
import pytest

import kala.universe as universe
from daily_run import DEFAULT_CONFIG, quarterly_walkforward_due
from kala.config import Config
from kala.papertrade import (
    PaperPosition,
    PaperTrader,
    _corporate_action_ratio,
    apply_corporate_action_adjustment,
)


def test_auto_paper_trade_defaults_off():
    """/positions must never show a stock the user hasn't /buy'd unless they
    opt into the old fully-autonomous benchmark behavior explicitly."""
    assert DEFAULT_CONFIG["auto_paper_trade"] is False


# ---------------------------------------------------------------------------
# quarterly_walkforward_due
# ---------------------------------------------------------------------------

def test_due_on_first_weekday_window_of_quarter(tmp_path):
    marker, label = quarterly_walkforward_due(date(2026, 7, 2), tmp_path)  # Thu, July
    assert marker is not None and label == "2026Q3"
    assert marker.name == ".walkforward_done_2026Q3"


def test_not_due_outside_quarter_months_or_window(tmp_path):
    assert quarterly_walkforward_due(date(2026, 8, 3), tmp_path) == (None, None)   # Aug: not a quarter month
    assert quarterly_walkforward_due(date(2026, 7, 8), tmp_path) == (None, None)   # day > 5
    assert quarterly_walkforward_due(date(2026, 7, 4), tmp_path) == (None, None)   # Saturday


def test_not_due_twice_per_quarter(tmp_path):
    marker, _ = quarterly_walkforward_due(date(2026, 7, 2), tmp_path)
    marker.touch()
    assert quarterly_walkforward_due(date(2026, 7, 3), tmp_path) == (None, None)


# ---------------------------------------------------------------------------
# universe.staleness_warning
# ---------------------------------------------------------------------------

def test_staleness_warns_when_refresh_date_unknown(monkeypatch):
    monkeypatch.setattr(universe, "UNIVERSE_UPDATED", None)
    w = universe.staleness_warning(today=date(2026, 7, 10))
    assert w is not None and "UNIVERSE_UPDATED" in w


def test_staleness_quiet_when_fresh(monkeypatch):
    monkeypatch.setattr(universe, "UNIVERSE_UPDATED", "2026-06-01")
    assert universe.staleness_warning(today=date(2026, 7, 10)) is None


def test_staleness_warns_when_old(monkeypatch):
    monkeypatch.setattr(universe, "UNIVERSE_UPDATED", "2025-11-01")
    w = universe.staleness_warning(today=date(2026, 7, 10))
    assert w is not None and "2025-11-01" in w


# ---------------------------------------------------------------------------
# corporate-action guard
# ---------------------------------------------------------------------------

def _flat_history(price=1000.0, n=80, start="2026-03-02"):
    idx = pd.bdate_range(start, periods=n)
    return pd.DataFrame(
        {"Open": np.full(n, price), "High": np.full(n, price * 1.005),
         "Low": np.full(n, price * 0.995), "Close": np.full(n, price),
         "Volume": np.full(n, 1e6)},
        index=idx,
    )


def _pos(entry_price, entry_date):
    return PaperPosition(ticker="SPLT.JK", entry_price=entry_price, shares=1000,
                         entry_date=entry_date, peak_price=entry_price)


def test_guard_fires_on_split_signature():
    h = _flat_history(price=500.0)                       # post-split adjusted chart
    entry_date = h.index[10].date().isoformat()
    costs = Config().costs
    # stored entry recorded pre-split at ~1000 (x2 the adjusted history)
    pos = _pos(entry_price=1000.0 * (1 + costs.buy_commission + costs.half_spread),
               entry_date=entry_date)
    result = _corporate_action_ratio(pos, h, costs)
    assert result is not None
    ratio, expected_entry = result
    assert ratio == pytest.approx(0.5, rel=0.02)
    assert expected_entry == pytest.approx(500.0 * costs.buy_multiplier(500.0))


def test_guard_quiet_on_consistent_entry_and_dividend_sized_drift():
    h = _flat_history(price=1000.0)
    entry_date = h.index[10].date().isoformat()
    costs = Config().costs
    exact = _pos(1000.0 * (1 + costs.buy_commission + costs.half_spread), entry_date)
    assert _corporate_action_ratio(exact, h, costs) is None
    # a ~3% dividend adjustment must NOT trip the guard
    divvy = _pos(1030.0 * (1 + costs.buy_commission + costs.half_spread), entry_date)
    assert _corporate_action_ratio(divvy, h, costs) is None


def test_guard_quiet_when_entry_date_outside_window():
    h = _flat_history()
    costs = Config().costs
    pos = _pos(1000.0, "2020-01-06")                     # far before the window
    assert _corporate_action_ratio(pos, h, costs) is None


# ---------------------------------------------------------------------------
# apply_corporate_action_adjustment
# ---------------------------------------------------------------------------

def test_apply_adjustment_preserves_position_value():
    pos = _pos(entry_price=1000.0, entry_date="2026-03-16")
    pos.peak_price = 1200.0
    old_value = pos.entry_price * pos.shares
    apply_corporate_action_adjustment(pos, ratio=0.5)     # 2:1 split
    new_value = pos.entry_price * pos.shares
    assert new_value == pytest.approx(old_value, rel=0.02)


def test_apply_adjustment_scales_entry_and_peak_by_ratio():
    pos = _pos(entry_price=1000.0, entry_date="2026-03-16")
    pos.peak_price = 1200.0
    apply_corporate_action_adjustment(pos, ratio=0.5)
    assert pos.entry_price == pytest.approx(500.0)
    assert pos.peak_price == pytest.approx(600.0)


def test_apply_adjustment_rounds_shares_to_lot():
    pos = _pos(entry_price=1000.0, entry_date="2026-03-16")
    pos.shares = 333   # not a clean multiple to begin with
    apply_corporate_action_adjustment(pos, ratio=0.5)
    assert pos.shares % 100 == 0


def test_apply_adjustment_returns_a_human_readable_note():
    pos = _pos(entry_price=1000.0, entry_date="2026-03-16")
    note = apply_corporate_action_adjustment(pos, ratio=0.5)
    assert "corporate action" in note
    assert "verify" in note.lower()


def test_step_auto_adjusts_and_warns_on_suspected_split(tmp_path):
    """End-to-end through PaperTrader.step: a held position whose stored entry
    is 2x the adjusted history must NOT get a SELL queued (even though the
    exit engine would read it as a catastrophic loss), must surface a
    warning ticket, AND must come out of step() with entry_price rescaled
    to match the adjusted history -- assertive handling, not a permanent
    skip that waits on manual intervention."""
    pt = PaperTrader.load(tmp_path / "state.json", start_capital=10_000_000)
    h = _flat_history(price=500.0)
    entry_date = h.index[-10].date().isoformat()   # recent -- isolates the CA
    costs = pt.cfg.costs                            # check from the (separate,
    pt.positions["SPLT.JK"] = _pos(                 # legitimate) max-holding-
        1000.0 * (1 + costs.buy_commission + costs.half_spread), entry_date)  # period exit

    report = pt.step({"SPLT.JK": h}, signals=[], today=h.index[-1].date().isoformat())
    assert not any(o.side == "SELL" for o in pt.pending), \
        "guard must prevent the false -50% stop from queueing a sell"
    assert any("corporate action" in s for s in report["skipped"])
    assert any("corporate action" in t for t in report["tickets"])
    assert pt.positions["SPLT.JK"].entry_price == pytest.approx(500.0 * costs.buy_multiplier(500.0),
                                                                rel=0.02)


def test_step_resumes_normal_exit_management_after_adjustment(tmp_path):
    """The whole point of making this assertive: the NEXT day's step() must
    manage the position normally (no repeated warning), since the stored
    entry is now consistent with the adjusted history."""
    pt = PaperTrader.load(tmp_path / "state.json", start_capital=10_000_000)
    h = _flat_history(price=500.0, n=90)
    entry_date = h.index[-10].date().isoformat()
    costs = pt.cfg.costs
    pt.positions["SPLT.JK"] = _pos(
        1000.0 * (1 + costs.buy_commission + costs.half_spread), entry_date)

    pt.step({"SPLT.JK": h}, signals=[], today=h.index[-2].date().isoformat())
    report2 = pt.step({"SPLT.JK": h}, signals=[], today=h.index[-1].date().isoformat())
    assert not any("corporate action" in s for s in report2["skipped"])


def test_step_normal_position_unaffected_by_guard(tmp_path):
    """Control: a consistent position flows through step() exactly as before
    (flat tape -> no exit, no warnings)."""
    pt = PaperTrader.load(tmp_path / "state.json", start_capital=10_000_000)
    h = _flat_history(price=1000.0)
    entry_date = h.index[10].date().isoformat()
    costs = pt.cfg.costs
    pt.positions["OKAY.JK"] = PaperPosition(
        ticker="OKAY.JK", shares=1000, entry_date=entry_date,
        entry_price=1000.0 * (1 + costs.buy_commission + costs.half_spread),
        peak_price=1000.0)

    report = pt.step({"OKAY.JK": h}, signals=[], today=h.index[-1].date().isoformat())
    assert not any("corporate action" in s for s in report["skipped"])
    assert "OKAY.JK" in pt.positions
