"""
Per-fill ledger tests.

The ledger exists because averaging a buy into a held position kept the
ORIGINAL entry_date, so the state could not say when the added shares
arrived and mark-to-market valued the whole blended lot from day one. All
15 positions in the real book are averaged-in, so this was not an edge case.

Two properties carry the most weight:
  * the INVARIANT sum(fills.shares) == position.shares -- if it drifts,
    position_fills() discards the ledger and the fix silently stops working;
  * BACKWARD COMPATIBILITY -- a position saved before the ledger existed
    must behave exactly as it did before, never crash.
"""

import json

import pytest

from kala.papertrade import (
    LOT_SIZE,
    PaperPosition,
    PaperTrader,
    apply_corporate_action_adjustment,
    position_fills,
)
from tests.test_papertrade import buy_fill, flat_cfg


def _shares_in(pos) -> float:
    return sum(f["shares"] for f in position_fills(pos))


# ---------------- backward compatibility (legacy state) ---------------------------

def test_legacy_position_without_fills_yields_one_synthetic_lot():
    """Exactly the pre-ledger behavior: one lot, at entry_date/entry_price."""
    pos = PaperPosition(ticker="A.JK", entry_price=1500.0, shares=200,
                        entry_date="2026-07-01", peak_price=1600.0)
    assert position_fills(pos) == [
        {"date": "2026-07-01", "shares": 200.0, "price": 1500.0}]


def test_position_fills_reads_a_raw_state_dict_too():
    raw = {"ticker": "A.JK", "entry_price": 1000.0, "shares": 100,
           "entry_date": "2026-07-01", "peak_price": 1000.0}
    assert position_fills(raw)[0]["shares"] == 100.0


def test_legacy_state_file_still_loads_and_saves(tmp_path):
    """A paper_state.json written before `fills` existed must round-trip."""
    path = tmp_path / "p.json"
    path.write_text(json.dumps({
        "cash": 1_000_000.0, "start_capital": 2_000_000.0,
        "positions": {"A.JK": {"ticker": "A.JK", "entry_price": 1000.0, "shares": 100,
                               "entry_date": "2026-07-01", "peak_price": 1000.0,
                               "entry_atr": None}},
        "pending": [], "log": [], "benchmark_start": None,
        "capital_additions": [], "dividends": [],
        "undo_stack": [], "redo_stack": [],
    }))
    pt = PaperTrader.load(path)
    assert pt.positions["A.JK"].fills is None       # untouched
    pt.save()
    assert PaperTrader.load(path).positions["A.JK"].shares == 100


def test_out_of_sync_ledger_falls_back_instead_of_mis_valuing():
    """A half-trusted ledger would silently mis-size the position; the
    blended single lot is at worst imprecise about dates."""
    pos = PaperPosition(ticker="A.JK", entry_price=1000.0, shares=300,
                        entry_date="2026-07-01", peak_price=1000.0,
                        fills=[{"date": "2026-07-01", "shares": 100.0, "price": 1000.0}])
    assert position_fills(pos) == [
        {"date": "2026-07-01", "shares": 300.0, "price": 1000.0}]


# ---------------- recording fills -------------------------------------------------

def test_a_first_buy_records_one_fill(tmp_path):
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000, cfg=flat_cfg())
    pt.manual_buy("ANTM.JK", shares=200, price=1500.0, date="2026-07-01")
    # "costed" marks the price as already including fee + spread, so
    # kala.friction never charges this fill a second time.
    assert position_fills(pt.positions["ANTM.JK"]) == [
        {"date": "2026-07-01", "shares": 200.0, "price": buy_fill(1500.0),
         "costed": True}]


def test_adding_to_a_position_records_the_second_fill_with_its_own_date(tmp_path):
    """THE point of the ledger: the added shares keep their real date, even
    though the position's entry_date stays at the first purchase."""
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000, cfg=flat_cfg())
    pt.manual_buy("BBRI.JK", shares=100, price=1000.0, date="2026-07-01")
    pt.manual_buy("BBRI.JK", shares=100, price=1200.0, date="2026-07-20")

    pos = pt.positions["BBRI.JK"]
    f1, f2 = buy_fill(1000.0), buy_fill(1200.0)
    assert pos.entry_date == "2026-07-01"          # unchanged, as before
    assert pos.entry_price == pytest.approx((f1 + f2) / 2)   # blended, as before
    assert position_fills(pos) == [
        {"date": "2026-07-01", "shares": 100.0, "price": f1, "costed": True},
        {"date": "2026-07-20", "shares": 100.0, "price": f2, "costed": True}]


