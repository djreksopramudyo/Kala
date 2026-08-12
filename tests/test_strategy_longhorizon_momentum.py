"""Long-horizon (12-1) momentum strategy tests. The non-negotiable one is
point-in-time safety: the feature at bar t must not move when FUTURE bars
change. Plus monotonicity (more momentum -> higher score) and that the
'skip most recent month' actually skips it."""

import numpy as np
import pandas as pd

from kala.strategies import get_strategy, list_strategies, walk_forward_strategy
from kala.strategy_longhorizon_momentum import (
    FULL_SCORE_RETURN,
    LOOKBACK,
    SKIP,
    WARMUP_BARS,
    compute_features_longhorizon,
    score_longhorizon,
)


def _df(close, start="2020-01-01"):
    close = np.asarray(close, dtype=float)
    idx = pd.bdate_range(start, periods=len(close))
    return pd.DataFrame({"Open": close, "High": close * 1.01, "Low": close * 0.99,
                         "Close": close, "Volume": np.full(len(close), 1e6)}, index=idx)


def test_registered_in_zoo():
    assert "long_momentum" in list_strategies()
    assert get_strategy("long_momentum").name == "long_momentum"


def test_feature_is_nan_until_enough_history():
    df = _df(np.linspace(100, 200, LOOKBACK - 5))   # fewer than LOOKBACK bars
    feats = compute_features_longhorizon(df)
    assert feats["mom_12_1"].isna().all()


def test_feature_point_in_time_safe_ignores_future():
    """The whole ballgame: bar t's momentum must be identical whether or not
    later bars exist / change. Compute on a long series, then truncate AFTER
    t and confirm the value at t is unchanged."""
    rng = np.random.default_rng(3)
    close = 1000 * np.exp(np.cumsum(rng.normal(0.0005, 0.015, LOOKBACK + 80)))
    full = compute_features_longhorizon(_df(close))
    t = LOOKBACK + 40                      # a bar with defined momentum

    # mutate everything strictly after t, recompute: value at t must not budge.
    close_mut = close.copy()
    close_mut[t + 1:] *= 3.0
    mut = compute_features_longhorizon(_df(close_mut))
    assert mut["mom_12_1"].iloc[t] == full["mom_12_1"].iloc[t]


def test_feature_measures_12_1_window_not_recent_month():
    """A price that rose steadily for a year but CRASHED in the last month
    must still show POSITIVE 12-1 momentum -- because the recent month is
    skipped. This is the defining behavior vs. plain trailing return."""
    up = np.linspace(100, 300, LOOKBACK + SKIP)   # year-long rise
    crash = up.copy()
    crash[-SKIP:] = np.linspace(300, 120, SKIP)   # last ~month collapses
    feats = compute_features_longhorizon(_df(crash))
    # at the final bar, near-edge is ~1 month ago (still ~300), far-edge ~12mo
    # ago (~100) -> strongly positive despite the crash the skip window hides.
    assert feats["mom_12_1"].iloc[-1] > 0.5


def test_score_monotonic_and_bounded():
    feats = pd.DataFrame({"mom_12_1": [-0.5, 0.0, 0.10, FULL_SCORE_RETURN, 1.0]})
    s = score_longhorizon(feats)
    assert list(s) == sorted(s)                    # non-decreasing in momentum
    assert s.iloc[0] == 0.0 and s.iloc[1] == 0.0   # negative/zero momentum -> no entry
    assert s.iloc[3] == 100.0 and s.iloc[4] == 100.0   # saturates at the cap


def test_score_nan_momentum_is_nan_not_zero():
    """NaN (insufficient history) must stay NaN so the backtest reads it as
    'do not enter', not as a real zero score."""
    s = score_longhorizon(pd.DataFrame({"mom_12_1": [np.nan]}))
    assert pd.isna(s.iloc[0])


# ---------------- harness warmup (the zero-trades regression) -----------------

def test_declares_warmup_at_least_its_lookback():
    """A 12-month feature must ask the harness for >= LOOKBACK bars of warmup,
    or every fold computes it all-NaN and the strategy trades zero times."""
    assert get_strategy("long_momentum").warmup_bars >= LOOKBACK
    assert WARMUP_BARS >= LOOKBACK


def _trending_df(n=1400, seed=0, start="2016-01-01"):
    """Persistent-drift random walk -- has real trailing-12m momentum, so a
    correctly-warmed long-momentum strategy should actually take trades."""
    idx = pd.bdate_range(start, periods=n)
    rng = np.random.default_rng(seed)
    close = 1000 * np.exp(np.cumsum(rng.normal(0.0009, 0.014, n)))
    return pd.DataFrame({"Open": close, "High": close * 1.01, "Low": close * 0.99,
                         "Close": close, "Volume": np.full(n, 2e6)}, index=idx)


def test_walk_forward_actually_takes_trades_with_declared_warmup():
    """The exact bug the user hit: with the default 60-bar warmup this strategy
    traded 0 times on every fold. Going through walk_forward_strategy (which
    passes the strategy's own warmup_bars) it must produce real OOS trades."""
    dfs = {f"S{i}.JK": _trending_df(seed=i) for i in range(8)}
    rep = walk_forward_strategy(get_strategy("long_momentum"), dfs,
                                train_bars=350, test_bars=90)
    total = sum(fr.oos_chosen.get("n", 0) for fr in rep.folds)
    assert total > 0, "long_momentum still takes zero trades — warmup not applied"


def test_explicit_warmup_kwarg_still_wins_over_strategy_default():
    """An explicit warmup_bars= must override the strategy's declared value —
    proves the setdefault wiring, and lets a caller reproduce the broken
    short-warmup behavior on purpose (e.g. to demonstrate the bug)."""
    dfs = {f"S{i}.JK": _trending_df(seed=i) for i in range(4)}
    rep = walk_forward_strategy(get_strategy("long_momentum"), dfs,
                                train_bars=350, test_bars=90, warmup_bars=60)
    total = sum(fr.oos_chosen.get("n", 0) for fr in rep.folds)
    assert total == 0    # starved of history on purpose -> the original zero-trades
