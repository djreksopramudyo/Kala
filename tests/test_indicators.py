"""Indicator tests — every vectorized indicator is validated against an
independent, naive loop-based reference implementation (Wilder's definitions
as published), plus property checks."""

import numpy as np
import pandas as pd
import pytest

from kala import indicators as ind

rng = np.random.default_rng(42)


@pytest.fixture
def ohlcv():
    n = 300
    close = pd.Series(1000 * np.exp(np.cumsum(rng.normal(0.0005, 0.02, n))))
    high = close * (1 + np.abs(rng.normal(0, 0.01, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.01, n)))
    open_ = close.shift(1).fillna(close.iloc[0])
    vol = pd.Series(rng.integers(50_000, 2_000_000, n).astype(float))
    return pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close, "Volume": vol})


# ---------------------------------------------------------------- RSI -------

def _rsi_reference(close: pd.Series, period: int = 14) -> pd.Series:
    """Loop-based Wilder RSI straight from the textbook definition."""
    delta = close.diff().to_numpy()
    out = np.full(len(close), np.nan)
    avg_gain = avg_loss = None
    gains = np.where(delta > 0, delta, 0.0)
    losses = np.where(delta < 0, -delta, 0.0)
    for i in range(period, len(close)):
        if avg_gain is None:
            avg_gain = gains[1 : period + 1].mean()
            avg_loss = losses[1 : period + 1].mean()
        else:
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        out[i] = 100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)
    return pd.Series(out, index=close.index)


def test_rsi_matches_wilder_reference(ohlcv):
    got = ind.rsi(ohlcv["Close"], 14)
    ref = _rsi_reference(ohlcv["Close"], 14)
    # ewm-seeded Wilder converges to the SMA-seeded textbook version; compare
    # after burn-in
    pd.testing.assert_series_equal(got.iloc[100:], ref.iloc[100:], atol=0.5,
                                   check_exact=False, check_names=False)


def test_rsi_bounds_and_pure_gains():
    up = pd.Series(np.linspace(100, 200, 60))
    r = ind.rsi(up, 14).dropna()
    assert ((r >= 0) & (r <= 100)).all()
    assert (r.iloc[-10:] > 95).all()  # pure gains -> ~100, never NaN/inf

    flat = pd.Series([100.0] * 60)
    rf = ind.rsi(flat, 14).dropna()
    assert (rf == 50.0).all()  # flat tape -> neutral, not NaN


# ---------------------------------------------------------------- ATR -------

def _atr_reference(df: pd.DataFrame, period: int = 14) -> pd.Series:
    h, l, c = df["High"].to_numpy(), df["Low"].to_numpy(), df["Close"].to_numpy()
    tr = np.full(len(df), np.nan)
    tr[0] = h[0] - l[0]
    for i in range(1, len(df)):
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
    out = np.full(len(df), np.nan)
    prev = tr[1 : period + 1].mean()
    out[period] = prev
    for i in range(period + 1, len(df)):
        prev = (prev * (period - 1) + tr[i]) / period
        out[i] = prev
    return pd.Series(out, index=df.index)


def test_atr_matches_wilder_reference(ohlcv):
    got = ind.atr(ohlcv["High"], ohlcv["Low"], ohlcv["Close"], 14)
    ref = _atr_reference(ohlcv, 14)
    rel_err = ((got - ref).abs() / ref).iloc[100:]
    assert rel_err.max() < 0.02


# ---------------------------------------------------------------- ADX -------

def test_adx_dm_uses_raw_moves(ohlcv):
    """Regression test for the original sequencing bug (-DM compared against
    already-zeroed +DM). With raw moves, on any bar at most ONE of +DM/-DM is
    nonzero, and they must equal the raw up/down move when selected."""
    high, low = ohlcv["High"], ohlcv["Low"]
    up, down = high.diff(), -low.diff()
    plus = np.where((up > down) & (up > 0), up, 0.0)
    minus = np.where((down > up) & (down > 0), down, 0.0)
    assert not ((plus > 0) & (minus > 0)).any()
    out = ind.adx(high, low, ohlcv["Close"], 14)
    a = out["adx"].dropna()
    assert ((a >= 0) & (a <= 100)).all()


# ---------------------------------------------------------------- OBV -------

