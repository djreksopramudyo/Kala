"""Tests for kala.regime — point-in-time IHSG regime classification."""

import numpy as np
import pandas as pd

from kala.regime import classify_market_regime, regime_at


def _bench(closes):
    closes = np.asarray(closes, dtype=float)
    idx = pd.bdate_range("2023-01-02", periods=len(closes))
    return pd.DataFrame({"Close": closes}, index=idx)


def test_warmup_bars_are_unknown_not_bear():
    df = _bench(np.linspace(1000, 1010, 49))  # < 50 bars: SMA50 never warms
    status = classify_market_regime(df)
    assert (status == "UNKNOWN").all()


def test_strong_uptrend_classified_bullish():
    df = _bench(1000 * np.exp(np.cumsum(np.full(120, 0.01))))
    status = classify_market_regime(df)
    assert status.iloc[-1] == "BULLISH"


def test_strong_downtrend_classified_bearish():
    df = _bench(1000 * np.exp(np.cumsum(np.full(120, -0.01))))
    status = classify_market_regime(df)
    assert status.iloc[-1] == "BEARISH"


def test_point_in_time_earlier_status_unaffected_by_future_bars():
    """Appending more history must not change an already-computed bar's status
    (same discipline required of composite_score)."""
    closes = 1000 * np.exp(np.cumsum(np.concatenate([
        np.full(80, 0.01), np.full(40, -0.02),
    ])))
    df_full = _bench(closes)
    df_cut = df_full.iloc[:80]

    status_full = classify_market_regime(df_full)
    status_cut = classify_market_regime(df_cut)
    pd.testing.assert_series_equal(status_cut.iloc[50:], status_full.iloc[50:80])


def test_regime_at_uses_asof_no_lookahead():
    closes = 1000 * np.exp(np.cumsum(np.full(120, 0.01)))
    df = _bench(closes)
    status = classify_market_regime(df)

    # A date that falls on a benchmark holiday (not in the index) must still
    # resolve to the latest KNOWN prior status, never a future one.
    holiday = df.index[60] + pd.Timedelta(hours=1)
    assert regime_at(status, holiday) == status.iloc[60]


def test_regime_at_before_history_returns_none():
    closes = 1000 * np.exp(np.cumsum(np.full(120, 0.01)))
    df = _bench(closes)
    status = classify_market_regime(df)
    before = df.index[0] - pd.Timedelta(days=5)
    assert regime_at(status, before) is None


def test_regime_at_empty_series_returns_none():
    assert regime_at(None, pd.Timestamp("2023-01-02")) is None
    assert regime_at(pd.Series(dtype=object), pd.Timestamp("2023-01-02")) is None
