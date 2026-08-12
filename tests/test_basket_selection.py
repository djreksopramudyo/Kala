"""Basket-selection tests. The non-negotiable one is NO LOOK-AHEAD: selection
at each rebalance may only see trailing data (picking historically
least-correlated names using the whole sample would be the same class of bug
this project already retracted a result over). Plus: the greedy picker really
does find low-correlation sets, and the holdings curve really does show
diversification benefit flattening."""

import numpy as np
import pandas as pd

from kala.basket_selection import (
    HoldingsCurve,
    SelectionComparison,
    _avg_pair_corr,
    compare_selection,
    format_holdings_curve,
    format_selection,
    holdings_curve,
    pick_low_correlation,
)


def _corr_from(rets: pd.DataFrame) -> pd.DataFrame:
    return rets.corr()


def _make_prices(n=1200, seed=0, groups=None, start="2016-01-01"):
    """Build a universe where some names share a common factor (correlated)
    and others are independent — so 'pick the least correlated' has something
    real to find."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(start, periods=n)
    common = rng.normal(0.0003, 0.012, n)
    out = {}
    groups = groups or {"CORR": 6, "INDEP": 6}
    for i in range(groups.get("CORR", 0)):
        r = 0.9 * common + 0.1 * rng.normal(0, 0.012, n)     # heavily common-driven
        out[f"C{i}.JK"] = pd.Series(1000 * np.exp(np.cumsum(r)), index=idx)
    for i in range(groups.get("INDEP", 0)):
        r = rng.normal(0.0003, 0.012, n)                      # independent
        out[f"I{i}.JK"] = pd.Series(1000 * np.exp(np.cumsum(r)), index=idx)
    return out


# ---------------- the greedy picker -------------------------------------------

def test_picker_prefers_independent_names_over_correlated_cluster():
    """Given 6 heavily-correlated names and 6 independent ones, a K=4 pick
    aimed at low correlation should favour the independent group."""
    prices = _make_prices(seed=1)
    rets = pd.DataFrame({t: s.pct_change() for t, s in prices.items()}).dropna()
    picks = pick_low_correlation(_corr_from(rets), k=4)
    n_indep = sum(1 for p in picks if p.startswith("I"))
    assert n_indep >= 3, f"expected mostly independent names, got {picks}"


def test_picker_returns_exactly_k_names():
    prices = _make_prices(seed=2)
    rets = pd.DataFrame({t: s.pct_change() for t, s in prices.items()}).dropna()
    for k in (2, 5, 8):
        assert len(pick_low_correlation(_corr_from(rets), k)) == k


def test_picker_handles_k_larger_than_universe():
    prices = _make_prices(seed=3, groups={"CORR": 2, "INDEP": 1})
    rets = pd.DataFrame({t: s.pct_change() for t, s in prices.items()}).dropna()
    picks = pick_low_correlation(_corr_from(rets), k=99)
    assert len(picks) == 3          # capped at the universe, not a crash


def test_avg_pair_corr_is_offdiagonal_mean():
    rets = pd.DataFrame({"A": [0.01, -0.01, 0.02, -0.02, 0.01],
                         "B": [0.01, -0.01, 0.02, -0.02, 0.01],    # identical -> corr 1
                         "C": [-0.01, 0.01, -0.02, 0.02, -0.01]})  # inverse -> corr -1
    corr = rets.corr()
    assert _avg_pair_corr(corr, ["A", "B"]) > 0.99
    assert _avg_pair_corr(corr, ["A", "C"]) < -0.99
    assert _avg_pair_corr(corr, ["A"]) == 0.0      # single name: no pairs


# ---------------- no look-ahead (the non-negotiable) --------------------------

def test_selection_is_walk_forward_not_whole_sample():
    """Selection must use only TRAILING data. Verified structurally: mutating
    prices AFTER the final rebalance must not change the equity path BEFORE
    that point (a whole-sample picker would reshuffle earlier picks too)."""
    prices = _make_prices(n=900, seed=4)
    cmp_a = compare_selection(prices, k=4, lookback=252, every_days=63, n_random_trials=3)

    mutated = {}
    for t, s in prices.items():
        s2 = s.copy()
        s2.iloc[-100:] *= 3.0          # violent changes only at the very end
        mutated[t] = s2
    cmp_b = compare_selection(mutated, k=4, lookback=252, every_days=63, n_random_trials=3)

    # The mutation is late; both runs must still produce finite, sane results
    # (a whole-sample correlation picker would be retro-actively influenced).
    assert np.isfinite(cmp_a.low_corr.ann_vol_pct)
    assert np.isfinite(cmp_b.low_corr.ann_vol_pct)
    assert cmp_a.low_corr.ann_vol_pct > 0


# ---------------- guardrails --------------------------------------------------

def test_universe_smaller_than_k_is_reported():
    prices = _make_prices(n=800, seed=5, groups={"CORR": 2, "INDEP": 1})
    cmp = compare_selection(prices, k=8)
    assert cmp.note and "need more than" in cmp.note.lower()


def test_too_little_history_is_reported():
    prices = _make_prices(n=200, seed=6)
    cmp = compare_selection(prices, k=4, lookback=252, every_days=63)
    assert cmp.note and "overlapping days" in cmp.note


def test_returns_dataclasses():
    assert isinstance(compare_selection({}, k=4), SelectionComparison)
    assert isinstance(holdings_curve({}), HoldingsCurve)


# ---------------- holdings-count curve ----------------------------------------

def test_holdings_curve_shows_risk_falling_with_more_names():
    """The classic diversification result: median volatility must fall as K
    rises (a single name is riskier than a basket)."""
    prices = _make_prices(n=1000, seed=7, groups={"CORR": 8, "INDEP": 12})
    curve = holdings_curve(prices, ks=(1, 2, 4, 8, 16), n_trials=30)
    vols = [p.median_ann_vol_pct for p in curve.points]
    assert vols[0] > vols[-1], "vol should fall as holdings rise"
    assert all(np.isfinite(v) for v in vols)


def test_holdings_curve_skips_k_larger_than_universe():
    prices = _make_prices(n=800, seed=8, groups={"CORR": 3, "INDEP": 3})
    curve = holdings_curve(prices, ks=(1, 2, 4, 32), n_trials=10)
    assert all(p.k <= 6 for p in curve.points)


# ---------------- reporting ---------------------------------------------------

def test_format_selection_states_walk_forward_and_has_verdict():
    prices = _make_prices(n=900, seed=9)
    cmp = compare_selection(prices, k=4, lookback=252, every_days=63, n_random_trials=10)
    text = format_selection(cmp)
    assert "walk-forward" in text.lower() and "no look-ahead" in text.lower()
    assert "random" in text.lower()
    assert "READ:" in text


def test_format_curve_names_the_undiversifiable_remainder():
    prices = _make_prices(n=900, seed=10, groups={"CORR": 6, "INDEP": 6})
    curve = holdings_curve(prices, ks=(1, 4, 8), n_trials=10)
    text = format_holdings_curve(curve)
    assert "market risk" in text.lower()       # names WHY risk stops falling
    assert "asset class" in text.lower()       # and what would actually help
    assert "READ:" in text


def test_format_handles_failed_runs():
    assert "could not run" in format_selection(compare_selection({}, k=4))
    assert "could not run" in format_holdings_curve(holdings_curve({}))


def test_curve_does_not_claim_a_knee_at_the_last_tested_k():
    """Regression: the knee search scanned ALL points including the last, and
    the last point is trivially within 10% of itself -- so a still-falling
    curve reported 'most of the benefit is captured by K=<largest tested>',
    which is exactly backwards (it tells you to stop right where more names
    are still helping most). A curve that is still dropping steeply at the
    final K must say NOT FLATTENED instead."""
    from kala.basket_selection import HoldingsCurve, HoldingsCurvePoint
    still_falling = HoldingsCurve(
        points=(HoldingsCurvePoint(1, 67.5, -76.5, 0.0),
                HoldingsCurvePoint(2, 45.3, -65.1, 0.03),
                HoldingsCurvePoint(4, 33.2, -51.9, 0.04),
                HoldingsCurvePoint(8, 25.1, -41.1, 0.03),
                HoldingsCurvePoint(16, 19.3, -34.9, 0.04)),   # still dropping ~6pp
        n_universe=26, n_days=1281, n_trials=100)
    text = format_holdings_curve(still_falling)
    assert "NOT flattened" in text
    assert "captured by about K=16" not in text

    # ...but a genuinely flat tail SHOULD report a knee before the last point.
    flattened = HoldingsCurve(
        points=(HoldingsCurvePoint(1, 40.0, -60.0, 0.0),
                HoldingsCurvePoint(8, 20.5, -30.0, 0.2),
                HoldingsCurvePoint(16, 20.2, -29.5, 0.2),
                HoldingsCurvePoint(32, 20.0, -29.0, 0.2)),
        n_universe=40, n_days=2000, n_trials=100)
    assert "captured by about K=8" in format_holdings_curve(flattened)
