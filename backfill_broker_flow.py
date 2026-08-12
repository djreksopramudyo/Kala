"""
Backfill kala.broker_flow_archive with real Invezgo foreign-flow data.

Costs ONE API call per ticker per business day (confirmed in
BROKER_FLOW_DATA_SPEC.md — the summary endpoint aggregates over from/to
rather than returning a daily series, so daily granularity needs from==to).
This script is budget-aware and resumable:

  * ``--max-requests`` caps how many calls THIS RUN makes (default 900,
    comfortably under Invezgo's 250 req/min and leaving headroom in a
    30,000 req/month Advance-tier budget for other work). It stops
    starting new tickers once the next one's uncovered days wouldn't fit
    -- it does not cut a ticker off mid-fetch.
  * Already-covered (ticker, date) ranges are skipped via
    BrokerFlowArchive.covered_range, so re-running this script daily/weekly
    as your monthly budget refills only spends calls on what's actually
    missing -- same resumable spirit as run_walkforward.py's --warehouse.

Usage:
    $env:KALA_INVEZGO_TOKEN = "..."
    python backfill_broker_flow.py --tickers BBCA.JK ANTM.JK --start 2024-12-01 --end 2024-12-31
    python backfill_broker_flow.py --max-tickers 40 --start 2025-01-01 --end 2025-01-31
    python backfill_broker_flow.py --max-tickers 40 --start 2025-01-01 --end 2025-01-31 --max-requests 900

Network access happens ONLY here — kala.invezgo_fetch's functions are
pure once given a client, same separation run_walkforward.py uses for yfinance.
"""

from __future__ import annotations

import argparse
import sys

import pandas as pd

from kala.broker_flow_archive import BrokerFlowArchive
from kala.invezgo_fetch import SOURCE, InvezgoClient, fetch_daily_foreign_net
from kala.universe import ALL_SHARIA_STOCKS


class _CountingClient:
    """Wraps an InvezgoClient, counting broker_summary calls so the backfill
    loop can stop before blowing the per-run request budget."""

    def __init__(self, inner: InvezgoClient):
        self.inner = inner
        self.n = 0

    def broker_summary(self, *args, **kwargs):
        self.n += 1
        return self.inner.broker_summary(*args, **kwargs)


def _uncovered_business_days(archive: BrokerFlowArchive, ticker: str,
                             start: str, end: str) -> int:
    """How many business days in [start, end] this ticker is NOT already
    covered for (source='invezgo') -- the actual call cost of backfilling
    it. Conservative: if there's ANY gap, this returns the full day count
    rather than trying to find exact holes (covered_range only gives
    min/max, same honest limitation Warehouse.covered_range documents)."""
    total_days = len(pd.bdate_range(start, end))
    covered = archive.covered_range(ticker, source=SOURCE)
    if covered and covered[0] <= start and covered[1] >= end:
        return 0
    return total_days


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tickers", nargs="*", default=None,
                    help="explicit ticker list; default = evenly spaced sample of the universe")
    ap.add_argument("--max-tickers", type=int, default=40,
                    help="sample size when --tickers not given (default 40 -- roughly what "
                         "fits a 30,000 req/month budget for one month of daily coverage)")
    ap.add_argument("--start", required=True, help="ISO start date, e.g. 2024-12-01")
    ap.add_argument("--end", required=True, help="ISO end date, e.g. 2024-12-31")
    ap.add_argument("--db", default="results/broker_flow.db",
                    help="BrokerFlowArchive SQLite path (default results/broker_flow.db)")
    ap.add_argument("--max-requests", type=int, default=900,
                    help="cap on API calls THIS RUN makes (default 900); stops starting new "
                         "tickers once the next one wouldn't fit in what's left")
    ap.add_argument("--investor", default="f", choices=["all", "f", "d"],
                    help="Invezgo investor filter (default f = foreign)")
    args = ap.parse_args()

    try:
        client = InvezgoClient()
        if not client.token:
            raise RuntimeError
    except Exception:
        print("No KALA_INVEZGO_TOKEN set — export/$env: it before running.", file=sys.stderr)
        return 1
    counting = _CountingClient(client)

    if args.tickers:
        tickers = args.tickers
    else:
        step = max(1, len(ALL_SHARIA_STOCKS) // args.max_tickers)
        tickers = ALL_SHARIA_STOCKS[::step][:args.max_tickers]

    archive = BrokerFlowArchive(args.db)

    print(f"Backfilling {len(tickers)} candidate ticker(s), {args.start}..{args.end}, "
         f"investor={args.investor}, budget={args.max_requests} req")

    done, skipped_full, skipped_budget = 0, 0, 0
    for ticker in tickers:
        cost = _uncovered_business_days(archive, ticker, args.start, args.end)
        if cost == 0:
            skipped_full += 1
            continue
        if counting.n + cost > args.max_requests:
            skipped_budget += 1
            continue

        df = fetch_daily_foreign_net(ticker, args.start, args.end,
                                     client=counting, investor=args.investor)
        if df is not None and len(df):
            n = archive.upsert(ticker, SOURCE, df)
            print(f"  {ticker}: {n} row(s) upserted ({counting.n} req used so far)")
            done += 1
        else:
            print(f"  {ticker}: no data returned ({counting.n} req used so far)")

    print(f"\nDone: {done} ticker(s) fetched, {skipped_full} already fully covered, "
         f"{skipped_budget} skipped (would exceed budget), {counting.n} request(s) used.")
    if skipped_budget:
        print("Re-run this same command later (once your monthly quota refills) to pick up "
             "the skipped tickers — already-covered ones won't re-cost anything.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
