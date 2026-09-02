"""Invezgo adapter tests: parsing + the daily foreign-net fetch loop, all
against the REAL /analysis/summary/stock/BBCA response saved as a fixture,
with the HTTP layer mocked (no network in tests). The parse logic is
identical across investor filters (same fields, confirmed live: investor=f
returns the same per-broker shape as investor=all, just mostly zeroed), so
exercising it on the fixture's investor=all payload proves the investor=f
path too."""

import json
from pathlib import Path

import pytest

from kala.invezgo_fetch import (
    InvezgoClient,
    _to_float,
    _top_broker_share,
    broker_net_frame,
    fetch_daily_foreign_net,
)

FIXTURE = Path(__file__).parent / "fixtures" / "invezgo_broker_summary_bbca.json"


@pytest.fixture
def broker_rows():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


# ---------------- _to_float --------------------------------------------------

def test_to_float_parses_string_numbers():
    assert _to_float("111500000") == 111500000.0
    assert _to_float("-4557300") == -4557300.0
    assert _to_float("2530.13308977") == pytest.approx(2530.13308977)


def test_to_float_none_for_null_empty_and_garbage():
    assert _to_float(None) is None
    assert _to_float("") is None
    assert _to_float("   ") is None
    assert _to_float("N/A") is None


# ---------------- broker_net_frame (real fixture) ----------------------------

def test_broker_net_frame_shape_and_values(broker_rows):
    df = broker_net_frame(broker_rows)
    assert len(df) == 86                       # real BBCA response has 86 brokers
    assert df.index.name == "code"
    # net_value sums to ~0 market-wide (every buy is a sell) -- the fact that
    # forces investor=foreign for a real foreign figure.
    assert abs(df["net_value"].sum()) < 1.0
    # top net buyer in this real response is Ciptadana (KI).
    assert df["net_value"].idxmax() == "KI"


def test_broker_net_frame_empty_input():
    df = broker_net_frame([])
    assert df.empty


# ---------------- InvezgoClient ----------------------------------------------

def test_client_requires_token(monkeypatch):
    monkeypatch.delenv("KALA_INVEZGO_TOKEN", raising=False)
    client = InvezgoClient(token="")
    with pytest.raises(RuntimeError, match="No Invezgo token"):
        client.broker_summary("BBCA", "2024-12-02", "2024-12-02")


def test_client_reads_token_from_env(monkeypatch):
    monkeypatch.setenv("KALA_INVEZGO_TOKEN", "secret123")
    assert InvezgoClient().token == "secret123"


