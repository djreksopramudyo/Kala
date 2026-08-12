"""Transaction costs on MANUAL fills, and the mixed book that results.

Manual /buy and /sell used to record the raw price you typed, adding no
commission, while automated fills embedded costs via the cost model. One
equity number therefore held two accounting standards, and for a book that
is entirely manual (this project's real one) reported returns were
optimistic by roughly the round-trip friction on every trade.

Manual fills now charge costs too. Trades booked BEFORE that are left
exactly as they were -- rewriting them would falsify history -- so a real
book is MIXED, and the property that matters most here is that
``kala.friction`` keeps the two straight: money already inside the recorded
prices is reported as spent but never deducted a second time.
"""

import pytest

from kala.config import Config, CostModel, RiskConfig
from kala.friction import friction_report
from kala.papertrade import (
    PaperPosition,
    PaperTrader,
    _costed_basis_fraction,
    apply_corporate_action_adjustment,
    position_fills,
)

# Defaults: buy 0.19% + 0.10% half spread -> x1.0029
#           sell 0.15% + 0.10% tax + 0.10% half spread -> x0.9965
BUY_MULT = 1.0029
SELL_MULT = 0.9965


def cfg():
    return Config(risk=RiskConfig(trailing_enabled=False, hard_stop_pct=-50.0,
                                  atr_stop_multiple=99.0, target_profit_pct=999.0))


def trader(tmp_path, name="p.json", capital=10_000_000, **kw):
    return PaperTrader.load(tmp_path / name, start_capital=capital, cfg=cfg(), **kw)


# ---------------------------------------------------------------------------
# The buy leg
# ---------------------------------------------------------------------------

def test_manual_buy_books_the_cost_inclusive_price(tmp_path):
    pt = trader(tmp_path)
    fill = pt.manual_buy("ANTM.JK", shares=200, price=1500.0)
    assert fill == pytest.approx(1500.0 * BUY_MULT) == pytest.approx(1504.35)
    assert pt.positions["ANTM.JK"].entry_price == pytest.approx(1504.35)


def test_manual_buy_debits_cash_by_the_costed_amount(tmp_path):
    pt = trader(tmp_path)
    pt.manual_buy("ANTM.JK", shares=200, price=1500.0)
    # 200 x 1504.35, NOT 200 x 1500 -- the difference is real money gone
    assert pt.cash == pytest.approx(10_000_000 - 200 * 1504.35)
    assert pt.cash < 10_000_000 - 200 * 1500.0


def test_peak_price_is_seeded_at_the_market_price_not_the_fill(tmp_path):
    """peak_price feeds the trailing stop, which compares it against later
    CLOSES. Seeding it at the cost-inclusive price would put it above
    anything the market printed and arm the stop early."""
    pt = trader(tmp_path)
    pt.manual_buy("ANTM.JK", shares=200, price=1500.0)
    assert pt.positions["ANTM.JK"].peak_price == 1500.0


def test_the_new_fill_is_marked_costed(tmp_path):
    pt = trader(tmp_path)
    pt.manual_buy("ANTM.JK", shares=200, price=1500.0, date="2026-07-01")
    (f,) = position_fills(pt.positions["ANTM.JK"])
    assert f["costed"] is True
    assert f["price"] == pytest.approx(1504.35)


def test_insufficient_cash_is_judged_on_the_costed_amount(tmp_path):
    """Cash that covers the raw price but not the commission must be
    rejected -- otherwise the book goes negative on a real fill."""
    pt = trader(tmp_path, capital=300_000)
    with pytest.raises(ValueError, match="not enough cash"):
        pt.manual_buy("ANTM.JK", shares=200, price=1500.0)   # 300,870 needed


# ---------------------------------------------------------------------------
# The sell leg
# ---------------------------------------------------------------------------

def test_manual_sell_credits_only_the_net_proceeds(tmp_path):
    pt = trader(tmp_path)
    pt.manual_buy("ANTM.JK", shares=200, price=1500.0)
    cash_after_buy = pt.cash
    pt.manual_sell("ANTM.JK", price=1650.0)
    assert pt.cash == pytest.approx(cash_after_buy + 200 * 1650.0 * SELL_MULT)
    assert pt.log[-1]["exit"] == pytest.approx(1644.225)


