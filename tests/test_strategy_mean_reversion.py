"""
Mean-reversion strategy tests: feature/score correctness, zoo registration,
and an end-to-end plumbing check through walk_forward_strategy. NOT a claim
of real edge -- the strategy itself is explicitly documented as UNTESTED
until a real walk-forward run is done; this only proves the code works.
"""

import numpy as np
import pandas as pd

import kala.strategy_mean_reversion  # noqa: F401  (registers "mean_reversion")
from kala.strategies import get_strategy, walk_forward_strategy
from kala.strategy_mean_reversion import (
    compute_features_mean_reversion,
    score_mean_reversion,
)


def _make_df(n=400, seed=0, drift=0.0005, start="2022-01-03"):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(start, periods=n)
    close = 1000.0 * np.exp(np.cumsum(rng.normal(drift, 0.015, n)))
    return pd.DataFrame(
        {"Open": close, "High": close * 1.005, "Low": close * 0.995,
         "Close": close, "Volume": np.full(n, 2_000_000.0)}, index=idx)


def _flat_then_drop_df(n=60):
    """Flat at 1000 for the warmup, then a sharp drop for the last bars --
    a stock trading well below its recent mean with oversold RSI."""
    idx = pd.bdate_range("2024-01-02", periods=n)
    close = np.full(n, 1000.0)
    close[-10:] = np.linspace(1000.0, 700.0, 10)
    return pd.DataFrame(
        {"Open": close, "High": close * 1.005, "Low": close * 0.995,
         "Close": close, "Volume": np.full(n, 1_000_000.0)}, index=idx)


def _flat_df(n=60):
    idx = pd.bdate_range("2024-01-02", periods=n)
    close = np.full(n, 1000.0)
    return pd.DataFrame(
        {"Open": close, "High": close * 1.005, "Low": close * 0.995,
         "Close": close, "Volume": np.full(n, 1_000_000.0)}, index=idx)


def _mild_noise_df(n=60, seed=7):
    """Small, mean-reverting wiggle around a flat level -- price stays AT
    its own rolling mean (no dip), so the mean-reversion score should read
    low, unlike a genuine oversold dip."""
    idx = pd.bdate_range("2024-01-02", periods=n)
    rng = np.random.default_rng(seed)
    close = 1000.0 + rng.normal(0.0, 1.0, n)
    return pd.DataFrame(
        {"Open": close, "High": close * 1.005, "Low": close * 0.995,
         "Close": close, "Volume": np.full(n, 1_000_000.0)}, index=idx)


# ---------------- compute_features_mean_reversion ---------------------------

def test_compute_features_adds_expected_columns():
    feats = compute_features_mean_reversion(_make_df(n=100))
    for col in ("sma_mid", "zscore", "rsi", "atr"):
        assert col in feats.columns


def test_compute_features_is_point_in_time_safe():
    """Truncating history must not change earlier feature values (no
    look-ahead) -- same contract as scoring.compute_features."""
    df = _make_df(n=200)
    full = compute_features_mean_reversion(df)
    truncated = compute_features_mean_reversion(df.iloc[:150])
    pd.testing.assert_series_equal(
        full["zscore"].iloc[:150], truncated["zscore"], check_names=False)
    pd.testing.assert_series_equal(
        full["rsi"].iloc[:150], truncated["rsi"], check_names=False)


def test_compute_features_zscore_nan_on_zero_std_not_crash():
    flat = _flat_df(n=60)
    feats = compute_features_mean_reversion(flat)
    assert feats["zscore"].tail(10).isna().all()


# ---------------- score_mean_reversion --------------------------------------

def test_score_high_for_oversold_dip():
    feats = compute_features_mean_reversion(_flat_then_drop_df())
    score = score_mean_reversion(feats)
    assert score.iloc[-1] > 50.0


def test_score_low_for_flat_at_mean():
    feats = compute_features_mean_reversion(_mild_noise_df())
    score = score_mean_reversion(feats)
    assert score.iloc[-1] < 25.0


def test_score_bounded_zero_to_hundred():
    feats = compute_features_mean_reversion(_make_df(n=300, seed=3))
    score = score_mean_reversion(feats)
    valid = score.dropna()
    assert (valid >= 0.0).all() and (valid <= 100.0).all()


# ---------------- zoo registration -------------------------------------------

def test_mean_reversion_is_registered():
    strat = get_strategy("mean_reversion")
    assert strat.name == "mean_reversion"
    assert strat.default_threshold == 60.0
    assert strat.default_thresholds_grid == (40.0, 50.0, 60.0, 70.0, 80.0)


# ---------------- end-to-end plumbing via walk_forward_strategy -------------

def test_walk_forward_strategy_runs_end_to_end_with_mean_reversion():
    """Not a claim of edge -- just proves the strategy runs cleanly through
    the SAME harness momentum uses, folds and all."""
    strat = get_strategy("mean_reversion")
    dfs = {f"T{i}.JK": _make_df(seed=i, drift=0.0003 * i) for i in range(3)}
    report = walk_forward_strategy(strat, dfs, train_bars=200, test_bars=60,
                                   warmup_bars=30, min_train_trades=1)
    assert len(report.folds) > 0
    for fr in report.folds:
        assert fr.chosen_threshold in strat.default_thresholds_grid
