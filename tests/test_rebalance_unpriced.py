"""A held position that can't be priced must not fabricate rebalance orders.

Every weight in plan_rebalance is value/pot. Dropping a held position from
holdings_value shrinks the pot, which inflates every remaining name's weight
by exactly the missing share — and pushes them over the band together. With
five equal holdings that is four SELL orders against a portfolio sitting
precisely on target.
"""

import pytest

from kala.rebalance import plan_rebalance

NAMES = ["AAA.JK", "BBB.JK", "CCC.JK", "DDD.JK", "EEE.JK"]
TARGET = {n: 20.0 for n in NAMES}
HOLDINGS = {n: 20_000_000.0 for n in NAMES}
PRICES = {n: 1000.0 for n in NAMES}


def test_on_target_portfolio_is_a_noop():
    plan = plan_rebalance(HOLDINGS, TARGET, PRICES, cash=0.0, band_pp=5.0)
    assert plan.is_noop


def test_unpriced_holding_does_not_fabricate_sells():
    """The regression. Before the fix this produced four SELL orders worth
    IDR 16,000,000 on a portfolio that had not drifted by a single rupiah."""
    holdings = {k: v for k, v in HOLDINGS.items() if k != "EEE.JK"}
    prices = {**PRICES, "EEE.JK": None}

    plan = plan_rebalance(holdings, TARGET, prices, cash=0.0, band_pp=5.0,
                          unpriced_holdings=["EEE.JK"])

    assert plan.is_noop, [f"{o.action} {o.ticker}" for o in plan.orders]
    assert plan.total_sell_value == 0.0


def test_refusal_explains_which_name_and_why():
    plan = plan_rebalance({}, TARGET, {}, cash=0.0, band_pp=5.0,
                          unpriced_holdings=["EEE.JK"])
    assert "EEE.JK" in plan.note
    assert "EEE.JK" in plan.skipped
    # must explain the mechanism, not just say "skipped"
    assert "weight" in plan.note.lower()


def test_unpriced_name_you_do_not_hold_still_plans_normally():
    """A target-only name that can't be priced leaves the pot intact — the
    rest of the plan is trustworthy and must not be thrown away."""
    target = {**TARGET, "ZZZ.JK": 0.0}
    drifted = {**HOLDINGS, "AAA.JK": 40_000_000.0}
    prices = {**PRICES, "ZZZ.JK": None}

    plan = plan_rebalance(drifted, target, prices, cash=0.0, band_pp=5.0,
                          unpriced_holdings=[])
    assert not plan.is_noop
    assert any(o.action == "SELL" and o.ticker == "AAA.JK" for o in plan.orders)


def test_genuine_drift_still_produces_orders_when_everything_is_priced():
    """Guard against 'fixing' this by simply never trading."""
    drifted = {**HOLDINGS, "AAA.JK": 40_000_000.0}
    plan = plan_rebalance(drifted, TARGET, PRICES, cash=0.0, band_pp=5.0)
    assert not plan.is_noop
    assert any(o.action == "SELL" for o in plan.orders)


def test_none_and_empty_list_both_mean_everything_was_priced():
    for value in (None, []):
        plan = plan_rebalance(HOLDINGS, TARGET, PRICES, cash=0.0,
                              band_pp=5.0, unpriced_holdings=value)
        assert plan.is_noop          # on target, so no-op for the RIGHT reason
        assert plan.note.startswith("No rebalancing needed")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
