"""
Overfitting-diagnostic tests: Deflated Sharpe Ratio + PBO (CSCV).

The invariants that matter:
  * DSR is always a probability (0-1); more trials at the same observed
    Sharpe must LOWER confidence (more room for the best-of-N effect).
  * A single trial needs no deflation (benchmark Sharpe = 0).
  * PBO on a config that STRICTLY dominates every period must be 0 (no
    overfitting signature -- it really does keep winning OOS).
  * PBO on genuine cross-period noise must land near the 50% coin-flip
    line, not near either extreme.
"""


import numpy as np
import pytest

from kala.overfitting import (
    DeflatedSharpeResult,
    PBOResult,
    _norm_cdf,
    _norm_ppf,
    deflated_sharpe_ratio,
    expected_max_sharpe_under_null,
    probability_backtest_overfitting,
)

# ---------------- normal CDF/PPF helpers (no-scipy implementation) ----------

def test_norm_cdf_known_values():
    assert _norm_cdf(0.0) == pytest.approx(0.5, abs=1e-9)
    assert _norm_cdf(1.6448536269514722) == pytest.approx(0.95, abs=1e-6)


def test_norm_ppf_is_inverse_of_cdf():
    for p in (0.01, 0.1, 0.25, 0.5, 0.75, 0.9, 0.99):
        assert _norm_cdf(_norm_ppf(p)) == pytest.approx(p, abs=1e-6)


def test_norm_ppf_rejects_out_of_range():
    with pytest.raises(ValueError):
        _norm_ppf(0.0)
    with pytest.raises(ValueError):
        _norm_ppf(1.0)


# ---------------- expected max Sharpe under the null ------------------------

def test_expected_max_sharpe_zero_for_single_trial():
    assert expected_max_sharpe_under_null(1, trial_variance=0.5) == 0.0


def test_expected_max_sharpe_grows_with_more_trials():
    v = 0.1
    sr_10 = expected_max_sharpe_under_null(10, v)
    sr_100 = expected_max_sharpe_under_null(100, v)
    sr_1000 = expected_max_sharpe_under_null(1000, v)
    assert 0 < sr_10 < sr_100 < sr_1000


def test_expected_max_sharpe_rejects_bad_input():
    with pytest.raises(ValueError):
        expected_max_sharpe_under_null(0, 0.1)
    with pytest.raises(ValueError):
        expected_max_sharpe_under_null(10, -0.1)


# ---------------- deflated Sharpe ratio --------------------------------------

def test_dsr_is_always_a_probability():
    r = deflated_sharpe_ratio(observed_sharpe=1.5, n_trials=5, n_observations=200)
    assert isinstance(r, DeflatedSharpeResult)
    assert 0.0 <= r.dsr <= 1.0


def test_dsr_single_trial_has_zero_benchmark():
    r = deflated_sharpe_ratio(observed_sharpe=1.0, n_trials=1, n_observations=200)
    assert r.sharpe_benchmark == 0.0


def test_dsr_more_trials_lowers_confidence_at_same_observed_sharpe():
    """The core deflation property: holding the observed Sharpe and sample
    size fixed, testing MORE configurations to find that Sharpe must make
    it LESS trustworthy, never more."""
    few = deflated_sharpe_ratio(observed_sharpe=0.5, n_trials=2, n_observations=60)
    many = deflated_sharpe_ratio(observed_sharpe=0.5, n_trials=500, n_observations=60)
    assert many.dsr < few.dsr
    assert many.sharpe_benchmark > few.sharpe_benchmark


def test_dsr_extreme_sharpe_survives_deflation_a_lot_of_trials():
    """A very strong, unambiguous Sharpe should still clear a high bar even
    after searching many trials -- deflation should not be able to erase a
    truly enormous effect size."""
    r = deflated_sharpe_ratio(observed_sharpe=4.0, n_trials=50, n_observations=500)
    assert r.dsr > 0.95


def test_dsr_weak_sharpe_many_trials_reads_as_noise():
    """This is the min-price-retraction shape: a modest Sharpe that only
    looked good because several configurations were tried."""
    r = deflated_sharpe_ratio(observed_sharpe=0.2, n_trials=200, n_observations=60)
    assert r.dsr < 0.5
    assert "noise" in r.verdict.lower()


def test_dsr_rejects_too_few_observations():
    with pytest.raises(ValueError):
        deflated_sharpe_ratio(observed_sharpe=1.0, n_trials=5, n_observations=1)


