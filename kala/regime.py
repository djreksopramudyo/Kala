"""
Point-in-time IHSG/JCI market-regime classification.

This rule set used to live only inline in the legacy
``kala_daily_trader.check_market_health`` (Close vs SMA20/SMA50 of the
benchmark index). It's the single source of truth the live bot and papertrade
paths already use to compute the ``market_status`` that feeds
``entries.evaluate_entry``'s ``block_buys_in_bear`` veto. Centralising it here
lets the backtest/walk-forward engine evaluate that same veto instead of
silently skipping it (see ``BacktestConfig.apply_entry_vetoes``).

Every value at bar *t* depends only on benchmark data up to and including
bar *t* (trailing rolling means, no centering) — same point-in-time
discipline as the rest of the engine.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

STATUSES = ("BULLISH", "MODERATE_BULL", "NEUTRAL", "BEARISH", "MODERATE_BEAR")

# Two very different things used to share the string 'UNKNOWN', and the entry
# veto could not tell them apart:
#
#   UNKNOWN     — "not knowable YET". Emitted below for bars before SMA50 is
#                 warm. There is no bear tape to miss because there is not yet
#                 enough benchmark history to classify one. Failing OPEN is
#                 correct: otherwise early history would spuriously veto every
#                 candidate.
#
#   UNAVAILABLE — "we TRIED to look and failed". Emitted only by the live
#                 ``check_market_health`` when the ^JKSE download errors or
#                 returns too few bars. The market has a real regime right now;
#                 we just could not see it, and it may be exactly the bear tape
#                 ``block_buys_in_bear`` exists to block. Failing open here
#                 turns a network blip into a silent green light.
#
# ``classify_market_regime`` never emits UNAVAILABLE, so every backtest and
# walk-forward number is unchanged by this distinction — it is a live-path
# sentinel only.
UNAVAILABLE = "UNAVAILABLE"


def classify_market_regime(benchmark: pd.DataFrame) -> pd.Series:
    """Per-bar regime status for a benchmark OHLCV frame (e.g. ^JKSE).

    Mirrors the legacy if/elif chain exactly (evaluated in order):
        Close > SMA20 > SMA50                  -> BULLISH
        Close > SMA20 (but not the above)       -> MODERATE_BULL
        Close > SMA50 (but not the above)       -> NEUTRAL
        Close < SMA20 < SMA50                   -> BEARISH
        otherwise                               -> MODERATE_BEAR

    Bars before SMA50 is warm are 'UNKNOWN' — never treated as a bear status,
    so early history can't spuriously veto every candidate.
    """
    close = benchmark["Close"]
    sma20 = close.rolling(20).mean()
    sma50 = close.rolling(50).mean()

    conditions = [
        (close > sma20) & (sma20 > sma50),
        (close > sma20),
        (close > sma50),
        (close < sma20) & (sma20 < sma50),
    ]
    choices = ["BULLISH", "MODERATE_BULL", "NEUTRAL", "BEARISH"]
    status = np.select(conditions, choices, default="MODERATE_BEAR")
    status = pd.Series(status, index=close.index, dtype=object)
    status[sma50.isna()] = "UNKNOWN"
    return status


def regime_at(regime: pd.Series | None, date) -> str | None:
    """Point-in-time lookup: the latest known regime at or before ``date``.

    Uses ``asof`` so a ticker's trading calendar need not exactly match the
    benchmark's (holidays, delistings, etc.) without ever looking ahead.
    Returns None if there's no regime series, or no benchmark data yet at
    ``date`` (e.g. a ticker with history predating the benchmark fetch).
    """
    if regime is None or len(regime) == 0:
        return None
    val = regime.asof(date)
    if val != val:  # NaN: date is before the first available benchmark bar
        return None
    return str(val)
