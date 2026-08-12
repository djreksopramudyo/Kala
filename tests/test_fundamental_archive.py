"""FundamentalArchive tests: dated point-in-time storage of reported
financial statements. The load-bearing pieces are ``as_of`` (never return a
snapshot from the future) and ``diff_observations`` (detect restatements
between two dated pulls) — those get the most coverage."""

import numpy as np
import pandas as pd
import pytest

from kala.fundamental_archive import FundamentalArchive


def _snap(items):
    """Build a long-format snapshot frame from
    (fiscal_year, period, line_item_id, line_item, amount) tuples."""
    return pd.DataFrame(
        items, columns=["fiscal_year", "period", "line_item_id", "line_item", "amount"])


def _fy(year, amount, item_id="revenue", name="Revenue"):
    return (year, "FY", item_id, name, amount)


# ---------------- record / read round-trip -----------------------------------

def test_record_then_read_round_trips(tmp_path):
    arc = FundamentalArchive(tmp_path / "f.db")
    n = arc.record("BBCA.JK", "IS", "invezgo", "2026-07-23",
                   _snap([_fy(2024, 100.0), _fy(2023, 90.0)]))
    assert n == 2
    got = arc.read("BBCA.JK")
    assert got is not None and len(got) == 2
    assert set(got["amount"]) == {100.0, 90.0}
    assert (got["observed_date"] == "2026-07-23").all()


def test_record_preserves_explicit_zero_but_nulls_missing(tmp_path):
    """A vendor-reported 0 must stay 0.0 (measured), a NaN must become NULL
    (absent) — the NaN-vs-0 discipline. They are NOT the same thing."""
    arc = FundamentalArchive(tmp_path / "f.db")
    arc.record("A.JK", "IS", "invezgo", "2026-07-23",
               _snap([_fy(2024, 0.0, "premi", "Premi"),
                      _fy(2023, np.nan, "premi", "Premi")]))
    got = arc.read("A.JK").set_index("fiscal_year")
    assert got.loc[2024, "amount"] == 0.0        # reported zero kept
    assert pd.isna(got.loc[2023, "amount"])      # absent -> NULL, not 0


def test_record_rejects_missing_required_column(tmp_path):
    arc = FundamentalArchive(tmp_path / "f.db")
    bad = pd.DataFrame({"fiscal_year": [2024], "period": ["FY"]})
    with pytest.raises(ValueError, match="missing required column"):
        arc.record("A.JK", "IS", "invezgo", "2026-07-23", bad)


def test_record_empty_frame_is_noop(tmp_path):
    arc = FundamentalArchive(tmp_path / "f.db")
    assert arc.record("A.JK", "IS", "invezgo", "2026-07-23", pd.DataFrame()) == 0
    assert arc.read("A.JK") is None


def test_read_missing_ticker_returns_none(tmp_path):
    arc = FundamentalArchive(tmp_path / "f.db")
    assert arc.read("NOPE.JK") is None


# ---------------- the point-in-time invariant: dated snapshots coexist -------

def test_same_period_two_dates_coexist_not_overwritten(tmp_path):
    """Pulling FY2020 today and again later must NOT overwrite — both dated
    rows have to survive or restatement detection is impossible."""
    arc = FundamentalArchive(tmp_path / "f.db")
    arc.record("A.JK", "IS", "invezgo", "2026-01-01", _snap([_fy(2020, 500.0)]))
    arc.record("A.JK", "IS", "invezgo", "2026-07-01", _snap([_fy(2020, 555.0)]))  # restated
    got = arc.read("A.JK")
    assert len(got) == 2
    assert set(got["amount"]) == {500.0, 555.0}
    assert arc.observed_dates("A.JK") == ["2026-01-01", "2026-07-01"]


def test_re_record_same_observed_date_overwrites(tmp_path):
    arc = FundamentalArchive(tmp_path / "f.db")
    arc.record("A.JK", "IS", "invezgo", "2026-01-01", _snap([_fy(2020, 500.0)]))
    arc.record("A.JK", "IS", "invezgo", "2026-01-01", _snap([_fy(2020, 501.0)]))  # same day, fixed
    got = arc.read("A.JK")
    assert len(got) == 1                 # same (…, observed_date) key -> replaced
    assert got["amount"].iloc[0] == 501.0


# ---------------- as_of: never read from the future --------------------------

