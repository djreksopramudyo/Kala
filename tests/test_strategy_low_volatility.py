"""Low-volatility anomaly strategy tests. The non-negotiable one is
point-in-time safety: realized vol at bar t must not move when FUTURE bars
change. Plus the DEFINING behavior — the score is INVERSE to volatility (a
calm stock outscores a wild one) — bounds, NaN handling, and warmup."""

import numpy as np
import pandas as pd

from kala.strategies import get_strategy, list_strategies, walk_forward_strategy
from kala.strategy_low_volatility import (
    HIGH_VOL_ANN,
    LOW_VOL_ANN,
    VOL_WINDOW,
    WARMUP_BARS,
    compute_features_low_volatility,
    score_low_volatility,
)


def _df(close, start="2020-01-01"):
    close = np.asarray(close, dtype=float)
    idx = pd.bdate_range(start, periods=len(close))
    return pd.DataFrame({"Open": close, "High": close * 1.01, "Low": close * 0.99,
                         "Close": close, "Volume": np.full(len(close), 1e6)}, index=idx)


def test_registered_in_zoo():
    assert "low_volatility" in list_strategies()
    assert get_strategy("low_volatility").name == "low_volatility"


def test_feature_is_nan_until_enough_history():
    df = _df(np.linspace(100, 200, VOL_WINDOW - 5))   # fewer than VOL_WINDOW bars
    feats = compute_features_low_volatility(df)
    assert feats["realized_vol"].isna().all()


def test_feature_point_in_time_safe_ignores_future():
    """The whole ballgame: bar t's realized vol must be identical whether or
    not later bars exist / change. Compute on a long series, then mutate
    everything AFTER t and confirm the value at t is unchanged."""
    rng = np.random.default_rng(3)
    close = 1000 * np.exp(np.cumsum(rng.normal(0.0005, 0.015, VOL_WINDOW + 80)))
    full = compute_features_low_volatility(_df(close))
    t = VOL_WINDOW + 40                    # a bar with defined realized vol

    close_mut = close.copy()
    close_mut[t + 1:] *= 3.0               # violent moves strictly after t
    mut = compute_features_low_volatility(_df(close_mut))
    assert mut["realized_vol"].iloc[t] == full["realized_vol"].iloc[t]


def test_calm_stock_has_lower_vol_than_wild_stock():
    """A quiet series (tiny daily moves) must show much lower realized_vol than
    a jumpy one over the same window — the raw signal the anomaly rides."""
    rng = np.random.default_rng(7)
    n = VOL_WINDOW + 50
    calm = 1000 * np.exp(np.cumsum(rng.normal(0.0, 0.003, n)))   # ~0.3%/day moves
    wild = 1000 * np.exp(np.cumsum(rng.normal(0.0, 0.030, n)))   # ~3%/day moves
    calm_vol = compute_features_low_volatility(_df(calm))["realized_vol"].iloc[-1]
    wild_vol = compute_features_low_volatility(_df(wild))["realized_vol"].iloc[-1]
    assert calm_vol < wild_vol


def test_score_is_inverse_to_volatility():
    """The DEFINING behavior: calmer (lower vol) must score HIGHER. This is
    what makes it the low-vol anomaly and not just another momentum re-skin."""
    feats = pd.DataFrame({"realized_vol": [0.10, 0.25, 0.45, 0.65, 0.90]})
    s = score_low_volatility(feats)
    assert list(s) == sorted(s, reverse=True)   # non-increasing as vol rises


def test_score_saturates_and_is_bounded():
    feats = pd.DataFrame({"realized_vol": [LOW_VOL_ANN - 0.05, LOW_VOL_ANN,
                                           HIGH_VOL_ANN, HIGH_VOL_ANN + 0.5]})
    s = score_low_volatility(feats)
    assert s.iloc[0] == 100.0 and s.iloc[1] == 100.0   # at/below floor -> max score
    assert s.iloc[2] == 0.0 and s.iloc[3] == 0.0       # at/above cap  -> zero score
    assert s.between(0.0, 100.0).all()


def test_score_nan_vol_is_nan_not_zero():
    """NaN (insufficient history) must stay NaN so the backtest reads it as
    'do not enter', not as a real zero (which would look like 'wildest possible
    stock' here and is a different, wrong signal)."""
    s = score_low_volatility(pd.DataFrame({"realized_vol": [np.nan]}))
    assert pd.isna(s.iloc[0])


# ---------------- harness warmup ---------------------------------------------

def test_declares_warmup_at_least_its_window():
    """The vol window must be covered by declared warmup, or every fold computes
    realized_vol all-NaN early and the strategy trades too little / not at all."""
    assert get_strategy("low_volatility").warmup_bars >= VOL_WINDOW
    assert WARMUP_BARS >= VOL_WINDOW


def _calm_df(n=1400, seed=0, start="2016-01-01"):
    """A low-vol, gently drifting name — the kind this strategy is built to
    BUY, so a correctly-warmed run should actually take trades on it."""
    idx = pd.bdate_range(start, periods=n)
    rng = np.random.default_rng(seed)
    close = 1000 * np.exp(np.cumsum(rng.normal(0.0004, 0.006, n)))   # calm drift
    return pd.DataFrame({"Open": close, "High": close * 1.01, "Low": close * 0.99,
                         "Close": close, "Volume": np.full(n, 2e6)}, index=idx)


def test_walk_forward_takes_trades_on_calm_names_with_declared_warmup():
    """Through walk_forward_strategy (which passes the strategy's own
    warmup_bars), a basket of low-vol names must produce real OOS trades —
    proving the feature is warmed and the inverse score actually fires."""
    dfs = {f"S{i}.JK": _calm_df(seed=i) for i in range(8)}
    rep = walk_forward_strategy(get_strategy("low_volatility"), dfs,
                                train_bars=350, test_bars=90)
    total = sum(fr.oos_chosen.get("n", 0) for fr in rep.folds)
    assert total > 0, "low_volatility takes zero trades — warmup or score wiring broke"
