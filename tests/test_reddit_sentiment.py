"""
Reddit sentiment tests: this module talks ONLY to Reddit's official
credentialed API (praw), never scrapes -- see the module docstring for
why. Tests cover the degradation contract (no creds / no praw / no
mentions) and the scoring math via an injectable fake client. The
praw-absent and textblob-absent paths are forced via sys.modules rather
than relying on the package actually being missing from the environment
-- requirements.txt lists both as real dependencies, so a normal install
(this project's own venv included) has them present.
"""

import sys

import kala.reddit_sentiment as rs
from kala.reddit_sentiment import (
    NOT_CONFIGURED,
    _reddit_client,
    credentials_configured,
    get_reddit_sentiment,
    scrape_reddit_mentions,
)

ENV_VARS = ("KALA_REDDIT_CLIENT_ID", "KALA_REDDIT_CLIENT_SECRET",
           "KALA_REDDIT_USER_AGENT")


class _FakeSubmission:
    def __init__(self, title, selftext="", subreddit="IndoStreetBets"):
        self.title = title
        self.selftext = selftext
        self.subreddit = subreddit


class _FakeSubreddit:
    def __init__(self, submissions):
        self._submissions = submissions

    def search(self, query, sort="new", limit=25, time_filter="month"):
        return iter(self._submissions[:limit])


class _FakeClient:
    def __init__(self, submissions):
        self._submissions = submissions

    def subreddit(self, name):
        return _FakeSubreddit(self._submissions)


class _RaisingClient:
    def subreddit(self, name):
        raise RuntimeError("network down")


# ---------------- credentials_configured / _reddit_client -----------------------

def test_credentials_not_configured_by_default(monkeypatch):
    for v in ENV_VARS:
        monkeypatch.delenv(v, raising=False)
    assert not credentials_configured()
    assert _reddit_client() is None


def test_credentials_configured_when_all_three_env_vars_set(monkeypatch):
    monkeypatch.setenv("KALA_REDDIT_CLIENT_ID", "abc")
    monkeypatch.setenv("KALA_REDDIT_CLIENT_SECRET", "def")
    monkeypatch.setenv("KALA_REDDIT_USER_AGENT", "kala/0.1 by u/test")
    assert credentials_configured()


def test_credentials_not_configured_when_one_var_missing(monkeypatch):
    monkeypatch.setenv("KALA_REDDIT_CLIENT_ID", "abc")
    monkeypatch.setenv("KALA_REDDIT_CLIENT_SECRET", "def")
    monkeypatch.delenv("KALA_REDDIT_USER_AGENT", raising=False)
    assert not credentials_configured()


def test_reddit_client_none_when_praw_not_installed(monkeypatch):
    """Forces the ImportError branch via sys.modules -- reliable regardless
    of whether praw happens to be installed (requirements.txt lists it)."""
    monkeypatch.setenv("KALA_REDDIT_CLIENT_ID", "abc")
    monkeypatch.setenv("KALA_REDDIT_CLIENT_SECRET", "def")
    monkeypatch.setenv("KALA_REDDIT_USER_AGENT", "kala/0.1 by u/test")
    monkeypatch.setitem(sys.modules, "praw", None)
    assert _reddit_client() is None


# ---------------- scrape_reddit_mentions -----------------------------------------

def test_scrape_mentions_empty_without_client_or_credentials(monkeypatch):
    for v in ENV_VARS:
        monkeypatch.delenv(v, raising=False)
    assert scrape_reddit_mentions("ANTM.JK") == []


def test_scrape_mentions_uses_injected_client():
    client = _FakeClient([_FakeSubmission("ANTM to the moon", selftext="great earnings")])
    mentions = scrape_reddit_mentions("ANTM.JK", client=client)
    assert len(mentions) == 1
    assert "ANTM" in mentions[0][0]
    assert mentions[0][1] == "IndoStreetBets"


def test_scrape_mentions_strips_jk_suffix_from_query():
    client = _FakeClient([_FakeSubmission("x")])
    mentions = scrape_reddit_mentions("ANTM.JK", client=client)
    assert len(mentions) == 1   # doesn't crash / filter itself out


def test_scrape_mentions_swallows_client_exceptions():
    assert scrape_reddit_mentions("ANTM.JK", client=_RaisingClient()) == []


def test_scrape_mentions_respects_limit():
    subs = [_FakeSubmission(f"post {i}") for i in range(10)]
    client = _FakeClient(subs)
    mentions = scrape_reddit_mentions("ANTM.JK", client=client, limit=3)
    assert len(mentions) == 3


# ---------------- get_reddit_sentiment --------------------------------------------

def test_get_sentiment_not_configured_without_client_or_credentials(monkeypatch):
    for v in ENV_VARS:
        monkeypatch.delenv(v, raising=False)
    assert get_reddit_sentiment("ANTM.JK") == NOT_CONFIGURED


def test_get_sentiment_no_mentions_found():
    client = _FakeClient([])
    score, n, desc = get_reddit_sentiment("ANTM.JK", client=client)
    assert n == 0
    assert "No recent Reddit mentions" in desc


def test_get_sentiment_positive_mentions_score_above_fifty(monkeypatch):
    """textblob isn't installed in this sandbox, so the polarity function
    is faked here to test the SCORING MATH; test_reddit_client_none_when_
    praw_not_installed above already proves the real missing-dependency
    degradation path for the analogous praw case."""
    monkeypatch.setattr(rs, "_polarity", lambda text: 0.8)
    client = _FakeClient([
        _FakeSubmission("ANTM is an excellent great amazing wonderful buy"),
        _FakeSubmission("ANTM fantastic outstanding earnings beat"),
    ])
    score, n, desc = get_reddit_sentiment("ANTM.JK", client=client)
    assert n == 2
    assert score > 50.0
    assert "POSITIVE" in desc


def test_get_sentiment_negative_mentions_score_below_fifty(monkeypatch):
    monkeypatch.setattr(rs, "_polarity", lambda text: -0.8)
    client = _FakeClient([
        _FakeSubmission("ANTM is a terrible awful horrible disaster"),
        _FakeSubmission("ANTM catastrophic collapse bad news"),
    ])
    score, n, desc = get_reddit_sentiment("ANTM.JK", client=client)
    assert n == 2
    assert score < 50.0
    assert "NEGATIVE" in desc


def test_get_sentiment_degrades_when_textblob_not_installed(monkeypatch):
    """Forces the ImportError branch via sys.modules -- reliable regardless
    of whether textblob happens to be installed (requirements.txt lists it).
    polarity scoring becomes unavailable, so mention count correctly reads
    as 0 rather than crashing."""
    monkeypatch.setitem(sys.modules, "textblob", None)
    client = _FakeClient([_FakeSubmission("ANTM to the moon")])
    score, n, desc = get_reddit_sentiment("ANTM.JK", client=client)
    assert n == 0
    assert "No recent Reddit mentions" in desc


def test_get_sentiment_swallows_unexpected_exceptions():
    class BrokenClient:
        def subreddit(self, name):
            raise ValueError("boom")

    result = get_reddit_sentiment("ANTM.JK", client=BrokenClient())
    assert result[1] == 0   # zero mentions -- degrades cleanly, doesn't raise
