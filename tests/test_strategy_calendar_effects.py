"""Turn-of-month strategy tests. The non-negotiable one is point-in-time
safety: tom_rank_in_month at bar t must not depend on rows AFTER t (the
specific failure mode this strategy's docstring explains was deliberately
avoided by not implementing the 'last day of month' half of the classic
effect). Plus the defining behavior — score is 100 only in the first
N_START_DAYS of a month — and that it needs no price data at all."""

import numpy as np
import pandas as pd

from kala.strategies import get_strategy, list_strategies, walk_forward_strategy
from kala.strategy_calendar_effects import (
    N_START_DAYS,
    WARMUP_BARS,
    compute_features_turn_of_month,
    score_turn_of_month,
)


def _df(n, start="2020-01-01", freq="B"):
    idx = pd.bdate_range(start, periods=n) if freq == "B" else pd.date_range(start, periods=n, freq=freq)
    close = np.full(n, 100.0)   # price is irrelevant to this strategy -- flat is fine
    return pd.DataFrame({"Open": close, "High": close, "Low": close,
                         "Close": close, "Volume": np.full(n, 1e6)}, index=idx)


def test_registered_in_zoo():
    assert "turn_of_month" in list_strategies()
    assert get_strategy("turn_of_month").name == "turn_of_month"


def test_rank_resets_at_month_start():
    # ~2 months of business days starting Jan 1 2024 (a Monday)
    df = _df(45, start="2024-01-01")
    feats = compute_features_turn_of_month(df)
    ranks = feats["tom_rank_in_month"]
    # first trading day of January -> rank 0
    assert ranks.iloc[0] == 0
    # first trading day of February must ALSO be rank 0, not a continuation
    feb_start = feats.index[feats.index.month == 2][0]
    assert ranks.loc[feb_start] == 0


def test_rank_increments_within_a_month():
    df = _df(10, start="2024-01-01")   # all within January
    feats = compute_features_turn_of_month(df)
    assert list(feats["tom_rank_in_month"]) == list(range(10))


def test_feature_point_in_time_safe_ignores_future_rows():
    """The whole ballgame: bar t's rank must be identical whether or not
    later rows exist. Compute on a long series, then TRUNCATE after t and
    confirm the value at t is unchanged -- proves no future row (e.g. 'does
    this month have more trading days later') leaks into the value at t."""
    df = _df(90, start="2024-01-01")
    full = compute_features_turn_of_month(df)
    t = 40   # some bar comfortably in the middle

    truncated = compute_features_turn_of_month(df.iloc[:t + 1])
    assert truncated["tom_rank_in_month"].iloc[t] == full["tom_rank_in_month"].iloc[t]


def test_score_is_100_only_in_first_n_days_of_month():
    df = _df(25, start="2024-01-01")   # all of January's business days
    feats = compute_features_turn_of_month(df)
    s = score_turn_of_month(feats)
    ranks = feats["tom_rank_in_month"]
    assert (s[ranks < N_START_DAYS] == 100.0).all()
    assert (s[ranks >= N_START_DAYS] == 0.0).all()


def test_score_needs_no_price_data():
    """Defining property: the score is identical regardless of price, since
    it's purely calendar-derived. Two DataFrames with wildly different
    prices but the SAME dates must score identically."""
    idx = pd.bdate_range("2024-01-01", periods=15)
    flat = pd.DataFrame({"Open": 100.0, "High": 101.0, "Low": 99.0,
                         "Close": 100.0, "Volume": 1e6}, index=idx)
    wild = pd.DataFrame({"Open": [50, 500] * 7 + [50], "High": [51, 501] * 7 + [51],
                         "Low": [49, 499] * 7 + [49], "Close": [50, 500] * 7 + [50],
                         "Volume": 1e6}, index=idx)
    s_flat = score_turn_of_month(compute_features_turn_of_month(flat))
    s_wild = score_turn_of_month(compute_features_turn_of_month(wild))
    assert (s_flat == s_wild).all()


def test_score_never_nan():
    """Unlike price-derived features, the calendar rank is always defined --
    even bar 0 of the whole dataset has a valid rank (0)."""
    df = _df(5, start="2024-01-01")
    s = score_turn_of_month(compute_features_turn_of_month(df))
    assert not s.isna().any()


# ---------------- harness warmup ---------------------------------------------

def test_declares_small_warmup_since_no_price_lookback_needed():
    assert get_strategy("turn_of_month").warmup_bars == WARMUP_BARS
    assert WARMUP_BARS < 60   # much smaller than a typical price-lookback strategy


def test_walk_forward_takes_trades_at_month_starts():
    """Through walk_forward_strategy, a basket of flat-price names must still
    take real OOS trades -- proving the signal fires from calendar alone,
    with no price movement required at all."""
    idx = pd.bdate_range("2016-01-01", periods=1400)
    dfs = {}
    for i in range(6):
        close = np.full(len(idx), 100.0 + i)   # flat, distinct per ticker
        dfs[f"S{i}.JK"] = pd.DataFrame({"Open": close, "High": close, "Low": close,
                                        "Close": close, "Volume": np.full(len(idx), 2e6)},
                                       index=idx)
    rep = walk_forward_strategy(get_strategy("turn_of_month"), dfs,
                                train_bars=350, test_bars=90)
    total = sum(fr.oos_chosen.get("n", 0) for fr in rep.folds)
    assert total > 0, "turn_of_month takes zero trades on flat-price data — calendar signal broke"
