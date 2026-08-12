"""
SQLite broker-flow / foreign-flow archive — a local, vendor-agnostic store
for IDX "bandarmology" data (which brokers/foreign investors are net
buying or selling a stock).

WHY THIS EXISTS, AND WHY IT'S BUILT BEFORE PICKING A VENDOR
---------------------------------------------------------------
Same job as ``kala.warehouse`` does for OHLCV bars: fetch once,
store every row, stop re-downloading history on every run. The STORAGE
layer doesn't need to know or care whether the numbers came from Invezgo,
Sectors.app, or anything else — it only needs a canonical schema. That
means this module can be built and fully tested right now, before a
vendor is chosen or paid for; the only thing that has to wait for actual
API access is a small fetch/normalize adapter (a `fetch_fn` passed to
``get_or_fetch``, exactly the same shape ``run_walkforward.py``'s
``fetch()`` already uses for yfinance) that maps whichever vendor's JSON
response onto the columns below.

CANONICAL SCHEMA
-----------------
One row per (ticker, date, source):
  * foreign_net_value   (REQUIRED) — net foreign buy value in IDR,
    positive = net foreign buying, negative = net foreign selling. This
    is the one figure every bandarmology vendor is expected to expose,
    even a cheap/basic tier that doesn't break out the full buy/sell
    split.
  * foreign_buy_value, foreign_sell_value, foreign_net_volume
    (all OPTIONAL / nullable) — the fuller breakdown, when a vendor's
    plan includes it. Store None rather than 0 when a vendor doesn't
    report a field — 0 would silently claim "measured, no activity"
    when the truth is "not available," which is exactly the kind of
    NaN-vs-0 confusion this project has already been bitten by once
    (see kala/intraday.py's NaN-guard history).

``source`` records which vendor a row came from, so switching or
comparing vendors later doesn't require picking one to overwrite.

WHAT THIS DOES NOT DO
-----------------------
No claim about historical depth or point-in-time integrity of any given
vendor's data — that's a question for the vendor's own docs/support, not
something this storage layer can verify. No scoring/signal logic either;
see kala/strategies.py for where a broker-flow-based Strategy would
eventually be registered and walk-forward tested, once real data exists
to test it against. Until then this is infrastructure, not a signal —
same status every other new data source in this project starts at.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from .logging_util import log_swallowed

_SCHEMA = """
CREATE TABLE IF NOT EXISTS broker_flow (
    ticker              TEXT NOT NULL,
    date                TEXT NOT NULL,   -- ISO YYYY-MM-DD
    source              TEXT NOT NULL,   -- e.g. "invezgo", "sectors"
    foreign_net_value   REAL NOT NULL,
    foreign_buy_value   REAL,            -- nullable: not every vendor/tier reports this
    foreign_sell_value  REAL,            -- nullable
    foreign_net_volume  REAL,            -- nullable
    PRIMARY KEY (ticker, date, source)
);
CREATE INDEX IF NOT EXISTS idx_broker_flow_ticker_date ON broker_flow(ticker, date);
"""

_REQUIRED_COLUMNS = ("foreign_net_value",)
_OPTIONAL_COLUMNS = ("foreign_buy_value", "foreign_sell_value", "foreign_net_volume",
                     "foreign_top_broker_share")

# Added after the table already existed in the wild (e.g. an already-
# backfilled results/broker_flow.db) -- CREATE TABLE IF NOT EXISTS is a
# no-op against an existing table, so this column needs an explicit
# migration rather than just being in _SCHEMA. What fraction of the day's
# total |foreign net flow| came from the single most active broker (0-1) --
# a concentration/conviction signal distinct from foreign_net_value's
# direction, derived from the SAME already-fetched per-broker response
# (see kala.invezgo_fetch.fetch_daily_foreign_net), no extra API cost.
_MIGRATIONS = ("ALTER TABLE broker_flow ADD COLUMN foreign_top_broker_share REAL",)


class BrokerFlowArchive:
    """One SQLite file, one connection per call — same pattern as
    ``kala.warehouse.Warehouse`` and
    ``kala.sentiment_archive.SentimentArchive``."""

    def __init__(self, db_path: str | Path = "results/broker_flow.db"):
        self.db_path = Path(db_path)
        # sqlite creates the file on connect, so pointing this at a path that
        # does not exist silently produces a valid, EMPTY archive -- which then
        # reads exactly like "the vendor has no rows for these tickers". Record
        # which happened so callers can tell a missing archive from an empty
        # one instead of reporting a data outage as a strategy result.
        self.created_empty = not self.db_path.exists()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            self._migrate(conn)

    def row_count(self) -> int:
        """Total stored rows — 0 for a freshly created or emptied archive."""
        with self._connect() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM broker_flow").fetchone()[0])

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _migrate(self, conn: sqlite3.Connection) -> None:
        """Add any columns missing from an already-existing database file
        (CREATE TABLE IF NOT EXISTS is a no-op once the table exists, so a
        schema addition needs an explicit ALTER here or it silently never
        applies to a database created before this column existed)."""
        existing = {row[1] for row in conn.execute("PRAGMA table_info(broker_flow)")}
        for stmt in _MIGRATIONS:
            col = stmt.split("ADD COLUMN")[1].split()[0]
            if col not in existing:
                conn.execute(stmt)

    def upsert(self, ticker: str, source: str, df: pd.DataFrame) -> int:
        """Store every row in ``df`` (DatetimeIndex, column
        ``foreign_net_value`` required; ``foreign_buy_value`` /
        ``foreign_sell_value`` / ``foreign_net_volume`` /
        ``foreign_top_broker_share`` optional — missing optional columns
        are stored as NULL, not 0). Existing (ticker, date, source) rows
        are overwritten. Returns rows written; 0 (not an error) for an
        empty/None frame."""
        if df is None or len(df) == 0:
            return 0
        missing = [c for c in _REQUIRED_COLUMNS if c not in df.columns]
        if missing:
            raise ValueError(f"df missing required column(s): {missing}")

        def _val(row, col):
            if col not in df.columns:
                return None
            v = row[col]
            return None if pd.isna(v) else float(v)

        rows = [
            (ticker, idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)[:10],
             source, float(row["foreign_net_value"]),
             _val(row, "foreign_buy_value"), _val(row, "foreign_sell_value"),
             _val(row, "foreign_net_volume"), _val(row, "foreign_top_broker_share"))
            for idx, row in df.iterrows()
        ]
        with self._connect() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO broker_flow "
                "(ticker, date, source, foreign_net_value, foreign_buy_value, "
                "foreign_sell_value, foreign_net_volume, foreign_top_broker_share) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
        return len(rows)

    def read(self, ticker: str, source: str | None = None,
            start: str | None = None, end: str | None = None) -> pd.DataFrame | None:
        """Rows for ``ticker`` in [start, end] (inclusive, ISO strings),
        or None if nothing is stored in that range. If ``source`` is
        omitted and more than one vendor has rows for this ticker, ALL of
        them come back (distinguishable via the returned 'source'
        column) — callers that need exactly one vendor's numbers must
        pass ``source`` explicitly."""
        query = ("SELECT date, source, foreign_net_value, foreign_buy_value, "
                 "foreign_sell_value, foreign_net_volume, foreign_top_broker_share "
                 "FROM broker_flow WHERE ticker = ?")
        params: list = [ticker]
        if source:
            query += " AND source = ?"
            params.append(source)
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
        df = pd.DataFrame(rows, columns=["date", "source", "foreign_net_value",
                                         "foreign_buy_value", "foreign_sell_value",
                                         "foreign_net_volume", "foreign_top_broker_share"])
        df.index = pd.DatetimeIndex(df.pop("date"))
        return df

    def covered_range(self, ticker: str, source: str | None = None) -> tuple[str, str] | None:
        """(earliest_date, latest_date) stored for ``ticker``, or None if
        nothing is stored. Does NOT guarantee no gaps in between — same
        honest limitation as Warehouse.covered_range."""
        query = "SELECT MIN(date), MAX(date) FROM broker_flow WHERE ticker = ?"
        params: list = [ticker]
        if source:
            query += " AND source = ?"
            params.append(source)
        with self._connect() as conn:
            row = conn.execute(query, params).fetchone()
        return (row[0], row[1]) if row and row[0] else None

    def tickers(self) -> list[str]:
        with self._connect() as conn:
            return sorted(r[0] for r in conn.execute("SELECT DISTINCT ticker FROM broker_flow"))

    def get_or_fetch(self, ticker: str, source: str, start: str, end: str,
                     fetch_fn) -> pd.DataFrame | None:
        """The main entry point once a vendor adapter exists: return
        [start, end] for ``ticker``/``source``, fetching from
        ``fetch_fn(ticker, start, end)`` only when not already covered,
        then caching what came back. ``fetch_fn`` is where a vendor's API
        response gets normalized onto this module's canonical columns --
        the one piece that's genuinely vendor-specific. Same conservative
        coverage check and same graceful degrade-to-cached-partial
        behavior as Warehouse.get_or_fetch."""
        covered = self.covered_range(ticker, source=source)
        if covered and covered[0] <= start and covered[1] >= end:
            cached = self.read(ticker, source=source, start=start, end=end)
            if cached is not None and len(cached):
                return cached

        try:
            fresh = fetch_fn(ticker, start, end)
        except Exception as e:
            log_swallowed(f"BrokerFlowArchive.get_or_fetch({ticker}, {source})", e)
            fresh = None

        if fresh is not None and len(fresh):
            self.upsert(ticker, source, fresh)
            return fresh
        return self.read(ticker, source=source, start=start, end=end)
