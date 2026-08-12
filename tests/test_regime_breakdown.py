"""
Regime-conditional performance breakdown tests: pools baseline-threshold
walk-forward OOS trades and buckets them by benchmark regime at entry.
"""

import numpy as np
import pandas as pd
import pytest

from kala.regime_breakdown import RegimeBreakdownResult, regime_conditional_breakdown


def _make_df(n=400, seed=0, drift=0.001, start="2022-01-03"):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(start, periods=n)
    close = 1000.0 * np.exp(np.cumsum(rng.normal(drift, 0.015, n)))
    return pd.DataFrame(
        {"Open": close, "High": close * 1.005, "Low": close * 0.995,
         "Close": close, "Volume": np.full(n, 2_000_000.0)}, index=idx)


def _bull_benchmark(n=400, start="2022-01-03"):
    idx = pd.bdate_range(start, periods=n)
    close = 1000.0 * np.exp(np.cumsum(np.full(n, 0.0015)))   # steady rally throughout
    return pd.DataFrame(
        {"Open": close, "High": close * 1.002, "Low": close * 0.998, "Close": close},
        index=idx)


def test_requires_a_benchmark():
    dfs = {"A.JK": _make_df(n=300)}
    with pytest.raises(ValueError, match="benchmark"):
        regime_conditional_breakdown(dfs, benchmark=None)


def test_requires_enough_benchmark_history():
    dfs = {"A.JK": _make_df(n=300)}
    short_bench = _bull_benchmark(n=10)
    with pytest.raises(ValueError, match="benchmark"):
        regime_conditional_breakdown(dfs, benchmark=short_bench)


def test_runs_end_to_end_and_returns_result():
    dfs = {f"T{i}.JK": _make_df(seed=i, drift=0.0012 + 0.0002 * i, n=400) for i in range(3)}
    bench = _bull_benchmark(n=400)
    result = regime_conditional_breakdown(dfs, benchmark=bench, train_bars=200,
                                          test_bars=60, warmup_bars=30)
    assert isinstance(result, RegimeBreakdownResult)
    assert result.n_trades_total >= 0


def test_steady_bull_benchmark_concentrates_trades_in_bull_buckets():
    """A benchmark that only ever rallies should tag OOS trades almost
    entirely BULLISH/MODERATE_BULL -- never BEARISH -- proving the tagging
    actually reflects the regime series, not noise."""
    dfs = {f"T{i}.JK": _make_df(seed=i, drift=0.0012 + 0.0002 * i, n=400) for i in range(3)}
    bench = _bull_benchmark(n=400)
    result = regime_conditional_breakdown(dfs, benchmark=bench, train_bars=200,
                                          test_bars=60, warmup_bars=30)
    if result.n_trades_total > 0:
        bear_trades = result.by_regime.get("BEARISH", {}).get("n", 0)
        bear_trades += result.by_regime.get("MODERATE_BEAR", {}).get("n", 0)
        assert bear_trades == 0


def test_summary_text_reports_total_and_per_regime_lines():
    dfs = {f"T{i}.JK": _make_df(seed=i, drift=0.0012 + 0.0002 * i, n=400) for i in range(3)}
    bench = _bull_benchmark(n=400)
    result = regime_conditional_breakdown(dfs, benchmark=bench, train_bars=200,
                                          test_bars=60, warmup_bars=30)
    text = result.summary_text()
    assert "REGIME-CONDITIONAL" in text
    assert f"total trades: {result.n_trades_total}" in text


def test_by_regime_stats_sum_to_total_trades():
    dfs = {f"T{i}.JK": _make_df(seed=i, drift=0.0012 + 0.0002 * i, n=400) for i in range(3)}
    bench = _bull_benchmark(n=400)
    result = regime_conditional_breakdown(dfs, benchmark=bench, train_bars=200,
                                          test_bars=60, warmup_bars=30)
    summed = sum(s.get("n", 0) for s in result.by_regime.values())
    assert summed == result.n_trades_total
