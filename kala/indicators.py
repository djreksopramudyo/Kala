"""
Vectorised technical indicators with textbook-correct definitions.

Each function is pure (no input mutation), returns values aligned to the input
index, and is validated in test_indicators.py against an independent loop-based
reference. Notable corrections vs. the original monolith:

  * RSI/ATR use Wilder's smoothing (the standard), not a simple rolling mean.
  * MACD exposes a SCALE-INVARIANT histogram (``hist_pct``) so one threshold
    works across a 100 IDR stock and a 10,000 IDR stock.
  * ADX computes +DM/-DM from RAW directional moves (the original compared
    -DM against an already-zeroed +DM).
  * ``cross_below`` is an EVENT (fires once, on the crossing bar), not a STATE.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _wilder(series: pd.Series, period: int) -> pd.Series:
    """Wilder's smoothing == EMA with alpha = 1/period."""
    return series.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


def sma(close: pd.Series, period: int) -> pd.Series:
    return close.rolling(period).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI. Pure gains -> 100, flat tape -> 50 (never NaN/inf there)."""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)

    avg_gain = _wilder(gain, period)
    avg_loss = _wilder(loss, period)

    rs = avg_gain / avg_loss
    out = 100.0 - 100.0 / (1.0 + rs)

    # No losses at all -> RSI 100; but a fully flat tape (no gains either) -> 50.
    out = out.where(avg_loss != 0, 100.0)
    out = out.where(~((avg_gain == 0) & (avg_loss == 0)), 50.0)

    out.iloc[:period] = np.nan  # warmup undefined
    return out


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's Average True Range."""
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    tr.iloc[0] = high.iloc[0] - low.iloc[0]  # no prior close on the first bar
    out = _wilder(tr, period)
    out.iloc[:period] = np.nan
    return out


def adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.DataFrame:
    """Average Directional Index with +DI/-DI. Returns columns adx/plus_di/minus_di."""
    up = high.diff()
    down = -low.diff()

    # Directional movement from RAW moves: on any bar at most one is non-zero.
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=high.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=high.index)

    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    tr.iloc[0] = high.iloc[0] - low.iloc[0]

    atr_s = _wilder(tr, period)
    plus_di = 100.0 * _wilder(plus_dm, period) / atr_s
    minus_di = 100.0 * _wilder(minus_dm, period) / atr_s

    di_sum = (plus_di + minus_di).replace(0.0, np.nan)
    dx = 100.0 * (plus_di - minus_di).abs() / di_sum
    adx_s = _wilder(dx, period)

    return pd.DataFrame(
        {"adx": adx_s, "plus_di": plus_di, "minus_di": minus_di}, index=high.index
    )


def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    """On-Balance Volume. Starts at 0; flat bars carry forward."""
    direction = np.sign(close.diff().fillna(0.0))
    return (direction * volume).cumsum()


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """MACD with a scale-invariant normalized histogram (``hist_pct``)."""
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - signal_line
    hist_pct = hist / close * 100.0  # invariant to price scale
    return pd.DataFrame(
        {"macd": macd_line, "signal": signal_line, "hist": hist, "hist_pct": hist_pct},
        index=close.index,
    )


def roc(close: pd.Series, period: int = 10) -> pd.Series:
    """Rate of change over ``period`` bars, in percent."""
    return close.pct_change(period) * 100.0


def cross_below(fast, slow) -> pd.Series:
    """EVENT: True only on the bar where ``fast`` crosses from >= to < ``slow``."""
    fast = pd.Series(fast).reset_index(drop=True) if not isinstance(fast, pd.Series) else fast
    slow = pd.Series(slow).reset_index(drop=True) if not isinstance(slow, pd.Series) else slow
    prev_above = fast.shift(1) >= slow.shift(1)
    now_below = fast < slow
    return (prev_above & now_below).fillna(False)


def cross_above(fast, slow) -> pd.Series:
    """EVENT: True only on the bar where ``fast`` crosses from <= to > ``slow``."""
    fast = pd.Series(fast).reset_index(drop=True) if not isinstance(fast, pd.Series) else fast
    slow = pd.Series(slow).reset_index(drop=True) if not isinstance(slow, pd.Series) else slow
    prev_below = fast.shift(1) <= slow.shift(1)
    now_above = fast > slow
    return (prev_below & now_above).fillna(False)


def overnight_gap_range_pct(df: pd.DataFrame, lookback: int = 60,
                            lo_pct: float = 10.0, hi_pct: float = 90.0,
                            min_obs: int = 20) -> tuple[float, float] | None:
    """Historical open-vs-prior-close gap range for THIS stock, as
    (lo_pct, hi_pct) percentiles of overnight gap % over the last
    ``lookback`` trading days. IDX's pre-opening auction routinely moves the
    open away from yesterday's close by an amount that varies a lot by
    ticker (a jumpy small-cap gaps more than a stable blue chip) — this
    measures each stock's own historical behaviour instead of assuming a
    flat percentage for every name. Returns None if there's too little
    history (< ``min_obs`` gap observations) to be meaningful."""
    close = df["Close"]
    open_ = df["Open"]
    gap_pct = (open_ / close.shift(1) - 1.0) * 100.0
    gap_pct = gap_pct.iloc[-lookback:].dropna()
    if len(gap_pct) < min_obs:
        return None
    lo = float(np.percentile(gap_pct, lo_pct))
    hi = float(np.percentile(gap_pct, hi_pct))
    return lo, hi