def test_broker_summary_sends_auth_and_params(monkeypatch, broker_rows):
    captured = {}

    class FakeResp:
        def raise_for_status(self): pass
        def json(self): return broker_rows

    def fake_get(url, params=None, headers=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        captured["headers"] = headers
        return FakeResp()

    monkeypatch.setattr("kala.invezgo_fetch.requests.get", fake_get)
    client = InvezgoClient(token="tok")
    out = client.broker_summary("BBCA", "2024-12-01", "2024-12-31", investor="all")

    assert out == broker_rows
    assert captured["url"].endswith("/analysis/summary/stock/BBCA")
    # market defaults to "RG" -- REQUIRED by the live API (confirmed: a call
    # without it 422s with "Path `market` should be `string`, but got
    # `undefined`") even though it's undocumented.
    assert captured["params"] == {"from": "2024-12-01", "to": "2024-12-31",
                                  "investor": "all", "market": "RG"}
    assert captured["headers"]["Authorization"] == "Bearer tok"


def test_broker_summary_market_override(monkeypatch, broker_rows):
    captured = {}

    class FakeResp:
        def raise_for_status(self): pass
        def json(self): return broker_rows

    def fake_get(url, params=None, headers=None, timeout=None):
        captured["params"] = params
        return FakeResp()

    monkeypatch.setattr("kala.invezgo_fetch.requests.get", fake_get)
    InvezgoClient(token="tok").broker_summary("BBCA", "2024-12-01", "2024-12-31", market="NG")
    assert captured["params"]["market"] == "NG"


def test_get_retries_429_then_succeeds(monkeypatch, broker_rows):
    """A rate-limited request should self-heal (sleep + retry), not fail the
    day outright -- otherwise a big backfill silently loses whichever days
    happen to land on a throttled request."""
    calls = []

    class Resp429:
        status_code = 429
        headers = {}
        def raise_for_status(self): pass

    class Resp200:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return broker_rows

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append(1)
        return Resp429() if len(calls) == 1 else Resp200()

    sleeps = []
    monkeypatch.setattr("kala.invezgo_fetch.requests.get", fake_get)
    monkeypatch.setattr("kala.invezgo_fetch.time.sleep", lambda s: sleeps.append(s))

    out = InvezgoClient(token="tok").broker_summary("BBCA", "2024-12-02", "2024-12-02")
    assert out == broker_rows
    assert len(calls) == 2                  # one 429, one success
    assert len(sleeps) == 1 and sleeps[0] > 0


def test_get_honors_retry_after_header(monkeypatch, broker_rows):
    calls = []

    class Resp429:
        status_code = 429
        headers = {"Retry-After": "7"}
        def raise_for_status(self): pass

    class Resp200:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return broker_rows

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append(1)
        return Resp429() if len(calls) == 1 else Resp200()

    sleeps = []
    monkeypatch.setattr("kala.invezgo_fetch.requests.get", fake_get)
    monkeypatch.setattr("kala.invezgo_fetch.time.sleep", lambda s: sleeps.append(s))

    InvezgoClient(token="tok").broker_summary("BBCA", "2024-12-02", "2024-12-02")
    assert sleeps == [7.0]                  # Retry-After wins over backoff math


def test_get_gives_up_after_max_retries(monkeypatch):
    class Resp429:
        status_code = 429
        headers = {}
        def raise_for_status(self):
            import requests
            raise requests.HTTPError("429 too many requests")

    monkeypatch.setattr("kala.invezgo_fetch.requests.get", lambda *a, **k: Resp429())
    monkeypatch.setattr("kala.invezgo_fetch.time.sleep", lambda s: None)

    client = InvezgoClient(token="tok", max_retries=2)
    import requests
    with pytest.raises(requests.HTTPError):
        client.broker_summary("BBCA", "2024-12-02", "2024-12-02")


def test_broker_summary_non_list_response_is_empty(monkeypatch):
    class FakeResp:
        def raise_for_status(self): pass
        def json(self): return {"error": "nope"}

    monkeypatch.setattr("kala.invezgo_fetch.requests.get",
                        lambda *a, **k: FakeResp())
    assert InvezgoClient(token="t").broker_summary("BBCA", "2024-12-02", "2024-12-02") == []


# ---------------- fetch_daily_foreign_net ------------------------------------

class _FakeClient:
    """Returns the same per-broker payload for every day, and records which
    days/investor/market were asked for."""
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def broker_summary(self, code, from_date, to_date, investor="all", market="RG"):
        self.calls.append((code, from_date, to_date, investor, market))
        return self.payload


def test_fetch_daily_foreign_net_one_row_per_business_day(broker_rows):
    client = _FakeClient(broker_rows)
    df = fetch_daily_foreign_net("BBCA.JK", "2024-12-02", "2024-12-06", client=client)
    # Mon-Fri = 5 business days, one row each.
    assert len(df) == 5
    assert list(df.columns) == ["foreign_net_value", "foreign_buy_value",
                                "foreign_sell_value", "foreign_net_volume",
                                "foreign_top_broker_share"]
    # summing net across ALL brokers in the fixture is ~0 -- proves the sum
    # logic runs; with a real investor=foreign payload it'd be the foreign net.
    assert abs(df["foreign_net_value"].iloc[0]) < 1.0
    # buy_value sum is the real market-wide total from the fixture.
    assert df["foreign_buy_value"].iloc[0] == pytest.approx(7_964_637_800_000.0)
    # concentration is computable and bounded even on this real 86-broker day.
    share = df["foreign_top_broker_share"].iloc[0]
    assert 0.0 < share <= 1.0


# ---------------- _top_broker_share -------------------------------------------

def test_top_broker_share_one_dominant_broker():
    brokers = [{"net_value": "1000"}, {"net_value": "-10"}, {"net_value": "5"}]
    # |1000| dominates |1000|+|10|+|5| = 1015
    assert _top_broker_share(brokers) == pytest.approx(1000 / 1015)


def test_top_broker_share_evenly_split():
    brokers = [{"net_value": "100"}, {"net_value": "-100"}]
    assert _top_broker_share(brokers) == pytest.approx(0.5)


def test_top_broker_share_none_when_all_zero():
    brokers = [{"net_value": "0"}, {"net_value": "0"}]
    assert _top_broker_share(brokers) is None


def test_top_broker_share_none_for_empty_list():
    assert _top_broker_share([]) is None


def test_fetch_daily_foreign_net_strips_jk_and_defaults_investor_f(broker_rows):
    client = _FakeClient(broker_rows)
    fetch_daily_foreign_net("ANTM.JK", "2024-12-02", "2024-12-02", client=client)
    assert client.calls[0][0] == "ANTM"              # .JK stripped
    assert client.calls[0][3] == "f"                 # default investor -- NOT "foreign"
    assert client.calls[0][4] == "RG"                # default market


def test_fetch_daily_foreign_net_passes_through_investor_and_market(broker_rows):
    client = _FakeClient(broker_rows)
    fetch_daily_foreign_net("ANTM.JK", "2024-12-02", "2024-12-02",
                            client=client, investor="d", market="NG")
    assert client.calls[0][3] == "d"
    assert client.calls[0][4] == "NG"


def test_fetch_daily_foreign_net_skips_failed_days(broker_rows):
    class FlakyClient:
        def __init__(self): self.n = 0
        def broker_summary(self, code, f, t, investor="all", market="RG"):
            self.n += 1
            if self.n == 2:
                raise RuntimeError("rate limited")
            return broker_rows

    df = fetch_daily_foreign_net("BBCA.JK", "2024-12-02", "2024-12-04",
                                 client=FlakyClient())
    # 3 business days, middle one failed -> 2 rows, no exception raised.
    assert len(df) == 2


def test_fetch_daily_foreign_net_none_when_all_empty():
    client = _FakeClient([])
    assert fetch_daily_foreign_net("BBCA.JK", "2024-12-02", "2024-12-06",
                                   client=client) is None


def test_fetch_daily_output_feeds_the_archive(tmp_path, broker_rows):
    """End-to-end: the adapter's frame upserts into BrokerFlowArchive
    unchanged -- proves the column contract matches."""
    from kala.broker_flow_archive import BrokerFlowArchive

    df = fetch_daily_foreign_net("BBCA.JK", "2024-12-02", "2024-12-03",
                                 client=_FakeClient(broker_rows))
    arc = BrokerFlowArchive(tmp_path / "bf.db")
    n = arc.upsert("BBCA.JK", "invezgo", df)
    assert n == 2
    assert arc.read("BBCA.JK") is not None
