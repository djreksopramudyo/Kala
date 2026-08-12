#!/usr/bin/env python3
"""Re-fetch ONLY the missing (ticker, date) cells in the broker-flow archive.

WHY A TARGETED FILL AND NOT A FRESH BACKFILL
--------------------------------------------
fetch_daily_foreign_net costs one API call PER DAY PER TICKER, so re-running a
2-year backfill over the whole cohort is ~15,000 calls against a 30,000/month
budget. The archive does not need that: measured on results/broker_flow.db the
32 full-span tickers sit at 96.7% coverage, so only ~500 cells are actually
missing. This fills those and leaves everything else untouched.

MARKET HOLIDAYS ARE NOT GAPS
-----------------------------
A date absent for EVERY ticker is an IDX holiday, not a fetch failure — 47 of
them in the Aug-2024..Jul-2026 window. Re-fetching those burns calls to
re-learn that the market was closed, and the API returns nothing anyway. They
are excluded by default (--include-holidays to override).

Requires KALA_INVEZGO_TOKEN. Start with --dry-run: it reports exactly what
would be fetched, and costs nothing.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys

import pandas as pd

from kala.broker_flow_archive import BrokerFlowArchive
from kala.invezgo_fetch import InvezgoClient, fetch_daily_foreign_net

HOLIDAY_THRESHOLD = 1.0   # absent for this fraction of tickers -> market holiday


def find_gaps(db_path: str, source: str = "invezgo",
              min_span_bdays: int = 400, include_holidays: bool = False):
    """Missing (ticker, date) cells, market holidays excluded by default.

    Returns (gaps, holidays, per_ticker_coverage)."""
    con = sqlite3.connect(db_path)
    df = pd.read_sql("SELECT ticker, date FROM broker_flow WHERE source = ?",
                     con, params=[source], parse_dates=["date"])
    con.close()
    if df.empty:
        return {}, [], {}

    present = {tk: set(g["date"]) for tk, g in df.groupby("ticker")}
    spans = {}
    for tk, dates in present.items():
        span = pd.bdate_range(min(dates), max(dates))
        if len(span) >= min_span_bdays:
            spans[tk] = span
    if not spans:
        return {}, [], {}

    window = pd.bdate_range(min(s[0] for s in spans.values()),
                            max(s[-1] for s in spans.values()))
    cohort = list(spans)

    holidays = []
    for d in window:
        absent = sum(1 for tk in cohort if d not in present[tk])
        if absent >= HOLIDAY_THRESHOLD * len(cohort):
            holidays.append(d)
    skip = set() if include_holidays else set(holidays)

    gaps = {}
    for tk in cohort:
        miss = [d for d in spans[tk] if d not in present[tk] and d not in skip]
        if miss:
            gaps[tk] = miss

    trading = [d for d in window if d not in set(holidays)]
    cov = {tk: sum(1 for d in trading if d in present[tk]) / len(trading) for tk in cohort}
    return gaps, holidays, cov


def _contiguous(dates):
    """Group consecutive business days so one call can cover a run."""
    runs, cur = [], [dates[0]]
    for prev, d in zip(dates, dates[1:]):
        if len(pd.bdate_range(prev, d)) == 2:
            cur.append(d)
        else:
            runs.append(cur); cur = [d]
    runs.append(cur)
    return runs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="results/broker_flow.db")
    ap.add_argument("--source", default="invezgo")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would be fetched; makes no API calls")
    ap.add_argument("--include-holidays", action="store_true",
                    help="also re-fetch dates absent for every ticker (usually pointless)")
    ap.add_argument("--max-calls", type=int, default=2000,
                    help="hard ceiling on API calls; refuses to start above it")
    ap.add_argument("--tickers", nargs="*", default=None)
    args = ap.parse_args()

    gaps, holidays, cov = find_gaps(args.db, args.source,
                                    include_holidays=args.include_holidays)
    if args.tickers:
        gaps = {t: d for t, d in gaps.items() if t in set(args.tickers)}

    if not gaps:
        print("No gaps to fill — archive is complete over its stored span.")
        return 0

    total = sum(len(v) for v in gaps.values())
    print(f"archive        : {args.db}")
    print(f"market holidays excluded: {len(holidays)}")
    print(f"tickers with gaps       : {len(gaps)}")
    print(f"missing (ticker,date) cells: {total}   <- one API call each")
    worst = sorted(cov.items(), key=lambda kv: kv[1])[:5]
    print("worst-covered tickers    : " +
          ", ".join(f"{t} {c*100:.1f}%" for t, c in worst))

    if args.dry_run:
        print("\n--dry-run: nothing fetched. Re-run without it to fill these.")
        for tk, days in sorted(gaps.items(), key=lambda kv: -len(kv[1]))[:10]:
            runs = _contiguous(days)
            print(f"  {tk:<10} {len(days):>4} day(s) in {len(runs)} run(s); "
                  f"first {days[0].date()} last {days[-1].date()}")
        return 0

    if total > args.max_calls:
        print(f"\nREFUSING: {total} calls exceeds --max-calls={args.max_calls}. "
              "Raise it deliberately, or narrow with --tickers.")
        return 2

    if not os.environ.get("KALA_INVEZGO_TOKEN", "").strip():
        print("\nKALA_INVEZGO_TOKEN is not set — cannot fetch.", file=sys.stderr)
        return 1

    archive = BrokerFlowArchive(args.db)
    client = InvezgoClient()
    filled = still_missing = 0

    for tk, days in sorted(gaps.items()):
        for run in _contiguous(days):
            start, end = run[0].strftime("%Y-%m-%d"), run[-1].strftime("%Y-%m-%d")
            got = fetch_daily_foreign_net(tk, start, end, client=client)
            if got is not None and len(got):
                archive.upsert(tk, args.source, got)
                filled += len(got)
                still_missing += len(run) - len(got)
            else:
                still_missing += len(run)
        print(f"  {tk:<10} done ({filled} filled so far)")

    print(f"\nfilled {filled} cell(s); {still_missing} still absent "
          "(genuinely no data, or still failing — re-run to retry).")
    _, _, cov2 = find_gaps(args.db, args.source)
    if cov2:
        before = sum(cov.values()) / len(cov)
        after = sum(cov2.values()) / len(cov2)
        print(f"mean coverage {before*100:.1f}% -> {after*100:.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
