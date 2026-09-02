"""A permanently-stale ticker must stop being re-downloaded every run.

The freshness test asks whether the newest stored bar is recent. For a delisted
or suspended ticker that can never be true, so it failed the check forever and
was re-fetched on every single run — 30% of the universe on a real sweep. The
cache could not tell "never fetched" from "fetched, and this is all that
exists", which is the same shape as an archive that silently creates itself.
"""

import pandas as pd
import pytest

from kala.warehouse import Warehouse


def _bars(idx):
    return pd.DataFrame({"Open": 100.0, "High": 101.0, "Low": 99.0,
                         "Close": 100.0, "Volume": 1e6}, index=idx)


@pytest.fixture
def wh(tmp_path):
    return Warehouse(str(tmp_path / "w.db"))


def test_never_asked_is_not_fresh(wh):
    assert wh.fetch_attempt("AAA.JK") is None
    assert wh.is_as_fresh_as_it_gets("AAA.JK", "2026-08-14") is False


def test_asked_today_with_nothing_newer_counts_as_fresh(wh):
    """The delisted case: stored data ends long ago, the source has no more."""
    idx = pd.bdate_range("2024-01-02", periods=30)
    wh.upsert("DEAD.JK", _bars(idx))
    newest = idx[-1].strftime("%Y-%m-%d")
    wh.record_fetch_attempt("DEAD.JK", "2026-08-14", newest)
    assert wh.is_as_fresh_as_it_gets("DEAD.JK", "2026-08-14") is True


def test_yesterdays_attempt_does_not_count(wh):
    idx = pd.bdate_range("2024-01-02", periods=30)
    wh.upsert("DEAD.JK", _bars(idx))
    wh.record_fetch_attempt("DEAD.JK", "2026-08-13", idx[-1].strftime("%Y-%m-%d"))
    assert wh.is_as_fresh_as_it_gets("DEAD.JK", "2026-08-14") is False


def test_source_had_newer_data_than_stored_is_not_fresh(wh):
    """If the source knows about a bar we did not store, we are behind."""
    idx = pd.bdate_range("2024-01-02", periods=30)
    wh.upsert("AAA.JK", _bars(idx))
    wh.record_fetch_attempt("AAA.JK", "2026-08-14", "2026-08-13")
    assert wh.is_as_fresh_as_it_gets("AAA.JK", "2026-08-14") is False


def test_asked_today_and_source_returned_nothing(wh):
    """A ticker that does not resolve at all: recorded, and not retried today."""
    wh.record_fetch_attempt("GONE.JK", "2026-08-14", None)
    assert wh.is_as_fresh_as_it_gets("GONE.JK", "2026-08-14") is True


def test_attempt_is_overwritten_not_duplicated(wh):
    wh.record_fetch_attempt("AAA.JK", "2026-08-13", "2026-08-12")
    wh.record_fetch_attempt("AAA.JK", "2026-08-14", "2026-08-13")
    assert wh.fetch_attempt("AAA.JK") == ("2026-08-14", "2026-08-13")


def test_attempts_do_not_disturb_bar_storage(wh):
    idx = pd.bdate_range("2025-01-01", periods=10)
    wh.upsert("AAA.JK", _bars(idx))
    wh.record_fetch_attempt("AAA.JK", "2026-08-14", None)
    assert len(wh.read("AAA.JK")) == 10
    assert wh.tickers() == ["AAA.JK"]


# ---- integration: the fetch loop must actually honour it -------------------

def test_fetch_stops_redownloading_a_permanently_stale_ticker(tmp_path, monkeypatch):
    """The regression, end to end.

    A delisted ticker's newest bar is old forever, so the freshness test fails
    on every run and it was re-downloaded every time. Unit-testing the
    Warehouse methods alone does NOT catch that — the defect lives in fetch()'s
    coverage loop, so the test has to go through fetch().
    """
    import run_walkforward as rw

    idx = pd.bdate_range("2022-01-03", periods=400)   # spans a 3y start, stale tail
    stale = pd.DataFrame({"Open": 100.0, "High": 101.0, "Low": 99.0,
                          "Close": 100.0, "Volume": 1e6}, index=idx)

    calls = {"n": 0}

    def fake_download(tickers, **kw):
        calls["n"] += 1
        return stale

    monkeypatch.setattr(rw.yf, "download", fake_download)
    db = str(tmp_path / "w.db")

    rw.fetch(["DEAD.JK"], "3y", warehouse_path=db)
    first = calls["n"]
    assert first == 1, "first run should download"

    rw.fetch(["DEAD.JK"], "3y", warehouse_path=db)
    assert calls["n"] == first, (
        "a permanently-stale ticker was re-downloaded — the negative cache is "
        "not being consulted in fetch()")


def test_fetch_still_redownloads_when_the_attempt_is_from_another_day(tmp_path, monkeypatch):
    """The cache must not pin a ticker forever — only for the day it asked."""
    import run_walkforward as rw
    from kala.warehouse import Warehouse

    idx = pd.bdate_range("2022-01-03", periods=400)
    stale = pd.DataFrame({"Open": 100.0, "High": 101.0, "Low": 99.0,
                          "Close": 100.0, "Volume": 1e6}, index=idx)
    calls = {"n": 0}
    monkeypatch.setattr(rw.yf, "download",
                        lambda tickers, **kw: (calls.__setitem__("n", calls["n"] + 1), stale)[1])
    db = str(tmp_path / "w.db")
    rw.fetch(["DEAD.JK"], "3y", warehouse_path=db)

    # back-date the attempt, as if it had happened yesterday
    Warehouse(db).record_fetch_attempt("DEAD.JK", "2000-01-01", "2023-07-01")
    rw.fetch(["DEAD.JK"], "3y", warehouse_path=db)
    assert calls["n"] == 2, "a stale attempt record should not suppress a re-fetch"
