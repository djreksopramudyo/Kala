"""backfill_broker_flow.py tests: budget accounting, coverage-skip, and the
main() loop end-to-end with the HTTP layer mocked (no network)."""

import numpy as np
import pandas as pd
import pytest

import backfill_broker_flow as bf
from kala.broker_flow_archive import BrokerFlowArchive


def _flow_df(start="2024-12-02", n=5, net=1_000_000.0):
    idx = pd.bdate_range(start, periods=n)
    return pd.DataFrame({"foreign_net_value": np.full(n, net),
                         "foreign_buy_value": np.full(n, net * 2),
                         "foreign_sell_value": np.full(n, net),
                         "foreign_net_volume": np.full(n, 1000.0)}, index=idx)


# ---------------- _CountingClient --------------------------------------------

def test_counting_client_counts_calls():
    class Inner:
        def broker_summary(self, *a, **k):
            return []
    c = bf._CountingClient(Inner())
    c.broker_summary("BBCA", "2024-12-02", "2024-12-02")
    c.broker_summary("BBCA", "2024-12-03", "2024-12-03")
    assert c.n == 2


# ---------------- _uncovered_business_days ------------------------------------

def test_uncovered_days_full_count_when_nothing_stored(tmp_path):
    arc = BrokerFlowArchive(tmp_path / "bf.db")
    n = bf._uncovered_business_days(arc, "BBCA.JK", "2024-12-02", "2024-12-06")
    assert n == 5           # Mon-Fri


def test_uncovered_days_zero_when_fully_covered(tmp_path):
    arc = BrokerFlowArchive(tmp_path / "bf.db")
    arc.upsert("BBCA.JK", "invezgo", _flow_df(n=5))
    n = bf._uncovered_business_days(arc, "BBCA.JK", "2024-12-02", "2024-12-06")
    assert n == 0


def test_uncovered_days_full_count_when_partially_covered(tmp_path):
    """Conservative: a partial gap still counts as the FULL range (same
    honest limitation as covered_range not tracking holes)."""
    arc = BrokerFlowArchive(tmp_path / "bf.db")
    arc.upsert("BBCA.JK", "invezgo", _flow_df(n=2))     # only 2 of 5 days
    n = bf._uncovered_business_days(arc, "BBCA.JK", "2024-12-02", "2024-12-06")
    assert n == 5


# ---------------- main() end-to-end -------------------------------------------

class _FakeInvezgoClient:
    def __init__(self, token="tok"):
        self.token = token
        self.calls = []

    def broker_summary(self, code, from_date, to_date, investor="all", market="RG"):
        self.calls.append((code, from_date, to_date, investor, market))
        return [{"code": "AB", "name": "TEST SEKURITAS", "buy_value": "1000",
                "sell_value": "500", "net_value": "500", "net_volume": "10",
                "buy_freq": "1", "sell_freq": "1", "net_freq": "0",
                "buy_avg": "100", "sell_avg": "100"}]


def test_main_requires_token(monkeypatch, capsys):
    monkeypatch.setattr("backfill_broker_flow.InvezgoClient",
                        lambda: _FakeInvezgoClient(token=""))
    monkeypatch.setattr("sys.argv", ["backfill_broker_flow.py",
                                     "--start", "2024-12-02", "--end", "2024-12-03"])
    rc = bf.main()
    assert rc == 1
    assert "KALA_INVEZGO_TOKEN" in capsys.readouterr().err


def test_main_fetches_and_upserts(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("backfill_broker_flow.InvezgoClient", _FakeInvezgoClient)
    db = tmp_path / "bf.db"
    monkeypatch.setattr("sys.argv", [
        "backfill_broker_flow.py", "--tickers", "BBCA.JK", "ANTM.JK",
        "--start", "2024-12-02", "--end", "2024-12-03", "--db", str(db)])
    rc = bf.main()
    assert rc == 0

    arc = BrokerFlowArchive(db)
    assert arc.read("BBCA.JK") is not None
    assert arc.read("ANTM.JK") is not None
    out = capsys.readouterr().out
    assert "Done: 2 ticker(s) fetched" in out


def test_main_skips_already_covered_ticker(tmp_path, monkeypatch, capsys):
    db = tmp_path / "bf.db"
    BrokerFlowArchive(db).upsert("BBCA.JK", "invezgo", _flow_df(start="2024-12-02", n=2))

    monkeypatch.setattr("backfill_broker_flow.InvezgoClient", _FakeInvezgoClient)
    monkeypatch.setattr("sys.argv", [
        "backfill_broker_flow.py", "--tickers", "BBCA.JK",
        "--start", "2024-12-02", "--end", "2024-12-03", "--db", str(db)])
    rc = bf.main()
    assert rc == 0
    out = capsys.readouterr().out
    assert "1 already fully covered" in out


def test_main_respects_request_budget(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("backfill_broker_flow.InvezgoClient", _FakeInvezgoClient)
    db = tmp_path / "bf.db"
    # 2 tickers x 2 business days = 4 calls needed; budget only allows 2.
    monkeypatch.setattr("sys.argv", [
        "backfill_broker_flow.py", "--tickers", "BBCA.JK", "ANTM.JK",
        "--start", "2024-12-02", "--end", "2024-12-03", "--db", str(db),
        "--max-requests", "2"])
    rc = bf.main()
    assert rc == 0
    out = capsys.readouterr().out
    assert "1 skipped (would exceed budget)" in out

    arc = BrokerFlowArchive(db)
    assert arc.read("BBCA.JK") is not None
    assert arc.read("ANTM.JK") is None      # skipped, budget exhausted


def test_main_threads_investor_choice(monkeypatch, tmp_path):
    fake = _FakeInvezgoClient()
    monkeypatch.setattr("backfill_broker_flow.InvezgoClient", lambda: fake)
    db = tmp_path / "bf.db"
    monkeypatch.setattr("sys.argv", [
        "backfill_broker_flow.py", "--tickers", "BBCA.JK",
        "--start", "2024-12-02", "--end", "2024-12-02", "--db", str(db),
        "--investor", "all"])
    bf.main()
    assert fake.calls[0][3] == "all"


def test_main_rejects_invalid_investor(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", [
        "backfill_broker_flow.py", "--tickers", "BBCA.JK",
        "--start", "2024-12-02", "--end", "2024-12-02", "--investor", "bogus"])
    with pytest.raises(SystemExit):
        bf.main()
