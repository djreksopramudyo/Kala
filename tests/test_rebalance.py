"""Rebalancing plan generator tests. The behaviors that matter for an honest
tool: (1) it does NOTHING when within band (anti-churn is the default),
(2) it never overspends available cash, (3) it never sells more than held,
(4) it's lot-aware, and (5) it reports the churn cost so the user can judge
whether a drift is worth fixing."""

import pytest

from kala.config import CostModel, us_equity_costs
from kala.rebalance import RebalancePlan, default_lot_size, plan_rebalance

# ---------------- lot sizing --------------------------------------------------

def test_default_lot_size_idx_vs_us():
    assert default_lot_size("ANTM.JK") == 100
    assert default_lot_size("bbca.jk") == 100
    assert default_lot_size("AAPL") == 1


# ---------------- the honest default: do nothing ------------------------------

def test_within_band_is_a_noop():
    # 52% / 48% vs a 50/50 target -> 2pp drift, inside the 5pp band -> no trades.
    plan = plan_rebalance(
        holdings_value={"A.JK": 5200.0, "B.JK": 4800.0},
        target_weights={"A.JK": 50.0, "B.JK": 50.0},
        prices={"A.JK": 100.0, "B.JK": 100.0}, cash=0.0)
    assert plan.is_noop
    assert "No rebalancing needed" in plan.note


def test_empty_portfolio_is_a_noop():
    plan = plan_rebalance({}, {"A.JK": 100.0}, {"A.JK": 100.0}, cash=0.0)
    assert plan.is_noop
    assert "Nothing to rebalance" in plan.note


# ---------------- actual rebalancing ------------------------------------------

# Realistic IDX scale: price 100, lot 100 -> one lot = IDR 10,000; holdings are
# whole-lot multiples (value/100 = shares, shares/100 = lots).

def test_over_target_generates_a_sell():
    # A is 80% vs 50% target (30pp over) -> should SELL some A.
    plan = plan_rebalance(
        holdings_value={"A.JK": 800_000.0, "B.JK": 200_000.0},   # 80 vs 20 lots
        target_weights={"A.JK": 50.0, "B.JK": 50.0},
        prices={"A.JK": 100.0, "B.JK": 100.0}, cash=0.0)
    sells = [o for o in plan.orders if o.action == "SELL"]
    assert any(o.ticker == "A.JK" for o in sells)
    a_sell = next(o for o in sells if o.ticker == "A.JK")
    assert a_sell.shares > 0 and a_sell.shares % 100 == 0   # lot-aligned


def test_under_target_generates_a_buy_funded_by_the_sell():
    plan = plan_rebalance(
        holdings_value={"A.JK": 800_000.0, "B.JK": 200_000.0},
        target_weights={"A.JK": 50.0, "B.JK": 50.0},
        prices={"A.JK": 100.0, "B.JK": 100.0}, cash=0.0)
    buys = [o for o in plan.orders if o.action == "BUY"]
    assert any(o.ticker == "B.JK" for o in buys)


def test_buys_never_exceed_available_cash():
    # Three under-target names, funded only by cash (nothing over target to
    # sell) -> total buys must be capped at available cash.
    plan = plan_rebalance(
        holdings_value={"A.JK": 100_000.0},          # 10 lots
        target_weights={"A.JK": 33.0, "B.JK": 33.0, "C.JK": 34.0},
        prices={"A.JK": 100.0, "B.JK": 100.0, "C.JK": 100.0},
        cash=300_000.0)
    total_buy = sum(o.value for o in plan.orders if o.action == "BUY")
    assert total_buy <= 300_000.0 + 1e-9


def test_sell_never_exceeds_holdings():
    # target 0 for a held name -> exit it, but never sell more than held.
    plan = plan_rebalance(
        holdings_value={"OLD.JK": 500_000.0, "KEEP.JK": 500_000.0},   # 50 lots each
        target_weights={"KEEP.JK": 100.0},       # OLD dropped from target
        prices={"OLD.JK": 100.0, "KEEP.JK": 100.0}, cash=0.0)
    old_sells = [o for o in plan.orders if o.ticker == "OLD.JK" and o.action == "SELL"]
    assert old_sells
    held_shares = 500_000.0 / 100.0
    assert old_sells[0].shares <= held_shares