def test_as_of_returns_none_before_first_snapshot(tmp_path):
    arc = FundamentalArchive(tmp_path / "f.db")
    arc.record("A.JK", "IS", "invezgo", "2026-07-01", _snap([_fy(2020, 100.0)]))
    # a backtest date before we ever pulled anything: we knew nothing.
    assert arc.as_of("A.JK", "IS", "invezgo", "2026-06-30") is None


def test_as_of_picks_latest_snapshot_on_or_before_date(tmp_path):
    arc = FundamentalArchive(tmp_path / "f.db")
    arc.record("A.JK", "IS", "invezgo", "2026-01-01", _snap([_fy(2020, 100.0)]))
    arc.record("A.JK", "IS", "invezgo", "2026-04-01", _snap([_fy(2020, 200.0)]))  # restated
    arc.record("A.JK", "IS", "invezgo", "2026-07-01", _snap([_fy(2020, 300.0)]))  # restated again

    # as of March: only the Jan snapshot existed -> original figure.
    mar = arc.as_of("A.JK", "IS", "invezgo", "2026-03-15")
    assert mar["amount"].iloc[0] == 100.0
    assert "observed_date" not in mar.columns   # point-in-time read drops it

    # as of May: April snapshot is the latest we'd pulled.
    may = arc.as_of("A.JK", "IS", "invezgo", "2026-05-15")
    assert may["amount"].iloc[0] == 200.0

    # a future snapshot must never leak back to an earlier as-of date.
    assert 300.0 not in set(may["amount"])


def test_as_of_exact_date_boundary_is_inclusive(tmp_path):
    arc = FundamentalArchive(tmp_path / "f.db")
    arc.record("A.JK", "IS", "invezgo", "2026-04-01", _snap([_fy(2020, 200.0)]))
    on_the_day = arc.as_of("A.JK", "IS", "invezgo", "2026-04-01")
    assert on_the_day is not None and on_the_day["amount"].iloc[0] == 200.0


# ---------------- diff_observations: the restatement detector ----------------

def test_diff_detects_changed_amount(tmp_path):
    arc = FundamentalArchive(tmp_path / "f.db")
    arc.record("A.JK", "IS", "invezgo", "2026-01-01",
               _snap([_fy(2020, 100.0), _fy(2019, 90.0)]))
    arc.record("A.JK", "IS", "invezgo", "2026-07-01",
               _snap([_fy(2020, 111.0), _fy(2019, 90.0)]))   # only FY2020 revised
    diff = arc.diff_observations("A.JK", "IS", "invezgo", "2026-01-01", "2026-07-01")
    assert len(diff) == 1
    row = diff.iloc[0]
    assert row["fiscal_year"] == 2020
    assert row["amount_before"] == 100.0
    assert row["amount_after"] == 111.0


def test_diff_empty_when_identical(tmp_path):
    arc = FundamentalArchive(tmp_path / "f.db")
    same = _snap([_fy(2020, 100.0), _fy(2019, 90.0)])
    arc.record("A.JK", "IS", "invezgo", "2026-01-01", same)
    arc.record("A.JK", "IS", "invezgo", "2026-07-01", same)
    diff = arc.diff_observations("A.JK", "IS", "invezgo", "2026-01-01", "2026-07-01")
    assert diff.empty


def test_diff_ignores_newly_appeared_period(tmp_path):
    """A fiscal year that only shows up in the later pull is NEW DATA, not a
    restatement -- it must not appear in the diff."""
    arc = FundamentalArchive(tmp_path / "f.db")
    arc.record("A.JK", "IS", "invezgo", "2026-01-01", _snap([_fy(2020, 100.0)]))
    arc.record("A.JK", "IS", "invezgo", "2026-07-01",
               _snap([_fy(2020, 100.0), _fy(2021, 130.0)]))   # FY2021 is just newer
    diff = arc.diff_observations("A.JK", "IS", "invezgo", "2026-01-01", "2026-07-01")
    assert diff.empty


def test_diff_counts_value_to_null_transition_as_change(tmp_path):
    arc = FundamentalArchive(tmp_path / "f.db")
    arc.record("A.JK", "IS", "invezgo", "2026-01-01", _snap([_fy(2020, 100.0)]))
    arc.record("A.JK", "IS", "invezgo", "2026-07-01", _snap([_fy(2020, np.nan)]))
    diff = arc.diff_observations("A.JK", "IS", "invezgo", "2026-01-01", "2026-07-01")
    assert len(diff) == 1
    assert diff.iloc[0]["amount_before"] == 100.0
    assert pd.isna(diff.iloc[0]["amount_after"])


