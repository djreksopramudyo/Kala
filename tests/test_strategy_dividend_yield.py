"""Dividend-yield strategy tests. Two things matter most here: point-in-time
safety (a dividend is final on its payment date, so bar t must not move when
later bars change), and the YIELD-TRAP guard — an extreme yield means the
price collapsed, which is the mean-reversion trade this project already found
loses money, so the score must NOT reward it monotonically."""

import numpy as np
import pandas as pd

from kala.strategies import get_strategy, list_strategies, walk_forward_strategy
from kala.strategy_dividend_yield import (
    CAP_YIELD,
    FULL_SCORE_YIELD,
    LOOKBACK,
    MIN_YIELD,
    WARMUP_BARS,
    compute_features_dividend_yield,
    score_dividend_yield,
)


def _df(n, close=1000.0, div_per_quarter=0.0, with_div_col=True, start="2018-01-01"):
    idx = pd.bdate_range(start, periods=n)
    closes = np.full(n, close, dtype=float)
    data = {"Open": closes, "High": closes * 1.01, "Low": closes * 0.99,
            "Close": closes, "Volume": np.full(n, 1e6)}
    if with_div_col:
        divs = np.zeros(n)
        divs[::63] = div_per_quarter        # a payment each ~quarter
        data["Dividends"] = divs
    return pd.DataFrame(data, index=idx)


def test_registered_in_zoo():
    assert "dividend_yield" in list_strategies()
    assert get_strategy("dividend_yield").name == "dividend_yield"


def test_declares_needs_dividends():
    """Without this flag, run_walkforward.py's fetch() strips the Dividends
    column and the strategy silently sees NaN forever -- an INCONCLUSIVE
    walk-forward run that looks like a null result but is actually just
    missing data. This is the flag that fixes that."""
    assert get_strategy("dividend_yield").needs_dividends is True


# ---------------- the missing-data distinction --------------------------------

def test_missing_dividends_column_is_nan_not_zero_yield():
    """A missing data source must NOT look like a genuine 'pays no dividend'.
    NaN -> the strategy declines to trade; 0.0 would be a real reading."""
    feats = compute_features_dividend_yield(_df(400, with_div_col=False))
    assert feats["trailing_yield"].isna().all()
    assert score_dividend_yield(feats).isna().all()


def test_zero_dividends_with_column_present_is_a_real_zero():
    feats = compute_features_dividend_yield(_df(400, div_per_quarter=0.0))
    tail = feats["trailing_yield"].dropna()
    assert len(tail) > 0
    assert (tail == 0.0).all()
    assert (score_dividend_yield(feats).dropna() == 0.0).all()


def test_feature_is_nan_until_enough_history():
    feats = compute_features_dividend_yield(_df(LOOKBACK - 5, div_per_quarter=10.0))
    assert feats["trailing_yield"].isna().all()


# ---------------- point-in-time safety ----------------------------------------

def test_feature_point_in_time_safe_ignores_future_dividends():
    """Bar t's trailing yield must be identical whether or not later bars (and
    later dividends) exist."""
    df = _df(LOOKBACK + 100, div_per_quarter=10.0)
    full = compute_features_dividend_yield(df)
    t = LOOKBACK + 40
    truncated = compute_features_dividend_yield(df.iloc[:t + 1])
    assert truncated["trailing_yield"].iloc[t] == full["trailing_yield"].iloc[t]


# ---------------- scoring shape, incl. the yield trap -------------------------

def test_score_rises_with_yield_in_the_healthy_range():
    feats = pd.DataFrame({"trailing_yield": [MIN_YIELD, 0.02, 0.03, FULL_SCORE_YIELD]})
    s = score_dividend_yield(feats)
    assert list(s) == sorted(s)
    assert s.iloc[0] == 0.0
    assert s.iloc[-1] == 100.0


def test_extreme_yield_is_penalised_not_rewarded():
    """The yield trap: a 30% trailing yield almost always means the price
    collapsed. Scoring it top would silently recreate the mean-reversion
    strategy this project already measured as NEGATIVE."""
    healthy = score_dividend_yield(pd.DataFrame({"trailing_yield": [FULL_SCORE_YIELD]}))
    extreme = score_dividend_yield(pd.DataFrame({"trailing_yield": [2 * CAP_YIELD]}))
    assert extreme.iloc[0] < healthy.iloc[0]
    assert extreme.iloc[0] == 0.0          # fully tapered out


def test_score_at_the_cap_is_still_full_credit():
    at_cap = score_dividend_yield(pd.DataFrame({"trailing_yield": [CAP_YIELD]}))
    assert at_cap.iloc[0] == 100.0


def test_score_is_bounded_and_nan_stays_nan():
    feats = pd.DataFrame({"trailing_yield": [np.nan, 0.0, 0.03, 0.5]})
    s = score_dividend_yield(feats)
    assert pd.isna(s.iloc[0])
    assert s.dropna().between(0.0, 100.0).all()


# ---------------- harness warmup ----------------------------------------------

def test_declares_warmup_at_least_its_lookback():
    assert get_strategy("dividend_yield").warmup_bars >= LOOKBACK
    assert WARMUP_BARS >= LOOKBACK


def test_walk_forward_takes_trades_on_dividend_payers():
    """A basket of steady payers must produce real OOS trades once warmed."""
    dfs = {}
    for i in range(6):
        n = 1400
        idx = pd.bdate_range("2016-01-01", periods=n)
        rng = np.random.default_rng(i)
        close = 1000 * np.exp(np.cumsum(rng.normal(0.0003, 0.010, n)))
        divs = np.zeros(n)
        divs[::63] = close[::63] * 0.0125      # ~5%/yr paid quarterly
        dfs[f"S{i}.JK"] = pd.DataFrame(
            {"Open": close, "High": close * 1.01, "Low": close * 0.99,
             "Close": close, "Volume": np.full(n, 2e6), "Dividends": divs}, index=idx)
    rep = walk_forward_strategy(get_strategy("dividend_yield"), dfs,
                                train_bars=350, test_bars=90)
    total = sum(fr.oos_chosen.get("n", 0) for fr in rep.folds)
    assert total > 0, "dividend_yield took zero trades — warmup or scoring wiring broke"
