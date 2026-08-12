"""Tests: position persistence, backtest execution realism, scoring purity."""

import numpy as np
import pandas as pd
import pytest

from kala.backtest import _is_arb_locked, backtest_ticker
from kala.config import BacktestConfig, Config, CostModel, RiskConfig
from kala.positions import Position, PositionStore
from kala.scoring import composite_score, compute_features


def make_df(closes, vols=None, lows=None, highs=None, opens=None):
    closes = np.asarray(closes, dtype=float)
    n = len(closes)
    return pd.DataFrame(
        {
            "Open": np.asarray(opens, dtype=float) if opens is not None else closes,
            "High": np.asarray(highs, dtype=float) if highs is not None else closes * 1.005,
            "Low": np.asarray(lows, dtype=float) if lows is not None else closes * 0.995,
            "Close": closes,
            "Volume": np.asarray(vols, dtype=float) if vols is not None else np.full(n, 1e6),
        },
        index=pd.bdate_range("2023-01-02", periods=n),
    )


# ----------------------------------------------------------------------------
# Positions
# ----------------------------------------------------------------------------

def test_position_store_roundtrip_and_peak(tmp_path):
    path = tmp_path / "positions.json"
    store = PositionStore.load(path)
    store.add(Position(ticker="BBRI.JK", entry_price=5200, shares=1000))
    store.save()

    store2 = PositionStore.load(path)
    p = store2.get("BBRI.JK")
    assert p is not None and p.entry_price == 5200
    p.update_peak(5800)
    p.update_peak(5500)            # lower print must NOT lower the peak
    assert p.peak_price == 5800
    store2.save()
    assert PositionStore.load(path).get("BBRI.JK").peak_price == 5800


def test_duplicate_position_rejected(tmp_path):
    store = PositionStore.load(tmp_path / "p.json")
    store.add(Position(ticker="TLKM.JK", entry_price=3500, shares=500))
    with pytest.raises(ValueError):
        store.add(Position(ticker="TLKM.JK", entry_price=3600, shares=100))


# ----------------------------------------------------------------------------
# Backtest mechanics
# ----------------------------------------------------------------------------

def test_arb_locked_bar_detection():
    bar = pd.Series({"Open": 900.0, "High": 905.0, "Low": 850.0, "Close": 850.0})
    assert _is_arb_locked(bar, prev_close=1000.0, arb_limit_pct=15.0)   # -15%, closed at low
    bar2 = pd.Series({"Open": 980.0, "High": 990.0, "Low": 960.0, "Close": 970.0})
    assert not _is_arb_locked(bar2, prev_close=1000.0, arb_limit_pct=15.0)


def test_backtest_stop_does_not_fill_on_locked_bar():
    """A crash via consecutive locked limit-down bars must carry the position
    (no fantasy fill at -5%) and only exit on the first tradable bar."""
    rng = np.random.default_rng(7)
    n_up = 120
    up = 1000 * np.exp(np.cumsum(rng.normal(0.004, 0.005, n_up)))  # strong clean uptrend
    last = up[-1]
    lock1, lock2 = last * 0.855, last * 0.855 * 0.855   # two -14.5% locked bars
    tail = np.full(5, lock2 * 0.99)                      # tradable bars after
    closes = np.concatenate([up, [lock1, lock2], tail])
    lows = closes * 0.995
    lows[n_up] = lock1            # locked: close == low
    lows[n_up + 1] = lock2
    df = make_df(closes, lows=lows)

    cfg = Config(
        risk=RiskConfig(trailing_enabled=False, hard_stop_pct=-5.0, atr_stop_multiple=99.0),
        backtest=BacktestConfig(score_entry_threshold=60.0, arb_limit_pct=15.0,
                                holding_max_days=500),
    )
    res = backtest_ticker("LOCK.JK", df, None, cfg)
    assert res.closed, "expected at least one trade"
    t = res.closed[-1]
    assert t.arb_locked_bars >= 1
    # realized loss must be far worse than the nominal -5% stop
    assert t.net_return_pct < -15.0


def test_backtest_costs_are_asymmetric_and_applied():
    """Entry+exit on a flat tape must lose ~(buy + sell + 2*spread)."""
    closes = np.concatenate([np.linspace(1000, 1400, 100), np.full(40, 1400.0)])
    df = make_df(closes)
    costs = CostModel(buy_commission=0.0019, sell_commission=0.0015,
                      sell_tax=0.0010, half_spread=0.0025)
    cfg = Config(
        costs=costs,
        risk=RiskConfig(trailing_enabled=False, hard_stop_pct=-50.0,
                        atr_stop_multiple=99.0, target_profit_pct=999.0),
        backtest=BacktestConfig(score_entry_threshold=60.0, holding_max_days=5),
    )
    res = backtest_ticker("FLAT.JK", df, None, cfg)
    flat_trades = [t for t in res.closed if t.exit_reason == "max holding period"
                   and abs(t.exit_price / (1 - costs.sell_total - costs.half_spread)
                           - t.entry_price / (1 + costs.buy_commission + costs.half_spread)) < 1e-6]
    assert flat_trades, "expected a flat round-trip trade"
    expected_drag = -(costs.buy_commission + costs.sell_total + 2 * costs.half_spread) * 100
    assert flat_trades[0].net_return_pct == pytest.approx(expected_drag, abs=0.05)


def test_backtest_entry_uses_next_open_no_lookahead():
    """Entry price must be the NEXT bar's open, never the signal bar's close."""
    rng = np.random.default_rng(3)
    closes = 1000 * np.exp(np.cumsum(rng.normal(0.003, 0.01, 160)))
    opens = closes * 1.02            # opens deliberately differ from closes
    df = make_df(closes, opens=opens)
    cfg = Config(risk=RiskConfig(trailing_enabled=False, atr_stop_multiple=99.0,
                                 hard_stop_pct=-50.0, target_profit_pct=999.0),
                 backtest=BacktestConfig(score_entry_threshold=55.0, holding_max_days=10))
    res = backtest_ticker("LOOK.JK", df, None, cfg)
    buy_cost = cfg.costs.buy_commission + cfg.costs.half_spread
    for t in res.closed:
        i = df.index.get_loc(t.entry_date)
        assert t.entry_price == pytest.approx(df["Open"].iloc[i] * (1 + buy_cost))


# ----------------------------------------------------------------------------
# Scoring purity
# ----------------------------------------------------------------------------

def test_compute_features_does_not_mutate_input():
    df = make_df(np.linspace(1000, 1100, 80))
    cols_before = list(df.columns)
    vals_before = df.to_numpy().copy()
    compute_features(df)
    assert list(df.columns) == cols_before
    np.testing.assert_array_equal(df.to_numpy(), vals_before)


def test_score_bounds_and_pointintime():
    """Score at bar t must not change when future bars are appended
    (point-in-time property required by the backtest)."""
    rng = np.random.default_rng(11)
    closes = 1000 * np.exp(np.cumsum(rng.normal(0.001, 0.015, 200)))
    df_full = make_df(closes)
    df_cut = df_full.iloc[:150]

    s_full = composite_score(compute_features(df_full))
    s_cut = composite_score(compute_features(df_cut))
    assert ((s_full.dropna() >= 0) & (s_full.dropna() <= 100)).all()
    pd.testing.assert_series_equal(s_cut.iloc[60:], s_full.iloc[60:150], atol=1e-6,
                                   check_exact=False)