def test_dropped_name_is_fully_exited():
    """A name no longer in the target (target 0) that's over band should be
    sold down toward zero -- the 'clean out what you no longer want' case."""
    plan = plan_rebalance(
        holdings_value={"OLD.JK": 500_000.0, "KEEP.JK": 500_000.0},
        target_weights={"KEEP.JK": 100.0},
        prices={"OLD.JK": 100.0, "KEEP.JK": 100.0}, cash=0.0)
    old_sell = next(o for o in plan.orders if o.ticker == "OLD.JK")
    # 500,000 value / 100 price = 5000 shares held; target 0 -> sell all 5000.
    assert old_sell.shares == 5000


# ---------------- targets need not sum to 100 (cash buffer) -------------------

def test_targets_below_100_leave_a_cash_buffer():
    # target 80% A, implicit 20% cash. Start 100% A -> should trim A to ~80%.
    plan = plan_rebalance(
        holdings_value={"A.JK": 1_000_000.0},     # 100 lots
        target_weights={"A.JK": 80.0},            # sums to 80 -> 20% cash target
        prices={"A.JK": 100.0}, cash=0.0)
    a_sell = next(o for o in plan.orders if o.ticker == "A.JK")
    assert a_sell.action == "SELL"
    # pot=1,000,000, target A value=800,000 -> sell ~200,000 = 2000 shares.
    assert a_sell.shares == pytest.approx(2000, abs=100)   # allow 1-lot rounding


# ---------------- cost estimate -----------------------------------------------

def test_cost_estimate_reported_when_cost_model_given():
    plan = plan_rebalance(
        holdings_value={"A.JK": 800_000.0, "B.JK": 200_000.0},
        target_weights={"A.JK": 50.0, "B.JK": 50.0},
        prices={"A.JK": 100.0, "B.JK": 100.0}, cash=0.0,
        cost_model=CostModel())
    assert plan.est_cost > 0
    # sanity: cost is a small fraction of the traded value, not larger than it.
    traded = plan.total_buy_value + plan.total_sell_value
    assert 0 < plan.est_cost < traded


def test_us_equity_costs_much_cheaper_than_idx_on_same_plan():
    args = dict(
        holdings_value={"A.JK": 800_000.0, "B.JK": 200_000.0},
        target_weights={"A.JK": 50.0, "B.JK": 50.0},
        prices={"A.JK": 100.0, "B.JK": 100.0}, cash=0.0)
    idx = plan_rebalance(**args, cost_model=CostModel())
    us = plan_rebalance(**args, cost_model=us_equity_costs())
    assert us.est_cost < idx.est_cost


# ---------------- missing prices degrade, don't crash -------------------------

def test_missing_price_skips_that_name_not_crash():
    plan = plan_rebalance(
        holdings_value={"A.JK": 800_000.0, "B.JK": 200_000.0},
        target_weights={"A.JK": 50.0, "B.JK": 50.0},
        prices={"A.JK": 100.0},                  # B has no price
        cash=0.0)
    assert "B.JK" in plan.skipped
    assert all(o.ticker != "B.JK" for o in plan.orders)


# ---------------- US single-share lots ----------------------------------------

def test_us_names_trade_in_single_shares():
    plan = plan_rebalance(
        holdings_value={"AAPL": 8000.0, "MSFT": 2000.0},
        target_weights={"AAPL": 50.0, "MSFT": 50.0},
        prices={"AAPL": 190.0, "MSFT": 410.0}, cash=0.0)
    # lot size 1 for bare US tickers -> share counts need not be multiples of 100
    assert any(o.shares % 100 != 0 for o in plan.orders) or plan.is_noop


def test_plan_dataclass_is_returned():
    plan = plan_rebalance({}, {}, {}, cash=0.0)
    assert isinstance(plan, RebalancePlan)
