"""Foreign-flow strategy tests: merge helper, feature/score math, the
degrade-to-no-signal contract when broker data is absent, and point-in-time
safety. All synthetic -- proves the SIGNAL logic; the real-data verdict is a
separate walk_forward_strategy run on a backfilled archive (see
strategy_foreign_flow.py's STATUS note)."""

import numpy as np
import pandas as pd

import kala.strategy_foreign_flow  # noqa: F401  (registers "foreign_flow")
from kala.strategies import get_strategy, list_strategies
from kala.strategy_foreign_flow import (
    FLOW_COLUMN,
    attach_foreign_flow,
    compute_features_foreign_flow,
    score_foreign_flow,
)


def _ohlcv(n=60, start="2024-01-02"):
    idx = pd.bdate_range(start, periods=n)
    px = np.linspace(1000, 1100, n)
    return pd.DataFrame({"Open": px, "High": px * 1.01, "Low": px * 0.99,
                         "Close": px, "Volume": np.full(n, 1e6)}, index=idx)


class _FakeArchive:
    """Minimal stand-in for BrokerFlowArchive.read."""
    def __init__(self, frames):
        self._frames = frames        # {ticker: DataFrame with FLOW_COLUMN}

    def read(self, ticker, source=None, start=None, end=None):
        return self._frames.get(ticker)


# ---------------- registration ----------------------------------------------

def test_foreign_flow_registered():
    assert "foreign_flow" in list_strategies()
    assert get_strategy("foreign_flow").name == "foreign_flow"


# ---------------- attach_foreign_flow ---------------------------------------

def test_attach_merges_flow_column_by_date():
    df = _ohlcv(n=10)
    flow = pd.DataFrame({FLOW_COLUMN: np.arange(10.0)}, index=df.index)
    out = attach_foreign_flow({"BBCA.JK": df}, _FakeArchive({"BBCA.JK": flow}))
    assert FLOW_COLUMN in out["BBCA.JK"].columns
    assert out["BBCA.JK"][FLOW_COLUMN].iloc[3] == 3.0


def test_attach_leaves_uncovered_ticker_without_flow_column():
    df = _ohlcv(n=10)
    out = attach_foreign_flow({"NOPE.JK": df}, _FakeArchive({}))
    assert FLOW_COLUMN not in out["NOPE.JK"].columns


def test_attach_does_not_mutate_input():
    df = _ohlcv(n=10)
    flow = pd.DataFrame({FLOW_COLUMN: np.arange(10.0)}, index=df.index)
    attach_foreign_flow({"BBCA.JK": df}, _FakeArchive({"BBCA.JK": flow}))
    assert FLOW_COLUMN not in df.columns          # original untouched


def test_attach_reindexes_partial_coverage_to_nan():
    df = _ohlcv(n=10)
    # archive only covers the first 3 dates
    flow = pd.DataFrame({FLOW_COLUMN: [1.0, 2.0, 3.0]}, index=df.index[:3])
    out = attach_foreign_flow({"BBCA.JK": df}, _FakeArchive({"BBCA.JK": flow}))
    merged = out["BBCA.JK"]
    assert merged[FLOW_COLUMN].iloc[0] == 1.0
    assert pd.isna(merged[FLOW_COLUMN].iloc[5])    # uncovered day -> NaN


# ---------------- features + score: missing data ----------------------------

def test_features_missing_column_yield_nan_score():
    feats = compute_features_foreign_flow(_ohlcv())
    assert feats["flow_z"].isna().all()
    assert score_foreign_flow(feats).isna().all()   # -> never enters


# ---------------- features + score: real signal -----------------------------

def test_strong_sustained_buying_scores_high():
    df = _ohlcv(n=60)
    # flat modest flow, then a sustained surge starting at day 45
    flow = np.concatenate([np.random.default_rng(0).normal(0, 1e6, 45),
                           np.full(15, 5e8)])
    df[FLOW_COLUMN] = flow
    feats = compute_features_foreign_flow(df)
    score = score_foreign_flow(feats)
    # the ONSET of the surge scores near the top -- foreign buying that is
    # unusually strong vs the stock's own recent norm...
    assert score.iloc[47] > 80
    # ...and an early flat-flow day (before the surge) does not.
    assert score.iloc[25] < 40
    # By design the score DECAYS as the surge becomes the new normal (the
    # z-score is 'unusual vs recent', not a running level) -- so 12 days into
    # a sustained surge it has faded well back down.
    assert score.iloc[-1] < score.iloc[47]


def test_net_selling_scores_zero():
    df = _ohlcv(n=60)
    df[FLOW_COLUMN] = np.concatenate([np.full(45, 1e7), np.full(15, -5e8)])
    feats = compute_features_foreign_flow(df)
    score = score_foreign_flow(feats)
    assert score.iloc[-1] == 0.0        # z below mean -> clipped to 0


def test_score_bounded_0_100():
    df = _ohlcv(n=60)
    df[FLOW_COLUMN] = np.random.default_rng(1).normal(0, 1e8, 60)
    score = score_foreign_flow(compute_features_foreign_flow(df))
    valid = score.dropna()
    assert (valid >= 0).all() and (valid <= 100).all()


# ---------------- point-in-time safety --------------------------------------

def test_score_is_point_in_time():
    """Truncating the frame at bar t must not change the score at any bar
    <= t: features look only backward, never at future flow."""
    df = _ohlcv(n=60)
    df[FLOW_COLUMN] = np.random.default_rng(2).normal(1e7, 1e8, 60)

    full = score_foreign_flow(compute_features_foreign_flow(df))
    cut = 40
    trunc = score_foreign_flow(compute_features_foreign_flow(df.iloc[:cut]))

    a = full.iloc[:cut].dropna()
    b = trunc.reindex(a.index)
    pd.testing.assert_series_equal(a, b, check_names=False)
