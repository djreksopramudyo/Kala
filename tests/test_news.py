"""
Tests for kala.news — the single-owner news/sentiment engine.

Scraped CONTENT can't be tested offline; what can (and must) be tested is the
degradation contract: with no network, changed site layouts, or the optional
dependencies (beautifulsoup4/textblob/deep-translator) missing entirely,
every function returns something neutral and usable — never an exception.
That contract is what makes it safe for daily_run to call this in an
unattended 17:00 run.

Also locks in the delegation: kala_engine.py must expose the SAME function
objects as kala.news (delete-and-delegate, not copy-paste — the whole
point of the unification).
"""

import pytest

import kala.news as news


class _Boom:
    """requests.get stand-in that fails like a dead network."""
    def __call__(self, *a, **k):
        raise ConnectionError("no network in tests")


def test_scrapers_return_empty_lists_when_network_dead(monkeypatch):
    monkeypatch.setattr(news.requests, "get", _Boom())
    assert news.scrape_idx_announcements("ANTM.JK") == []
    assert news.scrape_indonesian_news("ANTM.JK") == []


def test_get_news_sentiment_neutral_when_everything_unavailable(monkeypatch):
    monkeypatch.setattr(news.requests, "get", _Boom())
    score, n, desc = news.get_news_sentiment("ANTM.JK")
    assert score == 50 and n == 0
    assert isinstance(desc, str) and desc  # labelled, not silent


def test_translate_falls_back_to_original_text():
    # English fast-path never needs the translator at all
    text = "the company announced a dividend for the year"
    assert news.translate_to_english(text) == text
    # Indonesian text with the translator unavailable/network dead ->
    # original text back, no exception
    indo = "laba bersih perusahaan naik signifikan kuartal ini"
    assert isinstance(news.translate_to_english(indo), str)


def test_polarity_helper_none_when_textblob_missing_or_score_when_present():
    p = news._polarity("great excellent wonderful profit growth")
    assert p is None or (isinstance(p, float) and -1.0 <= p <= 1.0)


def test_news_brief_skips_no_news_tickers_and_caps_length(monkeypatch):
    calls = []

    def fake_sentiment(t):
        calls.append(t)
        if t == "QUIET.JK":
            return 50, 0, "No recent news found"
        return 72.0, 3, "POSITIVE (3 articles from Kontan): something..."

    monkeypatch.setattr(news, "get_news_sentiment", fake_sentiment)
    lines = news.news_brief(["QUIET.JK", "LOUD.JK", "ALSO.JK", "MORE.JK"], max_tickers=3)
    assert calls == ["QUIET.JK", "LOUD.JK", "ALSO.JK"]      # cap respected
    assert len(lines) == 2                                    # no-news skipped
    assert all(line.startswith("• ") for line in lines)


def test_kala_engine_delegates_to_shared_module():
    """The legacy file must re-export the exact same objects — copy-paste
    drift is the failure mode this unification exists to end."""
    # kala_engine.py itself hard-requires the full requirements.txt stack at
    # import time (pre-existing); skip cleanly in minimal environments.
    pytest.importorskip("bs4")
    pytest.importorskip("textblob")
    import kala_engine as iq
    assert iq.get_news_sentiment is news.get_news_sentiment
    assert iq.scrape_idx_announcements is news.scrape_idx_announcements
    assert iq.scrape_indonesian_news is news.scrape_indonesian_news
    assert iq.translate_to_english is news.translate_to_english
