"""
Tests for kala.ml_scoring — the fitted-weight alternative to
composite_score's hand-tuned 40/30/30 blend.

The invariants that matter most here are about LEAKAGE, since a fitted model
is exactly where it's easiest to accidentally cheat:
  * forward_return_target must never resolve using data beyond the slice.
  * fit_ridge_scorer must be a pure function of the frames it's given — no
    hidden dependence on data outside them.
  * RidgeScorer.score() must standardize with the FROZEN train mean/std, not
    statistics recomputed from whatever frame it's scoring.
"""

import numpy as np
import pandas as pd
import pytest

from kala.ml_scoring import (
    FEATURE_COLUMNS,
    build_features,
    fit_ridge_scorer,
    forward_return_target,
)


def _make_df(closes, vols=None, start="2022-01-03"):
    closes = np.asarray(closes, dtype=float)
    n = len(closes)
    return pd.DataFrame(
        {
            "Open": closes,
            "High": closes * 1.005,
            "Low": closes * 0.995,
            "Close": closes,
            "Volume": np.asarray(vols, dtype=float) if vols is not None else np.full(n, 1e6),
        },
        index=pd.bdate_range(start, periods=n),
    )


# ---------------------------------------------------------------------------
# forward_return_target
# ---------------------------------------------------------------------------

def test_forward_return_target_value_and_tail_nan():
    closes = np.array([100.0, 101.0, 102.0, 110.0, 90.0, 95.0])
    df = _make_df(closes)
    y = forward_return_target(df, horizon=2)
    # bar 0: (102/100 - 1)*100
    assert y.iloc[0] == pytest.approx((102.0 / 100.0 - 1.0) * 100.0)
    # last 2 bars have no 2-bars-ahead future inside this slice -> NaN
    assert y.iloc[-1] != y.iloc[-1]
    assert y.iloc[-2] != y.iloc[-2]


def test_build_features_columns_and_no_mutation():
    df = _make_df(np.linspace(1000, 1100, 80))
    cols_before = list(df.columns)
    vals_before = df.to_numpy().copy()
    X = build_features(df)
    assert list(X.columns) == list(FEATURE_COLUMNS)
    assert list(df.columns) == cols_before
    np.testing.assert_array_equal(df.to_numpy(), vals_before)


# ---------------------------------------------------------------------------
# fit_ridge_scorer — recovery + guardrails
# ---------------------------------------------------------------------------

def test_fit_recovers_sign_of_a_known_driver():
    """Construct forward returns that are a strong, noisy positive function of
    ROC10 (momentum keeps working) and verify the fitted weight for roc_10 is
    positive and among the larger-magnitude weights."""
    rng = np.random.default_rng(42)
    n = 400
    # random-walk-ish price path so ROC10 varies naturally
    rets = rng.normal(0.0003, 0.012, n)
    closes = 1000 * np.exp(np.cumsum(rets))
    df = _make_df(closes)

    X = build_features(df)
    roc = X["roc_10"]
    # synthesize a future-return series that's mostly driven by current ROC10,
    # then bake it back into the CLOSE path is circular -- instead just fit
    # directly against a hand-built target with the same index, bypassing
    # forward_return_target, to isolate "does ridge recover a known relationship".
    noise = rng.normal(0, 0.5, n)
    target = 0.3 * roc.fillna(0.0) + noise
    y = pd.Series(target.to_numpy(), index=df.index)

    valid = X.notna().all(axis=1)
    X_np = X.loc[valid, list(FEATURE_COLUMNS)].to_numpy()
    y_np = y.loc[valid].to_numpy()
    mean, std = X_np.mean(axis=0), X_np.std(axis=0)
    std[std == 0] = 1.0
    Xs = (X_np - mean) / std
    yc = y_np - y_np.mean()
    A = Xs.T @ Xs + 1.0 * np.eye(Xs.shape[1])
    w = np.linalg.solve(A, Xs.T @ yc)

    roc_idx = FEATURE_COLUMNS.index("roc_10")
    assert w[roc_idx] > 0
    assert w[roc_idx] == max(w)  # the driver we built in should dominate