def test_dsr_summary_text_contains_key_numbers():
    r = deflated_sharpe_ratio(observed_sharpe=1.5, n_trials=10, n_observations=200)
    txt = r.summary_text()
    assert "DSR=" in txt and "VERDICT" in txt


# ---------------- PBO (CSCV) --------------------------------------------------

def test_pbo_zero_when_one_config_strictly_dominates_every_period():
    """A configuration that wins EVERY single period, in-sample and out --
    the opposite of overfitting. PBO must read exactly 0."""
    rng = np.random.default_rng(0)
    n_periods, n_configs = 16, 5
    M = rng.normal(0, 0.1, size=(n_periods, n_configs))
    M[:, 0] = 10.0   # config 0 dominates unconditionally, every single period
    r = probability_backtest_overfitting(M, n_splits=8)
    assert isinstance(r, PBOResult)
    assert r.pbo == 0.0
    assert r.n_configs == 5 and r.n_periods == 16


def test_pbo_near_half_for_genuine_cross_period_noise():
    """Configs with IDENTICAL underlying distribution -- any apparent
    in-sample 'winner' is pure noise and should NOT reliably repeat
    out-of-sample. PBO should land near the 50% coin-flip line, not at
    either extreme like the dominant-config case above."""
    rng = np.random.default_rng(7)
    n_periods, n_configs = 80, 6
    M = rng.normal(0, 1.0, size=(n_periods, n_configs))   # no real skill differences
    r = probability_backtest_overfitting(M, n_splits=8)
    assert 0.2 <= r.pbo <= 0.8, f"expected near-coin-flip PBO for pure noise, got {r.pbo}"


def test_pbo_rejects_too_few_configs():
    with pytest.raises(ValueError):
        probability_backtest_overfitting(np.zeros((16, 1)), n_splits=8)


def test_pbo_rejects_odd_n_splits():
    with pytest.raises(ValueError):
        probability_backtest_overfitting(np.zeros((16, 3)), n_splits=7)


def test_pbo_rejects_non_divisible_periods():
    with pytest.raises(ValueError):
        probability_backtest_overfitting(np.zeros((15, 3)), n_splits=8)


def test_pbo_verdict_text_scales_with_severity():
    high = probability_backtest_overfitting(
        np.random.default_rng(1).normal(0, 1, (80, 6)), n_splits=8)
    dominant = np.full((16, 5), 0.0)
    dominant[:, 0] = 10.0
    low = probability_backtest_overfitting(dominant, n_splits=8)
    assert low.pbo < high.pbo
    assert "overfitting" in low.verdict.lower() or low.pbo < 0.3


def test_pbo_summary_text_contains_key_numbers():
    M = np.random.default_rng(2).normal(0, 1, (16, 4))
    r = probability_backtest_overfitting(M, n_splits=8)
    txt = r.summary_text()
    assert "PBO:" in txt and "VERDICT" in txt


# ---------------- integration: real walk-forward folds ----------------------

def _wf_universe(k=3, n=900):
    import pandas as pd
    idx = pd.bdate_range("2022-01-03", periods=n)
    dfs = {}
    for i in range(k):
        rng = np.random.default_rng(i)
        close = 1000.0 * np.exp(np.cumsum(rng.normal(0.0012 + 0.0002 * i, 0.015, n)))
        dfs[f"T{i}.JK"] = pd.DataFrame(
            {"Open": close, "High": close * 1.005, "Low": close * 0.995,
             "Close": close, "Volume": np.full(n, 2_000_000.0)}, index=idx)
    return dfs


def test_pbo_from_walkforward_sweep_runs_on_real_folds():
    from kala.config import Config
    from kala.overfitting import pbo_from_walkforward_sweep

    dfs = _wf_universe(k=3, n=900)
    cfg = Config()
    r = pbo_from_walkforward_sweep(dfs, cfg, thresholds=(45.0, 55.0, 65.0),
                                   train_bars=150, test_bars=60, warmup_bars=30,
                                   n_splits=2)
    assert isinstance(r, PBOResult)
    assert 0.0 <= r.pbo <= 1.0
    assert r.n_configs == 3


def test_pbo_from_walkforward_sweep_raises_when_not_enough_folds():
    from kala.config import Config
    from kala.overfitting import pbo_from_walkforward_sweep

    dfs = _wf_universe(k=2, n=400)   # too short for 8 folds
    cfg = Config()
    with pytest.raises(ValueError, match="fold"):
        pbo_from_walkforward_sweep(dfs, cfg, thresholds=(45.0, 55.0),
                                   train_bars=150, test_bars=60, warmup_bars=30,
                                   n_splits=8)
