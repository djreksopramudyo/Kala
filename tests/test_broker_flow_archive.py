"""BrokerFlowArchive tests: canonical, vendor-agnostic storage for foreign-
flow/bandarmology data -- no vendor adapter exists yet, this only proves
the storage layer (upsert/read/coverage/gap-aware fetch) is correct."""

import sqlite3

import numpy as np
import pandas as pd
import pytest

from kala.broker_flow_archive import BrokerFlowArchive


def _df(start="2024-01-02", n=5, net=1_000_000.0, buy=None, sell=None, vol=None, share=None):
    idx = pd.bdate_range(start, periods=n)
    data = {"foreign_net_value": np.full(n, net)}
    if buy is not None:
        data["foreign_buy_value"] = np.full(n, buy)
    if sell is not None:
        data["foreign_sell_value"] = np.full(n, sell)
    if vol is not None:
        data["foreign_net_volume"] = np.full(n, vol)
    if share is not None:
        data["foreign_top_broker_share"] = np.full(n, share)
    return pd.DataFrame(data, index=idx)


def test_upsert_then_read_round_trips(tmp_path):
    arc = BrokerFlowArchive(tmp_path / "bf.db")
    arc.upsert("ANTM.JK", "invezgo", _df())
    got = arc.read("ANTM.JK")
    assert got is not None
    assert len(got) == 5
    assert got["foreign_net_value"].iloc[0] == 1_000_000.0


def test_optional_columns_default_to_null_not_zero(tmp_path):
    """A vendor that only reports net value (no buy/sell breakdown) must
    NOT silently claim buy/sell were measured as zero."""
    arc = BrokerFlowArchive(tmp_path / "bf.db")
    arc.upsert("ANTM.JK", "invezgo", _df())   # no buy/sell/volume columns given
    got = arc.read("ANTM.JK")
    assert got["foreign_buy_value"].isna().all()
    assert got["foreign_sell_value"].isna().all()
    assert got["foreign_net_volume"].isna().all()


def test_optional_columns_stored_when_provided(tmp_path):
    arc = BrokerFlowArchive(tmp_path / "bf.db")
    arc.upsert("ANTM.JK", "invezgo",
              _df(net=100.0, buy=600.0, sell=500.0, vol=50_000.0, share=0.62))
    got = arc.read("ANTM.JK")
    assert got["foreign_buy_value"].iloc[0] == 600.0
    assert got["foreign_sell_value"].iloc[0] == 500.0
    assert got["foreign_net_volume"].iloc[0] == 50_000.0
    assert got["foreign_top_broker_share"].iloc[0] == 0.62


def test_migration_adds_share_column_to_pre_existing_database(tmp_path):
    """Exactly your situation: a broker_flow.db already backfilled BEFORE
    foreign_top_broker_share existed. Opening it with the new code must add
    the column (old rows read back NULL for it, not crash or silently drop
    the new column) rather than requiring a fresh backfill."""
    db_path = tmp_path / "old.db"
    # build a database using the OLD schema by hand -- no share column at all.
    with sqlite3.connect(db_path) as conn:
        conn.executescript("""
            CREATE TABLE broker_flow (
                ticker TEXT NOT NULL, date TEXT NOT NULL, source TEXT NOT NULL,
                foreign_net_value REAL NOT NULL, foreign_buy_value REAL,
                foreign_sell_value REAL, foreign_net_volume REAL,
                PRIMARY KEY (ticker, date, source)
            );
        """)
        conn.execute(
            "INSERT INTO broker_flow (ticker, date, source, foreign_net_value) "
            "VALUES ('BBCA.JK', '2024-12-02', 'invezgo', 12345.0)")

    arc = BrokerFlowArchive(db_path)          # opening it should migrate in place
    got = arc.read("BBCA.JK")
    assert got["foreign_net_value"].iloc[0] == 12345.0
    assert pd.isna(got["foreign_top_broker_share"].iloc[0])   # old row -> NULL, not 0/crash

    # and new writes to the migrated database work normally
    arc.upsert("ANTM.JK", "invezgo", _df(net=1.0, share=0.9))
    assert arc.read("ANTM.JK")["foreign_top_broker_share"].iloc[0] == 0.9


def test_read_missing_ticker_returns_none(tmp_path):
    arc = BrokerFlowArchive(tmp_path / "bf.db")
    assert arc.read("NOPE.JK") is None


def test_upsert_empty_frame_is_noop(tmp_path):
    arc = BrokerFlowArchive(tmp_path / "bf.db")
    assert arc.upsert("X.JK", "invezgo", pd.DataFrame()) == 0
    assert arc.read("X.JK") is None


def test_upsert_rejects_missing_required_column(tmp_path):
    arc = BrokerFlowArchive(tmp_path / "bf.db")
    bad = pd.DataFrame({"foreign_buy_value": [1.0]}, index=pd.bdate_range("2024-01-02", periods=1))
    with pytest.raises(ValueError, match="missing required column"):
        arc.upsert("X.JK", "invezgo", bad)