def test_a_flat_round_trip_now_shows_the_loss_it_really_is(tmp_path):
    """Buying and selling at the SAME price is not break-even; it costs a
    round trip's friction. That this used to read 0.0% is the whole reason
    for the change."""
    pt = trader(tmp_path)
    pt.manual_buy("ANTM.JK", shares=100, price=1000.0)
    pnl = pt.manual_sell("ANTM.JK", price=1000.0)
    assert pnl == pytest.approx((SELL_MULT / BUY_MULT - 1) * 100.0)
    assert pnl == pytest.approx(-0.638, abs=0.001)      # ~0.64% per round trip
    assert pt.cash < 10_000_000


def test_sell_marks_the_leg_costed_and_records_the_entry_fraction(tmp_path):
    pt = trader(tmp_path)
    pt.manual_buy("ANTM.JK", shares=100, price=1000.0)
    pt.manual_sell("ANTM.JK", price=1100.0)
    t = pt.log[-1]
    assert t["costed"] is True
    assert t["entry_costed_frac"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# The escape hatch
# ---------------------------------------------------------------------------

def test_charge_manual_costs_false_restores_raw_price_recording(tmp_path):
    pt = trader(tmp_path, charge_manual_costs=False)
    fill = pt.manual_buy("ANTM.JK", shares=200, price=1500.0)
    assert fill == 1500.0
    assert pt.positions["ANTM.JK"].entry_price == 1500.0
    assert pt.cash == pytest.approx(10_000_000 - 200 * 1500.0)
    pnl = pt.manual_sell("ANTM.JK", price=1650.0)
    assert pnl == pytest.approx(10.0)                   # the old contract


def test_uncosted_fills_carry_no_marker(tmp_path):
    pt = trader(tmp_path, charge_manual_costs=False)
    pt.manual_buy("ANTM.JK", shares=200, price=1500.0)
    (f,) = position_fills(pt.positions["ANTM.JK"])
    assert "costed" not in f
    assert _costed_basis_fraction(pt.positions["ANTM.JK"]) == 0.0


def test_the_switch_survives_a_reload(tmp_path):
    pt = trader(tmp_path, charge_manual_costs=False)
    pt.manual_buy("ANTM.JK", shares=100, price=1000.0)
    reloaded = PaperTrader.load(tmp_path / "p.json", cfg=cfg(),
                                charge_manual_costs=False)
    assert reloaded.manual_fill_price(1000.0, "BUY") == 1000.0


def test_tick_floor_mode_makes_manual_costs_price_aware(tmp_path):
    """A 67-rupiah stock cannot have a spread tighter than its 1-rupiah
    tick, so the flat 0.10% assumption understates it several-fold. The
    manual path must honour spread_mode, not hardcode the flat rate."""
    c = Config(costs=CostModel(spread_mode="tick_floor"))
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000, cfg=c)
    cheap = pt.manual_fill_price(67.0, "BUY")        # 1-rupiah tick = 1.5%
    assert cheap / 67.0 - 1 > 0.005                  # far above the flat 0.29%
    dear = pt.manual_fill_price(6700.0, "BUY")       # 25-rupiah tick = 0.37%
    assert (cheap / 67.0 - 1) > 2 * (dear / 6700.0 - 1)
    # the tick only stops binding once it is small relative to the price
    assert pt.manual_fill_price(50_000.0, "BUY") / 50_000.0 == pytest.approx(BUY_MULT)


# ---------------------------------------------------------------------------
# Friction on a mixed book -- the part that must never double-count
# ---------------------------------------------------------------------------

def legacy_state():
    """A book recorded the old way: raw prices, no markers anywhere."""
    return {
        "positions": {"OLD.JK": {"ticker": "OLD.JK", "entry_price": 1000.0,
                                 "shares": 100, "entry_date": "2026-06-01",
                                 "peak_price": 1000.0}},
        "log": [{"date": "2026-06-10", "ticker": "GONE.JK", "entry": 1000.0,
                 "exit": 1100.0, "entry_date": "2026-06-02", "shares": 100,
                 "pnl_pct": 10.0, "reason": "manual sell"}],
    }


def test_a_legacy_book_reports_exactly_as_it_did_before(tmp_path):
    """Regression guard: adding markers must not move the numbers for a
    book that has none. Its friction is still entirely undeducted."""
    r = friction_report(legacy_state(), CostModel())
    assert r.uncharged_friction_idr == pytest.approx(r.total_friction_idr)
    assert r.charged_friction_idr == 0.0
    assert r.net_pnl_idr < r.recorded_pnl_idr        # still overstated
    assert "never deducted" in r.note or "raw" in r.note


