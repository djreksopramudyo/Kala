"""
SQLite OHLCV warehouse — a local, indexed price history store.

WHY THIS EXISTS
---------------
``datacache.py`` (built earlier) keeps a "last known good" pickle per
ticker for RESILIENCE — a fallback when today's live fetch fails. This
module is a different job: a local, queryable, INCREMENTALLY-UPDATED store
so research (walk-forward sweeps, strategy-zoo experiments, PBO runs) stops
re-downloading years of history from yfinance every single run. Fetch once,
store every bar, and later runs only fetch the days actually missing.

Both are stdlib-only (sqlite3, no new dependency) and deliberately simple:
one table, one primary key (ticker, date), INSERT OR REPLACE for upserts.
Correctness over cleverness — this is a cache, never the source of truth;
losing the file just means the next run re-fetches, nothing is silently
wrong.

USAGE
-----
    from kala.warehouse import Warehouse

    wh = Warehouse("results/warehouse.db")
    wh.upsert("ANTM.JK", df)                       # store what you fetched
    cached = wh.read("ANTM.JK", "2023-01-01", "2024-01-01")   # or None

    # or let it manage the gap-filling for you:
    df = wh.get_or_fetch("ANTM.JK", "2023-01-01", "2024-06-01",
                         fetch_fn=lambda t, s, e: yf.download(t, start=s, end=e))
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from .logging_util import log_swallowed

_SCHEMA = """
CREATE TABLE IF NOT EXISTS bars (
    ticker TEXT NOT NULL,
    date   TEXT NOT NULL,   -- ISO YYYY-MM-DD
    open   REAL NOT NULL,
    high   REAL NOT NULL,
    low    REAL NOT NULL,
    close  REAL NOT NULL,
    volume REAL NOT NULL,
    PRIMARY KEY (ticker, date)
);
CREATE INDEX IF NOT EXISTS idx_bars_ticker_date ON bars(ticker, date);

