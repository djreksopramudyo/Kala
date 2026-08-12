"""Tests for kala.intraday — market hours, alert rules, dedup."""

from datetime import datetime

import pytest

from kala.config import RiskConfig
from kala.intraday import (
    AlertDedup,
    Quote,
    arb_lower_limit_pct,
    is_idx_open,
    position_alerts,
    position_stop_status,
    watchlist_alerts,
)
from kala.papertrade import PaperPosition
from kala.watchlist import WatchlistItem

# ---- market hours -----------------------------------------------------------

def test_idx_open_regular_session():
    assert is_idx_open(datetime(2026, 7, 6, 10, 0))      # Monday 10:00
    assert is_idx_open(datetime(2026, 7, 6, 14, 0))      # Monday session 2

def test_idx_closed_lunch_weekend_evening():
    assert not is_idx_open(datetime(2026, 7, 6, 12, 30))  # Monday lunch
    assert not is_idx_open(datetime(2026, 7, 4, 10, 0))   # Saturday
    assert not is_idx_open(datetime(2026, 7, 6, 17, 0))   # after close

def test_idx_friday_prayer_gap():
    assert not is_idx_open(datetime(2026, 7, 10, 12, 0))  # Fri 12:00 closed
    assert is_idx_open(datetime(2026, 7, 10, 14, 30))     # Fri session 2


# ---- ARB tiers --------------------------------------------------------------

def test_arb_tiers():
    assert arb_lower_limit_pct(150) == 35.0
    assert arb_lower_limit_pct(3000) == 25.0
    assert arb_lower_limit_pct(9000) == 20.0


# ---- position alerts --------------------------------------------------------

def _pos(entry=1000.0, peak=1000.0, atr=None):
    return PaperPosition(ticker="TEST.JK", entry_price=entry, shares=100,
                         entry_date="2026-07-01", peak_price=peak, entry_atr=atr)

def test_stop_breach_fires():
    q = Quote("TEST.JK", price=940.0, prev_close=990.0, day_high=995.0)
    types = {a["type"] for a in position_alerts(_pos(), q, RiskConfig())}
    assert "STOP" in types  # 940 < hard stop 950

def test_quiet_when_normal():
    q = Quote("TEST.JK", price=1010.0, prev_close=1000.0, day_high=1015.0)
    assert position_alerts(_pos(), q, RiskConfig()) == []


# ---- position stop status (always-on, not just on breach) ------------------

def test_stop_status_matches_alert_stop_exactly():
    """Single source of truth: the stop shown in a status line and the stop
    an alert fires against must be the exact same number."""
    q = Quote("TEST.JK", price=940.0, prev_close=990.0, day_high=995.0)
    cfg = RiskConfig()
    status = position_stop_status(_pos(), q, cfg)
    alert = next(a for a in position_alerts(_pos(), q, cfg) if a["type"] == "STOP")
    assert f"{status['stop']:,.0f}" in alert["text"]


def test_stop_status_reports_price_and_distance_when_quiet():
    q = Quote("TEST.JK", price=1010.0, prev_close=1000.0, day_high=1015.0)
    status = position_stop_status(_pos(), q, RiskConfig())
    assert status["ticker"] == "TEST.JK"
    assert status["price"] == pytest.approx(1010.0)
    assert status["stop"] < status["price"]          # not breached
    assert status["distance_pct"] > 0                # price is above the stop
    assert status["pnl_pct"] == pytest.approx(1.0)


def test_stop_status_negative_distance_when_breached():
    q = Quote("TEST.JK", price=940.0, prev_close=990.0, day_high=995.0)
    status = position_stop_status(_pos(), q, RiskConfig())
    assert status["distance_pct"] < 0                # price is below the stop
    assert status["price"] <= status["stop"]


def test_stop_status_target_still_short():
    """target_distance_pct positive == price hasn't reached the target yet."""
    cfg = RiskConfig(target_profit_pct=8.0)
    q = Quote("TEST.JK", price=1010.0, prev_close=1000.0, day_high=1015.0)
    status = position_stop_status(_pos(entry=1000.0, peak=1000.0), q, cfg)
    assert status["target"] == pytest.approx(1080.0)      # entry * 1.08
    assert status["target_distance_pct"] > 0               # still short of it


