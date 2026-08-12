"""
Linear, ridge-regularized alternative to composite_score's hand-tuned 40/30/30
weights — the flagged upgrade path: replace hand-tuned score weights with a
fitted linear/regression model that predicts forward returns, and treat
avg_net/trade (already an EV) as the primary optimization object.

Deliberately NOT deep learning and NOT a new dependency: closed-form ridge
regression on six point-in-time features, computed with plain numpy. Four of
those six are exactly what composite_score already uses (trend ratio, RSI,
ROC10, and implicitly through warmup, SMA50); two (ADX, ATR%) are indicators
compute_features already computes but composite_score never looks at. The
difference from the hand-tuned version isn't the inputs, it's that the
weights are FITTED from historical forward returns instead of hand-picked.

This is a proxy label, not the real trade outcome: the target is a simple
N-bar forward return, not a simulation of the actual exit engine (target
profit / stop / trailing / holding-max). A more faithful label would need to
run backtest_ticker per candidate day, which is far more expensive — noted
here rather than silently assumed away.

Leakage discipline: fit ONLY on a train window's data (the caller is
responsible for slicing that window before calling fit_ridge_scorer — this
module has no calendar awareness of its own), freeze the resulting
RidgeScorer, and call .score() on a *different* window. Standardization uses
the TRAIN mean/std, frozen into the scorer — scoring a test window never
recomputes statistics from test data. Mixing fit and score on the same window
is target leakage, not validation, exactly like tuning score_entry_threshold
on the window you're about to report results for.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .scoring import compute_features

FEATURE_COLUMNS = ("trend_ratio", "rsi", "roc_10", "macd_hist_pct", "adx", "atr_pct")

MIN_FIT_ROWS = 50  # below this, there's not enough evidence to trust a fit


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """Point-in-time predictor columns, index-aligned to df. Reuses
    compute_features so the model sees exactly what composite_score sees,
    plus adx/atr_pct (already computed there, never used by composite_score).
    """
    feats = compute_features(df)
    out = pd.DataFrame(index=feats.index)
    out["trend_ratio"] = feats["sma_fast"] / feats["sma_slow"] - 1.0
    out["rsi"] = feats["rsi"]
    out["roc_10"] = feats["roc_10"]
    out["macd_hist_pct"] = feats["macd_hist_pct"]
    out["adx"] = feats["adx"]
    out["atr_pct"] = feats["atr"] / feats["Close"] * 100.0
    return out


def forward_return_target(df: pd.DataFrame, horizon: int = 10) -> pd.Series:
    """Simple N-bar forward return in percent: (Close[t+horizon]/Close[t] - 1) * 100.

    NaN for the last `horizon` bars of `df` — there is no future to look at
    inside this slice. Callers must never backfill or otherwise resolve that
    NaN using data outside the slice; fit_ridge_scorer drops those rows.
    """
    close = df["Close"]
    return (close.shift(-horizon) / close - 1.0) * 100.0


@dataclass
class RidgeScorer:
    """Frozen, fitted linear scorer. `.score(df)` returns a Series directly
    comparable to a threshold — same contract as composite_score's output,
    just in predicted-forward-return-percent units instead of 0-100."""

    weights: np.ndarray             # len(FEATURE_COLUMNS), on STANDARDIZED features
    bias: float
    mean: np.ndarray                # TRAIN feature means (frozen at fit time)
    std: np.ndarray                 # TRAIN feature stds (frozen at fit time)
    horizon: int
    alpha: float
    n_train_rows: int

    def score(self, df: pd.DataFrame) -> pd.Series:
        X = build_features(df)
        valid = X.notna().all(axis=1)
        Xs = (X[list(FEATURE_COLUMNS)].to_numpy() - self.mean) / self.std
        pred = Xs @ self.weights + self.bias
        return pd.Series(pred, index=df.index).where(valid)

    def weights_by_feature(self) -> dict:
        return dict(zip(FEATURE_COLUMNS, self.weights.round(4).tolist()))


def fit_ridge_scorer(dfs: dict[str, pd.DataFrame], horizon: int = 10,
                     alpha: float = 10.0) -> RidgeScorer | None:
    """Pool (features, forward_return) rows across every ticker in `dfs` and
    fit closed-form ridge regression on STANDARDIZED features:

        w = (Xs^T Xs + alpha*I)^-1 Xs^T (y - mean(y))

    Ridge (not plain OLS) because six correlated technical-indicator columns
    on noisy financial data is exactly the setting where OLS coefficients
    blow up; alpha=10 is a deliberately conservative, UN-tuned regularization
    strength (tuning it via search would just reopen the overfitting question
    one level up) — it pulls the fit toward "small, stable weights" rather
    than chasing whichever column happens to fit train-window noise best.

    `dfs` is assumed to already be sliced to the caller's train window (this
    function has no calendar logic — see the module docstring on leakage
    discipline). Returns None if there isn't enough clean data to fit, so
    callers can fall back to the hand-tuned composite_score — the same
    "not enough evidence to deviate" discipline as pick_threshold's baseline
    fallback in walkforward.py.
    """
    X_rows, y_rows = [], []
    for df in dfs.values():
        X = build_features(df)
        y = forward_return_target(df, horizon)
        valid = X.notna().all(axis=1) & y.notna()
        if valid.sum() == 0:
            continue
        X_rows.append(X.loc[valid, list(FEATURE_COLUMNS)].to_numpy())
        y_rows.append(y.loc[valid].to_numpy())

    if not X_rows:
        return None
    X_all = np.concatenate(X_rows, axis=0)
    y_all = np.concatenate(y_rows, axis=0)
    if len(y_all) < MIN_FIT_ROWS:
        return None

    mean = X_all.mean(axis=0)
    std = X_all.std(axis=0)
    std[std == 0] = 1.0  # guard a constant column (e.g. ADX flat in a tiny sample)
    Xs = (X_all - mean) / std

    y_mean = float(y_all.mean())
    yc = y_all - y_mean
    n_features = Xs.shape[1]
    A = Xs.T @ Xs + alpha * np.eye(n_features)
    b = Xs.T @ yc
    w = np.linalg.solve(A, b)

    return RidgeScorer(weights=w, bias=y_mean, mean=mean, std=std,
                       horizon=horizon, alpha=alpha, n_train_rows=len(y_all))
