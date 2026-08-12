"""
Last-good EOD price cache — resilience against yfinance flakiness.

yfinance intermittently returns None / empty / a 403 (you've hit all three
this project). Without a fallback, a single transient failure makes a held
position show "no data", a scan return nothing, /status compute a wrong
equity. This module keeps the LAST SUCCESSFUL OHLCV frame per ticker on
disk and serves it when a live fetch fails, so a blip degrades gracefully
(slightly stale data + a logged note) instead of failing outright.

Deliberately dependency-free: pandas pickle, no parquet/pyarrow requirement.
The cache is a convenience, never a source of truth — a corrupt/unreadable
cache file is treated as a miss, never an error.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .logging_util import log_swallowed

CACHE_DIR = Path(__file__).resolve().parent.parent / "results" / "price_cache"

_REQUIRED = ("Open", "High", "Low", "Close", "Volume")

# How old a cached frame may be before it stops being "a blip's worth of
# stale" and becomes actively misleading. The cache exists to survive a
# transient yfinance failure — hours, or a day or two — not a month.
#
# Roughly the 5 trading days kala_daily_trader.STALE_DATA_DAYS already uses
# to flag a frozen ticker in the scan. That check protects the scan; this one
# protects everything ELSE that reads a price through the cache, above all
# _last_close() -> /rebalance and /buy, which had no age bound at all: a
# 47-day-old close was served as today's price and produced a fully
# populated, entirely confident rebalance plan.
DEFAULT_MAX_AGE_DAYS = 7


def _safe_name(ticker: str) -> str:
    return "".join(c if (c.isalnum() or c in ".-_^") else "_" for c in ticker)


def save_frame(ticker: str, df: pd.DataFrame, cache_dir: Path | None = None) -> None:
    """Persist a good OHLCV frame as this ticker's last-known-good snapshot.
    Never raises — a cache write failure must not break a live run."""
    if df is None or len(df) == 0:
        return
    d = Path(cache_dir) if cache_dir else CACHE_DIR
    try:
        d.mkdir(parents=True, exist_ok=True)
        df.to_pickle(d / f"{_safe_name(ticker)}.pkl")
    except Exception as e:
        log_swallowed(f"datacache.save_frame({ticker})", e)


def frame_age_days(df: pd.DataFrame, today=None) -> int | None:
    """Calendar days between ``df``'s last bar and ``today``, or None if that
    can't be determined. Tz-aware indexes are normalised so the subtraction
    can't raise on a mixed-awareness comparison."""
    if df is None or not len(df):
        return None
    try:
        last = pd.Timestamp(df.index[-1])
        if last.tzinfo is not None:
            last = last.tz_localize(None)
        now = pd.Timestamp(today) if today is not None else pd.Timestamp.today()
        if now.tzinfo is not None:
            now = now.tz_localize(None)
        return int((now.normalize() - last.normalize()).days)
    except Exception as e:
        log_swallowed("datacache.frame_age_days", e)
        return None


def load_frame(ticker: str, cache_dir: Path | None = None,
               max_age_days: int | None = None, today=None) -> pd.DataFrame | None:
    """Return the last-good frame for ``ticker``, or None on any miss/error
    (missing file, unreadable pickle, malformed frame). Never raises.

    ``max_age_days``: when given, a frame whose newest bar is older than this
    is treated as a MISS rather than served. Callers on a price path should
    always pass it (production ones get ``DEFAULT_MAX_AGE_DAYS`` via
    ``with_fallback``); it stays opt-in here so this remains a pure loader
    that a caller can use to inspect the cache regardless of age.

    Returning None on an over-age frame is deliberate: every price consumer
    already has a hardened "no price" path (plan_rebalance refuses to plan,
    the daily message flags the holding as unevaluated), and being told
    nothing is knowable beats being handed a month-old number that looks
    exactly like today's.
    """
    d = Path(cache_dir) if cache_dir else CACHE_DIR
    path = d / f"{_safe_name(ticker)}.pkl"
    if not path.exists():
        return None
    try:
        df = pd.read_pickle(path)
        if isinstance(df, pd.DataFrame) and all(c in df.columns for c in _REQUIRED) and len(df):
            if max_age_days is not None:
                age = frame_age_days(df, today=today)
                if age is None or age > max_age_days:
                    log_swallowed(
                        f"datacache: REFUSING cache for {ticker} — {age} days "
                        f"old (limit {max_age_days}); a stale price is worse "
                        f"than no price",
                        RuntimeError("cached frame exceeds max age"))
                    return None
            return df
    except Exception as e:
        log_swallowed(f"datacache.load_frame({ticker})", e)
    return None


def with_fallback(ticker: str, live: pd.DataFrame | None,
                  cache_dir: Path | None = None,
                  max_age_days: int | None = DEFAULT_MAX_AGE_DAYS,
                  today=None) -> pd.DataFrame | None:
    """Given the result of a live fetch, return it (and refresh the cache) if
    good, else fall back to the last-good cached frame (logged as stale).
    None when the live fetch misses AND the cache misses or is too old.

    The age bound is ON by default here — this is the resilience path, and
    resilience means surviving a blip, not silently trading on last month's
    prices."""
    if live is not None and len(live):
        save_frame(ticker, live, cache_dir)
        return live
    cached = load_frame(ticker, cache_dir, max_age_days=max_age_days, today=today)
    if cached is not None:
        log_swallowed(f"datacache: serving STALE cache for {ticker} "
                      f"(live fetch empty)", RuntimeError("live fetch returned no data"))
    return cached
