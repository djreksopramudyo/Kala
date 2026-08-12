"""Ramadan-effect strategy tests. The table is a pure per-row date lookup
with no dependency on other rows, so point-in-time safety is close to a
formality here -- but it's still verified empirically, matching house
style, rather than assumed. Plus the defining behavior (score 100 only
inside a known Ramadan range), the coverage-gap fail-closed behavior, and
that it needs no price data at all."""

import numpy as np
import pandas as pd

from kala.strategies import get_strategy, list_strategies, walk_forward_strategy
from kala.strategy_ramadan_effect import (
    RAMADAN_PERIODS,
    WARMUP_BARS,
    compute_features_ramadan,
    score_ramadan,
)


def _df(dates):
    idx = pd.DatetimeIndex(dates)
    close = np.full(len(idx), 100.0)
    return pd.DataFrame({"Open": close, "High": close, "Low": close,
                         "Close": close, "Volume": np.full(len(idx), 1e6)}, index=idx)


def test_registered_in_zoo():
    assert "ramadan_effect" in list_strategies()
    assert get_strategy("ramadan_effect").name == "ramadan_effect"


def test_table_has_no_overlaps_and_is_sorted():
    """Sanity check on the supplied table itself -- adjacent periods must not
    overlap and must be in chronological order (catches a fat-fingered date)."""
    starts = [pd.Timestamp(s) for s, _ in RAMADAN_PERIODS]
    ends = [pd.Timestamp(e) for _, e in RAMADAN_PERIODS]
    assert starts == sorted(starts)
    for s, e in zip(starts, ends):
        assert s <= e
    for i in range(len(starts) - 1):
        assert ends[i] < starts[i + 1]


def test_known_ramadan_dates_are_flagged():
    # 2024 Ramadan: 2024-03-12 .. 2024-04-09 (from the supplied table)
    df = _df(["2024-03-11", "2024-03-12", "2024-03-20", "2024-04-09", "2024-04-10"])
    feats = compute_features_ramadan(df)
    expected = [False, True, True, True, False]
    assert list(feats["is_ramadan"]) == expected


def test_dates_outside_table_coverage_fail_closed_not_unknown():
    """2016 (before the table's 2017 start) and 2027 (after its 2026 end)
    must read as NOT Ramadan, never as some 'unknown' sentinel -- the
    documented fail-closed behavior, not silently fabricated coverage."""
    df = _df(["2016-06-15", "2027-04-01"])
    feats = compute_features_ramadan(df)
    assert not feats["is_ramadan"].any()


def test_feature_point_in_time_safe_ignores_future_rows():
    """Even though a per-date table lookup can't realistically leak future
    rows, verify it empirically anyway: truncating after bar t must not
    change the value at t."""
    dates = pd.bdate_range("2024-02-01", periods=60)
    df = _df(dates)
    full = compute_features_ramadan(df)
    t = 30

    truncated = compute_features_ramadan(df.iloc[:t + 1])
    assert truncated["is_ramadan"].iloc[t] == full["is_ramadan"].iloc[t]


def test_score_is_100_only_during_ramadan():
    df = _df(["2024-03-11", "2024-03-12", "2024-04-09", "2024-04-10"])
    feats = compute_features_ramadan(df)
    s = score_ramadan(feats)
    assert list(s) == [0.0, 100.0, 100.0, 0.0]


def test_score_needs_no_price_data():
    """Defining property: identical dates score identically regardless of
    wildly different prices."""
    idx = pd.DatetimeIndex(["2024-03-15", "2024-03-16"])
    flat = pd.DataFrame({"Open": 100.0, "High": 101.0, "Low": 99.0,
                         "Close": 100.0, "Volume": 1e6}, index=idx)
    wild = pd.DataFrame({"Open": [50, 5000], "High": [51, 5001],
                         "Low": [49, 4999], "Close": [50, 5000],
                         "Volume": 1e6}, index=idx)
    s_flat = score_ramadan(compute_features_ramadan(flat))
    s_wild = score_ramadan(compute_features_ramadan(wild))
    assert (s_flat == s_wild).all()


def test_score_never_nan():
    df = _df(["2016-01-01", "2024-03-15", "2027-01-01"])
    s = score_ramadan(compute_features_ramadan(df))
    assert not s.isna().any()


# ---------------- harness warmup ---------------------------------------------

def test_declares_small_warmup_since_no_price_lookback_needed():
    assert get_strategy("ramadan_effect").warmup_bars == WARMUP_BARS
    assert WARMUP_BARS < 60


def test_walk_forward_takes_trades_during_ramadan_with_declared_warmup():
    """Through walk_forward_strategy, a basket of flat-price names spanning
    several real Ramadan periods must produce real OOS trades -- proving the
    signal fires from the date table alone, with no price movement needed."""
    idx = pd.bdate_range("2018-01-01", periods=1400)   # spans 2018-2023 Ramadans
    dfs = {}
    for i in range(6):
        close = np.full(len(idx), 100.0 + i)
        dfs[f"S{i}.JK"] = pd.DataFrame({"Open": close, "High": close, "Low": close,
                                        "Close": close, "Volume": np.full(len(idx), 2e6)},
                                       index=idx)
    rep = walk_forward_strategy(get_strategy("ramadan_effect"), dfs,
                                train_bars=350, test_bars=90)
    total = sum(fr.oos_chosen.get("n", 0) for fr in rep.folds)
    assert total > 0, "ramadan_effect takes zero trades — table lookup or warmup broke"
