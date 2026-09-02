"""
Daily/periodic fundamentals archival — run this to lay down DATED snapshots
of companies' reported financial statements, building the point-in-time
history that ``kala/fundamental_screen.py`` needs but ``yfinance`` and (on a
single pull) Invezgo cannot provide.

WHY BOTHER, given the statements barely change day to day: the value isn't
the daily cadence, it's the DATE STAMP. Once you have the same fiscal period
pulled at two dates weeks/months apart, ``FundamentalArchive.diff_observations``
can finally answer the question blocking any fundamental backtest — does the
vendor restate history? — empirically instead of by assumption. See
``kala/fundamental_archive.py``'s module docstring for the full reasoning.
Run it monthly (a cron entry, or alongside archive_sentiment.py) and the
answer accumulates on its own.

Network access happens ONLY here — kala.fundamental_archive is pure storage,
kala.invezgo_fetch is the (degradation-safe) fetcher. Needs KALA_INVEZGO_TOKEN.

Budget: ONE Invezgo API call per (ticker, statement). --statements defaults
to IS only (1 call/ticker); add BS/CF to triple that. Snapshots already
recorded for today are skipped, so a re-run the same day costs nothing.

Usage:
    python archive_fundamentals.py --tickers BBCA ANTM
    python archive_fundamentals.py --tickers BBCA --statements IS BS CF --type FY
    python archive_fundamentals.py                      # held + watchlist tickers
    python archive_fundamentals.py --db results/fundamentals.db
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from kala.clock import today_str_wib
from kala.fundamental_archive import FundamentalArchive
from kala.invezgo_fetch import (
    SOURCE,
    VALID_STATEMENT_TYPES,
    VALID_STATEMENTS,
    InvezgoClient,
    fetch_financial_statement,
)
from kala.universe_sources import default_universe

# Anchored to the repository, not the caller's working directory — see
# archive_sentiment.py for why a bare relative path silently shrinks the
# archived universe.
ROOT = Path(__file__).resolve().parent
STATE_PATH = ROOT / "paper_state.json"
WATCHLIST_PATH = ROOT / "watchlist.json"


def _tickers_to_archive(explicit: list[str] | None) -> list[str]:
    """Explicit --tickers if given, else the union of open paper-trading
    positions and the watchlist -- the names actually worth tracking. Each
    source still degrades to 'contributes nothing' rather than crashing the
    run, and now reports on stderr when it does. (Mirrors
    archive_sentiment.py's selection; both call the same helper.)"""
    if explicit:
        return list(explicit)
    return default_universe(STATE_PATH, WATCHLIST_PATH).tickers


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Archive today's reported financial statements as a dated, "
                    "point-in-time snapshot (for eventual restatement checking).")
    ap.add_argument("--tickers", nargs="*", default=None,
                    help="IDX codes (BBCA) or yfinance form (BBCA.JK); "
                         "default = open positions + watchlist")
    ap.add_argument("--statements", nargs="*", default=["IS"], choices=VALID_STATEMENTS,
                    help="which statements to pull (default IS only; each is 1 API call/ticker)")
    ap.add_argument("--type", dest="type_", default="FY", choices=VALID_STATEMENT_TYPES,
                    help="FY=annual (default), Q=quarterly, Q1-Q4=specific quarter")
    ap.add_argument("--limit", type=int, default=8, help="periods requested per call (default 8)")
    ap.add_argument("--db", default="results/fundamentals.db")
    args = ap.parse_args(argv)

    tickers = _tickers_to_archive(args.tickers)
    if not tickers:
        print("No tickers to archive (no open positions, no watchlist, and none given via "
              "--tickers).", file=sys.stderr)
        return 1

    try:
        client = InvezgoClient()
        if not client.token:
            raise RuntimeError
    except Exception:
        print("No KALA_INVEZGO_TOKEN set — export it before running.", file=sys.stderr)
        return 1

    archive = FundamentalArchive(args.db)
    today = today_str_wib()
    total_rows = 0
    for t in tickers:
        for stmt in args.statements:
            snap = archive.get_or_snapshot(
                t, stmt, SOURCE, today,
                fetch_fn=lambda tk, st: fetch_financial_statement(
                    tk, statement=st, client=client, type_=args.type_, limit=args.limit),
            )
            n = 0 if snap is None else len(snap)
            total_rows += n
            print(f"{t} {stmt}: {n} line-item cell(s)")

    dates = sorted({d for t in tickers for d in archive.observed_dates(t)})
    print(f"\nArchived {total_rows} cell(s) across {len(tickers)} ticker(s) for {today} "
          f"-> {args.db}")
    if len(dates) >= 2:
        print(f"Snapshot dates now stored: {dates[0]} .. {dates[-1]} "
              f"({len(dates)} distinct) — diff_observations can compare them.")
    else:
        print("Only one snapshot date so far — take another in a few weeks, then "
              "diff_observations can check for restatements.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