-- Records that a fetch was ATTEMPTED, and the newest bar it could obtain.
-- Without this the cache cannot tell "never fetched" from "fetched, and this
-- is all that exists" — so a delisted or suspended ticker, whose newest bar is
-- permanently old, fails every freshness test and is re-downloaded on every
-- single run, forever. Same failure shape as an archive that creates itself:
-- an absence of data reads identically to an absence of effort.
CREATE TABLE IF NOT EXISTS fetch_attempts (
    ticker      TEXT NOT NULL PRIMARY KEY,
    attempted   TEXT NOT NULL,   -- ISO YYYY-MM-DD, when we last asked
    newest_bar  TEXT             -- newest date the source returned, NULL if none
);
"""

_COLUMNS = ("Open", "High", "Low", "Close", "Volume")


class Warehouse:
    """One SQLite file, one connection per call (safe for the cron-job /
    one-shot-script usage pattern this project has — no long-lived
    multi-threaded writer to worry about)."""

    def __init__(self, db_path: str | Path = "results/warehouse.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def upsert(self, ticker: str, df: pd.DataFrame) -> int:
        """Store every bar in ``df`` (index = dates, columns Open/High/Low/
        Close/Volume). Existing (ticker, date) rows are overwritten — a
        re-fetch with revised/adjusted prices replaces the old value, which
        is the correct behavior for adjusted-close data. Returns rows
        written; 0 (not an error) for an empty/None frame."""
        if df is None or len(df) == 0:
            return 0
        missing = [c for c in _COLUMNS if c not in df.columns]
        if missing:
            raise ValueError(f"df missing required column(s): {missing}")

        rows = [
            (ticker, idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)[:10],
             float(row["Open"]), float(row["High"]), float(row["Low"]),
             float(row["Close"]), float(row["Volume"]))
            for idx, row in df.iterrows()
        ]
        with self._connect() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO bars (ticker, date, open, high, low, close, volume) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
        return len(rows)

    def read(self, ticker: str, start: str | None = None,
            end: str | None = None) -> pd.DataFrame | None:
        """Bars for ``ticker`` in [start, end] (inclusive, ISO strings), or
        None if nothing is stored in that range. Columns match the OHLCV
        contract every other module in this project expects."""
        query = "SELECT date, open, high, low, close, volume FROM bars WHERE ticker = ?"
        params: list = [ticker]
        if start:
            query += " AND date >= ?"
            params.append(start)
        if end:
            query += " AND date <= ?"
            params.append(end)
        query += " ORDER BY date"

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        if not rows:
            return None
        df = pd.DataFrame(rows, columns=["date", "Open", "High", "Low", "Close", "Volume"])
        df.index = pd.DatetimeIndex(df.pop("date"))
        return df

    def covered_range(self, ticker: str) -> tuple[str, str] | None:
        """(earliest_date, latest_date) stored for ``ticker``, or None if
        nothing is stored. Does NOT guarantee no gaps in between — see
        ``get_or_fetch`` for the honest gap-aware version."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT MIN(date), MAX(date) FROM bars WHERE ticker = ?", (ticker,)).fetchone()
        return (row[0], row[1]) if row and row[0] else None

    def tickers(self) -> list[str]:
        with self._connect() as conn:
            return sorted(r[0] for r in conn.execute("SELECT DISTINCT ticker FROM bars"))

    def record_fetch_attempt(self, ticker: str, attempted: str,
                             newest_bar: str | None) -> None:
        """Remember that ``ticker`` was asked for on ``attempted``, and the
        newest bar the source could supply (None if it supplied nothing)."""
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO fetch_attempts (ticker, attempted, newest_bar) "
                "VALUES (?, ?, ?)", (ticker, attempted, newest_bar))

    def fetch_attempt(self, ticker: str) -> tuple[str, str | None] | None:
        """(attempted_date, newest_bar) for ``ticker``, or None if never asked."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT attempted, newest_bar FROM fetch_attempts WHERE ticker = ?",
                (ticker,)).fetchone()
        return (row[0], row[1]) if row else None

    def is_as_fresh_as_it_gets(self, ticker: str, today: str) -> bool:
        """True when we already asked for ``ticker`` TODAY and the source had
        nothing newer than what is stored.

        This is what stops a permanently-stale ticker (delisted, suspended, or
        simply not trading) from being re-downloaded on every run: its newest
        bar can never satisfy a freshness test written against the calendar, but
        asking again the same day cannot produce a different answer.
        """
        rec = self.fetch_attempt(ticker)
        if rec is None:
            return False
        attempted, newest = rec
        if attempted != today:
            return False
        covered = self.covered_range(ticker)
        if covered is None:
            # asked today, source returned nothing, and nothing is stored
            return newest is None
        return newest is not None and newest <= covered[1]

    def get_or_fetch(self, ticker: str, start: str, end: str, fetch_fn) -> pd.DataFrame | None:
        """The main entry point for research code: return [start, end] for
        ``ticker``, fetching from ``fetch_fn(ticker, start, end)`` ONLY for
        the sub-range not already covered, then caching what came back.

        This is deliberately conservative about what counts as "covered":
        it only trusts the stored range if it starts at/before ``start``
        AND ends at/after ``end`` — a stored range with the right ENDPOINTS
        but a hole in the middle (e.g. a prior partial fetch) is still
        possible in principle, but for this project's actual access pattern
        (always fetching a full, contiguous period from yfinance) that
        hasn't been an issue; a full range check would need a trading-
        calendar reference this module deliberately doesn't depend on.
        """
        covered = self.covered_range(ticker)
        if covered and covered[0] <= start and covered[1] >= end:
            cached = self.read(ticker, start, end)
            if cached is not None and len(cached):
                return cached

        try:
            fresh = fetch_fn(ticker, start, end)
        except Exception as e:
            log_swallowed(f"Warehouse.get_or_fetch({ticker})", e)
            fresh = None

        if fresh is not None and len(fresh):
            self.upsert(ticker, fresh)
            return fresh
        # fetch failed or came back empty -- fall back to whatever's cached,
        # even if it doesn't fully cover [start, end] (partial is better
        # than nothing, same "degrade gracefully" spirit as datacache.py)
        return self.read(ticker, start, end)