def test_stop_status_target_reached_is_non_positive_distance():
    cfg = RiskConfig(target_profit_pct=8.0)
    q = Quote("TEST.JK", price=1090.0, prev_close=1085.0, day_high=1090.0)
    status = position_stop_status(_pos(entry=1000.0, peak=1000.0), q, cfg)
    assert status["target"] == pytest.approx(1080.0)
    assert status["target_distance_pct"] <= 0               # at/past the target


def test_stop_status_nan_price_gives_nan_distance_not_a_fake_zero():
    """The real bug: `quote.price > 0` is False for NaN too (Python), so a
    bad/missing quote used to fall through to a fabricated 0.0 -- which
    reads as 'exactly at the stop' and would fire a false stop-hit alarm on
    every affected position, even though nothing is actually known. NaN
    must propagate instead: honestly 'unknown', and it can't misfire any
    <= 0 / < 3 flag comparison downstream (NaN comparisons are all False)."""
    import math
    q = Quote("TEST.JK", price=math.nan, prev_close=990.0, day_high=995.0)
    status = position_stop_status(_pos(), q, RiskConfig())
    assert math.isnan(status["distance_pct"])
    assert math.isnan(status["target_distance_pct"])
    # and it must not look like a triggered stop/target to a naive reader
    assert not (status["distance_pct"] <= 0)
    assert not (status["target_distance_pct"] <= 0)


def test_stop_status_zero_price_gives_nan_distance_not_a_fake_zero():
    import math
    q = Quote("TEST.JK", price=0.0, prev_close=990.0, day_high=995.0)
    status = position_stop_status(_pos(), q, RiskConfig())
    assert math.isnan(status["distance_pct"])
    assert math.isnan(status["target_distance_pct"])


def test_stop_status_never_mutates_stored_peak():
    pos = _pos(peak=1000.0)
    q = Quote("TEST.JK", price=1200.0, prev_close=1190.0, day_high=1210.0)
    position_stop_status(pos, q, RiskConfig())
    assert pos.peak_price == 1000.0   # read-only, same guarantee as position_alerts

def test_trailing_stop_uses_day_high():
    # peak on file 1000, but today spiked to 1100 (+10%) -> phase-3 trail
    # at 1100*0.97=1067; price 1050 is below it -> STOP fires.
    q = Quote("TEST.JK", price=1050.0, prev_close=1080.0, day_high=1100.0)
    types = {a["type"] for a in position_alerts(_pos(), q, RiskConfig())}
    assert "STOP" in types

def test_limit_down_fires():
    q = Quote("TEST.JK", price=750.0, prev_close=1000.0, day_high=1000.0)
    types = {a["type"] for a in position_alerts(_pos(entry=1000), q, RiskConfig())}
    assert "ARB" in types  # -25% on a 200-5000 name

def test_take_profit_fires():
    q = Quote("TEST.JK", price=1090.0, prev_close=1050.0, day_high=1090.0)
    types = {a["type"] for a in position_alerts(_pos(), q, RiskConfig())}
    assert "TP" in types


# ---- watchlist --------------------------------------------------------------

def test_watchlist_dip():
    items = [WatchlistItem(ticker="VAL.JK", fair_value=2000.0, thesis="cheap")]
    quotes = {"VAL.JK": Quote("VAL.JK", price=1600.0, prev_close=1700.0, day_high=1700.0)}
    alerts = watchlist_alerts(items, quotes, min_discount_pct=15.0)
    assert len(alerts) == 1 and alerts[0]["type"] == "DIP"


# ---- dedup ------------------------------------------------------------------

def test_dedup_once_per_day(tmp_path):
    d = AlertDedup(tmp_path / "state.json")
    a = [{"type": "STOP", "ticker": "X.JK", "text": "t"}]
    assert d.filter_new(a, "2026-07-06") == a       # first time -> passes
    assert d.filter_new(a, "2026-07-06") == []      # repeat same day -> muted
    assert d.filter_new(a, "2026-07-07") == a       # new day -> passes again

def test_dedup_persists(tmp_path):
    p = tmp_path / "state.json"
    a = [{"type": "STOP", "ticker": "X.JK", "text": "t"}]
    d1 = AlertDedup(p); d1.filter_new(a, "2026-07-06"); d1.save()
    d2 = AlertDedup(p)
    assert d2.filter_new(a, "2026-07-06") == []     # survives process restart
