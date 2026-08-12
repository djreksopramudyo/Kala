"""Weekly Telegram scorecard — the wrapper daily_run appends once a week.

The scoring maths itself is covered by test_live_scorecard.py; what is tested
here is the wrapper's decision-making, especially the branch that must NOT
silently produce a flattering-looking zero when benchmark data is missing.
"""

import pandas as pd
import pytest

from kala.live_scorecard import fetch_benchmark, round_trip_cost, weekly_scorecard_text


def _bench(start="2026-01-02", n=200, first=100.0, step=0.1):
    idx = pd.bdate_range(start, periods=n)
    return pd.Series([first + i * step for i in range(n)], index=idx)


def _state():
    return {
        "positions": {
            "BBCA.JK": {"entry_price": 1000.0, "shares": 100,
                        "entry_date": "2026-02-02"},
        },
        "log": [],
    }


def test_returns_none_when_nothing_traded_yet():
    """An empty book has nothing to score — the daily message should not get
    an empty scorecard block appended to it."""
    assert weekly_scorecard_text({}, {}, fetch=lambda *a: _bench()) is None
    assert weekly_scorecard_text({"positions": {}, "log": []}, {},
                                 fetch=lambda *a: _bench()) is None


def test_missing_benchmark_says_so_instead_of_scoring_against_zero():
    """The important one. With no benchmark series every excess figure would
    compute against 0.0 and the report would read like the book performed
    exactly at benchmark — a false result. It must report the gap instead."""
    text = weekly_scorecard_text(_state(), {"BBCA.JK": 1100.0},
                                 benchmark_ticker="NOSUCH.JK",
                                 fetch=lambda *a: None)
    assert "skipped" in text.lower()
    assert "NOSUCH.JK" in text
    # and must not present any excess/verdict numbers
    assert "%" not in text


def test_empty_benchmark_series_treated_as_missing():
    """A zero-row series is 'no data' just as much as None is."""
    text = weekly_scorecard_text(_state(), {"BBCA.JK": 1100.0},
                                 fetch=lambda *a: pd.Series(dtype=float))
    assert "skipped" in text.lower()


def test_scores_normally_when_benchmark_available():
    text = weekly_scorecard_text(_state(), {"BBCA.JK": 1100.0},
                                 benchmark_ticker="XIJI.JK",
                                 fetch=lambda *a: _bench())
    assert "XIJI.JK" in text
    # the formatter's own power caveat must survive into the weekly message —
    # this figure is not evidence and the message has to keep saying so
    assert "not evidence" in text.lower() or "luck" in text.lower()


def test_charges_the_same_friction_as_the_cli():
    """round_trip_cost lives in the module precisely so the weekly report and
    the CLI cannot drift apart; assert it is a sane positive fraction."""
    c = round_trip_cost()
    assert 0.0 < c < 0.05        # a few tenths of a percent, not 5%


def test_fetch_benchmark_unwraps_single_ticker_frame(monkeypatch):
    """yfinance returns a one-column DataFrame in some versions; the caller
    wants a Series either way."""
    idx = pd.bdate_range("2026-01-02", periods=5)
    frame = pd.DataFrame({"Close": pd.DataFrame({"XIJI.JK": range(5)}, index=idx)
                          .iloc[:, 0]}, index=idx)
    wrapped = pd.concat({"Close": frame[["Close"]]}, axis=1)

    fake = type("M", (), {"download": staticmethod(lambda *a, **k: wrapped)})
    monkeypatch.setitem(__import__("sys").modules, "yfinance", fake)

    out = fetch_benchmark("XIJI.JK")
    assert isinstance(out, pd.Series)
    assert len(out) == 5


def test_fetch_benchmark_returns_none_on_download_failure(monkeypatch):
    """A network failure must degrade to None (-> 'skipped' message), never
    raise out of the daily run and kill the whole message."""
    def boom(*a, **k):
        raise RuntimeError("network down")

    fake = type("M", (), {"download": staticmethod(boom)})
    monkeypatch.setitem(__import__("sys").modules, "yfinance", fake)

    assert fetch_benchmark("XIJI.JK") is None


def test_fetch_benchmark_returns_none_on_empty_download(monkeypatch):
    fake = type("M", (), {"download": staticmethod(lambda *a, **k: pd.DataFrame())})
    monkeypatch.setitem(__import__("sys").modules, "yfinance", fake)

    assert fetch_benchmark("XIJI.JK") is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
