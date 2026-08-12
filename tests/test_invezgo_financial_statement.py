"""Invezgo financial-statement adapter tests: the normalizer runs against
the REAL /analysis/financial-statement/BBCA responses saved as fixtures (FY
and Q), with the HTTP layer mocked. Proves the {rows, columns} matrix
flattens to the long-format cells FundamentalArchive stores, and that the
fetch helper + archive column contract line up end to end."""

import json
from pathlib import Path

import pandas as pd
import pytest

from kala.fundamental_archive import FundamentalArchive
from kala.invezgo_fetch import (
    InvezgoClient,
    fetch_financial_statement,
    normalize_financial_statement,
)

FIXT = Path(__file__).parent / "fixtures"
FY_FIXTURE = FIXT / "invezgo_financial_statement_bbca_is_fy.json"
Q_FIXTURE = FIXT / "invezgo_financial_statement_bbca_is_q.json"


@pytest.fixture
def fy_response():
    return json.loads(FY_FIXTURE.read_text())


@pytest.fixture
def q_response():
    return json.loads(Q_FIXTURE.read_text())


# ---------------- normalize_financial_statement (real fixtures) --------------

def test_normalize_fy_flattens_matrix_to_long_cells(fy_response):
    df = normalize_financial_statement(fy_response)
    assert list(df.columns) == ["fiscal_year", "period", "line_item_id",
                                "line_item", "amount"]
    # 37 line items x 7 annual columns (FY2019..FY2025) = 259 cells, minus any
    # abstract header rows (dropped). Just assert it's a real, non-trivial grid.
    assert len(df) > 200
    assert set(df["period"]) == {"FY"}
    assert set(df["fiscal_year"]) == {2019, 2020, 2021, 2022, 2023, 2024, 2025}


def test_normalize_preserves_real_reported_values(fy_response):
    """Spot-check against known figures in the fixture: 'Beban bunga'
    (interest expense) differs year to year -- proves per-cell values are
    carried through, not collapsed."""
    df = normalize_financial_statement(fy_response)
    beban = df[df["line_item"] == "Beban bunga"].set_index("fiscal_year")["amount"]
    assert beban.loc[2025] == pytest.approx(13364495000000.0)
    assert beban.loc[2024] == pytest.approx(12532290000000.0)
    assert beban.loc[2019] == pytest.approx(-13360347000000.0)


def test_normalize_quarterly_carries_quarter_periods(q_response):
    df = normalize_financial_statement(q_response)
    # quarterly fixture columns span Q1 2026 back to Q2 2023.
    assert set(df["period"]) <= {"Q1", "Q2", "Q3", "Q4"}
    assert {"Q1", "Q2", "Q3"} <= set(df["period"])
    # (year, period) pairs must be distinct per line item -- no collision
    # between e.g. Q2 2025 and Q2 2024.
    one_item = df[df["line_item_id"] == df["line_item_id"].iloc[0]]
    assert one_item.duplicated(subset=["fiscal_year", "period"]).sum() == 0


def test_normalize_empty_or_garbage_response_is_empty_frame():
    assert normalize_financial_statement({}).empty
    assert normalize_financial_statement({"rows": []}).empty
    assert normalize_financial_statement(None).empty
    # columns still present so downstream code doesn't KeyError.
    assert list(normalize_financial_statement(None).columns) == \
        ["fiscal_year", "period", "line_item_id", "line_item", "amount"]


def test_normalize_skips_abstract_header_rows():
    resp = {
        "columns": [{"year": 2024, "period": "FY", "label": "FY 2024"}],
        "rows": [
            {"id": "hdr", "name": "ASSETS", "is_abstract": True,
             "values": [{"year": 2024, "period": "FY", "amount": None}]},
            {"id": "cash", "name": "Cash", "is_abstract": False,
             "values": [{"year": 2024, "period": "FY", "amount": 5.0}]},
        ],
    }
    df = normalize_financial_statement(resp)
    assert list(df["line_item"]) == ["Cash"]       # abstract header dropped


def test_normalize_absent_amount_is_none_not_zero():
    resp = {
        "columns": [{"year": 2024, "period": "FY"}],
        "rows": [{"id": "x", "name": "X", "is_abstract": False,
                  "values": [{"year": 2024, "period": "FY", "amount": None}]}],
    }
    df = normalize_financial_statement(resp)
    assert pd.isna(df["amount"].iloc[0])           # None -> NaN (archive stores NULL)


# ---------------- InvezgoClient.financial_statement --------------------------

def test_financial_statement_sends_params_and_auth(monkeypatch, fy_response):
    captured = {}

    class FakeResp:
        def raise_for_status(self): pass
        def json(self): return fy_response

    def fake_get(url, params=None, headers=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        captured["headers"] = headers
        return FakeResp()

    monkeypatch.setattr("kala.invezgo_fetch.requests.get", fake_get)
    out = InvezgoClient(token="tok").financial_statement("BBCA", statement="IS",
                                                         type_="FY", limit=8)
    assert out == fy_response
    assert captured["url"].endswith("/analysis/financial-statement/BBCA")
    # no market/investor/from/to for this endpoint -- only statement/type/limit.
    assert captured["params"] == {"statement": "IS", "type": "FY", "limit": 8}
    assert captured["headers"]["Authorization"] == "Bearer tok"


def test_financial_statement_non_dict_response_is_empty(monkeypatch):
    class FakeResp:
        def raise_for_status(self): pass
        def json(self): return ["unexpected", "list"]

    monkeypatch.setattr("kala.invezgo_fetch.requests.get", lambda *a, **k: FakeResp())
    assert InvezgoClient(token="t").financial_statement("BBCA") == {}


# ---------------- fetch_financial_statement (fetch_fn shape) -----------------

class _FakeClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def financial_statement(self, code, statement="IS", type_="FY", limit=8):
        self.calls.append((code, statement, type_, limit))
        return self.response


def test_fetch_financial_statement_strips_jk_and_normalizes(fy_response):
    client = _FakeClient(fy_response)
    df = fetch_financial_statement("BBCA.JK", statement="IS", client=client)
    assert client.calls[0][0] == "BBCA"            # .JK stripped
    assert df is not None and len(df) > 200
    assert list(df.columns) == ["fiscal_year", "period", "line_item_id",
                                "line_item", "amount"]


def test_fetch_financial_statement_none_on_empty(monkeypatch):
    df = fetch_financial_statement("BBCA.JK", client=_FakeClient({}))
    assert df is None


def test_fetch_financial_statement_swallows_errors():
    class Boom:
        def financial_statement(self, *a, **k):
            raise RuntimeError("network down")

    assert fetch_financial_statement("BBCA.JK", client=Boom()) is None


# ---------------- end-to-end: adapter output feeds the archive ---------------

def test_normalized_frame_records_into_archive(tmp_path, fy_response):
    """The adapter's long frame records into FundamentalArchive unchanged --
    proves the column contract matches, same as the broker-flow end-to-end
    test does for its archive."""
    df = normalize_financial_statement(fy_response)
    arc = FundamentalArchive(tmp_path / "f.db")
    n = arc.record("BBCA.JK", "IS", "invezgo", "2026-07-23", df)
    assert n == len(df)
    # and a point-in-time read comes back with the real FY2025 interest expense.
    snap = arc.as_of("BBCA.JK", "IS", "invezgo", "2026-07-23")
    beban = snap[(snap["line_item"] == "Beban bunga") & (snap["fiscal_year"] == 2025)]
    assert beban["amount"].iloc[0] == pytest.approx(13364495000000.0)
