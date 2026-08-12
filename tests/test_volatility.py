"""
GARCH(1,1) volatility-forecasting tests: fit sanity, forecast direction
under an obvious vol-regime shift, and the risk_pct scaling helper. This
is sizing infrastructure, not a signal -- tests only prove the math
behaves as documented, not that it improves outcomes.
"""

import numpy as np
import pytest

from kala.volatility import (
    Garch11Params,
    fit_garch11,
    forecast_volatility,
    scaled_risk_pct,
)


def _low_vol_returns(n=250, seed=0):
    rng = np.random.default_rng(seed)
    return rng.normal(0.0, 0.005, n)


def _regime_shift_returns(n_low=150, n_high=100, seed=1):
    """Calm, then a sustained volatility spike -- GARCH should forecast
    HIGHER vol right after the spike than right after the calm stretch."""
    rng = np.random.default_rng(seed)
    low = rng.normal(0.0, 0.004, n_low)
    high = rng.normal(0.0, 0.035, n_high)
    return np.concatenate([low, high])


# ---------------- fit_garch11 -------------------------------------------------

def test_fit_returns_none_for_insufficient_history():
    assert fit_garch11(_low_vol_returns(n=30)) is None


def test_fit_returns_none_for_zero_variance_series():
    assert fit_garch11(np.zeros(200)) is None


def test_fit_returns_valid_stationary_params():
    params = fit_garch11(_low_vol_returns(n=250))
    assert isinstance(params, Garch11Params)
    assert params.alpha >= 0
    assert params.beta >= 0
    assert params.alpha + params.beta < 1.0
    assert params.omega > 0
    assert params.long_run_var > 0


def test_fit_accepts_pandas_series():
    import pandas as pd
    s = pd.Series(_low_vol_returns(n=250))
    params = fit_garch11(s)
    assert params is not None


# ---------------- forecast_volatility -----------------------------------------

def test_forecast_is_positive():
    returns = _low_vol_returns(n=250)
    params = fit_garch11(returns)
    vol = forecast_volatility(returns, params)
    assert vol > 0


def test_forecast_higher_right_after_a_volatility_spike():
    """The core GARCH property this module exists to capture: recent large
    shocks raise the near-term forecast above the long-run average."""
    calm = _low_vol_returns(n=250, seed=2)
    spiked = _regime_shift_returns(n_low=150, n_high=100, seed=3)

    calm_params = fit_garch11(calm)
    spiked_params = fit_garch11(spiked)
    assert calm_params is not None and spiked_params is not None

    calm_forecast = forecast_volatility(calm, calm_params)
    spiked_forecast = forecast_volatility(spiked, spiked_params)
    assert spiked_forecast > calm_forecast


def test_long_horizon_forecast_converges_toward_long_run_variance():
    returns = _regime_shift_returns()
    params = fit_garch11(returns)
    far_forecast = forecast_volatility(returns, params, horizon=500)
    long_run_vol = np.sqrt(params.long_run_var)
    assert far_forecast == pytest.approx(long_run_vol, rel=0.05)


# ---------------- scaled_risk_pct ---------------------------------------------

def test_scale_up_when_forecast_calmer_than_reference():
    scaled = scaled_risk_pct(base_risk_pct=2.0, forecast_vol=0.01, reference_vol=0.02)
    assert scaled > 2.0


def test_scale_down_when_forecast_more_volatile_than_reference():
    scaled = scaled_risk_pct(base_risk_pct=2.0, forecast_vol=0.04, reference_vol=0.02)
    assert scaled < 2.0


def test_scale_clamped_to_max():
    scaled = scaled_risk_pct(base_risk_pct=2.0, forecast_vol=0.001, reference_vol=0.02,
                             max_scale=1.5)
    assert scaled == pytest.approx(2.0 * 1.5)


def test_scale_clamped_to_min():
    scaled = scaled_risk_pct(base_risk_pct=2.0, forecast_vol=1.0, reference_vol=0.02,
                             min_scale=0.5)
    assert scaled == pytest.approx(2.0 * 0.5)


def test_scale_falls_back_to_base_on_invalid_input():
    assert scaled_risk_pct(2.0, forecast_vol=0.0, reference_vol=0.02) == 2.0
    assert scaled_risk_pct(2.0, forecast_vol=0.02, reference_vol=0.0) == 2.0
