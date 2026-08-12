"""Gap finder for the broker-flow archive: holidays are not gaps."""

import numpy as np
import pandas as pd
import pytest

from kala.broker_flow_archive import BrokerFlowArchive
from refetch_flow_gaps import find_gaps


@pytest.fixture
def archive(tmp_path):
    """Two tickers over a long span; one shared closed day, one single-ticker hole."""
    db = tmp_path / "bf.db"
    a = BrokerFlowArchive(str(db))
    days = pd.bdate_range("2024-01-01", periods=420)
    holiday = days[100]          # absent for BOTH -> market holiday
    hole = days[200]             # absent for AAA only -> fetch failure

    for tk, drop in (("AAA.JK", {holiday, hole}), ("BBB.JK", {holiday})):
        idx = pd.DatetimeIndex([d for d in days if d not in drop])
        a.upsert(tk, "invezgo",
                 pd.DataFrame({"foreign_net_value": np.full(len(idx), 1e9)}, index=idx))
    return str(db), holiday, hole


def test_single_ticker_hole_is_a_gap(archive):
    db, _, hole = archive
    gaps, _, _ = find_gaps(db)
    assert "AAA.JK" in gaps
    assert hole in gaps["AAA.JK"]


def test_market_holiday_is_not_a_gap(archive):
    db, holiday, _ = archive
    gaps, holidays, _ = find_gaps(db)
    assert holiday in holidays
    assert holiday not in gaps.get("AAA.JK", [])
    assert "BBB.JK" not in gaps          # BBB is missing ONLY the holiday


def test_holidays_can_be_opted_back_in(archive):
    db, holiday, _ = archive
    gaps, _, _ = find_gaps(db, include_holidays=True)
    assert holiday in gaps["BBB.JK"]


def test_coverage_is_measured_against_trading_days(archive):
    db, _, _ = archive
    _, _, cov = find_gaps(db)
    assert cov["BBB.JK"] == 1.0          # complete once holidays are discounted
    assert cov["AAA.JK"] < 1.0


def test_empty_archive_is_not_an_error(tmp_path):
    BrokerFlowArchive(str(tmp_path / "empty.db"))
    assert find_gaps(str(tmp_path / "empty.db")) == ({}, [], {})