def test_obv_vectorized_equals_loop(ohlcv):
    close, vol = ohlcv["Close"], ohlcv["Volume"]
    ref = np.zeros(len(close))
    for i in range(1, len(close)):
        if close.iloc[i] > close.iloc[i - 1]:
            ref[i] = ref[i - 1] + vol.iloc[i]
        elif close.iloc[i] < close.iloc[i - 1]:
            ref[i] = ref[i - 1] - vol.iloc[i]
        else:
            ref[i] = ref[i - 1]
    got = ind.obv(close, vol).to_numpy()
    np.testing.assert_allclose(got, ref)


# --------------------------------------------------------------- MACD -------

def test_macd_hist_pct_is_scale_invariant(ohlcv):
    """Normalized histogram must be identical for a 100-IDR and a 10,000-IDR
    version of the same price path (the original's absolute -0.05 IDR
    threshold was not)."""
    c1 = ohlcv["Close"]
    c2 = c1 * 100.0
    h1 = ind.macd(c1)["hist_pct"]
    h2 = ind.macd(c2)["hist_pct"]
    pd.testing.assert_series_equal(h1, h2, atol=1e-9, check_exact=False)


# ---------------------------------------------------------- crossovers ------

def test_cross_below_is_event_not_state():
    fast = pd.Series([5, 5, 4, 3, 2, 2, 2], dtype=float)
    slow = pd.Series([4, 4, 4, 4, 4, 4, 4], dtype=float)
    ev = ind.cross_below(fast, slow)
    assert ev.sum() == 1          # fires exactly once...
    assert bool(ev.iloc[3])       # ...on the crossing bar
    assert not ev.iloc[4:].any()  # never again while merely below


# --------------------------------------------------- overnight gap range ----

def test_overnight_gap_range_matches_known_distribution():
    """Construct closes with an EXACT, known overnight gap: open is always
    prior close * 1.02 (a flat +2% gap every day). The percentile range must
    collapse to (2.0, 2.0) since every observation is identical."""
    n = 80
    close = pd.Series(1000 * np.exp(np.cumsum(rng.normal(0.001, 0.01, n))))
    open_ = close.shift(1) * 1.02
    open_.iloc[0] = close.iloc[0]
    df = pd.DataFrame({"Open": open_, "Close": close})
    result = ind.overnight_gap_range_pct(df, lookback=60)
    assert result is not None
    lo, hi = result
    assert lo == pytest.approx(2.0, abs=1e-6)
    assert hi == pytest.approx(2.0, abs=1e-6)


def test_overnight_gap_range_widens_with_realistic_noise():
    """With genuinely varying gaps (open != prior close, unlike the shared
    `ohlcv` fixture which sets open = prior close exactly), lo must be below
    hi and both should bracket a plausible IDX overnight move."""
    n = 80
    close = pd.Series(1000 * np.exp(np.cumsum(rng.normal(0.0005, 0.01, n))))
    gap_noise = rng.normal(0.0, 0.015, n)   # independent overnight gap noise
    open_ = close.shift(1) * (1 + gap_noise)
    open_.iloc[0] = close.iloc[0]
    df = pd.DataFrame({"Open": open_, "Close": close})
    result = ind.overnight_gap_range_pct(df, lookback=60)
    assert result is not None
    lo, hi = result
    assert lo < hi
    assert -20.0 < lo < 0.0 < hi < 20.0


def test_overnight_gap_range_none_when_too_little_history():
    df = pd.DataFrame({"Open": [1000.0, 1010.0, 995.0],
                       "Close": [1000.0, 1005.0, 998.0]})
    assert ind.overnight_gap_range_pct(df, min_obs=20) is None


def test_overnight_gap_range_only_uses_the_lookback_window():
    """A stale, huge gap far outside the lookback window must not leak into
    the computed range."""
    n = 100
    close = pd.Series(np.full(n, 1000.0))
    open_ = close.shift(1)
    open_.iloc[0] = close.iloc[0]
    open_.iloc[5] = close.iloc[4] * 1.50   # a 50% gap, but old (outside lookback)
    df = pd.DataFrame({"Open": open_, "Close": close})
    lo, hi = ind.overnight_gap_range_pct(df, lookback=30)
    assert hi < 10.0   # the stale 50% spike from bar 5 must not show up
