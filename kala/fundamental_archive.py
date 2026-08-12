"""
SQLite point-in-time fundamentals archive — dated snapshots of a company's
reported financial-statement line items, stored so that "what did we know
about FY2020 as of date X" is answerable, and so restatements can be
detected empirically.

WHY THIS EXISTS, AND WHY IT'S DIFFERENT FROM broker_flow_archive
-----------------------------------------------------------------
Same "fetch once, store, stop re-downloading" job as ``kala.warehouse``
(OHLCV) and ``kala.broker_flow_archive`` (bandarmology). But fundamentals
have a hazard those don't, and it's the whole reason
``kala/fundamental_screen.py`` is marked NOT walk-forward validated:

  A vendor's financial-statement endpoint returns "FY2020 as the vendor
  currently knows it." That is NOT necessarily "FY2020 as it was reported
  back in early 2021." Companies restate. Feeding a since-restated figure
  into a 2020 backtest is a look-ahead bug — the exact class of mistake
  this project already caught and retracted once (PROJECT_STATUS.md,
  "Retraction").

Invezgo's ``/analysis/financial-statement/{code}`` response was inspected
(see ``tests/fixtures/invezgo_financial_statement_bbca_is_*.json``) and
carries NO revision/amendment flag and NO filing/disclosure date — the
complete field set is ``amount, col, columns, display_order, id,
is_abstract, level, name, parent_id, period, rows, values, year``. So the
vendor gives us no way, from a single pull, to tell an original figure
from a restated one, nor when a figure became public. Both point-in-time
hazards therefore have to be handled HERE, by us:

  1. RESTATEMENT — solved by making the OBSERVED date (the date WE pulled
     the data) part of the primary key, so pulling "FY2020" today and
     again in three months produces two coexisting dated rows.
     ``diff_observations`` then reports exactly which line items changed
     between two snapshots: a non-empty diff means the vendor restates
     and is NOT point-in-time safe for those periods. (This test needs
     calendar time to pass between two real pulls — it cannot be answered
     from a single session. Archiving now is what makes it answerable
     later. Same "archive daily so it's backtestable eventually" logic as
     ``kala.sentiment_archive``.)

  2. REPORTING LAG — solved by ``as_of``, which only ever returns the
     latest snapshot we actually OBSERVED on or before a given date. A
     backtest at 2020-12-31 can't see a snapshot first pulled in 2021, so
     it can't accidentally use FY2020 figures that weren't public yet.
     (The vendor gives no filing date, so a strategy still has to assume a
     conservative reporting lag on top of this; ``as_of`` guarantees you
     never read a snapshot from the future, which is the load-bearing half.)

CANONICAL SCHEMA
-----------------
One row per (ticker, statement, source, fiscal_year, period, line_item,
observed_date) — long format, one financial-statement CELL per row:
  * fiscal_year (INTEGER) + period (TEXT: FY / Q1..Q4) — which reporting
    period the figure is FOR.
  * line_item_id (TEXT) — the vendor's stable id hash for the line item
    (unique within a statement); line_item (TEXT) — its human-readable
    name, denormalized alongside for convenience.
  * amount (REAL, NULLABLE) — the reported figure. NULL means the cell was
    genuinely absent from the response; an explicit 0 the vendor sent is
    stored as 0.0, NOT collapsed to NULL (the same NaN-vs-0 discipline the
    broker-flow schema is built on).
  * observed_date (TEXT, in the PK) — ISO YYYY-MM-DD, the date WE pulled
    this. The one field that makes point-in-time integrity checkable.

WHAT THIS DOES NOT DO
-----------------------
No signal/scoring logic (that's ``kala/fundamental_screen.py``, which ranks
CURRENT snapshots only and says so). No claim that the data IS point-in-time
safe — this module is the instrument for FINDING OUT, not a certificate that
the answer is yes. Until ``diff_observations`` has been run across snapshots
taken weeks/months apart and comes back clean, a fundamental strategy fed
from this archive stays UNVALIDATED, same status every new data source in
this project starts at.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from .logging_util import log_swallowed

_SCHEMA = """
CREATE TABLE IF NOT EXISTS fundamentals (
    ticker         TEXT NOT NULL,
    statement      TEXT NOT NULL,   -- BS / IS / CF
    source         TEXT NOT NULL,   -- e.g. "invezgo"
    fiscal_year    INTEGER NOT NULL,
    period         TEXT NOT NULL,   -- FY / Q1 / Q2 / Q3 / Q4
    line_item_id   TEXT NOT NULL,   -- vendor's stable id for the line item
    line_item      TEXT NOT NULL,   -- human-readable name (denormalized)
    amount         REAL,            -- nullable: NULL = absent, 0.0 = vendor reported 0
    observed_date  TEXT NOT NULL,   -- ISO YYYY-MM-DD, the date WE pulled this
    PRIMARY KEY (ticker, statement, source, fiscal_year, period, line_item_id, observed_date)
);
CREATE INDEX IF NOT EXISTS idx_fundamentals_lookup
    ON fundamentals(ticker, statement, source, observed_date);
