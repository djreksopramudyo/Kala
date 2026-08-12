"""
Multi-horizon sign-sum trend tests.

The signal is simple enough that the risk isn't subtle look-ahead (shift()
only reaches backwards) but rather getting the AGGREGATION wrong in ways that
silently change what's being tested: signs mis-summed, flat stretches read as
uptrends, or the 0-100 mapping putting "neutral" somewhere other than where
the threshold grid assumes it is.
"""

import numpy as np
import pandas as pd

from kala.strategies import get_strategy
from kala.strategy_multihorizon_trend import (
    LOOKBACKS,
    compute_features_multihorizon_trend,
    score_multihorizon_trend,
)


def _frame(closes):
    closes = np.asarray(closes, dtype=float)
    n = len(closes)
    idx = pd.bdate_range("2020-01-01", periods=n)
    return pd.DataFrame({"Open": closes, "High": closes * 1.01,
                         "Low": closes * 0.99, "Close": closes,
                         "Volume": np.full(n, 1_000_000.0)}, index=idx)


def _feats(closes):
    return compute_features_multihorizon_trend(_frame(closes))


# ---------------- the sign sum ---------------------------------------------------

def test_monotonically_rising_series_scores_maximum():
    """Every horizon up -> sum = +4 -> score 100."""
    feats = _feats(np.linspace(100, 200, 120))
    assert feats["trend_sign_sum"].iloc[-1] == len(LOOKBACKS)
    assert score_multihorizon_trend(feats).iloc[-1] == 100.0


def test_monotonically_falling_series_scores_zero():
    feats = _feats(np.linspace(200, 100, 120))
    assert feats["trend_sign_sum"].iloc[-1] == -len(LOOKBACKS)
    assert score_multihorizon_trend(feats).iloc[-1] == 0.0


def test_flat_series_is_neutral_not_bullish():
    """Exact ties must contribute 0, not +1 -- a stock that didn't move is
    not in an uptrend. Matters on thinly-traded IDX names that print the
    same close for days."""
    feats = _feats(np.full(120, 1000.0))
    assert feats["trend_sign_sum"].iloc[-1] == 0
    assert score_multihorizon_trend(feats).iloc[-1] == 50.0


def test_mixed_horizons_land_between_the_extremes():
    """Recent up, older down -> some horizons agree, some don't."""
    closes = np.concatenate([np.linspace(200, 100, 80), np.linspace(100, 130, 15)])
    feats = _feats(closes)
    total = feats["trend_sign_sum"].iloc[-1]
    assert -len(LOOKBACKS) < total < len(LOOKBACKS)
    score = score_multihorizon_trend(feats).iloc[-1]
    assert 0.0 < score < 100.0


def test_sum_matches_a_hand_computed_value():
    """Independent recomputation of the definition, not a re-run of the code
    under test."""
    rng = np.random.default_rng(7)
    closes = 1000 * np.exp(np.cumsum(rng.normal(0, 0.02, 200)))
    feats = _feats(closes)
    t = 150
    expected = sum(np.sign(closes[t] - closes[t - lb]) for lb in LOOKBACKS)
    assert feats["trend_sign_sum"].iloc[t] == expected


def test_sum_is_bounded_by_the_number_of_lookbacks():
    rng = np.random.default_rng(3)
    closes = 1000 * np.exp(np.cumsum(rng.normal(0, 0.03, 400)))
    total = _feats(closes)["trend_sign_sum"].dropna()
    assert total.abs().max() <= len(LOOKBACKS)


# ---------------- point-in-time --------------------------------------------------

def test_score_at_bar_t_is_unchanged_by_future_bars():
    """Truncating at bar t must not change bar t's value. shift() cannot look
    forward, but this guards a future refactor from introducing something
    that can (e.g. a centered window or a full-series normalization)."""
    rng = np.random.default_rng(11)
    closes = 1000 * np.exp(np.cumsum(rng.normal(0.0005, 0.02, 300)))
    full = _feats(closes)
    for t in (100, 180, 260):
        truncated = compute_features_multihorizon_trend(_frame(closes[:t + 1]))
        a, b = full["trend_sign_sum"].iloc[t], truncated["trend_sign_sum"].iloc[t]
        assert (pd.isna(a) and pd.isna(b)) or a == b


def test_early_bars_are_nan_until_the_longest_lookback_is_available():
    feats = _feats(np.linspace(100, 200, 120))
    longest = max(LOOKBACKS)
    assert feats["trend_sign_sum"].iloc[:longest].isna().all()
    assert feats["trend_sign_sum"].iloc[longest:].notna().all()


def test_nan_score_means_no_entry_not_a_bad_score():
    feats = _feats(np.linspace(100, 200, 120))
    assert score_multihorizon_trend(feats).iloc[:max(LOOKBACKS)].isna().all()


# ---------------- score mapping / threshold contract -----------------------------

def test_neutral_maps_to_fifty_so_the_threshold_grid_means_what_it_says():
    """The registered grid assumes 50 is neutral: 60 selects 'majority of
    horizons up', 40 selects 'no net downtrend'. If this mapping moves, the
    grid silently starts testing different rules."""
    feats = pd.DataFrame({"trend_sign_sum": [-4.0, -2.0, 0.0, 2.0, 4.0]})
    scores = score_multihorizon_trend(feats)
    assert list(scores) == [0.0, 25.0, 50.0, 75.0, 100.0]


def test_score_is_monotone_in_the_sign_sum():
    feats = pd.DataFrame({"trend_sign_sum": [-4.0, -2.0, 0.0, 2.0, 4.0]})
    scores = score_multihorizon_trend(feats)
    assert list(scores) == sorted(scores)


def test_registered_thresholds_select_distinct_rules():
    """A grid whose entries collapse to the same rule wastes folds."""
    strat = get_strategy("multihorizon_trend")
    levels = [0.0, 25.0, 50.0, 75.0, 100.0]
    selected = {thr: tuple(x >= thr for x in levels)
                for thr in strat.default_thresholds_grid}
    assert len(set(selected.values())) == len(strat.default_thresholds_grid)


# ---------------- registration + harness contract --------------------------------

def test_registered_in_the_zoo():
    strat = get_strategy("multihorizon_trend")
    assert strat.name == "multihorizon_trend"
    assert strat.warmup_bars > max(LOOKBACKS)
    # Result recorded 2026-08-03 (see PROJECT_STATUS.md): null-to-negative,
    # not untested -- the description must say so plainly rather than
    # leaving a stale "UNTESTED" claim once a real verdict exists.
    assert "NEGATIVE" in strat.description
    assert "Do not trade" in strat.description


def test_features_keep_all_original_columns():
    df = _frame(np.linspace(100, 200, 120))
    feats = compute_features_multihorizon_trend(df)
    for col in ("Open", "High", "Low", "Close", "Volume"):
        assert col in feats.columns
    assert len(feats) == len(df)


def test_short_history_produces_no_signal_rather_than_crashing():
    feats = _feats(np.linspace(100, 110, 10))
    assert feats["trend_sign_sum"].isna().all()
    assert score_multihorizon_trend(feats).isna().all()


def test_does_not_mutate_the_caller_frame():
    df = _frame(np.linspace(100, 200, 120))
    before = set(df.columns)
    compute_features_multihorizon_trend(df)
    assert set(df.columns) == before
