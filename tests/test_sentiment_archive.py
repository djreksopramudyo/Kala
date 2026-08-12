"""SentimentArchive tests: this is the fix for 'sentiment is unbacktestable'
-- it only STORES readings, it doesn't claim any signal value on its own."""

from kala.sentiment_archive import SentimentArchive


def test_record_then_history_round_trips(tmp_path):
    arc = SentimentArchive(tmp_path / "sent.db")
    arc.record("ANTM.JK", "2026-07-20", "news", 65.0, 3, "POSITIVE (3 articles)")
    hist = arc.history("ANTM.JK")
    assert len(hist) == 1
    assert hist[0]["score"] == 65.0
    assert hist[0]["source"] == "news"


def test_history_empty_for_unknown_ticker(tmp_path):
    arc = SentimentArchive(tmp_path / "sent.db")
    assert arc.history("NOPE.JK") == []


def test_record_overwrites_same_day_same_source(tmp_path):
    arc = SentimentArchive(tmp_path / "sent.db")
    arc.record("ANTM.JK", "2026-07-20", "news", 40.0, 1, "first read")
    arc.record("ANTM.JK", "2026-07-20", "news", 70.0, 2, "second read, same day")
    hist = arc.history("ANTM.JK")
    assert len(hist) == 1
    assert hist[0]["score"] == 70.0


def test_record_keeps_separate_sources_on_same_day(tmp_path):
    arc = SentimentArchive(tmp_path / "sent.db")
    arc.record("ANTM.JK", "2026-07-20", "news", 60.0, 2, "news read")
    arc.record("ANTM.JK", "2026-07-20", "reddit", 45.0, 1, "reddit read")
    hist = arc.history("ANTM.JK")
    assert len(hist) == 2
    assert {h["source"] for h in hist} == {"news", "reddit"}


def test_history_filters_by_source(tmp_path):
    arc = SentimentArchive(tmp_path / "sent.db")
    arc.record("ANTM.JK", "2026-07-20", "news", 60.0, 2, "x")
    arc.record("ANTM.JK", "2026-07-20", "reddit", 45.0, 1, "y")
    hist = arc.history("ANTM.JK", source="reddit")
    assert len(hist) == 1
    assert hist[0]["source"] == "reddit"


def test_history_filters_by_date_range(tmp_path):
    arc = SentimentArchive(tmp_path / "sent.db")
    for d in ("2026-07-01", "2026-07-10", "2026-07-20"):
        arc.record("ANTM.JK", d, "news", 50.0, 1, "x")
    hist = arc.history("ANTM.JK", start="2026-07-05", end="2026-07-15")
    assert [h["date"] for h in hist] == ["2026-07-10"]


def test_history_sorted_oldest_first(tmp_path):
    arc = SentimentArchive(tmp_path / "sent.db")
    arc.record("ANTM.JK", "2026-07-20", "news", 50.0, 1, "x")
    arc.record("ANTM.JK", "2026-07-01", "news", 50.0, 1, "x")
    hist = arc.history("ANTM.JK")
    assert [h["date"] for h in hist] == ["2026-07-01", "2026-07-20"]


def test_coverage_days_counts_distinct_dates(tmp_path):
    arc = SentimentArchive(tmp_path / "sent.db")
    assert arc.coverage_days("ANTM.JK") == 0
    arc.record("ANTM.JK", "2026-07-01", "news", 50.0, 1, "x")
    arc.record("ANTM.JK", "2026-07-01", "reddit", 50.0, 1, "x")   # same day, different source
    arc.record("ANTM.JK", "2026-07-02", "news", 50.0, 1, "x")
    assert arc.coverage_days("ANTM.JK") == 2


def test_coverage_days_filters_by_source(tmp_path):
    arc = SentimentArchive(tmp_path / "sent.db")
    arc.record("ANTM.JK", "2026-07-01", "news", 50.0, 1, "x")
    arc.record("ANTM.JK", "2026-07-02", "reddit", 50.0, 1, "x")
    assert arc.coverage_days("ANTM.JK", source="news") == 1


def test_tickers_lists_distinct_stored_tickers(tmp_path):
    arc = SentimentArchive(tmp_path / "sent.db")
    arc.record("BBCA.JK", "2026-07-01", "news", 50.0, 1, "x")
    arc.record("ANTM.JK", "2026-07-01", "news", 50.0, 1, "x")
    assert arc.tickers() == ["ANTM.JK", "BBCA.JK"]


def test_persists_across_new_instances(tmp_path):
    path = tmp_path / "sent.db"
    SentimentArchive(path).record("ANTM.JK", "2026-07-01", "news", 50.0, 1, "x")
    reopened = SentimentArchive(path)
    assert len(reopened.history("ANTM.JK")) == 1
