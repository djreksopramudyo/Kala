"""
Trend-vs-range classifier — a DIFFERENT regime signal from ``regime.py``.

``regime.py`` classifies the BENCHMARK (^JKSE) as bullish/bearish via
SMA20/SMA50 -- direction. This module classifies a single TICKER's own
price action as trending or ranging via ADX -- strength/choppiness,
regardless of direction. A stock can be in a range-bound BULL market
(direction up, but choppy, low-ADX) where momentum entries whipsaw just as
easily as in a bear range. Two independent axes, both worth an entry
filter.

ADX conventions (Wilder): >=25 = trending, <20 = ranging/choppy,
20-25 = transitional. Same point-in-time discipline as regime.py: ADX at
bar *t* only ever looks at bars up to and including *t*.
"""

from __future__ import annotations

import pandas as pd

from . import indicators as ind

TRENDING = "TRENDING"
TRANSITIONAL = "TRANSITIONAL"
RANGING = "RANGING"


def classify_trend_range(high: pd.Series, low: pd.Series, close: pd.Series,
                         period: int = 14, trend_adx: float = 25.0,
                         range_adx: float = 20.0) -> pd.Series:
    """Per-bar TRENDING / TRANSITIONAL / RANGING classification from this
    ticker's own ADX. Bars before ADX is warm read as TRANSITIONAL (neither
    a trend nor range veto should fire on insufficient history)."""
    adx_val = ind.adx(high, low, close, period)["adx"]
    status = pd.Series(TRANSITIONAL, index=close.index, dtype=object)
    status[adx_val >= trend_adx] = TRENDING
    status[adx_val < range_adx] = RANGING
    status[adx_val.isna()] = TRANSITIONAL
    return status
