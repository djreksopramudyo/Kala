"""archive_sentiment.py tests: ticker-selection logic + an end-to-end main()
run with news/reddit fetchers mocked out (no network in tests)."""

import json

import archive_sentiment as arch


def test_explicit_tickers_take_priority(monkeypatch, tmp_path):
    monkeypatch.setattr(arch, "STATE_PATH", str(tmp_path / "nope.json"))
    monkeypatch.setattr(arch, "WATCHLIST_PATH", str(tmp_path / "nope2.json"))
    assert arch._tickers_to_archive(["X.JK", "Y.JK"]) == ["X.JK", "Y.JK"]


def test_falls_back_to_positions_and_watchlist(monkeypatch, tmp_path):
    statefile = tmp_path / "state.json"
    statefile.write_text(json.dumps({
        "cash": 1.0, "start_capital": 1.0,
        "positions": {"ANTM.JK": {"ticker": "ANTM.JK", "entry_price": 1.0, "shares": 1,
                                  "entry_date": "2026-01-01", "peak_price": 1.0}},
        "log": [], "pending": [], "undo_stack": [], "redo_stack": [], "benchmark_start": None,
        "capital_additions": [],
    }), encoding="utf-8")
    watchlistfile = tmp_path / "watchlist.json"
    watchlistfile.write_text(json.dumps({
        "BBCA.JK": {"ticker": "BBCA.JK", "fair_value": 10000.0, "score": None,
                    "thesis": "", "added": "2026-01-01", "source": ""},
    }), encoding="utf-8")

    monkeypatch.setattr(arch, "STATE_PATH", str(statefile))
    monkeypatch.setattr(arch, "WATCHLIST_PATH", str(watchlistfile))
    assert arch._tickers_to_archive(None) == ["ANTM.JK", "BBCA.JK"]


def test_returns_empty_when_nothing_available(monkeypatch, tmp_path):
    monkeypatch.setattr(arch, "STATE_PATH", str(tmp_path / "nope.json"))
    monkeypatch.setattr(arch, "WATCHLIST_PATH", str(tmp_path / "nope2.json"))
    assert arch._tickers_to_archive(None) == []


def test_main_archives_each_ticker_and_writes_to_db(monkeypatch, tmp_path, capsys):
    db_path = tmp_path / "sentiment.db"
    monkeypatch.setattr(arch, "get_news_sentiment", lambda t: (60.0, 2, "POSITIVE (2 articles)"))
    monkeypatch.setattr(arch, "get_reddit_sentiment", lambda t: (50.0, 0, "No recent Reddit mentions found"))
    monkeypatch.setattr("sys.argv", ["archive_sentiment.py", "--tickers", "ANTM.JK", "BBCA.JK",
                                     "--db", str(db_path)])

    rc = arch.main()
    assert rc == 0

    out = capsys.readouterr().out
    assert "ANTM.JK: news=60" in out
    assert "Archived 2 ticker(s)" in out

    from kala.sentiment_archive import SentimentArchive
    saved = SentimentArchive(db_path)
    assert saved.tickers() == ["ANTM.JK", "BBCA.JK"]
    assert saved.history("ANTM.JK", source="news")[0]["score"] == 60.0


def test_main_returns_error_when_no_tickers(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("sys.argv", ["archive_sentiment.py",
                                     "--db", str(tmp_path / "sentiment.db")])
    monkeypatch.setattr(arch, "STATE_PATH", str(tmp_path / "nope.json"))
    monkeypatch.setattr(arch, "WATCHLIST_PATH", str(tmp_path / "nope2.json"))
    rc = arch.main()
    assert rc == 1
    assert "No tickers to archive" in capsys.readouterr().err
