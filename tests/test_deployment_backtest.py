"""Deployment (lump sum vs DCA) tests. Uses SYNTHETIC price paths with known
direction so the structural truths are verifiable rather than hoped for: in a
rising market lump sum must win (cash misses the drift), in a falling market
DCA must win (cash avoids the fall), and DCA must always cut the worst-case
when the fall comes right after deployment starts."""

import numpy as np
import pandas as pd

from kala.deployment_backtest import (
    MONTH_DAYS,
    DeploymentComparison,
    _simulate_window,
    compare_deployment,
    format_deployment,
)


def _series(values, start="2016-01-01"):
    idx = pd.bdate_range(start, periods=len(values))
    return pd.Series(np.asarray(values, dtype=float), index=idx)


def _trending(n, daily, start=1000.0):
    return start * np.cumprod(np.full(n, 1.0 + daily))


# ---------------- guardrails --------------------------------------------------

def test_too_little_history_is_reported():
    prices = {"A": _series(np.linspace(100, 110, 100))}
    cmp = compare_deployment(prices, horizon_days=756, dca_months=12)
    assert cmp.note and "overlapping days" in cmp.note


def test_returns_dataclass():
    cmp = compare_deployment({}, horizon_days=756)
    assert isinstance(cmp, DeploymentComparison)


# ---------------- the structural truths ---------------------------------------

def test_rising_market_lump_sum_wins():
    """The core reason lump sum wins on average: in a market that drifts up,
    money held in cash waiting to be deployed misses that drift."""
    lump, dca, _, _ = _simulate_window(_trending(756, 0.0005), dca_months=12,
                                       cost_rate=0.0, daily_cash_rate=0.0)
    assert lump > dca


def test_falling_market_dca_wins():
    """The mirror case, and DCA's actual selling point: in a market that
    falls, staying partly in cash avoids part of the fall."""
    lump, dca, _, _ = _simulate_window(_trending(756, -0.0005), dca_months=12,
                                       cost_rate=0.0, daily_cash_rate=0.0)
    assert dca > lump


def test_dca_cuts_worst_case_drawdown_on_a_crash_at_the_start():
    """DCA's protection is specifically against deploying right before a
    crash — its max drawdown must be shallower when the fall comes early."""
    n = 756
    level = np.concatenate([
        _trending(200, -0.004, start=1000.0),               # early crash
        _trending(n - 200, 0.0006, start=1000.0 * (1 - 0.004) ** 200),  # recovery
    ])
    _, _, lump_dd, dca_dd = _simulate_window(level, dca_months=12,
                                             cost_rate=0.0, daily_cash_rate=0.0)
    assert dca_dd > lump_dd     # both negative; ">" means shallower


def test_single_slice_dca_equals_lump_sum():
    """Sanity on the mechanism: DCA with exactly 1 slice IS lump sum, so the
    two arms must agree (up to float noise)."""
    level = _trending(400, 0.0004)
    lump, dca, _, _ = _simulate_window(level, dca_months=1, cost_rate=0.002,
                                       daily_cash_rate=0.0)
    assert abs(lump - dca) < 1e-9


def test_cash_yield_helps_dca():
    """Undeployed cash earning a real rate must improve DCA's outcome — the
    honest best case for DCA, and why the CLI exposes it."""
    level = _trending(756, 0.0005)
    _, dca_no_yield, _, _ = _simulate_window(level, 12, cost_rate=0.0, daily_cash_rate=0.0)
    daily = (1.05) ** (1 / 252) - 1        # 5%/yr
    _, dca_with_yield, _, _ = _simulate_window(level, 12, cost_rate=0.0, daily_cash_rate=daily)
    assert dca_with_yield > dca_no_yield


def test_costs_reduce_both_arms():
    level = _trending(756, 0.0005)
    free_l, free_d, _, _ = _simulate_window(level, 12, cost_rate=0.0, daily_cash_rate=0.0)
    cost_l, cost_d, _, _ = _simulate_window(level, 12, cost_rate=0.01, daily_cash_rate=0.0)
    assert cost_l < free_l and cost_d < free_d


