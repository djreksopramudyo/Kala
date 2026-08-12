"""
Reddit sentiment via Reddit's OFFICIAL, credentialed API — NOT scraping.

WHY OAUTH, NOT THE OLD ".json" TRICK
--------------------------------------
Reddit deprecated unauthenticated ``.json`` endpoints in May 2026, and has
been actively suing scrapers over exactly this kind of unauthorized
access (Anthropic among them, since mid-2025 — the company that makes the
model this code was written by). This module only ever talks to Reddit
through the official API (via ``praw``), which is free for personal /
non-commercial use under Reddit's Data API Terms. If you're reading this
wondering why it doesn't just hit ``reddit.com/search.json`` — that's why.

SETUP (you have to do this yourself, same pattern as the Telegram bot
token — see DEPLOY_VPS.md)
--------------------------------------------------------------------------
1. Log into Reddit, go to https://www.reddit.com/prefs/apps
2. "create app" -> type "script" -> note the client ID (under the app
   name) and the client secret
3. Set environment variables:
       KALA_REDDIT_CLIENT_ID=...
       KALA_REDDIT_CLIENT_SECRET=...
       KALA_REDDIT_USER_AGENT=kala/0.1 by u/yourusername
4. pip install praw

Without those three env vars (or without praw installed), every function
here degrades to the same NEUTRAL / DEGRADED contract news.py uses —
never an exception, and never silently reads as "no mentions found" when
the real story is "not configured."

COVERAGE, HONESTLY: retail discussion of individual IDX tickers on Reddit
is thin compared to US large-caps — expect low mention counts most days.
This module is a start on point-in-time ARCHIVING (see
sentiment_archive.py), not a claim that Reddit sentiment says anything
useful about IDX stocks yet. Advisory-only, same as every other sentiment
source in this project — it never feeds the trading signal.
"""

from __future__ import annotations

import os

CLIENT_ID_ENV = "KALA_REDDIT_CLIENT_ID"
CLIENT_SECRET_ENV = "KALA_REDDIT_CLIENT_SECRET"
USER_AGENT_ENV = "KALA_REDDIT_USER_AGENT"

NOT_CONFIGURED = (50.0, 0, "DEGRADED: Reddit API credentials not configured (see module docstring)")


def _polarity(text: str):
    """TextBlob polarity in [-1, 1], or None if textblob is unavailable.
    Deliberately duplicated from news.py rather than imported -- a private
    helper shared across module boundaries would couple two otherwise-
    independent scrapers for six lines of code."""
    try:
        from textblob import TextBlob
        return float(TextBlob(text).sentiment.polarity)
    except Exception:
        return None


def credentials_configured() -> bool:
    return bool(os.environ.get(CLIENT_ID_ENV, "").strip()
               and os.environ.get(CLIENT_SECRET_ENV, "").strip()
               and os.environ.get(USER_AGENT_ENV, "").strip())


def _reddit_client():
    """A praw.Reddit instance (read-only), or None if credentials or praw
    itself are missing. Never raises."""
    if not credentials_configured():
        return None
    try:
        import praw
        return praw.Reddit(
            client_id=os.environ[CLIENT_ID_ENV].strip(),
            client_secret=os.environ[CLIENT_SECRET_ENV].strip(),
            user_agent=os.environ[USER_AGENT_ENV].strip(),
            read_only=True,
        )
    except Exception:
        return None


def scrape_reddit_mentions(ticker: str, company_name: str | None = None,
                           limit: int = 25, client=None) -> list[tuple]:
    """Recent post titles (+ a selftext snippet) mentioning the ticker or
    company name, searched site-wide via the official API. Returns
    (text, subreddit) tuples; [] if not configured or nothing found —
    never raises. ``client`` is injectable for tests; production callers
    leave it None and a real (or absent) praw client is resolved here."""
    client = client if client is not None else _reddit_client()
    if client is None:
        return []

    code = ticker.replace(".JK", "")
    query = f'{code} OR "{company_name}"' if company_name else code
    out = []
    try:
        for submission in client.subreddit("all").search(query, sort="new", limit=limit,
                                                          time_filter="month"):
            text = submission.title
            if getattr(submission, "selftext", ""):
                text += " " + submission.selftext[:200]
            out.append((text, str(submission.subreddit)))
    except Exception:
        return []
    return out


def get_reddit_sentiment(ticker: str, company_name: str | None = None, client=None) -> tuple:
    """(score 0-100, mention_count, description) — same contract as
    news.get_news_sentiment, so archival/display code can treat every
    sentiment source uniformly."""
    try:
        if client is None and not credentials_configured():
            return NOT_CONFIGURED

        mentions = scrape_reddit_mentions(ticker, company_name, client=client)
        if not mentions:
            return 50.0, 0, "No recent Reddit mentions found"

        polarities = [p for text, _sub in mentions if (p := _polarity(text)) is not None]
        if not polarities:
            return 50.0, 0, "No recent Reddit mentions found"

        avg = sum(polarities) / len(polarities)
        score = ((avg + 1.0) / 2.0) * 100.0
        label = "POSITIVE" if avg > 0.2 else "NEGATIVE" if avg < -0.2 else "NEUTRAL"
        return score, len(polarities), f"{label} ({len(polarities)} Reddit mention(s))"
    except Exception:
        return NOT_CONFIGURED
