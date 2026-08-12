"""
Strategy zoo tests: a new (features, score) pair must get IDENTICAL
walk-forward treatment to the built-in momentum score -- same folds, same
cost model, same alpha check -- via score_override, not a parallel path.
"""

import numpy as np
import pandas as pd
import pytest

from kala.strategies import (
    Strategy,
    get_strategy,
    list_strategies,
    register_strategy,
    score_all,
    score_series,
    walk_forward_strategy,
)


def _make_df(n=400, seed=0, drift=0.001, start="2022-01-03"):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(start, periods=n)
    close = 1000.0 * np.exp(np.cumsum(rng.normal(drift, 0.015, n)))
    return pd.DataFrame(
        {"Open": close, "High": close * 1.005, "Low": close * 0.995,
         "Close": close, "Volume": np.full(n, 2_000_000.0)}, index=idx)


def test_momentum_is_registered_by_default():
    assert "momentum" in list_strategies()
    strat = get_strategy("momentum")
    assert strat.default_threshold == 60.0


def test_get_unknown_strategy_raises_with_available_list():
    with pytest.raises(KeyError, match="unknown strategy"):
        get_strategy("nope_this_does_not_exist")


def test_register_and_retrieve_custom_strategy():
    def feats(df):
        out = df.copy()
        out["dummy"] = 1.0
        return out

    def score(feats):
        return pd.Series(50.0, index=feats.index)

    register_strategy(Strategy(name="_test_dummy", compute_features=feats,
                               score=score, default_threshold=50.0))
    got = get_strategy("_test_dummy")
    assert got.name == "_test_dummy"
    assert "_test_dummy" in list_strategies()


def test_score_series_matches_compute_features_then_score():
    def feats(df):
        out = df.copy()
        out["x"] = out["Close"] * 2
        return out

    def score(f):
        return f["x"]

    strat = Strategy(name="_test_double", compute_features=feats, score=score,
                     default_threshold=1000.0)
    df = _make_df(n=50)
    s = score_series(strat, df)
    pd.testing.assert_series_equal(s, df["Close"] * 2, check_names=False)


def test_score_all_covers_every_ticker():
    def feats(df):
        return df

    def score(f):
        return f["Close"]

    strat = Strategy(name="_test_all", compute_features=feats, score=score,
                     default_threshold=0.0)
    dfs = {"A.JK": _make_df(seed=1), "B.JK": _make_df(seed=2)}
    scores = score_all(strat, dfs)
    assert set(scores) == {"A.JK", "B.JK"}
    assert len(scores["A.JK"]) == len(dfs["A.JK"])


def test_walk_forward_strategy_with_momentum_matches_plain_walk_forward():
    """The zoo's runner, called with the registered momentum strategy, must
    produce identical results to calling walk_forward directly with the
    default composite_score -- proving score_override round-trips cleanly,
    not a parallel/divergent code path."""
    from kala.walkforward import walk_forward

    dfs = {f"T{i}.JK": _make_df(seed=i, drift=0.0012 + 0.0002 * i) for i in range(3)}
    momentum = get_strategy("momentum")

    direct = walk_forward(dfs, train_bars=200, test_bars=60, warmup_bars=60,
                          thresholds=(45.0, 55.0, 65.0), min_train_trades=5)
    via_zoo = walk_forward_strategy(momentum, dfs, train_bars=200, test_bars=60,
                                    warmup_bars=60, thresholds=(45.0, 55.0, 65.0),
                                    min_train_trades=5)
    assert direct.pooled_baseline == via_zoo.pooled_baseline
    assert direct.pooled_chosen == via_zoo.pooled_chosen


def test_walk_forward_strategy_uses_strategy_own_threshold_grid_by_default():
    """A strategy whose score scale differs from 0-100 must NOT silently
    fall back to momentum's 50-75 grid -- that would be meaningless noise."""
    def feats(df):
        return df

    def score(f):
        # z-score-like scale: centered around 0, not 0-100
        return (f["Close"] - f["Close"].rolling(20).mean()) / f["Close"].rolling(20).std()

    strat = Strategy(name="_test_zscore", compute_features=feats, score=score,
                     default_threshold=0.5, default_thresholds_grid=(0.0, 0.5, 1.0))
    dfs = {"A.JK": _make_df(n=300, seed=5)}
    report = walk_forward_strategy(strat, dfs, train_bars=150, test_bars=60,
                                   warmup_bars=30, min_train_trades=1)
    for fr in report.folds:
        assert fr.chosen_threshold in (0.0, 0.5, 1.0)


def test_walk_forward_strategy_custom_thresholds_override():
    def feats(df):
        return df

    def score(f):
        return f["Close"] * 0 + 999.0    # constant, always above any reasonable threshold

    strat = Strategy(name="_test_const", compute_features=feats, score=score,
                     default_threshold=500.0, default_thresholds_grid=(500.0,))
    dfs = {"A.JK": _make_df(n=300, seed=6)}
    report = walk_forward_strategy(strat, dfs, thresholds=(10.0, 20.0),
                                   train_bars=150, test_bars=60, warmup_bars=30,
                                   min_train_trades=1)
    for fr in report.folds:
        assert fr.chosen_threshold in (10.0, 20.0)
