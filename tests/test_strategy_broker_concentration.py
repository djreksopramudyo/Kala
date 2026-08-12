"""Broker-concentration strategy tests: feature/score math, the two-signal
blend (flow direction AND concentration), missing-data degradation, and
point-in-time safety. Synthetic, same spirit as test_strategy_foreign_flow.py
-- proves the SIGNAL logic; the real-data verdict needs a backfilled
archive."""

import numpy as np
import pandas as pd

import kala.strategy_broker_concentration  # noqa: F401  (registers "broker_concentration")
from kala.strategies import get_strategy, list_strategies
from kala.strategy_broker_concentration import (
    SHARE_COLUMN,
    compute_features_broker_concentration,
    score_broker_concentration,
)
from kala.strategy_foreign_flow import FLOW_COLUMN


def _ohlcv(n=60, start="2024-01-02"):
    idx = pd.bdate_range(start, periods=n)
    px = np.linspace(1000, 1100, n)
    return pd.DataFrame({"Open": px, "High": px * 1.01, "Low": px * 0.99,
                         "Close": px, "Volume": np.full(n, 1e6)}, index=idx)


def test_registered():
    assert "broker_concentration" in list_strategies()
    assert get_strategy("broker_concentration").name == "broker_concentration"


def test_missing_columns_yield_nan_score():
    feats = compute_features_broker_concentration(_ohlcv())
    assert feats["top_broker_share"].isna().all()
    assert score_broker_concentration(feats).isna().all()


def test_strong_buying_plus_high_concentration_scores_near_100():
    df = _ohlcv(n=60)
    df[FLOW_COLUMN] = np.concatenate([np.random.default_rng(0).normal(0, 1e6, 45),
                                      np.full(15, 5e8)])
    df[SHARE_COLUMN] = 0.9   # highly concentrated in one broker every day
    feats = compute_features_broker_concentration(df)
    score = score_broker_concentration(feats)
    assert score.iloc[47] > 80    # onset of the surge, same as foreign_flow


def test_diffuse_flow_caps_the_score_even_with_strong_buying():
    df = _ohlcv(n=60)
    df[FLOW_COLUMN] = np.concatenate([np.random.default_rng(0).normal(0, 1e6, 45),
                                      np.full(15, 5e8)])
    df[SHARE_COLUMN] = 0.05   # very diffuse -- many brokers, none dominant
    feats = compute_features_broker_concentration(df)
    score = score_broker_concentration(feats)
    # strong flow_z alone would score >80 (see test above); diffuse
    # concentration should pull the blended score down well below that.
    assert score.iloc[47] < 60


def test_high_concentration_but_net_selling_does_not_score_high():
    df = _ohlcv(n=60)
    df[FLOW_COLUMN] = np.concatenate([np.full(45, 1e7), np.full(15, -5e8)])  # selling
    df[SHARE_COLUMN] = 0.95  # concentrated selling
    feats = compute_features_broker_concentration(df)
    score = score_broker_concentration(feats)
    # flow_component is 0 (net selling -> z below mean -> clipped to 0),
    # so even with share=0.95 the blend caps at 0.5*0 + 0.5*95 = 47.5.
    assert score.iloc[-1] < 50


def test_score_bounded_0_100():
    df = _ohlcv(n=60)
    df[FLOW_COLUMN] = np.random.default_rng(1).normal(0, 1e8, 60)
    df[SHARE_COLUMN] = np.random.default_rng(2).uniform(0, 1, 60)
    score = score_broker_concentration(compute_features_broker_concentration(df))
    valid = score.dropna()
    assert (valid >= 0).all() and (valid <= 100).all()


def test_score_is_point_in_time():
    df = _ohlcv(n=60)
    df[FLOW_COLUMN] = np.random.default_rng(3).normal(1e7, 1e8, 60)
    df[SHARE_COLUMN] = np.random.default_rng(4).uniform(0, 1, 60)

    full = score_broker_concentration(compute_features_broker_concentration(df))
    cut = 40
    trunc = score_broker_concentration(compute_features_broker_concentration(df.iloc[:cut]))

    a = full.iloc[:cut].dropna()
    b = trunc.reindex(a.index)
    pd.testing.assert_series_equal(a, b, check_names=False)