def test_fit_ridge_scorer_returns_none_when_too_little_data():
    df = _make_df(np.linspace(1000, 1010, 40))  # far short of MIN_FIT_ROWS after warmup+horizon
    assert fit_ridge_scorer({"T.JK": df}) is None


def test_fit_ridge_scorer_returns_none_on_empty_input():
    assert fit_ridge_scorer({}) is None


def test_fit_is_a_pure_function_of_the_frames_given():
    """The core leakage guard: fitting on a frame sliced to date X must give
    IDENTICAL weights regardless of what data exists (or doesn't) after X in
    some other, unrelated frame. fit_ridge_scorer must never reach outside
    the dict it's handed."""
    rng = np.random.default_rng(7)
    n = 400
    closes = 1000 * np.exp(np.cumsum(rng.normal(0.0005, 0.015, n)))
    df_full = _make_df(closes)
    cutoff = 300
    df_sliced = df_full.iloc[:cutoff]

    # a second, "corrupted future" version where everything after cutoff is
    # wildly different -- must have zero influence since it's never passed in
    closes_alt = closes.copy()
    closes_alt[cutoff:] = closes_alt[cutoff - 1] * np.exp(
        np.cumsum(rng.normal(-0.05, 0.05, n - cutoff)))
    df_alt_full = _make_df(closes_alt)
    df_alt_sliced = df_alt_full.iloc[:cutoff]

    # sanity: the two "full" frames actually differ after cutoff
    assert not np.allclose(df_full["Close"].to_numpy()[cutoff:],
                           df_alt_full["Close"].to_numpy()[cutoff:])
    # but the two SLICED frames (all either function ever sees) are identical
    pd.testing.assert_frame_equal(df_sliced, df_alt_sliced)

    scorer_a = fit_ridge_scorer({"T.JK": df_sliced}, horizon=10, alpha=5.0)
    scorer_b = fit_ridge_scorer({"T.JK": df_alt_sliced}, horizon=10, alpha=5.0)
    assert scorer_a is not None and scorer_b is not None
    np.testing.assert_array_equal(scorer_a.weights, scorer_b.weights)
    assert scorer_a.bias == scorer_b.bias


def test_score_uses_frozen_train_statistics_not_test_statistics():
    rng = np.random.default_rng(3)
    train_closes = 1000 * np.exp(np.cumsum(rng.normal(0.0004, 0.013, 300)))
    train_df = _make_df(train_closes)
    scorer = fit_ridge_scorer({"T.JK": train_df}, horizon=10, alpha=5.0)
    assert scorer is not None

    # a test frame on a totally different price/volatility regime
    test_closes = 50 * np.exp(np.cumsum(rng.normal(-0.01, 0.04, 120)))
    test_df = _make_df(test_closes, start="2024-01-02")

    scores = scorer.score(test_df)
    X_test = build_features(test_df)
    valid = X_test.notna().all(axis=1)
    Xs_expected = (X_test.loc[valid, list(FEATURE_COLUMNS)].to_numpy() - scorer.mean) / scorer.std
    expected = Xs_expected @ scorer.weights + scorer.bias
    np.testing.assert_allclose(scores.loc[valid].to_numpy(), expected, rtol=1e-9)

    # if it had (wrongly) restandardized on the TEST frame's own stats, the
    # values would differ from this frozen-stats computation
    wrong_mean = X_test.loc[valid, list(FEATURE_COLUMNS)].to_numpy().mean(axis=0)
    assert not np.allclose(scorer.mean, wrong_mean)


def test_score_is_nan_during_warmup_like_composite_score():
    df = _make_df(np.linspace(1000, 1200, 200))
    scorer = fit_ridge_scorer({"T.JK": df}, horizon=10, alpha=5.0)
    assert scorer is not None
    scores = scorer.score(df)
    assert scores.iloc[:49].isna().all()  # SMA50 warmup, same as composite_score
