"""Core-satellite tests. Synthetic paths with known properties so the
structural truths are checked, not hoped for: a satellite sleeve that really
does outperform must show up as earning its risk, one that underperforms must
be called out, concentration must raise volatility, and a SHORT overlap (the
realistic case when an IDX index ETF is younger than the stocks) must produce
a loud caveat rather than a confident-looking table."""

import numpy as np
import pandas as pd

from kala.core_satellite_backtest import (
    CoreSatelliteComparison,
    compare_core_satellite,
    format_core_satellite,
)


def _series(vals, start="2016-01-01"):
    idx = pd.bdate_range(start, periods=len(vals))
    return pd.Series(np.asarray(vals, dtype=float), index=idx)


def _path(n, drift, vol, seed):
    rng = np.random.default_rng(seed)
    return 1000 * np.exp(np.cumsum(rng.normal(drift, vol, n)))


def _core_and_sats(n=1500, core_drift=0.0004, sat_drift=0.0004,
                   core_vol=0.008, sat_vol=0.016, n_sats=6, seed=0,
                   market_beta=0.7):
    """Core + satellites sharing a COMMON MARKET FACTOR, which is how real
    equities and their index actually behave.

    An earlier version generated fully INDEPENDENT paths, and that quietly
    broke a test premise in an instructive way: blending two uncorrelated
    assets can produce LOWER volatility than either one alone (that's the
    diversification benefit), so 'core < blend < satellites' simply isn't
    true for independent series. Real IDX stocks are highly correlated with
    the IDX index, so the correlated generator here is both more realistic
    and the setting in which that ordering actually holds.
    """
    rng = np.random.default_rng(seed)
    market = rng.normal(0.0, 1.0, n)                    # shared factor
    core_r = core_drift + core_vol * market
    core = _series(1000 * np.exp(np.cumsum(core_r)))
    sats = {}
    for i in range(n_sats):
        idio = np.random.default_rng(seed + 100 + i).normal(0.0, 1.0, n)
        r = sat_drift + sat_vol * (market_beta * market +
                                   np.sqrt(max(0.0, 1 - market_beta ** 2)) * idio)
        sats[f"S{i}.JK"] = _series(1000 * np.exp(np.cumsum(r)))
    return core, sats


# ---------------- guardrails --------------------------------------------------

def test_no_satellites_is_reported():
    core, _ = _core_and_sats()
    cmp = compare_core_satellite(core, {})
    assert cmp.note and "at least one satellite" in cmp.note


def test_short_overlap_is_reported_not_silently_run():
    """The realistic IDX case: the index ETF is much younger than the stocks,
    so they overlap only over the ETF's short life. The study must refuse
    rather than quietly comparing on a few months."""
    sats = {f"S{i}.JK": _series(_path(1500, 0.0004, 0.015, i), start="2016-01-01")
            for i in range(4)}
    sat_end = list(sats.values())[0].index[-1]
    # young ETF listing shortly before the satellites' history ends -> a real
    # but very short overlap (not zero, which would be a different error).
    core_start = sat_end - pd.tseries.offsets.BDay(50)
    core = _series(_path(60, 0.0004, 0.01, 1), start=core_start)
    cmp = compare_core_satellite(core, sats, subwindow_days=504)
    assert cmp.note and "too little history" in cmp.note
    assert "newer than the satellite" in cmp.note      # names the likely cause


def test_returns_dataclass():
    assert isinstance(compare_core_satellite(_series([1.0, 2.0]), {}),
                      CoreSatelliteComparison)


# ---------------- structural truths -------------------------------------------

def test_concentrated_satellites_are_more_volatile_than_a_broad_core():
    """The premise the holdings curve established: fewer, individually
    riskier names = more portfolio volatility."""
    core, sats = _core_and_sats(core_vol=0.007, sat_vol=0.020, n_sats=5, seed=2)
    cmp = compare_core_satellite(core, sats)
    assert cmp.satellite_only.ann_vol_pct > cmp.core_only.ann_vol_pct
    assert cmp.core_only.ann_vol_pct < cmp.blend.ann_vol_pct < cmp.satellite_only.ann_vol_pct


def test_blend_sits_between_the_two_pure_arms_on_return():
    core, sats = _core_and_sats(core_drift=0.0002, sat_drift=0.0008, seed=3)
    cmp = compare_core_satellite(core, sats, core_weight=0.5)
    lo = min(cmp.core_only.cagr_pct, cmp.satellite_only.cagr_pct)
    hi = max(cmp.core_only.cagr_pct, cmp.satellite_only.cagr_pct)
    assert lo - 1e-6 <= cmp.blend.cagr_pct <= hi + 1e-6


def test_core_weight_one_makes_blend_identical_to_core():
    """Sanity on the mechanism: 100% core weight means the blend IS the core."""
    core, sats = _core_and_sats(seed=4)
    cmp = compare_core_satellite(core, sats, core_weight=1.0)
    assert abs(cmp.blend.cagr_pct - cmp.core_only.cagr_pct) < 1e-6
    assert abs(cmp.blend.ann_vol_pct - cmp.core_only.ann_vol_pct) < 1e-6


