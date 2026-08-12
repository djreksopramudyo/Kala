"""
Daily sentiment archival — run this once a day (e.g. wired into
daily_run.py, or its own cron entry) to build the point-in-time sentiment
history that doesn't exist yet. See kala/sentiment_archive.py's
module docstring for why this is the actual fix for "sentiment is
unbacktestable" — it isn't, once enough of these daily runs have piled up.

Network access happens ONLY here — kala.sentiment_archive is pure
storage, kala.news / kala.reddit_sentiment are the (already
degradation-safe) fetchers.

Usage:
    python archive_sentiment.py                      # archives held + watchlist tickers
    python archive_sentiment.py --tickers ANTM.JK BBCA.JK
    python archive_sentiment.py --db results/sentiment.db
"""

from __future__ import annotations

import argparse
import sys

from kala.clock import today_str_wib
from kala.news import get_news_sentiment
from kala.reddit_sentiment import get_reddit_sentiment
from kala.sentiment_archive import SentimentArchive

STATE_PATH = "paper_state.json"
WATCHLIST_PATH = "watchlist.json"


def _tickers_to_archive(explicit: list[str] | None) -> list[str]:
    """Explicit --tickers if given, else the union of open paper-trading
    positions and the watchlist -- the names actually worth tracking
    sentiment on. Each source degrades to 'contributes nothing' on any
    failure (missing state file, corrupt JSON) rather than crashing the
    whole run."""
    if explicit:
        return list(explicit)

    tickers: set[str] = set()
    try:
        from kala.papertrade import PaperTrader
        pt = PaperTrader.load(STATE_PATH, start_capital=10_000_000)
        tickers.update(pt.positions)
    except Exception:
        pass
    try:
        from kala.watchlist import WatchlistStore
        wl = WatchlistStore.load(WATCHLIST_PATH)
        tickers.update(item.ticker for item in wl)
    except Exception:
        pass
    return sorted(tickers)


def main() -> int:
    ap = argparse.ArgumentParser(description="Archive today's sentiment readings for later backtestability")
    ap.add_argument("--tickers", nargs="*", default=None,
                    help="explicit ticker list; default = open positions + watchlist")
    ap.add_argument("--db", default="results/sentiment.db")
    args = ap.parse_args()

    tickers = _tickers_to_archive(args.tickers)
    if not tickers:
        print("No tickers to archive (no open positions, no watchlist, and none given via "
             "--tickers).", file=sys.stderr)
        return 1

    archive = SentimentArchive(args.db)
    today = today_str_wib()
    for t in tickers:
        news_score, news_n, news_desc = get_news_sentiment(t)
        archive.record(t, today, "news", news_score, news_n, news_desc)

        reddit_score, reddit_n, reddit_desc = get_reddit_sentiment(t)
        archive.record(t, today, "reddit", reddit_score, reddit_n, reddit_desc)

        print(f"{t}: news={news_score:.0f} ({news_n} article(s)), "
             f"reddit={reddit_score:.0f} ({reddit_n} mention(s))")

    print(f"\nArchived {len(tickers)} ticker(s) for {today} -> {args.db}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
