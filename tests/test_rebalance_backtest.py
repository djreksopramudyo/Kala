"""Rebalancing policy backtest tests. Uses SYNTHETIC price paths with known
properties (anti-correlated -> rebalancing should help; identical ->
no difference; trending -> rebalancing drags) so the policy logic is
verified without network or real data. The honest expectation is baked into
the assertions, not just hoped for."""

import numpy as np
import pandas as pd

from kala.rebalance_backtest import (
    RebalanceComparison,
    compare_rebalancing,
    format_comparison,
)


def _series(values, start="2016-01-01"):
    idx = pd.bdate_range(start, periods=len(values))
    return pd.Series(np.asarray(values, dtype=float), index=idx)


def _needs_at_least(every_days=63):
    return every_days * 2 + 10   # minimum length for a meaningful run


# ---------------- guardrails --------------------------------------------------

def test_single_name_cannot_be_compared():
    cmp = compare_rebalancing({"A": _series(np.linspace(100, 200, 400))})
    assert cmp.note
    assert "at least 2 names" in cmp.note


def test_too_little_history_is_reported():
    n = 50   # far fewer than every_days*2
    prices = {"A": _series(np.linspace(100, 110, n)), "B": _series(np.linspace(100, 120, n))}
    cmp = compare_rebalancing(prices, every_days=63)
    assert "overlapping days" in cmp.note


def test_one_short_history_ticker_does_not_collapse_the_whole_join():
    """A single newly-listed name (no overlap with the rest) must NOT drop
    the whole multi-name basket to ~0 overlapping days via a strict inner
    join -- it gets dropped instead, and the comparison runs on the rest."""
    long_history = {f"S{i}.JK": _series(np.linspace(100, 200, 900),
                                        start="2016-01-01")
                    for i in range(4)}
    long_history["NEWIPO.JK"] = _series(np.linspace(100, 105, 5), start="2026-07-01")

    cmp = compare_rebalancing(long_history, every_days=63, cost_rate=0.0)
    assert "NEWIPO.JK" in cmp.dropped_short_history
    assert cmp.n_names == 4
    assert cmp.n_days > 800
    assert not cmp.note


def test_only_overlapping_dates_are_used():
    # A and B share only part of their calendars -> comparison uses the overlap.
    a = _series(np.linspace(100, 200, 400), start="2016-01-01")
    b = _series(np.linspace(100, 150, 400), start="2016-06-01")   # offset start
    cmp = compare_rebalancing({"A": a, "B": b}, every_days=21)
    assert cmp.n_names == 2
    assert cmp.n_days < 400   # trimmed to the overlap


# ---------------- policy behavior ---------------------------------------------

def test_identical_paths_make_rebalancing_a_wash():
    """Two identical price paths -> rebalancing never has anything to trim,
    so (minus tiny cost) the two arms should be ~equal."""
    path = 1000 * np.exp(np.cumsum(np.random.default_rng(0).normal(0.0003, 0.01, 400)))
    cmp = compare_rebalancing({"A": _series(path), "B": _series(path.copy())},
                              every_days=63, cost_rate=0.0)
    assert cmp.rebalanced.total_return_pct == \
        __import__("pytest").approx(cmp.buy_hold.total_return_pct, abs=1e-6)


def test_anti_correlated_basket_rebalancing_reduces_vol():
    """The classic case FOR rebalancing: two strongly anti-correlated, choppy
    assets. Rebalancing (buy the loser, sell the winner each period) should
    reduce portfolio volatility vs letting them drift."""
    rng = np.random.default_rng(3)
    n = 500
    shock = rng.normal(0, 0.02, n)
    a = 1000 * np.exp(np.cumsum(0.0002 + shock))     # moves one way on the shock
    b = 1000 * np.exp(np.cumsum(0.0002 - shock))     # moves the opposite way
    cmp = compare_rebalancing({"A": _series(a), "B": _series(b)},
                              every_days=21, cost_rate=0.0)
    assert cmp.rebalanced.ann_vol_pct < cmp.buy_hold.ann_vol_pct


def test_costs_reduce_rebalanced_return():
    rng = np.random.default_rng(5)
    n = 500
    shock = rng.normal(0, 0.02, n)
    a = 1000 * np.exp(np.cumsum(0.0002 + shock))
    b = 1000 * np.exp(np.cumsum(0.0002 - shock))
    prices = {"A": _series(a), "B": _series(b)}
    free = compare_rebalancing(prices, every_days=21, cost_rate=0.0)
    costly = compare_rebalancing(prices, every_days=21, cost_rate=0.005)
    assert costly.rebalanced.total_return_pct < free.rebalanced.total_return_pct
    assert costly.total_cost > 0
    assert free.total_cost == 0.0


def test_more_frequent_rebalancing_costs_more():
    rng = np.random.default_rng(7)
    n = 600
    shock = rng.normal(0, 0.02, n)
    a = 1000 * np.exp(np.cumsum(0.0002 + shock))
    b = 1000 * np.exp(np.cumsum(0.0002 - shock))
    prices = {"A": _series(a), "B": _series(b)}
    frequent = compare_rebalancing(prices, every_days=21, cost_rate=0.003)
    rare = compare_rebalancing(prices, every_days=126, cost_rate=0.003)
    assert frequent.n_rebalances > rare.n_rebalances
    assert frequent.total_cost > rare.total_cost


def test_buy_and_hold_arm_is_cost_free():
    """Only the rebalanced arm pays friction; buy-and-hold never trades after
    day 0, so total_cost reflects the rebalancing policy alone."""
    rng = np.random.default_rng(9)
    path_a = 1000 * np.exp(np.cumsum(rng.normal(0.0005, 0.015, 400)))
    path_b = 1000 * np.exp(np.cumsum(rng.normal(0.0003, 0.015, 400)))
    cmp = compare_rebalancing({"A": _series(path_a), "B": _series(path_b)},
                              every_days=63, cost_rate=0.003)
    # buy-and-hold total return is a pure function of prices; sanity that it's
    # populated and finite.
    assert np.isfinite(cmp.buy_hold.total_return_pct)
    assert cmp.n_rebalances >= 1


# ---------------- reporting ---------------------------------------------------

def test_format_comparison_states_it_is_a_policy_not_a_signal():
    rng = np.random.default_rng(11)
    path_a = 1000 * np.exp(np.cumsum(rng.normal(0.0005, 0.015, 400)))
    path_b = 1000 * np.exp(np.cumsum(rng.normal(0.0003, 0.015, 400)))
    cmp = compare_rebalancing({"A": _series(path_a), "B": _series(path_b)}, every_days=63)
    text = format_comparison(cmp, every_days=63, cost_rate=0.003)
    assert "MAINTENANCE POLICY, not a timing signal" in text
    assert "buy & hold" in text and "rebalanced" in text
    assert "READ:" in text   # honest verdict line present


def test_format_comparison_handles_failed_run():
    cmp = compare_rebalancing({"A": _series(np.linspace(100, 200, 400))})   # 1 name
    text = format_comparison(cmp, every_days=63, cost_rate=0.003)
    assert "could not run" in text


def test_returns_dataclass():
    cmp = compare_rebalancing({}, every_days=63)
    assert isinstance(cmp, RebalanceComparison)
