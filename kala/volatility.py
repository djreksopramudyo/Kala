"""
GARCH(1,1) volatility forecasting for risk-based position sizing.

WHY THIS EXISTS
---------------
``PaperTrader.size_position``'s ``risk_pct`` is currently a FLAT constant
(2% by default) regardless of how volatile a stock currently is. Sizing the
same risk budget into a calm blue-chip and a stock mid volatility-spike
treats very different risk profiles identically. A GARCH(1,1) forecast of
near-term volatility lets the caller scale ``risk_pct`` DOWN when a stock's
volatility is elevated relative to its own history, and back UP when it's
calm -- same risk budget, sized to CURRENT conditions instead of a flat
number.

STATUS: sizing mechanics only, not a trading signal -- this claims no
edge. Feed ``scaled_risk_pct``'s output into an EXISTING call to
``PaperTrader.size_position(risk_pct=...)`` if you want to try it; nothing
here is wired in by default, and ``size_position``'s own default is
unchanged.

No external GARCH library (``arch``, ...) is available in this
environment, so this ships a minimal, dependency-free GARCH(1,1) fit via
grid search over (alpha, beta) with variance targeting for omega --
coarse but sufficient for a volatility-scaling multiplier, not
research-grade parameter precision.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

_ALPHA_GRID = tuple(round(0.02 + 0.02 * i, 2) for i in range(15))   # 0.02 .. 0.30
_BETA_GRID = tuple(round(0.50 + 0.03 * i, 2) for i in range(17))    # 0.50 .. 0.98


@dataclass(frozen=True)
class Garch11Params:
    omega: float
    alpha: float
    beta: float
    loglik: float
    long_run_var: float


def _conditional_variance_path(eps: np.ndarray, omega: float, alpha: float,
                               beta: float, sigma2_0: float) -> np.ndarray:
    """sigma2[0] = sigma2_0 (a seed, not fitted); sigma2[t] for t>=1 follows
    the GARCH(1,1) recursion off eps[t-1] and sigma2[t-1]."""
    n = len(eps)
    sigma2 = np.empty(n)
    sigma2[0] = sigma2_0
    for t in range(1, n):
        sigma2[t] = omega + alpha * eps[t - 1] ** 2 + beta * sigma2[t - 1]
    return sigma2


def _gaussian_loglik(eps: np.ndarray, sigma2: np.ndarray) -> float:
    sigma2 = np.clip(sigma2, 1e-12, None)
    return float(-0.5 * np.sum(np.log(2.0 * np.pi * sigma2) + eps ** 2 / sigma2))


def fit_garch11(returns: pd.Series | np.ndarray, min_obs: int = 60) -> Garch11Params | None:
    """Fit GARCH(1,1) to a return series via grid search + variance
    targeting (omega = long_run_var * (1 - alpha - beta) for each grid
    point, so every candidate is stationarity-consistent by construction).
    Returns None if there isn't enough history, or if returns have no
    variance (e.g. a halted/flat name) -- nothing to fit.
    """
    eps = np.asarray(returns, dtype=float)
    eps = eps[np.isfinite(eps)]
    if len(eps) < min_obs:
        return None
    eps = eps - eps.mean()   # demean: GARCH models the variance, not the drift
    long_run_var = float(np.var(eps))
    if long_run_var <= 0:
        return None

    best: Garch11Params | None = None
    for alpha in _ALPHA_GRID:
        for beta in _BETA_GRID:
            if alpha + beta >= 0.999:
                continue
            omega = long_run_var * (1.0 - alpha - beta)
            sigma2 = _conditional_variance_path(eps, omega, alpha, beta, long_run_var)
            ll = _gaussian_loglik(eps, sigma2)
            if best is None or ll > best.loglik:
                best = Garch11Params(omega=omega, alpha=alpha, beta=beta,
                                     loglik=ll, long_run_var=long_run_var)
    return best


def forecast_volatility(returns: pd.Series | np.ndarray, params: Garch11Params,
                        horizon: int = 1) -> float:
    """Forecast daily volatility (std dev, NOT variance) ``horizon`` steps
    ahead, using the fitted GARCH(1,1) recursion seeded off the LAST
    observed return and its final in-sample conditional variance, then
    mean-reverting the multi-step forecast toward the long-run variance at
    rate (alpha+beta)^h -- the standard GARCH forecast-convergence formula.
    """
    eps = np.asarray(returns, dtype=float)
    eps = eps[np.isfinite(eps)]
    eps = eps - eps.mean()
    sigma2_path = _conditional_variance_path(eps, params.omega, params.alpha,
                                             params.beta, params.long_run_var)
    sigma2_last = float(sigma2_path[-1])
    eps_last = float(eps[-1])
    sigma2_next = params.omega + params.alpha * eps_last ** 2 + params.beta * sigma2_last

    if horizon <= 1:
        return float(np.sqrt(max(sigma2_next, 0.0)))

    persistence = params.alpha + params.beta
    sigma2_h = params.long_run_var + (persistence ** (horizon - 1)) * (sigma2_next - params.long_run_var)
    return float(np.sqrt(max(sigma2_h, 0.0)))


def scaled_risk_pct(base_risk_pct: float, forecast_vol: float, reference_vol: float,
                    min_scale: float = 0.5, max_scale: float = 1.5) -> float:
    """Scale a flat risk_pct by how the CURRENT volatility forecast
    compares to a reference (e.g. the stock's own long-run vol, or a
    universe-wide median): calmer than reference -> scale up (more room
    within the same risk budget); more volatile -> scale down. Clamped to
    [min_scale, max_scale] so one extreme reading can't blow the position
    up or down to near-zero.
    """
    if forecast_vol <= 0 or reference_vol <= 0:
        return base_risk_pct
    scale = reference_vol / forecast_vol
    scale = max(min_scale, min(max_scale, scale))
    return base_risk_pct * scale
