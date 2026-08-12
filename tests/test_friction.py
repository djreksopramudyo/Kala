"""
Friction-tracker tests. The thing that must not regress: the distinction
between "friction already embedded in the fill" and "friction paid at the
broker but never recorded". Getting that backwards either double-counts costs
or hides them entirely, and both produce a confidently wrong P&L.
"""

import pytest

from kala.config import CostModel
from kala.friction import FrictionReport, format_friction, friction_report


def _state(positions=None, log=None):
    return {"positions": positions or {}, "log": log or []}


def _closed(ticker="A.JK", entry=1000.0, exit_px=1100.0, shares=1000,
            entry_date="2026-07-01", date="2026-07-15"):
    return {"ticker": ticker, "entry": entry, "exit": exit_px, "shares": shares,
            "entry_date": entry_date, "date": date, "reason": "manual sell"}


def _open(ticker="B.JK", entry=1000.0, shares=1000, entry_date="2026-07-01"):
    return {ticker: {"ticker": ticker, "entry_price": entry, "shares": shares,
                     "entry_date": entry_date}}


# ---------------- guardrails -----------------------------------------------------

def test_empty_state_reports_nothing_rather_than_crashing():
    r = friction_report(_state())
    assert r.total_friction_idr == 0.0
    assert "no trades" in format_friction(r).lower()


def test_returns_dataclass():
    assert isinstance(friction_report(_state()), FrictionReport)


@pytest.mark.parametrize("bad", [
    {"ticker": "X", "entry": 0.0, "exit": 100.0, "shares": 100},
    {"ticker": "X", "entry": 100.0, "exit": 100.0, "shares": 0},
    {"ticker": "X", "entry": None, "exit": None, "shares": None},
])
def test_junk_rows_contribute_nothing_instead_of_nan(bad):
    r = friction_report(_state(log=[bad]))
    assert r.total_friction_idr == 0.0
    assert r.n_closed == 0


# ---------------- the core arithmetic --------------------------------------------

def test_closed_trade_charges_both_legs():
    costs = CostModel()
    r = friction_report(_state(log=[_closed()]), costs=costs)
    expected = (1000.0 * 1000 * (costs.buy_total + costs.half_spread)
                + 1100.0 * 1000 * (costs.sell_total + costs.half_spread))
    assert r.closed_friction_idr == pytest.approx(expected)


def test_open_position_charges_only_the_buy_leg():
    """The sell leg hasn't happened yet -- counting it would overstate money
    actually spent."""
    costs = CostModel()
    r = friction_report(_state(positions=_open()), costs=costs)
    expected = 1000.0 * 1000 * (costs.buy_total + costs.half_spread)
    assert r.open_friction_idr == pytest.approx(expected)
    assert r.closed_friction_idr == 0.0


def test_tick_floor_costs_more_than_flat_for_a_cheap_stock():
    """A 67-rupiah stock cannot trade tighter than its 1-rupiah tick, so the
    honest spread is far above the flat 0.10% assumption."""
    cheap = _state(log=[_closed(entry=67.0, exit_px=70.0, shares=10_000)])
    flat = friction_report(cheap, costs=CostModel(spread_mode="flat"))
    tick = friction_report(cheap, costs=CostModel(spread_mode="tick_floor"))
    assert tick.total_friction_idr > flat.total_friction_idr * 2


def test_totals_combine_open_and_closed():
    r = friction_report(_state(positions=_open(), log=[_closed()]))
    assert r.total_friction_idr == pytest.approx(
        r.closed_friction_idr + r.open_friction_idr)


# ---------------- the accounting-standard distinction (the important one) --------

def test_manual_book_deducts_friction_from_recorded_pnl():
    """Default (already_charged=False): recorded P&L is overstated, so the net
    figure must be LOWER than what the state reports."""
    r = friction_report(_state(log=[_closed()]))
    assert r.recorded_pnl_idr == pytest.approx(100_000.0)   # (1100-1000)*1000
    assert r.net_pnl_idr < r.recorded_pnl_idr
    assert r.net_pnl_idr == pytest.approx(
        r.recorded_pnl_idr - r.closed_friction_idr)


