"""
Mark-to-market equity curve tests.

The property that matters most is CASH EXACTNESS: the reconstruction replays
every buy and sell from the log, so if it drifts, the whole curve is wrong by
a silent constant and still looks perfectly plausible. Verified here against
a hand-computed balance, and separately against the user's real 30-lot state
(matched to the rupiah) during development.

Second: LOT-level accounting. The real state contains a same-day re-entry
(SRTG sold and re-bought on 2026-07-24), so collapsing by ticker would
double-count or drop a leg.
"""

import numpy as np
import pandas as pd
import pytest

from kala.chart import held_lots, mark_to_market_points


def _closes(start="2026-07-01", periods=20, price=1000.0):
    idx = pd.bdate_range(start, periods=periods)
    return pd.Series(np.full(periods, float(price)), index=idx)


def _rising(start="2026-07-01", periods=20, lo=1000.0, hi=1200.0):
    idx = pd.bdate_range(start, periods=periods)
    return pd.Series(np.linspace(lo, hi, periods), index=idx)


def _closed(ticker="A.JK", entry=1000.0, exit_px=1100.0, shares=100,
            entry_date="2026-07-01", date="2026-07-10"):
    return {"ticker": ticker, "entry": entry, "exit": exit_px, "shares": shares,
            "entry_date": entry_date, "date": date, "reason": "manual sell"}


def _open(ticker="B.JK", entry=1000.0, shares=100, entry_date="2026-07-01"):
    return {ticker: {"ticker": ticker, "entry_price": entry, "shares": shares,
                     "entry_date": entry_date, "peak_price": entry}}


# ---------------- lots ------------------------------------------------------------

def test_same_day_re_entry_produces_two_independent_lots():
    """The real failure this guards: SRTG was sold AND re-bought on the same
    day at a different cost basis. Per-ticker accounting would merge them."""
    log = [_closed("SRTG.JK", entry=1687.52, exit_px=1695.0, shares=1400,
                   entry_date="2026-07-17", date="2026-07-24")]
    positions = _open("SRTG.JK", entry=1742.61, shares=1000, entry_date="2026-07-24")
    lots = held_lots(log, positions)
    assert len(lots) == 2
    assert {lot["shares"] for lot in lots} == {1400.0, 1000.0}
    assert sum(1 for lot in lots if lot["exit_date"] is None) == 1


def test_lots_read_both_objects_and_dicts():
    """generate_dashboard passes PaperPosition objects; a raw JSON reader
    passes dicts. Both must work."""
    from kala.papertrade import PaperPosition
    obj = {"X.JK": PaperPosition(ticker="X.JK", entry_price=100.0, shares=50,
                                 entry_date="2026-07-01", peak_price=100.0)}
    assert held_lots([], obj)[0]["shares"] == 50.0
    assert held_lots([], _open("X.JK", shares=50))[0]["shares"] == 50.0


def test_lots_skip_junk_rows():
    bad = [{"ticker": "", "shares": 10, "entry_date": "2026-07-01"},
           {"ticker": "A.JK", "shares": 0, "entry_date": "2026-07-01"},
           {"ticker": "A.JK", "shares": 10, "entry_date": ""}]
    assert held_lots(bad, {}) == []


# ---------------- cash exactness (the one that must not drift) --------------------

def test_cash_reconstruction_is_exact():
    """Hand-computed: start 1,000,000; buy 100 sh @1000 (-100,000);
    sell them @1100 (+110,000) -> 1,010,000 cash, no holdings left."""
    log = [_closed(entry=1000.0, exit_px=1100.0, shares=100,
                   entry_date="2026-07-01", date="2026-07-10")]
    points, _ = mark_to_market_points(
        log, {}, {"A.JK": _closes(periods=20)}, start_capital=1_000_000.0)
    assert points[-1][1] == pytest.approx(1_010_000.0)


def test_deposit_lands_on_its_own_date_not_day_one():
    """A mid-period deposit must not retroactively inflate earlier equity --
    the same distortion equity_curve_points was fixed for."""
    adds = [{"date": "2026-07-08", "amount": 500_000.0}]
    points, _ = mark_to_market_points(
        [], _open(), {"B.JK": _closes(periods=15)},
        start_capital=1_500_000.0, capital_additions=adds)
    by_date = dict(points)
    assert by_date["2026-07-07"] == pytest.approx(1_000_000.0)   # pre-deposit
    assert by_date["2026-07-08"] == pytest.approx(1_500_000.0)   # deposit day


def test_dividends_are_credited_as_cash():
    points, _ = mark_to_market_points(
        [], _open(), {"B.JK": _closes(periods=10)}, start_capital=1_000_000.0,
        dividends=[{"date": "2026-07-06", "amount": 25_000.0}])
    by_date = dict(points)
    assert by_date["2026-07-03"] == pytest.approx(1_000_000.0)
    assert by_date["2026-07-06"] == pytest.approx(1_025_000.0)


# ---------------- the actual point of the feature ---------------------------------

def test_curve_moves_with_price_even_when_no_trade_closes():
    """THE reason this exists: a book holding an appreciating position with
    zero closed trades must show a RISING line, where the realized-only
    curve is flat."""
    points, _ = mark_to_market_points(
        [], _open(entry=1000.0, shares=100), {"B.JK": _rising(periods=10)},
        start_capital=1_000_000.0)
    values = [v for _, v in points]
    assert values[-1] > values[0]
    assert len(set(values)) > 1                 # genuinely varies day to day


