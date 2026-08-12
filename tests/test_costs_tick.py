"""Tick-size-aware spread costs.

The flat 0.10% half-spread assumption is structurally too optimistic for
cheap IDX stocks: the exchange tick sets a hard floor on the quoted spread
(a 67-rupiah stock cannot trade tighter than its 1-rupiah tick ≈ 1.5%).
These tests pin the tier table, the floor math, the backward-compat
guarantee (flat mode is bit-identical to the historical scalars), and the
engine-level effect (same trades, honestly lower returns).
"""

import numpy as np
import pandas as pd
import pytest

from kala.backtest import backtest_ticker
from kala.config import BacktestConfig, Config, CostModel, RiskConfig, idx_tick_size

# ---------------- tick tier table ----------------

@pytest.mark.parametrize("price,tick", [
    (67, 1.0), (199, 1.0),
    (200, 2.0), (318, 2.0), (499, 2.0),
    (500, 5.0), (1500, 5.0), (1999, 5.0),
    (2000, 10.0), (4690, 10.0), (4999, 10.0),
    (5000, 25.0), (10000, 25.0),
])
def test_idx_tick_tiers(price, tick):
    assert idx_tick_size(price) == tick


# ---------------- half_spread_at ----------------

def test_flat_mode_ignores_price():
    c = CostModel()   # spread_mode defaults to "flat"
    for price in (67, 318, 1500, 25000):
        assert c.half_spread_at(price) == c.half_spread


def test_tick_floor_binds_for_cheap_stocks():
    c = CostModel(spread_mode="tick_floor")
    # 67 rupiah: half a 1-rupiah tick = 1/67/2 ≈ 0.75% — 7.5x the flat 0.10%
    assert c.half_spread_at(67) == pytest.approx(1 / 67 / 2)
    # 318 rupiah, tick 2: 2/318/2 ≈ 0.31%
    assert c.half_spread_at(318) == pytest.approx(2 / 318 / 2)


def test_flat_assumption_binds_for_expensive_stocks():
    c = CostModel(spread_mode="tick_floor")
    # 25,000 rupiah: half a 25-tick = 25/25000/2 = 0.05% < flat 0.10% -> flat wins
    assert c.half_spread_at(25_000) == c.half_spread


def test_nonpositive_price_falls_back_to_flat():
    c = CostModel(spread_mode="tick_floor")
    assert c.half_spread_at(0) == c.half_spread
    assert c.half_spread_at(-5) == c.half_spread


def test_flat_multipliers_equal_historical_scalars():
    """Backward compat: in flat mode the new methods must reproduce the old
    precomputed scalars EXACTLY — every validated number depends on it."""
    c = CostModel()
    for price in (67, 318, 1500, 25000):
        assert c.buy_multiplier(price) == pytest.approx(
            1.0 + c.buy_commission + c.half_spread, abs=0)
        assert c.sell_multiplier(price) == pytest.approx(
            1.0 - c.sell_total - c.half_spread, abs=0)


# ---------------- engine integration ----------------

def _cheap_stock_df(n_ramp=120, n_flat=60, scale=300.0):
    """Noisy uptrend then flat, priced in the 200-500 tier (tick 2) where
    the floor clearly exceeds the flat assumption."""
    rng = np.random.default_rng(3)
    ramp = scale * np.exp(np.cumsum(rng.normal(0.004, 0.006, n_ramp)))
    closes = np.concatenate([ramp, np.full(n_flat, ramp[-1])])
    n = len(closes)
    return pd.DataFrame(
        {"Open": closes, "High": closes * 1.005, "Low": closes * 0.995,
         "Close": closes, "Volume": np.full(n, 1e6)},
        index=pd.bdate_range("2022-01-03", periods=n))


def _cfg(spread_mode):
    return Config(
        risk=RiskConfig(trailing_enabled=False, hard_stop_pct=-50.0,
                        atr_stop_multiple=99.0, target_profit_pct=999.0),
        backtest=BacktestConfig(score_entry_threshold=60.0, holding_max_days=10,
                                apply_entry_vetoes=False),
        costs=CostModel(spread_mode=spread_mode))


def test_backtest_same_trades_lower_returns_under_tick_floor():
    """Honest spreads must change the BOOKED RETURNS, never the DECISIONS:
    entries fire on the raw score and exits on raw prices, so both arms
    trade the identical dates — tick_floor just books each leg at a worse
    price. Every trade's net return must come out strictly lower."""
    df = _cheap_stock_df()
    flat = backtest_ticker("FLAT.JK", df, None, _cfg("flat"))
    tick = backtest_ticker("TICK.JK", df, None, _cfg("tick_floor"))

    assert flat.closed and tick.closed
    assert len(flat.closed) == len(tick.closed)
    for tf, tt in zip(flat.closed, tick.closed):
        assert tf.entry_date == tt.entry_date       # decisions identical
        assert tf.exit_date == tt.exit_date
        # ~0.2-0.3% worse per leg at this price tier -> clearly lower net
        assert tt.net_return_pct < tf.net_return_pct - 0.1


def test_papertrade_buy_fill_costs_more_under_tick_floor(tmp_path):
    from kala.papertrade import PaperTrader, PendingOrder

    def fill_price(mode):
        pt = PaperTrader.load(tmp_path / f"{mode}.json", start_capital=10_000_000,
                              cfg=_cfg(mode))
        pt.pending = [PendingOrder(ticker="CHEAP.JK", side="BUY", shares=100,
                                   reason="test", queued="2026-07-01")]
        h = _cheap_stock_df().iloc[:70]
        pt.step({"CHEAP.JK": h}, [], today="2026-07-02")
        return pt.positions["CHEAP.JK"].entry_price

    assert fill_price("tick_floor") > fill_price("flat")
