"""52-week-high proximity strategy tests. The non-negotiable one is
point-in-time safety: the nearness ratio at bar t must not move when FUTURE
bars change. Plus monotonicity (closer to the high -> higher score), the
ratio's (0, 1] bound, NaN handling, and warmup. Also a test that pins the
DISTINCTION from momentum: a stock that ran up then pulled back has weak
nearness despite strong trailing return."""

import numpy as np
import pandas as pd

from kala.strategies import get_strategy, list_strategies, walk_forward_strategy
from kala.strategy_high_proximity import (
    FLOOR_DISCOUNT,
    HIGH_WINDOW,
    WARMUP_BARS,
    compute_features_high_proximity,
    score_high_proximity,
)


def _df(close, start="2019-01-01"):
    close = np.asarray(close, dtype=float)
    idx = pd.bdate_range(start, periods=len(close))
    return pd.DataFrame({"Open": close, "High": close * 1.01, "Low": close * 0.99,
                         "Close": close, "Volume": np.full(len(close), 1e6)}, index=idx)


def test_registered_in_zoo():
    assert "high_proximity" in list_strategies()
    assert get_strategy("high_proximity").name == "high_proximity"


def test_feature_is_nan_until_enough_history():
    df = _df(np.linspace(100, 200, HIGH_WINDOW - 5))   # fewer than HIGH_WINDOW bars
    feats = compute_features_high_proximity(df)
    assert feats["high_nearness"].isna().all()


def test_nearness_is_bounded_0_to_1():
    """The current close is always <= a trailing max that includes it, so the
    ratio can never exceed 1.0 and (for positive prices) never be <= 0."""
    rng = np.random.default_rng(1)
    close = 1000 * np.exp(np.cumsum(rng.normal(0.0, 0.02, HIGH_WINDOW + 100)))
    feats = compute_features_high_proximity(_df(close))
    near = feats["high_nearness"].dropna()
    assert (near > 0).all() and (near <= 1.0 + 1e-9).all()


def test_at_new_high_nearness_is_one():
    """A strictly increasing series is always at its own trailing high, so
    nearness == 1.0 everywhere it's defined."""
    df = _df(np.linspace(100, 300, HIGH_WINDOW + 50))
    feats = compute_features_high_proximity(df)
    assert feats["high_nearness"].dropna().min() == \
        __import__("pytest").approx(1.0)


def test_feature_point_in_time_safe_ignores_future():
    """The whole ballgame: bar t's nearness must be identical whether or not
    later bars exist / change. Mutate everything strictly after t, recompute,
    confirm t is unchanged."""
    rng = np.random.default_rng(3)
    close = 1000 * np.exp(np.cumsum(rng.normal(0.0003, 0.015, HIGH_WINDOW + 80)))
    full = compute_features_high_proximity(_df(close))
    t = HIGH_WINDOW + 40

    close_mut = close.copy()
    close_mut[t + 1:] *= 5.0            # huge future high strictly after t
    mut = compute_features_high_proximity(_df(close_mut))
    assert mut["high_nearness"].iloc[t] == full["high_nearness"].iloc[t]


def test_distinct_from_momentum_runup_then_pullback():
    """The defining George-Hwang distinction: a stock that rallied hard then
    pulled back has STRONG trailing return but WEAK 52w-high nearness. Nearness
    must reflect the pullback (well below 1.0), unlike a momentum score."""
    up = np.linspace(100, 300, HIGH_WINDOW)          # big run-up (strong momentum)
    pullback = np.concatenate([up, np.linspace(300, 210, 30)])   # then -30% off the high
    feats = compute_features_high_proximity(_df(pullback))
    # at the final bar: high ~300, close ~210 -> nearness ~0.70, NOT near 1.0
    assert feats["high_nearness"].iloc[-1] < 0.80
    assert feats["high_nearness"].iloc[-1] > 0.60


def test_score_monotonic_and_bounded():
    floor = 1.0 - FLOOR_DISCOUNT
    feats = pd.DataFrame({"high_nearness": [floor - 0.1, floor, 0.85, 0.95, 1.0]})
    s = score_high_proximity(feats)
    assert list(s) == sorted(s)                       # non-decreasing in nearness
    assert s.iloc[0] == 0.0 and s.iloc[1] == 0.0      # at/below floor -> no entry
    assert s.iloc[4] == 100.0                          # at the high -> max score
    assert s.between(0.0, 100.0).all()


def test_score_nan_nearness_is_nan_not_zero():
    s = score_high_proximity(pd.DataFrame({"high_nearness": [np.nan]}))
    assert pd.isna(s.iloc[0])


# ---------------- harness warmup ---------------------------------------------

def test_declares_warmup_at_least_its_window():
    assert get_strategy("high_proximity").warmup_bars >= HIGH_WINDOW
    assert WARMUP_BARS >= HIGH_WINDOW


def _rising_df(n=1400, seed=0, start="2016-01-01"):
    """Persistent-uptrend random walk -- frequently near its own high, so a
    correctly-warmed proximity strategy should actually take trades."""
    idx = pd.bdate_range(start, periods=n)
    rng = np.random.default_rng(seed)
    close = 1000 * np.exp(np.cumsum(rng.normal(0.0008, 0.012, n)))
    return pd.DataFrame({"Open": close, "High": close * 1.01, "Low": close * 0.99,
                         "Close": close, "Volume": np.full(n, 2e6)}, index=idx)


def test_walk_forward_takes_trades_with_declared_warmup():
    dfs = {f"S{i}.JK": _rising_df(seed=i) for i in range(8)}
    rep = walk_forward_strategy(get_strategy("high_proximity"), dfs,
                                train_bars=350, test_bars=90)
    total = sum(fr.oos_chosen.get("n", 0) for fr in rep.folds)
    assert total > 0, "high_proximity takes zero trades — warmup or score wiring broke"