def test_already_charged_book_does_not_double_deduct():
    """When fills embedded costs, subtracting again would double-count."""
    r = friction_report(_state(log=[_closed()]), already_charged=True)
    assert r.net_pnl_idr == pytest.approx(r.recorded_pnl_idr)


def test_note_states_which_accounting_world_applies():
    manual = friction_report(_state(log=[_closed()]))
    auto = friction_report(_state(log=[_closed()]), already_charged=True)
    assert "never deducted" in manual.note
    assert "ALREADY paid" in auto.note
    assert manual.note != auto.note


def test_friction_share_of_gross_only_reported_on_a_profit():
    """Dividing by a negative or zero P&L would produce a nonsense percentage."""
    loser = friction_report(_state(log=[_closed(entry=1000.0, exit_px=900.0)]))
    assert loser.friction_share_of_gross_pct == 0.0
    winner = friction_report(_state(log=[_closed()]))
    assert winner.friction_share_of_gross_pct > 0.0


# ---------------- pace / annualization -------------------------------------------

def test_annualized_pace_uses_the_observed_window():
    """2 round trips over ~14 days -> roughly 52/year, not 2."""
    log = [_closed(entry_date="2026-07-01", date="2026-07-07"),
           _closed(entry_date="2026-07-08", date="2026-07-15")]
    r = friction_report(_state(log=log))
    assert r.days_observed == 14
    assert 40 < r.round_trips_per_year < 70


def test_projection_scales_with_trading_frequency():
    """Trading twice as often in the same window must project twice the cost."""
    slow = _state(log=[_closed(entry_date="2026-07-01", date="2026-07-30")])
    fast = _state(log=[_closed(entry_date="2026-07-01", date="2026-07-08"),
                       _closed(entry_date="2026-07-09", date="2026-07-16"),
                       _closed(entry_date="2026-07-17", date="2026-07-30")])
    assert (friction_report(fast).projected_annual_friction_idr
            > friction_report(slow).projected_annual_friction_idr)


def test_undated_trades_do_not_fabricate_a_pace():
    log = [{"ticker": "X", "entry": 1000.0, "exit": 1100.0, "shares": 100}]
    r = friction_report(_state(log=log))
    assert r.days_observed == 0
    assert r.round_trips_per_year == 0.0
    assert r.projected_annual_friction_idr == 0.0


def test_unparseable_dates_do_not_crash_the_report():
    log = [_closed(entry_date="not-a-date", date="also-bad")]
    r = friction_report(_state(log=log))
    assert r.days_observed == 0
    format_friction(r)


# ---------------- formatting -----------------------------------------------------

def test_format_leads_with_rupiah_and_flags_the_no_edge_context():
    text = format_friction(friction_report(_state(positions=_open(), log=[_closed()])))
    assert "TOTAL PAID TO TRADE" in text
    assert "Rp" in text
    assert "16 hypotheses" in text
    assert "Trading less" in text


def test_format_shows_the_reported_vs_real_split_for_a_manual_book():
    text = format_friction(friction_report(_state(log=[_closed()])))
    assert "REPORTED vs REAL" in text
    assert "P&L in reality" in text


def test_format_omits_the_reported_vs_real_split_when_already_charged():
    text = format_friction(friction_report(_state(log=[_closed()]), already_charged=True))
    assert "REPORTED vs REAL" not in text


def test_today_closes_the_pace_window_instead_of_the_last_trade():
    """Someone who traded in a burst then stopped has a LOWER real pace than
    the burst implies. Passing today must reflect that, or the projected
    annual cost is badly overstated."""
    log = [_closed(entry_date="2026-07-01", date="2026-07-08"),
           _closed(entry_date="2026-07-02", date="2026-07-09")]
    burst = friction_report(_state(log=log))                       # window ends at last trade
    real = friction_report(_state(log=log), today="2026-08-03")    # ...and a month of silence
    assert real.days_observed > burst.days_observed
    assert real.round_trips_per_year < burst.round_trips_per_year
    assert real.projected_annual_friction_idr < burst.projected_annual_friction_idr
