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
from pathlib import Path

from kala.clock import today_str_wib
from kala.news import get_news_sentiment
from kala.reddit_sentiment import get_reddit_sentiment
from kala.sentiment_archive import SentimentArchive
from kala.universe_sources import default_universe

# Anchored to the repository, not the caller's working directory. A bare
# "paper_state.json" resolves against cwd, so the same command archives a
# different (silently smaller) universe depending on where it is run from.
ROOT = Path(__file__).resolve().parent
STATE_PATH = ROOT / "paper_state.json"
WATCHLIST_PATH = ROOT / "watchlist.json"


def _tickers_to_archive(explicit: list[str] | None) -> list[str]:
    """Explicit --tickers if given, else the union of open paper-trading
    positions and the watchlist -- the names actually worth tracking
    sentiment on. Each source still degrades to 'contributes nothing' rather
    than crashing the whole run, but now says so on stderr; see
    kala/universe_sources.py for why the silence mattered."""
    if explicit:
        return list(explicit)
    return default_universe(STATE_PATH, WATCHLIST_PATH).tickers


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
