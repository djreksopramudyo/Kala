"""Weighting-scheme backtest tests. Uses SYNTHETIC price paths with known
properties so the weighting logic is verified without network or real data.
The honest expectations are baked into the assertions: weights are always a
valid long-only simplex, min-variance actually reduces vol on an
anti-correlated basket when the covariance is well-estimated, costs behave,
and equal_weight is literally 1/N."""

import numpy as np
import pandas as pd

from kala.weighting_backtest import (
    SCHEMES,
    WeightingComparison,
    _equal_weights,
    _inverse_vol_weights,
    _min_variance_weights,
    compare_weighting,
    format_weighting_comparison,
)


def _series(values, start="2016-01-01"):
    idx = pd.bdate_range(start, periods=len(values))
    return pd.Series(np.asarray(values, dtype=float), index=idx)


def _returns(n, cols, seed=0, vols=None):
    rng = np.random.default_rng(seed)
    vols = vols or [0.01] * len(cols)
    data = {c: rng.normal(0, v, n) for c, v in zip(cols, vols)}
    return pd.DataFrame(data, index=pd.bdate_range("2016-01-01", periods=n))


# ---------------- weight rules: valid long-only simplex ----------------------

def test_all_schemes_return_long_only_simplex():
    rets = _returns(200, ["A", "B", "C"], seed=1, vols=[0.01, 0.02, 0.03])
    for name, fn in SCHEMES.items():
        w = fn(rets)
        assert np.all(w >= -1e-12), f"{name} produced a negative (short) weight"
        assert abs(w.sum() - 1.0) < 1e-9, f"{name} weights don't sum to 1"


def test_equal_weights_is_one_over_n():
    rets = _returns(50, ["A", "B", "C", "D"])
    w = _equal_weights(rets)
    assert np.allclose(w, 0.25)


def test_inverse_vol_gives_calmer_name_more_weight():
    # B is 3x as volatile as A -> A should get the larger inverse-vol weight.
    rets = _returns(300, ["A", "B"], seed=2, vols=[0.01, 0.03])
    w = _inverse_vol_weights(rets)
    a_idx, b_idx = 0, 1
    assert w[a_idx] > w[b_idx]


def test_inverse_vol_handles_zero_vol_column_without_warning():
    """A flat (zero-vol) column -- e.g. a thinly-traded name with an
    unchanged close for the whole window -- must fall back gracefully
    (masked out, not equal-share'd into dominating) and must NOT raise a
    divide-by-zero RuntimeWarning (the real bug the user's terminal showed:
    np.where evaluates 1.0/vol everywhere before masking, so vol==0 still
    warns even though the result is discarded)."""
    import warnings
    rets = pd.DataFrame({"FLAT": [0.0] * 50, "NORMAL": np.random.default_rng(9).normal(0, 0.01, 50)})
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        w = _inverse_vol_weights(rets)
    assert w[0] == 0.0            # the flat/zero-vol name gets no weight
    assert w[1] == 1.0            # all weight goes to the one with real vol


def test_min_variance_tilts_from_the_high_vol_name():
    # Uncorrelated, A calm B wild -> min-variance should underweight B vs 1/N.
    rets = _returns(400, ["A", "B"], seed=4, vols=[0.008, 0.03])
    w = _min_variance_weights(rets)
    assert w[1] < 0.5   # B (the wild one) gets less than equal share
    assert np.all(w >= 0) and abs(w.sum() - 1.0) < 1e-9


def test_min_variance_falls_back_on_degenerate_covariance():
    # All-NaN returns -> degenerate -> equal-weight fallback, not a crash.
    rets = pd.DataFrame({"A": [np.nan] * 10, "B": [np.nan] * 10})
    w = _min_variance_weights(rets)
    assert np.allclose(w, 0.5)


# ---------------- guardrails --------------------------------------------------

def test_single_name_cannot_be_compared():
    cmp = compare_weighting({"A": _series(np.linspace(100, 200, 400))})
    assert cmp.note and "at least 2 names" in cmp.note


def test_too_little_history_is_reported():
    prices = {"A": _series(np.linspace(100, 110, 80)),
              "B": _series(np.linspace(100, 120, 80))}
    cmp = compare_weighting(prices, lookback=126, every_days=63)
    assert "overlapping days" in cmp.note