def test_a_fully_costed_book_deducts_nothing_further(tmp_path):
    pt = trader(tmp_path)
    pt.manual_buy("A.JK", shares=100, price=1000.0, date="2026-07-01")
    pt.manual_sell("A.JK", price=1100.0, date="2026-07-05")
    pt.manual_buy("B.JK", shares=100, price=2000.0, date="2026-07-06")

    state = {"positions": {t: vars(p) for t, p in pt.positions.items()},
             "log": pt.log}
    r = friction_report(state, cfg().costs)
    assert r.uncharged_friction_idr == pytest.approx(0.0)
    assert r.charged_friction_idr == pytest.approx(r.total_friction_idr)
    # nothing left to subtract: the costs are already inside the prices
    assert r.net_pnl_idr == pytest.approx(r.recorded_pnl_idr)
    assert "ALREADY paid" in r.note


def test_a_mixed_book_splits_charged_from_uncharged(tmp_path):
    pt = trader(tmp_path)
    pt.manual_buy("NEW.JK", shares=100, price=1000.0, date="2026-07-01")
    state = legacy_state()
    state["positions"]["NEW.JK"] = vars(pt.positions["NEW.JK"])

    r = friction_report(state, CostModel())
    assert r.charged_friction_idr > 0
    assert r.uncharged_friction_idr > 0
    assert (r.charged_friction_idr + r.uncharged_friction_idr
            == pytest.approx(r.total_friction_idr))
    assert "Mixed book" in r.note


def test_a_position_can_mix_legacy_and_costed_shares(tmp_path):
    """Adding to a position opened before the change leaves ONE position
    holding both kinds of shares. The split must follow the money, not the
    share count."""
    pt = trader(tmp_path)
    pt.positions["X.JK"] = PaperPosition(          # pre-existing, raw price
        ticker="X.JK", entry_price=1000.0, shares=100,
        entry_date="2026-06-01", peak_price=1000.0)
    pt.manual_buy("X.JK", shares=100, price=1000.0, date="2026-07-01")

    pos = pt.positions["X.JK"]
    fills = position_fills(pos)
    assert [f.get("costed", False) for f in fills] == [False, True]
    frac = _costed_basis_fraction(pos)
    assert 0.0 < frac < 1.0
    # the costed lot cost slightly more, so it is slightly over half the basis
    assert frac == pytest.approx(BUY_MULT / (1 + BUY_MULT))


def test_selling_a_legacy_position_leaves_its_buy_leg_undeducted(tmp_path):
    """The closed-trade log outlives the fill ledger, so it has to remember
    that the ENTRY was never costed -- otherwise a position opened under the
    old rules looks fully costed the moment it is sold."""
    pt = trader(tmp_path)
    pt.positions["X.JK"] = PaperPosition(
        ticker="X.JK", entry_price=1000.0, shares=100,
        entry_date="2026-06-01", peak_price=1000.0)
    pt.manual_sell("X.JK", price=1100.0, date="2026-07-01")

    t = pt.log[-1]
    assert t["costed"] is True                  # the sell WAS costed
    assert "entry_costed_frac" not in t         # the buy was not

    r = friction_report({"positions": {}, "log": pt.log}, cfg().costs)
    assert r.charged_friction_idr > 0           # sell leg
    assert r.uncharged_friction_idr > 0         # buy leg
    assert r.net_pnl_idr < r.recorded_pnl_idr   # only the buy leg is deducted


def test_net_pnl_deducts_only_the_undeducted_buy_leg(tmp_path):
    pt = trader(tmp_path)
    pt.positions["X.JK"] = PaperPosition(
        ticker="X.JK", entry_price=1000.0, shares=100,
        entry_date="2026-06-01", peak_price=1000.0)
    pt.manual_sell("X.JK", price=1100.0, date="2026-07-01")

    costs = cfg().costs
    r = friction_report({"positions": {}, "log": pt.log}, costs)
    buy_leg = 1000.0 * 100 * (costs.buy_total + costs.half_spread_at(1000.0))
    assert r.recorded_pnl_idr - r.net_pnl_idr == pytest.approx(buy_leg)