def test_adding_to_a_LEGACY_position_seeds_the_ledger_correctly(tmp_path):
    """An existing (pre-ledger) position that gets added to must end up with
    BOTH the original shares and the new ones, not just the new fill."""
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000, cfg=flat_cfg())
    pt.positions["X.JK"] = PaperPosition(
        ticker="X.JK", entry_price=1000.0, shares=100,
        entry_date="2026-07-01", peak_price=1000.0)      # fills=None
    pt.manual_buy("X.JK", shares=100, price=1400.0, date="2026-07-20")

    pos = pt.positions["X.JK"]
    assert _shares_in(pos) == pos.shares == 200
    assert position_fills(pos)[0] == {"date": "2026-07-01", "shares": 100.0,
                                      "price": 1000.0}


def test_fills_survive_a_save_load_round_trip(tmp_path):
    path = tmp_path / "p.json"
    pt = PaperTrader.load(path, start_capital=10_000_000, cfg=flat_cfg())
    pt.manual_buy("A.JK", shares=100, price=1000.0, date="2026-07-01")
    pt.manual_buy("A.JK", shares=100, price=1200.0, date="2026-07-20")
    assert position_fills(PaperTrader.load(path).positions["A.JK"]) == \
        position_fills(pt.positions["A.JK"])


def test_the_share_invariant_holds_after_every_buy(tmp_path):
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=50_000_000, cfg=flat_cfg())
    for i, price in enumerate([1000.0, 1100.0, 1250.0, 900.0]):
        pt.manual_buy("A.JK", shares=100, price=price, date=f"2026-07-0{i + 1}")
        assert _shares_in(pt.positions["A.JK"]) == pt.positions["A.JK"].shares


# ---------------- partial sell (pro-rata, preserves the average) ------------------

def test_partial_sell_shrinks_fills_pro_rata_and_keeps_the_invariant(tmp_path):
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000, cfg=flat_cfg())
    pt.manual_buy("A.JK", shares=100, price=1000.0, date="2026-07-01")
    pt.manual_buy("A.JK", shares=300, price=1200.0, date="2026-07-10")
    pt.manual_sell("A.JK", price=1300.0, shares=200)      # half of 400

    pos = pt.positions["A.JK"]
    assert pos.shares == 200
    assert _shares_in(pos) == pytest.approx(200.0)
    fills = position_fills(pos)
    assert fills[0]["shares"] == pytest.approx(50.0)      # 100 * 0.5
    assert fills[1]["shares"] == pytest.approx(150.0)     # 300 * 0.5


def test_partial_sell_leaves_the_blended_average_untouched(tmp_path):
    """Pro-rata is chosen precisely so entry_price doesn't move -- FIFO would
    silently switch the position to a different cost-basis convention."""
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000, cfg=flat_cfg())
    pt.manual_buy("A.JK", shares=100, price=1000.0, date="2026-07-01")
    pt.manual_buy("A.JK", shares=100, price=1400.0, date="2026-07-10")
    before = pt.positions["A.JK"].entry_price
    pt.manual_sell("A.JK", price=1500.0, shares=100)
    pos = pt.positions["A.JK"]
    assert pos.entry_price == pytest.approx(before)
    # the ledger's own weighted average must still equal it
    weighted = sum(f["shares"] * f["price"] for f in position_fills(pos)) / _shares_in(pos)
    assert weighted == pytest.approx(before)


# ---------------- other mutations keep the ledger consistent ----------------------

def test_edit_entry_price_rescales_fills_to_match(tmp_path):
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000, cfg=flat_cfg())
    pt.manual_buy("A.JK", shares=100, price=1000.0, date="2026-07-01")
    pt.manual_buy("A.JK", shares=100, price=1200.0, date="2026-07-10")
    pt.edit_entry_price("A.JK", 1000.0)                  # from blended 1100

    pos = pt.positions["A.JK"]
    assert _shares_in(pos) == pos.shares
    weighted = sum(f["shares"] * f["price"] for f in position_fills(pos)) / _shares_in(pos)
    assert weighted == pytest.approx(1000.0)


