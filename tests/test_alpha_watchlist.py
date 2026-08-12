"""Tests for benchmark-relative alpha reporting and the watchlist store."""

import numpy as np
import pandas as pd
import pytest

from kala.backtest import backtest_ticker
from kala.config import Config
from kala.watchlist import WatchlistItem, WatchlistStore


def make_df(closes, index=None):
    closes = np.asarray(closes, dtype=float)
    n = len(closes)
    return pd.DataFrame(
        {
            "Open": closes,
            "High": closes * 1.005,
            "Low": closes * 0.995,
            "Close": closes,
            "Volume": np.full(n, 1e6),
        },
        index=index if index is not None else pd.bdate_range("2023-01-02", periods=n),
    )


# ---------------------------------------------------------------- alpha -----

def test_alpha_fields_none_without_benchmark():
    rng = np.random.default_rng(2)
    df = make_df(1000 * np.exp(np.cumsum(rng.normal(0.001, 0.01, 200))))
    res = backtest_ticker("X.JK", df, None, Config())
    assert res.buy_hold_return_pct is not None          # always computable
    assert res.benchmark_return_pct is None             # no benchmark given
    assert res.alpha_vs_benchmark_pct is None
    assert res.alpha_vs_buy_hold_pct == pytest.approx(
        res.total_return_pct - res.buy_hold_return_pct)


def test_alpha_vs_benchmark_is_excess_return():
    rng = np.random.default_rng(4)
    n = 250
    idx = pd.bdate_range("2023-01-02", periods=n)
    stock = make_df(1000 * np.exp(np.cumsum(rng.normal(0.0008, 0.012, n))), idx)
    bench = make_df(np.linspace(7000, 7700, n), idx)    # index +10% over window
    res = backtest_ticker("X.JK", stock, bench, Config())
    assert res.benchmark_return_pct == pytest.approx(10.0, abs=0.2)
    assert res.alpha_vs_benchmark_pct == pytest.approx(
        res.total_return_pct - res.benchmark_return_pct)


def test_benchmark_aligned_to_ticker_window():
    """Benchmark covering a LONGER period must be sliced to the ticker's dates,
    otherwise the comparison is unfair."""
    n = 100
    idx_stock = pd.bdate_range("2023-06-01", periods=n)
    stock = make_df(np.full(n, 1000.0), idx_stock)
    # benchmark spans a year around it; +50% overall but FLAT inside the window
    idx_b = pd.bdate_range("2023-01-02", periods=400)
    b_close = np.concatenate([
        np.linspace(6000, 7000, 100),                  # before the window
        np.full(200, 7000.0),                          # flat during (covers window)
        np.linspace(7000, 9000, 100),                  # after the window
    ])
    bench = make_df(b_close, idx_b)
    res = backtest_ticker("X.JK", stock, bench, Config())
    assert res.benchmark_return_pct == pytest.approx(0.0, abs=0.5)


# ------------------------------------------------------------- watchlist ----

def test_watchlist_roundtrip_and_alerts(tmp_path):
    path = tmp_path / "watchlist.json"
    wl = WatchlistStore.load(path)
    wl.add(WatchlistItem(ticker="BBCA.JK", fair_value=11000, score=82,
                         thesis="dominant bank, high ROE", source="fundamental_screen"))
    wl.add(WatchlistItem(ticker="UNVR.JK", fair_value=4000, score=71,
                         thesis="brand moat, margin pressure temporary"))
    wl.save()

    wl2 = WatchlistStore.load(path)
    assert len(wl2) == 2
    assert wl2.get("BBCA.JK").thesis.startswith("dominant")

    # BBCA at 20% discount -> alert; UNVR only 5% below fair -> no alert
    alerts = wl2.alerts({"BBCA.JK": 8800.0, "UNVR.JK": 3800.0}, min_discount_pct=15.0)
    assert [a["ticker"] for a in alerts] == ["BBCA.JK"]
    assert alerts[0]["discount_pct"] == pytest.approx(20.0)


def test_watchlist_alerts_sorted_and_skip_missing(tmp_path):
    wl = WatchlistStore.load(tmp_path / "w.json")
    wl.add(WatchlistItem(ticker="A.JK", fair_value=1000))
    wl.add(WatchlistItem(ticker="B.JK", fair_value=1000))
    wl.add(WatchlistItem(ticker="C.JK", fair_value=1000))
    # A at -30%, B at -18%, C has no price today (suspended / no data)
    alerts = wl.alerts({"A.JK": 700.0, "B.JK": 820.0}, min_discount_pct=15.0)
    assert [a["ticker"] for a in alerts] == ["A.JK", "B.JK"]   # deepest first


def test_watchlist_update_replaces_by_default(tmp_path):
    wl = WatchlistStore.load(tmp_path / "w.json")
    wl.add(WatchlistItem(ticker="A.JK", fair_value=1000))
    wl.add(WatchlistItem(ticker="A.JK", fair_value=1200))     # refreshed estimate
    assert len(wl) == 1 and wl.get("A.JK").fair_value == 1200
    with pytest.raises(ValueError):
        wl.add(WatchlistItem(ticker="A.JK", fair_value=900), replace=False)