def test_strong_satellites_win_most_rolling_windows():
    """If the satellites genuinely outperform throughout, the blend should
    beat core-only in a large majority of rolling windows."""
    core, sats = _core_and_sats(core_drift=0.0001, sat_drift=0.0009,
                                sat_vol=0.010, seed=5)
    cmp = compare_core_satellite(core, sats, core_weight=0.5, subwindow_days=252)
    assert cmp.blend_win_rate_pct > 60.0


def test_weak_satellites_lose_most_rolling_windows():
    core, sats = _core_and_sats(core_drift=0.0009, sat_drift=0.0001,
                                sat_vol=0.020, seed=6)
    cmp = compare_core_satellite(core, sats, core_weight=0.5, subwindow_days=252)
    assert cmp.blend_win_rate_pct < 40.0


# ---------------- reporting ---------------------------------------------------

def test_verdict_calls_out_a_sleeve_that_does_not_earn_its_risk():
    core, sats = _core_and_sats(core_drift=0.0009, sat_drift=0.0000,
                                core_vol=0.008, sat_vol=0.022, seed=7)
    cmp = compare_core_satellite(core, sats, core_weight=0.5, subwindow_days=252)
    text = format_core_satellite(cmp)
    assert "did NOT earn its risk" in text
    # and points at the right remedy, not a re-pick (selection was already null)
    assert "already tested" in text and "null" in text


def test_verdict_credits_a_sleeve_that_does_earn_its_risk():
    core, sats = _core_and_sats(core_drift=0.0001, sat_drift=0.0009,
                                sat_vol=0.010, seed=8)
    cmp = compare_core_satellite(core, sats, core_weight=0.5, subwindow_days=252)
    text = format_core_satellite(cmp)
    assert "EARNED its risk" in text


def test_short_sample_gets_a_loud_caveat_in_the_verdict():
    """Just over the minimum to run, but well under 3 years -> the verdict must
    shout about sample size rather than presenting a confident conclusion."""
    n = 560          # ~2.2y, enough for a 504d subwindow but short
    core = _series(_path(n, 0.0004, 0.008, 9))
    sats = {f"S{i}.JK": _series(_path(n, 0.0004, 0.016, 20 + i)) for i in range(4)}
    cmp = compare_core_satellite(core, sats, subwindow_days=504)
    text = format_core_satellite(cmp)
    assert "SAMPLE IS SHORT" in text


def test_format_states_the_question_and_has_a_verdict():
    core, sats = _core_and_sats(seed=10)
    cmp = compare_core_satellite(core, sats)
    text = format_core_satellite(cmp)
    assert "EARN the extra risk" in text
    assert "core only" in text and "satellites only" in text
    assert "rolling windows" in text
    assert "READ:" in text


def test_format_handles_failed_run():
    text = format_core_satellite(compare_core_satellite(_series([1.0, 2.0]), {}))
    assert "could not run" in text


# ---------------- sizing sweep ------------------------------------------------

def test_sweep_endpoints_match_the_pure_arms():
    """core_weight=1.0 must reproduce core-only and 0.0 must reproduce
    satellites-only -- the sweep and the three-arm comparison have to agree."""
    from kala.core_satellite_backtest import sweep_core_weight
    core, sats = _core_and_sats(seed=11)
    cmp = compare_core_satellite(core, sats)
    sw = sweep_core_weight(core, sats, weights=(0.0, 0.5, 1.0))
    by_w = {p.core_weight: p for p in sw.points}
    assert abs(by_w[1.0].cagr_pct - cmp.core_only.cagr_pct) < 1e-6
    assert abs(by_w[0.0].cagr_pct - cmp.satellite_only.cagr_pct) < 1e-6


def test_sweep_returns_a_point_per_weight():
    from kala.core_satellite_backtest import sweep_core_weight
    core, sats = _core_and_sats(seed=12)
    weights = (0.0, 0.25, 0.5, 0.75, 1.0)
    sw = sweep_core_weight(core, sats, weights=weights)
    assert tuple(p.core_weight for p in sw.points) == weights


def test_sweep_verdict_refuses_to_crown_an_optimum():
    """The sweep runs over ONE realized history, so its argmax is the weight
    that happened to suit the past. The output must warn against adopting it
    rather than presenting a 'best' weight -- this project has thirteen failed
    studies' worth of reasons not to read a maximum off a single backtest."""
    from kala.core_satellite_backtest import format_sizing_sweep, sweep_core_weight
    core, sats = _core_and_sats(seed=13)
    text = format_sizing_sweep(sweep_core_weight(core, sats))
    assert "overfitting" in text.lower()
    assert "not to pick a number" in text.lower() or "not to pick" in text.lower()
    assert "best" in text.lower()          # it names the trap explicitly


def test_sweep_handles_failed_run():
    from kala.core_satellite_backtest import format_sizing_sweep, sweep_core_weight
    assert "could not run" in format_sizing_sweep(sweep_core_weight(_series([1.0, 2.0]), {}))