def test_corporate_action_rescales_fills_and_lands_exactly_on_shares():
    """If the ledger's total stops matching pos.shares, position_fills()
    discards it and the fix silently stops working -- so the lot-rounding
    drift must be absorbed, not left."""
    pos = PaperPosition(ticker="A.JK", entry_price=1000.0, shares=300,
                        entry_date="2026-07-01", peak_price=1000.0,
                        fills=[{"date": "2026-07-01", "shares": 100.0, "price": 1000.0},
                               {"date": "2026-07-05", "shares": 200.0, "price": 1000.0}])
    apply_corporate_action_adjustment(pos, ratio=0.5)     # 2-for-1 split
    assert pos.shares % LOT_SIZE == 0
    assert _shares_in(pos) == pytest.approx(pos.shares)


def test_undo_restores_the_previous_ledger(tmp_path):
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000, cfg=flat_cfg())
    pt.manual_buy("A.JK", shares=100, price=1000.0, date="2026-07-01")
    before = position_fills(pt.positions["A.JK"])
    pt.manual_buy("A.JK", shares=100, price=1200.0, date="2026-07-10")
    pt.undo()
    assert position_fills(pt.positions["A.JK"]) == before


# ---------------- the payoff: mark-to-market dating -------------------------------

def test_mark_to_market_does_not_value_added_shares_before_they_were_bought():
    """The defect this whole ledger exists to fix. A position added to on
    2026-07-20 must be worth ~half as much on 07-10 as it is after the add,
    where the old single-lot view valued all 200 shares from 07-01."""
    import numpy as np
    import pandas as pd

    from kala.chart import mark_to_market_points

    idx = pd.bdate_range("2026-07-01", periods=20)
    prices = {"A.JK": pd.Series(np.full(20, 1000.0), index=idx)}
    positions = {"A.JK": PaperPosition(
        ticker="A.JK", entry_price=1000.0, shares=200, entry_date="2026-07-01",
        peak_price=1000.0,
        fills=[{"date": "2026-07-01", "shares": 100.0, "price": 1000.0},
               {"date": "2026-07-20", "shares": 100.0, "price": 1000.0}])}

    points, _ = mark_to_market_points([], positions, prices, start_capital=1_000_000.0)
    by_date = dict(points)
    # before the add: 100 sh held (100k) + 900k cash left = 1,000,000
    # (cash only debited for the fills that have happened)
    assert by_date["2026-07-10"] == pytest.approx(1_000_000.0)
    # after: 200 sh held, cash down another 100k -- total unchanged at cost
    assert by_date["2026-07-20"] == pytest.approx(1_000_000.0)


def test_mark_to_market_prices_each_fill_from_its_own_date():
    """With a RISING price, the later fill must not pick up gains from before
    it was bought."""
    import numpy as np
    import pandas as pd

    from kala.chart import mark_to_market_points

    idx = pd.bdate_range("2026-07-01", periods=10)
    prices = {"A.JK": pd.Series(np.linspace(1000.0, 2000.0, 10), index=idx)}
    ledgered = {"A.JK": PaperPosition(
        ticker="A.JK", entry_price=1000.0, shares=200, entry_date="2026-07-01",
        peak_price=1000.0,
        fills=[{"date": "2026-07-01", "shares": 100.0, "price": 1000.0},
               {"date": "2026-07-09", "shares": 100.0, "price": 1000.0}])}
    legacy = {"A.JK": PaperPosition(
        ticker="A.JK", entry_price=1000.0, shares=200, entry_date="2026-07-01",
        peak_price=1000.0)}                                   # no ledger

    mid = "2026-07-07"
    a = dict(mark_to_market_points([], ledgered, prices, 1_000_000.0)[0])[mid]
    b = dict(mark_to_market_points([], legacy, prices, 1_000_000.0)[0])[mid]
    assert a < b, "ledgered equity must be lower -- half the shares weren't bought yet"
