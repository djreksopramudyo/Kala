"""
Trend-vs-range classifier tests: a per-TICKER ADX-based regime signal,
distinct from regime.py's benchmark-level bull/bear classification.
"""

import numpy as np
import pandas as pd

from kala.regime_filter import RANGING, TRANSITIONAL, TRENDING, classify_trend_range


def _trending_df(n=100):
    idx = pd.bdate_range("2022-01-03", periods=n)
    close = 1000.0 * np.exp(np.cumsum(np.full(n, 0.006)))  # steady one-way drift
    return pd.DataFrame(
        {"High": close * 1.003, "Low": close * 0.997, "Close": close}, index=idx)


def _choppy_df(n=100, seed=1):
    idx = pd.bdate_range("2022-01-03", periods=n)
    rng = np.random.default_rng(seed)
    close = 1000.0 + np.cumsum(rng.normal(0.0, 0.5, n))   # tiny mean-reverting noise
    close = np.clip(close, 990.0, 1010.0)
    return pd.DataFrame(
        {"High": close + 1.0, "Low": close - 1.0, "Close": close}, index=idx)


def test_classify_trend_range_returns_expected_labels_only():
    status = classify_trend_range(_trending_df()["High"], _trending_df()["Low"],
                                  _trending_df()["Close"])
    assert set(status.unique()) <= {TRENDING, TRANSITIONAL, RANGING}


def test_strong_one_way_drift_reads_as_trending():
    df = _trending_df()
    status = classify_trend_range(df["High"], df["Low"], df["Close"])
    assert status.iloc[-1] == TRENDING


def test_tight_choppy_range_reads_as_ranging():
    df = _choppy_df()
    status = classify_trend_range(df["High"], df["Low"], df["Close"])
    assert status.iloc[-1] == RANGING


def test_early_bars_before_adx_warmup_are_transitional():
    df = _trending_df(n=20)
    status = classify_trend_range(df["High"], df["Low"], df["Close"])
    assert status.iloc[0] == TRANSITIONAL


def test_is_point_in_time_safe():
    df = _trending_df(n=100)
    full = classify_trend_range(df["High"], df["Low"], df["Close"])
    truncated = classify_trend_range(df["High"].iloc[:60], df["Low"].iloc[:60],
                                     df["Close"].iloc[:60])
    assert (full.iloc[:60] == truncated).all()


def test_custom_thresholds_change_classification():
    df = _trending_df()
    lenient = classify_trend_range(df["High"], df["Low"], df["Close"], trend_adx=999.0)
    assert lenient.iloc[-1] != TRENDING