def test_diff_both_null_is_not_a_change(tmp_path):
    arc = FundamentalArchive(tmp_path / "f.db")
    arc.record("A.JK", "IS", "invezgo", "2026-01-01", _snap([_fy(2020, np.nan)]))
    arc.record("A.JK", "IS", "invezgo", "2026-07-01", _snap([_fy(2020, np.nan)]))
    diff = arc.diff_observations("A.JK", "IS", "invezgo", "2026-01-01", "2026-07-01")
    assert diff.empty


def test_diff_returns_empty_when_a_snapshot_missing(tmp_path):
    arc = FundamentalArchive(tmp_path / "f.db")
    arc.record("A.JK", "IS", "invezgo", "2026-01-01", _snap([_fy(2020, 100.0)]))
    # 'after' date never recorded -> nothing to compare, empty (not a crash).
    diff = arc.diff_observations("A.JK", "IS", "invezgo", "2026-01-01", "2099-01-01")
    assert diff.empty
    assert list(diff.columns) == ["fiscal_year", "period", "line_item_id",
                                  "line_item", "amount_before", "amount_after"]


# ---------------- misc scoping / persistence ---------------------------------

def test_statements_kept_separate(tmp_path):
    arc = FundamentalArchive(tmp_path / "f.db")
    arc.record("A.JK", "IS", "invezgo", "2026-07-23", _snap([_fy(2020, 1.0)]))
    arc.record("A.JK", "BS", "invezgo", "2026-07-23", _snap([_fy(2020, 2.0)]))
    assert len(arc.read("A.JK")) == 2
    assert len(arc.read("A.JK", statement="BS")) == 1
    assert arc.read("A.JK", statement="BS")["amount"].iloc[0] == 2.0


def test_tickers_lists_distinct(tmp_path):
    arc = FundamentalArchive(tmp_path / "f.db")
    arc.record("B.JK", "IS", "invezgo", "2026-07-23", _snap([_fy(2020, 1.0)]))
    arc.record("A.JK", "IS", "invezgo", "2026-07-23", _snap([_fy(2020, 1.0)]))
    assert arc.tickers() == ["A.JK", "B.JK"]


def test_persists_across_new_instances(tmp_path):
    path = tmp_path / "f.db"
    FundamentalArchive(path).record("A.JK", "IS", "invezgo", "2026-07-23",
                                    _snap([_fy(2020, 1.0)]))
    assert FundamentalArchive(path).read("A.JK") is not None


# ---------------- get_or_snapshot: idempotent-within-a-day fetch -------------

def test_get_or_snapshot_skips_fetch_when_today_already_recorded(tmp_path):
    arc = FundamentalArchive(tmp_path / "f.db")
    arc.record("A.JK", "IS", "invezgo", "2026-07-23", _snap([_fy(2020, 1.0)]))
    calls = []

    def fetch_fn(t, s):
        calls.append((t, s))
        return _snap([_fy(2020, 999.0)])

    got = arc.get_or_snapshot("A.JK", "IS", "invezgo", "2026-07-23", fetch_fn)
    assert len(calls) == 0                       # already had today's snapshot
    assert got["amount"].iloc[0] == 1.0
    assert "observed_date" not in got.columns


def test_get_or_snapshot_fetches_and_stores_when_absent(tmp_path):
    arc = FundamentalArchive(tmp_path / "f.db")
    calls = []

    def fetch_fn(t, s):
        calls.append((t, s))
        return _snap([_fy(2020, 42.0)])

    got = arc.get_or_snapshot("A.JK", "IS", "invezgo", "2026-07-23", fetch_fn)
    assert calls == [("A.JK", "IS")]
    assert got["amount"].iloc[0] == 42.0
    assert arc.read("A.JK") is not None           # persisted


def test_get_or_snapshot_degrades_on_fetch_none(tmp_path):
    arc = FundamentalArchive(tmp_path / "f.db")
    assert arc.get_or_snapshot("A.JK", "IS", "invezgo", "2026-07-23",
                               lambda t, s: None) is None


def test_get_or_snapshot_swallows_fetch_exceptions(tmp_path):
    arc = FundamentalArchive(tmp_path / "f.db")

    def raising(t, s):
        raise RuntimeError("network down")

    # no prior snapshot -> degrades to None, does not raise.
    assert arc.get_or_snapshot("A.JK", "IS", "invezgo", "2026-07-23", raising) is None
