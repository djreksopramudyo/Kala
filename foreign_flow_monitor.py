"""
Show what foreign money is currently doing in your watchlist, off the
broker-flow data already backfilled into results/broker_flow.db.

This is a MONITOR, not a signal. It reads the archive you already paid to
fill and ranks names by how unusually hard foreign money is net-buying each
one right now. The identical number, tested as a buy signal, was
inconclusive (PROJECT_STATUS.md) — so read this as context ("foreigners are
loading up on X"), never as "X is a buy." No network, no API cost: it only
reads the local archive.

Usage:
    python foreign_flow_monitor.py                         # watchlist + open positions
    python foreign_flow_monitor.py --tickers ANTM.JK BBCA.JK
    python foreign_flow_monitor.py --db results/broker_flow.db
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from kala.broker_flow_archive import BrokerFlowArchive
from kala.foreign_flow_monitor import format_report, rank_foreign_accumulation
from kala.universe_sources import default_universe

# Anchored to the repository, not the caller's working directory — see
# archive_sentiment.py for why a bare relative path silently shrinks the
# universe this ranks over.
ROOT = Path(__file__).resolve().parent
STATE_PATH = ROOT / "paper_state.json"
WATCHLIST_PATH = ROOT / "watchlist.json"


def _default_tickers() -> list[str]:
    """Open paper-trading positions + watchlist — same selection the sentiment
    and fundamentals archival CLIs use, through the same helper. Each source
    still degrades to nothing rather than crashing, and now reports on stderr
    when it does."""
    return default_universe(STATE_PATH, WATCHLIST_PATH).tickers


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Descriptive foreign-accumulation monitor over the local "
                    "broker-flow archive (NOT a validated buy signal).")
    ap.add_argument("--tickers", nargs="*", default=None,
                    help="tickers to rank; default = open positions + watchlist")
    ap.add_argument("--all", action="store_true",
                    help="rank EVERY ticker stored in the archive (ignores --tickers). "
                         "Use this when you don't know which names were backfilled -- the "
                         "backfill takes an even sample across the universe, not the big "
                         "liquid names you'd guess.")
    ap.add_argument("--db", default="results/broker_flow.db")
    ap.add_argument("--source", default="invezgo", help="vendor tag stored in the archive")
    args = ap.parse_args(argv)

    archive = BrokerFlowArchive(args.db)
    stored = sorted(archive.tickers())
    if not stored:
        print(f"No broker-flow data in {args.db} yet — backfill it first with "
              "backfill_broker_flow.py.", file=sys.stderr)
        return 1

    if args.all:
        tickers = stored
    else:
        tickers = args.tickers if args.tickers else _default_tickers()
    if not tickers:
        print("No tickers to rank (no open positions, no watchlist, none given via "
              "--tickers). Tip: --all ranks everything in the archive.", file=sys.stderr)
        return 1

    ranked = rank_foreign_accumulation(archive, tickers, source=args.source)
    print(format_report(ranked))

    covered = [t for t in tickers if t in set(stored)]
    if not covered:
        # none of the requested names are in the archive -- show what IS, so the
        # user isn't left guessing (the whole reason the default query missed).
        shown = ", ".join(stored[:20])
        print(f"\n  None of those are in the archive. It holds {len(stored)} ticker(s); "
              f"try --all, or pick from:\n  {shown}{' …' if len(stored) > 20 else ''}")
    elif len(covered) < len(tickers):
        missing = sorted(set(tickers) - set(stored))
        print(f"\n  ({len(missing)} of {len(tickers)} not in the archive: "
              f"{', '.join(missing[:8])}{' …' if len(missing) > 8 else ''})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
