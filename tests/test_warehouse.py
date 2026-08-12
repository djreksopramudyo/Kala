"""SQLite OHLCV warehouse tests: upsert/read round-trip, gap-aware fetching."""

import numpy as np
import pandas as pd
import pytest

from kala.warehouse import Warehouse


def _df(start="2024-01-02", n=5, level=1000.0):
    idx = pd.bdate_range(start, periods=n)
    return pd.DataFrame(
        {"Open": np.full(n, level), "High": np.full(n, level * 1.01),
         "Low": np.full(n, level * 0.99), "Close": np.full(n, level),
         "Volume": np.full(n, 1e6)}, index=idx)


def test_upsert_then_read_round_trips(tmp_path):
    wh = Warehouse(tmp_path / "wh.db")
    wh.upsert("ANTM.JK", _df())
    got = wh.read("ANTM.JK")
    assert got is not None
    assert len(got) == 5
    assert list(got.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert got["Close"].iloc[0] == 1000.0


def test_read_missing_ticker_returns_none(tmp_path):
    wh = Warehouse(tmp_path / "wh.db")
    assert wh.read("NOPE.JK") is None


def test_upsert_empty_frame_is_noop(tmp_path):
    wh = Warehouse(tmp_path / "wh.db")
    assert wh.upsert("X.JK", pd.DataFrame()) == 0
    assert wh.read("X.JK") is None


def test_upsert_rejects_missing_columns(tmp_path):
    wh = Warehouse(tmp_path / "wh.db")
    bad = pd.DataFrame({"Close": [1.0]}, index=pd.bdate_range("2024-01-02", periods=1))
    with pytest.raises(ValueError, match="missing required column"):
        wh.upsert("X.JK", bad)


def test_upsert_overwrites_existing_bar(tmp_path):
    """A re-fetch with revised (e.g. adjusted) prices must replace, not
    duplicate, the stored row for that date."""
    wh = Warehouse(tmp_path / "wh.db")
    wh.upsert("A.JK", _df(level=1000.0))
    wh.upsert("A.JK", _df(level=1100.0))    # same dates, revised prices
    got = wh.read("A.JK")
    assert len(got) == 5                    # no duplicates
    assert got["Close"].iloc[0] == 1100.0   # latest value wins


def test_read_respects_date_range(tmp_path):
    wh = Warehouse(tmp_path / "wh.db")
    wh.upsert("A.JK", _df(n=10))
    full = wh.read("A.JK")
    sliced = wh.read("A.JK", start=full.index[2].strftime("%Y-%m-%d"),
                     end=full.index[5].strftime("%Y-%m-%d"))
    assert len(sliced) == 4


def test_covered_range_reports_min_max(tmp_path):
    wh = Warehouse(tmp_path / "wh.db")
    assert wh.covered_range("A.JK") is None
    wh.upsert("A.JK", _df(n=5))
    lo, hi = wh.covered_range("A.JK")
    assert lo == "2024-01-02"
    assert hi == "2024-01-08"


def test_tickers_lists_distinct_stored_tickers(tmp_path):
    wh = Warehouse(tmp_path / "wh.db")
    wh.upsert("B.JK", _df())
    wh.upsert("A.JK", _df())
    assert wh.tickers() == ["A.JK", "B.JK"]


def test_persists_across_new_warehouse_instances(tmp_path):
    """The whole point: data survives process restarts."""
    path = tmp_path / "wh.db"
    Warehouse(path).upsert("A.JK", _df())
    reopened = Warehouse(path)
    assert reopened.read("A.JK") is not None


# ---------------- get_or_fetch: the gap-aware research entry point ----------

def test_get_or_fetch_uses_cache_without_calling_fetch_fn_when_covered(tmp_path):
    wh = Warehouse(tmp_path / "wh.db")
    wh.upsert("A.JK", _df(n=10))
    calls = []

    def fetch_fn(t, s, e):
        calls.append((t, s, e))
        return _df(n=10)

    full = wh.read("A.JK")
    got = wh.get_or_fetch("A.JK", full.index[0].strftime("%Y-%m-%d"),
                          full.index[-1].strftime("%Y-%m-%d"), fetch_fn)
    assert len(calls) == 0          # cache already covers it -- no fetch needed
    assert got is not None and len(got) == 10


def test_get_or_fetch_calls_fetch_fn_when_not_covered(tmp_path):
    wh = Warehouse(tmp_path / "wh.db")
    calls = []

    def fetch_fn(t, s, e):
        calls.append((t, s, e))
        return _df(n=5)

    got = wh.get_or_fetch("A.JK", "2024-01-02", "2024-01-08", fetch_fn)
    assert len(calls) == 1
    assert got is not None and len(got) == 5
    # and it's cached now, for next time
    assert wh.read("A.JK") is not None


def test_get_or_fetch_caches_the_fresh_fetch(tmp_path):
    wh = Warehouse(tmp_path / "wh.db")
    wh.get_or_fetch("A.JK", "2024-01-02", "2024-01-08", lambda t, s, e: _df(n=5))
    # second call with a fetch_fn that would raise -- must NOT be called
    def boom(t, s, e):
        raise AssertionError("fetch_fn should not be called -- already covered")
    got = wh.get_or_fetch("A.JK", "2024-01-02", "2024-01-08", boom)
    assert got is not None and len(got) == 5


def test_get_or_fetch_falls_back_to_partial_cache_on_fetch_failure(tmp_path):
    """If the live fetch fails/returns empty, degrade to whatever's cached
    rather than propagating the failure -- same resilience spirit as
    datacache.with_fallback."""
    wh = Warehouse(tmp_path / "wh.db")
    wh.upsert("A.JK", _df(n=5))

    def failing_fetch(t, s, e):
        return None

    got = wh.get_or_fetch("A.JK", "2024-01-02", "2024-01-08", failing_fetch)
    assert got is not None and len(got) == 5


def test_get_or_fetch_returns_none_when_both_fetch_and_cache_miss(tmp_path):
    wh = Warehouse(tmp_path / "wh.db")
    got = wh.get_or_fetch("GONE.JK", "2024-01-02", "2024-01-08", lambda t, s, e: None)
    assert got is None


def test_get_or_fetch_swallows_fetch_fn_exceptions(tmp_path):
    wh = Warehouse(tmp_path / "wh.db")
    wh.upsert("A.JK", _df(n=5))

    def raising_fetch(t, s, e):
        raise RuntimeError("network down")

    got = wh.get_or_fetch("A.JK", "2024-01-02", "2024-01-08", raising_fetch)
    assert got is not None and len(got) == 5   # falls back to cache, doesn't propagate