def test_one_short_history_ticker_does_not_collapse_the_whole_join():
    """The exact bug the user hit: 39 tickers with full 10y history plus ONE
    newly-listed name (few days) must NOT drop everyone to ~0 overlapping
    days via a strict inner join. The short one gets dropped instead, and the
    rest of the basket runs normally."""
    long_history = {f"S{i}.JK": _series(np.linspace(100, 200, 2000),
                                        start="2016-01-01")
                    for i in range(6)}
    # a name that only started trading recently -- 5 days, all in 2026, no
    # overlap at all with the other six's 2016-2023 window.
    long_history["NEWIPO.JK"] = _series(np.linspace(100, 105, 5), start="2026-07-01")

    cmp = compare_weighting(long_history, every_days=63, lookback=126, cost_rate=0.0)
    assert "NEWIPO.JK" in cmp.dropped_short_history
    assert cmp.n_names == 6                     # the six long-history names kept
    assert cmp.n_days > 1500                     # NOT collapsed to ~0 by the short one
    assert cmp.stats                              # comparison actually ran


def test_dropped_tickers_reported_in_failed_run_message():
    prices = {"A": _series(np.linspace(100, 200, 2000), start="2016-01-01"),
              "TOOSHORT.JK": _series([100.0, 101.0], start="2026-07-01")}
    cmp = compare_weighting(prices, lookback=126, every_days=63)
    text = format_weighting_comparison(cmp, cost_rate=0.003)
    assert "TOOSHORT.JK" in text


# ---------------- policy behavior ---------------------------------------------

def _anti_correlated_basket(n=900, seed=3):
    rng = np.random.default_rng(seed)
    shock = rng.normal(0, 0.02, n)
    a = 1000 * np.exp(np.cumsum(0.0002 + shock))     # moves one way on the shock
    b = 1000 * np.exp(np.cumsum(0.0002 - shock))     # opposite way
    return {"A": _series(a), "B": _series(b)}


def _distinct_vol_basket(n=900, seed=8):
    """Three uncorrelated names with clearly DIFFERENT vols. Here min-variance
    has something real to do — tilt toward the calm names — unlike an
    equal-vol anti-correlated pair, where the min-variance portfolio is just
    50/50 by symmetry and correctly equals 1/N."""
    rng = np.random.default_rng(seed)
    out = {}
    for name, vol in zip(["CALM", "MID", "WILD"], [0.006, 0.015, 0.035]):
        path = 1000 * np.exp(np.cumsum(rng.normal(0.0003, vol, n)))
        out[name] = _series(path)
    return out


def test_min_variance_reduces_vol_vs_equal_weight_on_distinct_vol_basket():
    """When individual vols genuinely differ and the covariance is
    well-estimated, min-variance SHOULD deliver lower realized vol than 1/N by
    tilting toward the calm names. This proves the machinery actually uses the
    covariance — NOT that it wins on real data, where estimation error (not
    the math) is the whole problem."""
    cmp = compare_weighting(_distinct_vol_basket(), every_days=21,
                            lookback=126, cost_rate=0.0)
    assert cmp.stats["min_variance"].ann_vol_pct < cmp.stats["equal_weight"].ann_vol_pct
    # inverse-vol should also cut vol vs 1/N here (it's the robust version).
    assert cmp.stats["inverse_vol"].ann_vol_pct < cmp.stats["equal_weight"].ann_vol_pct


def test_costs_reduce_return_for_every_scheme():
    prices = _anti_correlated_basket()
    free = compare_weighting(prices, every_days=21, lookback=126, cost_rate=0.0)
    costly = compare_weighting(prices, every_days=21, lookback=126, cost_rate=0.005)
    for name in free.schemes:
        assert costly.stats[name].total_return_pct <= free.stats[name].total_return_pct + 1e-9
        assert costly.costs_pct[name] > 0
        assert free.costs_pct[name] == 0.0


def test_equal_weight_scheme_still_pays_rebalancing_cost():
    """Even 1/N drifts and must be reset, so it isn't cost-free — the
    comparison is scheme-vs-scheme, not free-vs-costly."""
    cmp = compare_weighting(_anti_correlated_basket(), every_days=21,
                            lookback=126, cost_rate=0.003)
    assert cmp.costs_pct["equal_weight"] > 0


# ---------------- reporting ---------------------------------------------------

def test_format_states_the_1_over_n_question_and_has_a_verdict():
    cmp = compare_weighting(_anti_correlated_basket(), every_days=63, lookback=126)
    text = format_weighting_comparison(cmp, cost_rate=0.003)
    assert "beat naive 1/N" in text
    assert "equal_weight" in text and "min_variance" in text and "inverse_vol" in text
    assert "READ:" in text


def test_format_handles_failed_run():
    cmp = compare_weighting({"A": _series(np.linspace(100, 200, 400))})   # 1 name
    text = format_weighting_comparison(cmp, cost_rate=0.003)
    assert "could not run" in text


def test_returns_dataclass():
    cmp = compare_weighting({}, every_days=63)
    assert isinstance(cmp, WeightingComparison)
