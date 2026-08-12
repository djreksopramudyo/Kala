"""
Sentiment archive — the point-in-time record every sentiment source in
this project has been missing until now.

WHY THIS EXISTS
----------------
``kala/news.py``'s own module docstring says it plainly: sentiment is
UNBACKTESTABLE because there is no point-in-time archive of what a
scraper would have returned on any historical date. That's not a
permanent law of nature — it's true only because nothing has ever STORED
a reading. This module is the fix: run it daily (see
``archive_sentiment.py``) and, months from now, there IS a real archive
to walk-forward test against — the same "fetch once, store every reading,
stop re-deriving history you already have" idea as
``kala.warehouse`` for OHLCV price bars, applied to sentiment
instead.

Until that archive spans enough real calendar time to build real
walk-forward folds (a year or more, realistically — ``coverage_days``
tells you exactly how far along you are), nothing here should be treated
as validated. It's infrastructure for BECOMING testable later, not a
signal today. Sentiment stays advisory-only (see news.py) regardless of
how much history accumulates.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sentiment (
    ticker      TEXT NOT NULL,
    date        TEXT NOT NULL,   -- ISO YYYY-MM-DD, the day this reading was TAKEN
    source      TEXT NOT NULL,   -- e.g. "news", "reddit"
    score       REAL NOT NULL,   -- 0-100, same scale as news.get_news_sentiment
    count       INTEGER NOT NULL,
    description TEXT NOT NULL,
    PRIMARY KEY (ticker, date, source)
);
CREATE INDEX IF NOT EXISTS idx_sentiment_ticker_date ON sentiment(ticker, date);
"""


class SentimentArchive:
    """One SQLite file. Same one-connection-per-call pattern as
    ``kala.warehouse.Warehouse`` — this project's usage (a daily
    cron-style script) never has concurrent writers to worry about."""

    def __init__(self, db_path: str | Path = "results/sentiment.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def record(self, ticker: str, date: str, source: str, score: float,
              count: int, description: str) -> None:
        """Store (or overwrite) today's reading for (ticker, source). A
        same-day re-run replaces yesterday's-run-today's-value rather than
        duplicating — the archive tracks one reading per ticker/source/day,
        not every individual poll."""
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO sentiment "
                "(ticker, date, source, score, count, description) VALUES (?, ?, ?, ?, ?, ?)",
                (ticker, date, source, float(score), int(count), description))

    def history(self, ticker: str, source: str | None = None,
               start: str | None = None, end: str | None = None) -> list[dict]:
        """Archived readings for ``ticker``, oldest first. Filter to one
        ``source`` and/or a date range; omit either to get everything."""
        query = "SELECT date, source, score, count, description FROM sentiment WHERE ticker = ?"
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
        return [{"date": r[0], "source": r[1], "score": r[2], "count": r[3], "description": r[4]}
               for r in rows]

    def coverage_days(self, ticker: str, source: str | None = None) -> int:
        """How many distinct calendar days of archived readings exist for
        this ticker — the honest 'how close to walk-forward-testable are
        we' number. 0 means nothing archived yet."""
        query = "SELECT COUNT(DISTINCT date) FROM sentiment WHERE ticker = ?"
        params: list = [ticker]
        if source:
            query += " AND source = ?"
            params.append(source)
        with self._connect() as conn:
            return int(conn.execute(query, params).fetchone()[0])

    def tickers(self) -> list[str]:
        with self._connect() as conn:
            return sorted(r[0] for r in conn.execute("SELECT DISTINCT ticker FROM sentiment"))