def test_upsert_overwrites_existing_row_same_source(tmp_path):
    arc = BrokerFlowArchive(tmp_path / "bf.db")
    arc.upsert("A.JK", "invezgo", _df(net=100.0))
    arc.upsert("A.JK", "invezgo", _df(net=200.0))    # same dates, revised figures
    got = arc.read("A.JK")
    assert len(got) == 5
    assert got["foreign_net_value"].iloc[0] == 200.0


def test_different_sources_kept_separate(tmp_path):
    arc = BrokerFlowArchive(tmp_path / "bf.db")
    arc.upsert("A.JK", "invezgo", _df(net=100.0))
    arc.upsert("A.JK", "sectors", _df(net=999.0))
    all_rows = arc.read("A.JK")
    assert len(all_rows) == 10   # both vendors' rows, not overwritten
    only_sectors = arc.read("A.JK", source="sectors")
    assert len(only_sectors) == 5
    assert (only_sectors["foreign_net_value"] == 999.0).all()


def test_read_respects_date_range(tmp_path):
    arc = BrokerFlowArchive(tmp_path / "bf.db")
    arc.upsert("A.JK", "invezgo", _df(n=10))
    full = arc.read("A.JK")
    sliced = arc.read("A.JK", start=full.index[2].strftime("%Y-%m-%d"),
                      end=full.index[5].strftime("%Y-%m-%d"))
    assert len(sliced) == 4


def test_covered_range_reports_min_max(tmp_path):
    arc = BrokerFlowArchive(tmp_path / "bf.db")
    assert arc.covered_range("A.JK") is None
    arc.upsert("A.JK", "invezgo", _df(n=5))
    lo, hi = arc.covered_range("A.JK")
    assert lo == "2024-01-02"
    assert hi == "2024-01-08"


def test_covered_range_filters_by_source(tmp_path):
    arc = BrokerFlowArchive(tmp_path / "bf.db")
    arc.upsert("A.JK", "invezgo", _df(start="2024-01-02", n=5))
    arc.upsert("A.JK", "sectors", _df(start="2024-06-01", n=5))
    lo, hi = arc.covered_range("A.JK", source="invezgo")
    assert lo == "2024-01-02"


def test_tickers_lists_distinct_stored_tickers(tmp_path):
    arc = BrokerFlowArchive(tmp_path / "bf.db")
    arc.upsert("B.JK", "invezgo", _df())
    arc.upsert("A.JK", "invezgo", _df())
    assert arc.tickers() == ["A.JK", "B.JK"]


def test_persists_across_new_instances(tmp_path):
    path = tmp_path / "bf.db"
    BrokerFlowArchive(path).upsert("A.JK", "invezgo", _df())
    reopened = BrokerFlowArchive(path)
    assert reopened.read("A.JK") is not None


# ---------------- get_or_fetch: the gap-aware research entry point ----------

def test_get_or_fetch_uses_cache_without_calling_fetch_fn_when_covered(tmp_path):
    arc = BrokerFlowArchive(tmp_path / "bf.db")
    arc.upsert("A.JK", "invezgo", _df(n=10))
    calls = []

    def fetch_fn(t, s, e):
        calls.append((t, s, e))
        return _df(n=10)

    full = arc.read("A.JK")
    got = arc.get_or_fetch("A.JK", "invezgo", full.index[0].strftime("%Y-%m-%d"),
                           full.index[-1].strftime("%Y-%m-%d"), fetch_fn)
    assert len(calls) == 0
    assert got is not None and len(got) == 10


def test_get_or_fetch_calls_fetch_fn_when_not_covered(tmp_path):
    arc = BrokerFlowArchive(tmp_path / "bf.db")
    calls = []

    def fetch_fn(t, s, e):
        calls.append((t, s, e))
        return _df(n=5)

    got = arc.get_or_fetch("A.JK", "invezgo", "2024-01-02", "2024-01-08", fetch_fn)
    assert len(calls) == 1
    assert got is not None and len(got) == 5
    assert arc.read("A.JK") is not None


def test_get_or_fetch_falls_back_to_partial_cache_on_fetch_failure(tmp_path):
    arc = BrokerFlowArchive(tmp_path / "bf.db")
    arc.upsert("A.JK", "invezgo", _df(n=5))

    got = arc.get_or_fetch("A.JK", "invezgo", "2024-01-02", "2024-01-08",
                           lambda t, s, e: None)
    assert got is not None and len(got) == 5


def test_get_or_fetch_returns_none_when_both_fetch_and_cache_miss(tmp_path):
    arc = BrokerFlowArchive(tmp_path / "bf.db")
    got = arc.get_or_fetch("GONE.JK", "invezgo", "2024-01-02", "2024-01-08", lambda t, s, e: None)
    assert got is None


def test_get_or_fetch_swallows_fetch_fn_exceptions(tmp_path):
    arc = BrokerFlowArchive(tmp_path / "bf.db")
    arc.upsert("A.JK", "invezgo", _df(n=5))

    def raising_fetch(t, s, e):
        raise RuntimeError("network down")

    got = arc.get_or_fetch("A.JK", "invezgo", "2024-01-02", "2024-01-08", raising_fetch)
    assert got is not None and len(got) == 5