def test_realized_curve_stays_flat_for_the_same_book():
    """Contrast control -- proves the difference is real, not a test artifact."""
    from kala.chart import equity_curve_points
    realized = equity_curve_points([], start_capital=1_000_000.0)
    assert len({v for _, v in realized}) == 1


def test_a_sold_lot_stops_being_marked_after_its_exit():
    """Post-exit the proceeds are cash; continuing to value the shares would
    double-count them."""
    log = [_closed(entry=1000.0, exit_px=1100.0, shares=100,
                   entry_date="2026-07-01", date="2026-07-08")]
    points, _ = mark_to_market_points(
        log, {}, {"A.JK": _rising(periods=15, lo=1000.0, hi=5000.0)},
        start_capital=1_000_000.0)
    tail = [v for d, v in points if d > "2026-07-08"]
    assert len(set(tail)) == 1                  # flat after the sale
    assert tail[0] == pytest.approx(1_010_000.0)


def test_series_starts_at_first_activity_not_at_price_history_start():
    """Price history reaches back to 2026-07-01, but the account's first
    activity is 2026-07-08. Plotting the earlier days would invent account
    history that doesn't exist."""
    points, _ = mark_to_market_points(
        [], _open(entry=1000.0, shares=100, entry_date="2026-07-08"),
        {"B.JK": _closes(periods=15)}, start_capital=1_000_000.0)
    assert min(d for d, _ in points) == "2026-07-08"
    # and on that first day cash has simply become shares at cost
    assert dict(points)["2026-07-08"] == pytest.approx(1_000_000.0)


def test_a_lot_bought_mid_series_is_not_valued_before_its_entry():
    """Two lots, one bought later: the later one must contribute nothing
    until its own entry date, or early equity is overstated."""
    positions = {**_open("EARLY.JK", entry=1000.0, shares=100,
                         entry_date="2026-07-01"),
                 **_open("LATE.JK", entry=1000.0, shares=100,
                         entry_date="2026-07-09")}
    prices = {"EARLY.JK": _closes(periods=15), "LATE.JK": _closes(periods=15)}
    points, _ = mark_to_market_points(
        [], positions, prices, start_capital=1_000_000.0)
    by_date = dict(points)
    # LATE hasn't been bought yet -> equity is unchanged from the start
    assert by_date["2026-07-03"] == pytest.approx(1_000_000.0)
    # after buying it, cash fell 100k and holdings rose 100k -> still 1M
    assert by_date["2026-07-09"] == pytest.approx(1_000_000.0)


# ---------------- degraded data ---------------------------------------------------

def test_missing_price_history_falls_back_to_cost_and_warns():
    """Dropping an unpriced holding would silently shrink equity; holding it
    at cost is bounded and, crucially, REPORTED."""
    points, warnings = mark_to_market_points(
        [], _open("GHOST.JK", entry=1000.0, shares=100),
        {"OTHER.JK": _closes(periods=10)}, start_capital=1_000_000.0)
    assert points and all(v == pytest.approx(1_000_000.0) for _, v in points)
    assert warnings and "GHOST.JK" in warnings[0]


def test_no_price_history_at_all_returns_a_warning_not_a_crash():
    points, warnings = mark_to_market_points(
        [], _open(), {}, start_capital=1_000_000.0)
    assert points == []
    assert warnings and "cannot mark to market" in warnings[0]


def test_gaps_carry_the_last_close_forward():
    """A suspended/non-trading day leaves the position at its last traded
    price -- not zero, not NaN."""
    idx = pd.DatetimeIndex(["2026-07-01", "2026-07-02", "2026-07-06"])
    sparse = pd.Series([1000.0, 1100.0, 1200.0], index=idx)
    full = _closes(start="2026-07-01", periods=6)          # supplies the day axis
    points, _ = mark_to_market_points(
        [], {**_open("B.JK", entry=1000.0, shares=100),
             **_open("PAD.JK", entry=0.01, shares=1)},
        {"B.JK": sparse, "PAD.JK": full}, start_capital=1_000_000.0)
    by_date = dict(points)
    # 2026-07-03 has no B.JK bar -> must reuse 07-02's 1100, not vanish
    assert by_date["2026-07-03"] == pytest.approx(by_date["2026-07-02"])


def test_empty_state_returns_nothing_rather_than_a_fake_point():
    assert mark_to_market_points([], {}, {}, start_capital=1_000_000.0) == ([], [])


def test_today_clamps_the_series():
    points, _ = mark_to_market_points(
        [], _open(), {"B.JK": _closes(periods=20)}, start_capital=1_000_000.0,
        today="2026-07-08")
    assert max(d for d, _ in points) <= "2026-07-08"


def test_points_shape_matches_equity_curve_points():
    """Both feed the same renderer, so the shape must agree."""
    points, _ = mark_to_market_points(
        [], _open(), {"B.JK": _closes(periods=5)}, start_capital=1_000_000.0)
    assert all(isinstance(d, str) and isinstance(v, float) for d, v in points)
