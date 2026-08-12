"""
Feature engineering and the composite 0-100 score.

Two hard invariants, both enforced by tests:

  * ``compute_features`` NEVER mutates its input — it returns a fresh frame.
    (The original wrote SMA/RSI columns straight into the caller's DataFrame.)
  * ``composite_score`` is POINT-IN-TIME: the score at bar t depends only on
    data up to bar t. No full-series normalisation, no centred windows, no
    look-ahead — otherwise the backtest silently cheats.
"""

from __future__ import annotations

import pandas as pd

from . import indicators as ind

FAST_SMA = 10
SLOW_SMA = 50
RSI_PERIOD = 14
ATR_PERIOD = 14
ROC_PERIOD = 10


def compute_features(df: pd.DataFrame) -> pd.DataFrame:
    """Return a COPY of ``df`` with indicator columns added. Input untouched."""
    feats = df.copy()

    close = feats["Close"]
    feats["sma_fast"] = ind.sma(close, FAST_SMA)
    feats["sma_slow"] = ind.sma(close, SLOW_SMA)
    feats["rsi"] = ind.rsi(close, RSI_PERIOD)
    feats["roc_10"] = ind.roc(close, ROC_PERIOD)
    feats["atr"] = ind.atr(feats["High"], feats["Low"], close, ATR_PERIOD)

    macd = ind.macd(close)
    feats["macd_hist_pct"] = macd["hist_pct"]

    adx = ind.adx(feats["High"], feats["Low"], close, ATR_PERIOD)
    feats["adx"] = adx["adx"]

    return feats


def composite_score(feats: pd.DataFrame) -> pd.Series:
    """Causal 0-100 score blending trend, momentum and rate-of-change.

    Each component is mapped through a FIXED threshold (not a series-wide
    z-score), which is what keeps the score point-in-time.
    """
    sma_fast = feats["sma_fast"]
    sma_slow = feats["sma_slow"]
    rsi = feats["rsi"]
    roc_10 = feats["roc_10"]

    # Trend (0-40): how far fast SMA sits above slow SMA.
    trend = (((sma_fast / sma_slow) - 1.0) * 20.0 + 0.5).clip(0.0, 1.0) * 40.0

    # Momentum (0-30): RSI mapped so 40 -> 0, 70 -> full.
    momentum = ((rsi - 40.0) / 30.0).clip(0.0, 1.0) * 30.0

    # Rate of change (0-30): 10-bar return, 0% -> neutral.
    roc_component = ((roc_10 / 10.0) + 0.5).clip(0.0, 1.0) * 30.0

    score = trend + momentum + roc_component

    # Undefined until every input is warm.
    valid = sma_slow.notna() & rsi.notna() & roc_10.notna()
    return score.where(valid)