def test_open_position_friction_is_priced_per_fill(tmp_path):
    """Blending the average would price a mixed position at one rate; the
    legs belong to different worlds and have to be valued separately."""
    pt = trader(tmp_path)
    pt.positions["X.JK"] = PaperPosition(
        ticker="X.JK", entry_price=1000.0, shares=100,
        entry_date="2026-06-01", peak_price=1000.0)
    pt.manual_buy("X.JK", shares=100, price=1000.0, date="2026-07-01")

    costs = CostModel()
    state = {"positions": {"X.JK": vars(pt.positions["X.JK"])}, "log": []}
    r = friction_report(state, costs)
    legacy_leg = 1000.0 * 100 * (costs.buy_total + costs.half_spread_at(1000.0))
    assert r.uncharged_friction_idr == pytest.approx(legacy_leg)
    assert r.charged_friction_idr > 0


def test_already_charged_true_still_covers_unmarked_records(tmp_path):
    """Backward compatibility: the old whole-book flag still classifies
    records that carry no marker."""
    r = friction_report(legacy_state(), CostModel(), already_charged=True)
    assert r.uncharged_friction_idr == pytest.approx(0.0)
    assert r.net_pnl_idr == pytest.approx(r.recorded_pnl_idr)


def test_a_junk_costed_fraction_falls_back_instead_of_poisoning_the_split():
    state = legacy_state()
    state["log"][0]["entry_costed_frac"] = "not a number"
    r = friction_report(state, CostModel())
    assert r.charged_friction_idr + r.uncharged_friction_idr == pytest.approx(
        r.total_friction_idr)
    assert r.uncharged_friction_idr > 0


def test_an_out_of_range_costed_fraction_is_clamped():
    state = legacy_state()
    state["log"][0]["entry_costed_frac"] = 5.0
    r = friction_report(state, CostModel())
    assert r.charged_friction_idr <= r.total_friction_idr + 1e-6
    assert r.uncharged_friction_idr >= -1e-6


# ---------------------------------------------------------------------------
# The markers must survive the operations that rewrite the ledger
# ---------------------------------------------------------------------------

def test_partial_sell_keeps_the_costed_markers(tmp_path):
    pt = trader(tmp_path)
    pt.manual_buy("A.JK", shares=200, price=1000.0, date="2026-07-01")
    pt.manual_sell("A.JK", price=1100.0, shares=100)
    (f,) = position_fills(pt.positions["A.JK"])
    assert f["costed"] is True
    assert _costed_basis_fraction(pt.positions["A.JK"]) == pytest.approx(1.0)


def test_edit_entry_price_keeps_the_costed_markers(tmp_path):
    pt = trader(tmp_path)
    pt.manual_buy("A.JK", shares=100, price=1000.0)
    pt.edit_entry_price("A.JK", 1200.0)
    (f,) = position_fills(pt.positions["A.JK"])
    assert f["costed"] is True
    assert f["price"] == pytest.approx(1200.0)


def test_edit_entry_price_does_not_add_costs_on_top(tmp_path):
    """It corrects the STORED cost basis directly. Adding costs here would
    inject them into positions opened before /buy started charging them."""
    pt = trader(tmp_path)
    pt.manual_buy("A.JK", shares=100, price=1000.0)
    pt.edit_entry_price("A.JK", 1200.0)
    assert pt.positions["A.JK"].entry_price == 1200.0


def test_corporate_action_adjustment_keeps_the_costed_markers(tmp_path):
    pt = trader(tmp_path)
    pt.manual_buy("A.JK", shares=200, price=1000.0, date="2026-07-01")
    apply_corporate_action_adjustment(pt.positions["A.JK"], 0.5)   # 2:1 split
    fills = position_fills(pt.positions["A.JK"])
    assert fills and all(f["costed"] is True for f in fills)
    assert _costed_basis_fraction(pt.positions["A.JK"]) == pytest.approx(1.0)


def test_a_legacy_position_never_gains_a_marker_by_being_read(tmp_path):
    pos = PaperPosition(ticker="X.JK", entry_price=1000.0, shares=100,
                        entry_date="2026-06-01", peak_price=1000.0)
    for _ in range(3):
        fills = position_fills(pos)
        pos.fills = fills
    assert all("costed" not in f for f in position_fills(pos))
    assert _costed_basis_fraction(pos) == 0.0