def test_dca_deploys_over_the_expected_span():
    """All slices must be deployed by month N -- after that the DCA arm is
    fully invested, so from then on it tracks the basket 1:1 like lump sum."""
    n = MONTH_DAYS * 12 + 300
    level = _trending(n, 0.0)          # flat market: no drift to confuse it
    lump, dca, _, _ = _simulate_window(level, dca_months=12, cost_rate=0.0,
                                       daily_cash_rate=0.0)
    # flat prices, no costs, no cash yield -> both end at exactly 1.0x
    assert abs(lump - 1.0) < 1e-9
    assert abs(dca - 1.0) < 1e-9


# ---------------- rolling-window comparison -----------------------------------

def _long_rising_basket(n=2500, seed=1):
    rng = np.random.default_rng(seed)
    path = 1000 * np.exp(np.cumsum(rng.normal(0.0005, 0.012, n)))
    return {"A": _series(path), "B": _series(path * 1.01)}


def test_rolling_comparison_reports_a_distribution():
    cmp = compare_deployment(_long_rising_basket(), horizon_days=504,
                             dca_months=12, cost_rate=0.001, step_days=21)
    assert cmp.lump.n_windows > 10          # many start dates, not one
    assert 0.0 <= cmp.lump_win_rate_pct <= 100.0
    assert cmp.lump.p5_terminal <= cmp.lump.median_terminal <= cmp.lump.p95_terminal


def test_rising_basket_lump_wins_majority_of_windows():
    cmp = compare_deployment(_long_rising_basket(), horizon_days=504,
                             dca_months=12, cost_rate=0.001, step_days=21)
    assert cmp.lump_win_rate_pct > 50.0


# ---------------- reporting ---------------------------------------------------

def test_format_reports_both_average_and_worst_case():
    cmp = compare_deployment(_long_rising_basket(), horizon_days=504,
                             dca_months=12, cost_rate=0.001, step_days=21)
    text = format_deployment(cmp, cost_rate=0.001)
    assert "LUMP SUM" in text and "DCA" in text
    assert "worst" in text.lower()          # worst-case row present, not just averages
    assert "DISTRIBUTION" in text           # states it's many start dates
    assert "READ:" in text


def test_format_handles_failed_run():
    cmp = compare_deployment({}, horizon_days=756)
    text = format_deployment(cmp, cost_rate=0.003)
    assert "could not run" in text


def test_verdict_credits_dca_for_better_MEDIAN_drawdown_not_just_worst():
    """Regression: an earlier verdict looked only at the WORST-case drawdown.
    On a basket where both schedules share the same single worst crash, it
    wrongly announced DCA 'did not buy better protection' while DCA was
    meaningfully better in the TYPICAL window -- the drawdown a user actually
    lives through most of the time. Construct that exact situation and assert
    the verdict now credits it."""
    from kala.deployment_backtest import (
        DeploymentComparison,
        DeploymentStats,
        format_deployment,
    )
    lump = DeploymentStats(n_windows=100, median_terminal=1.24, mean_terminal=1.27,
                           p5_terminal=0.88, p95_terminal=1.6, worst_terminal=0.79,
                           median_max_drawdown_pct=-32.4,     # notably deeper
                           worst_max_drawdown_pct=-48.9)      # but SAME worst case
    dca = DeploymentStats(n_windows=100, median_terminal=1.08, mean_terminal=1.20,
                          p5_terminal=0.87, p95_terminal=1.5, worst_terminal=0.77,
                          median_max_drawdown_pct=-29.5,
                          worst_max_drawdown_pct=-48.9)
    cmp = DeploymentComparison(lump, dca, lump_win_rate_pct=62.0, median_gap_pct=2.9,
                               dca_months=12, horizon_days=756, cash_yield_annual=0.0,
                               n_days=2006)
    text = format_deployment(cmp, cost_rate=0.003)
    assert "did not buy meaningfully better" not in text
    assert "median" in text.lower() and "-32.4" in text