"""

_REQUIRED_COLUMNS = ("fiscal_year", "period", "line_item_id", "line_item", "amount")

_READ_COLUMNS = ["fiscal_year", "period", "line_item_id", "line_item",
                 "amount", "observed_date"]


class FundamentalArchive:
    """One SQLite file, one connection per call — same pattern as
    ``kala.warehouse.Warehouse`` and ``kala.broker_flow_archive``."""

    def __init__(self, db_path: str | Path = "results/fundamentals.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def record(self, ticker: str, statement: str, source: str,
               observed_date: str, df: pd.DataFrame) -> int:
        """Store one dated snapshot: every line-item cell in ``df`` tagged
        with ``observed_date`` (the date this was pulled). ``df`` columns
        required: fiscal_year, period, line_item_id, line_item, amount
        (amount may be NaN -> stored NULL; an explicit 0 stays 0.0).
        Re-recording the SAME (…, observed_date) overwrites — recording the
        same period on a DIFFERENT observed_date adds a new coexisting
        snapshot (that's the whole point). Returns rows written; 0 (not an
        error) for an empty/None frame."""
        if df is None or len(df) == 0:
            return 0
        missing = [c for c in _REQUIRED_COLUMNS if c not in df.columns]
        if missing:
            raise ValueError(f"df missing required column(s): {missing}")

        rows = [
            (ticker, statement, source, int(row["fiscal_year"]), str(row["period"]),
             str(row["line_item_id"]), str(row["line_item"]),
             None if pd.isna(row["amount"]) else float(row["amount"]),
             observed_date)
            for _, row in df.iterrows()
        ]
        with self._connect() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO fundamentals "
                "(ticker, statement, source, fiscal_year, period, line_item_id, "
                "line_item, amount, observed_date) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
        return len(rows)

    def read(self, ticker: str, statement: str | None = None,
             source: str | None = None, observed_date: str | None = None) -> pd.DataFrame | None:
        """Raw rows for ``ticker`` (optionally narrowed by statement /
        source / a specific observed_date snapshot), or None if nothing
        matches. Returns long format with an ``observed_date`` column, so a
        caller that didn't pin ``observed_date`` can see which snapshot each
        row came from."""
        query = ("SELECT fiscal_year, period, line_item_id, line_item, amount, observed_date "
                 "FROM fundamentals WHERE ticker = ?")
        params: list = [ticker]
        if statement:
            query += " AND statement = ?"
            params.append(statement)
        if source:
            query += " AND source = ?"
            params.append(source)
        if observed_date:
            query += " AND observed_date = ?"
            params.append(observed_date)
        query += " ORDER BY fiscal_year, period, line_item_id"

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        if not rows:
            return None
        return pd.DataFrame(rows, columns=_READ_COLUMNS)

    def observed_dates(self, ticker: str, statement: str | None = None,
                       source: str | None = None) -> list[str]:
        """Distinct snapshot dates stored for ``ticker`` (ascending). The
        number of these, and how far apart they are, is exactly what
        governs whether ``diff_observations`` can say anything yet."""
        query = "SELECT DISTINCT observed_date FROM fundamentals WHERE ticker = ?"
        params: list = [ticker]
        if statement:
            query += " AND statement = ?"
            params.append(statement)
        if source:
            query += " AND source = ?"
            params.append(source)
        query += " ORDER BY observed_date"
        with self._connect() as conn:
            return [r[0] for r in conn.execute(query, params).fetchall()]

    def as_of(self, ticker: str, statement: str, source: str,
              as_of_date: str) -> pd.DataFrame | None:
        """POINT-IN-TIME READ: the latest snapshot we actually OBSERVED on
        or before ``as_of_date``, as long-format rows (fiscal_year, period,
        line_item_id, line_item, amount). None if we hadn't pulled anything
        for this ticker/statement/source by then — which is the correct
        answer for a backtest date before this archive started: we knew
        nothing yet, so we get nothing, never a figure from the future.

        NOTE this guarantees you never read a snapshot pulled AFTER
        ``as_of_date``; it does NOT by itself model reporting lag WITHIN a
        snapshot (the vendor ships no filing date), so a strategy should
        still refuse to act on a fiscal period until a conservative lag has
        elapsed. This is the load-bearing half of point-in-time safety, not
        the whole of it."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT MAX(observed_date) FROM fundamentals "
                "WHERE ticker = ? AND statement = ? AND source = ? AND observed_date <= ?",
                (ticker, statement, source, as_of_date)).fetchone()
        latest = row[0] if row else None
        if not latest:
            return None
        snap = self.read(ticker, statement=statement, source=source, observed_date=latest)
        if snap is None:
            return None
        return snap.drop(columns=["observed_date"])

    def diff_observations(self, ticker: str, statement: str, source: str,
                          before: str, after: str) -> pd.DataFrame:
        """RESTATEMENT DETECTOR: line items whose reported amount CHANGED
        between the ``before`` snapshot and the ``after`` snapshot, for the
        SAME (fiscal_year, period, line_item). An empty frame means the
        vendor reported those periods identically at both pull dates —
        evidence (not proof, until many periods/tickers agree) that the
        data is point-in-time stable. A non-empty frame means at least one
        historical figure was revised between pulls: that period is NOT
        safe to backtest as if the later figure was known at the earlier
        date.

        Only periods present in BOTH snapshots are compared — a fiscal
        period that simply appeared in the later pull (newer data) is not a
        restatement and is excluded. A cell going value<->NULL counts as a
        change. Columns: fiscal_year, period, line_item_id, line_item,
        amount_before, amount_after."""
        b = self.read(ticker, statement=statement, source=source, observed_date=before)
        a = self.read(ticker, statement=statement, source=source, observed_date=after)
        cols = ["fiscal_year", "period", "line_item_id", "line_item",
                "amount_before", "amount_after"]
        if b is None or a is None:
            return pd.DataFrame(columns=cols)

        key = ["fiscal_year", "period", "line_item_id"]
        merged = b.merge(a, on=key, suffixes=("_before", "_after"))
        if merged.empty:
            return pd.DataFrame(columns=cols)

        ab, aa = merged["amount_before"], merged["amount_after"]
        both_nan = ab.isna() & aa.isna()
        # unequal amounts, OR exactly one side NULL -> a change; NULL==NULL is not.
        changed = (~both_nan) & ((ab != aa) | (ab.isna() ^ aa.isna()))
        out = merged.loc[changed].copy()
        # line_item name follows the "after" snapshot (current label wins).
        out["line_item"] = out["line_item_after"]
        return out[cols].reset_index(drop=True)

    def tickers(self) -> list[str]:
        with self._connect() as conn:
            return sorted(r[0] for r in conn.execute("SELECT DISTINCT ticker FROM fundamentals"))

    def get_or_snapshot(self, ticker: str, statement: str, source: str,
                        observed_date: str, fetch_fn) -> pd.DataFrame | None:
        """Take today's snapshot for ``ticker``/``statement`` unless one was
        ALREADY recorded on ``observed_date`` (idempotent within a day — a
        re-run doesn't burn a second API call). ``fetch_fn(ticker,
        statement)`` returns the normalized long-format frame; failures are
        logged and degrade to whatever snapshot is already stored for that
        date (or None), never raised. Returns the snapshot as stored (no
        observed_date column)."""
        existing = self.read(ticker, statement=statement, source=source,
                             observed_date=observed_date)
        if existing is not None and len(existing):
            return existing.drop(columns=["observed_date"])
        try:
            fresh = fetch_fn(ticker, statement)
        except Exception as e:
            log_swallowed(f"FundamentalArchive.get_or_snapshot({ticker}, {statement})", e)
            fresh = None
        if fresh is not None and len(fresh):
            self.record(ticker, statement, source, observed_date, fresh)
            return fresh
        again = self.read(ticker, statement=statement, source=source,
                         observed_date=observed_date)
        return again.drop(columns=["observed_date"]) if again is not None else None
