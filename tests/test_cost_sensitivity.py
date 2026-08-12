"""
Transaction-cost sensitivity sweep tests: cost-grid construction and the
breakeven-multiplier logic, on synthetic data (fast, deterministic).
"""

import numpy as np
import pandas as pd

from kala.config import Config, CostModel
from kala.cost_sensitivity import (
    CostSweepPoint,
    CostSweepResult,
    scaled_cost_model,
    sweep_costs,
)


def _make_df(n=400, seed=0, drift=0.001, start="2022-01-03"):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(start, periods=n)
    close = 1000.0 * np.exp(np.cumsum(rng.normal(drift, 0.015, n)))
    return pd.DataFrame(
        {"Open": close, "High": close * 1.005, "Low": close * 0.995,
         "Close": close, "Volume": np.full(n, 2_000_000.0)}, index=idx)


# ---------------- scaled_cost_model ------------------------------------------

def test_scaled_cost_model_multiplier_one_is_unchanged():
    base = CostModel()
    scaled = scaled_cost_model(base, 1.0)
    assert scaled == base


def test_scaled_cost_model_zero_is_frictionless():
    base = CostModel()
    scaled = scaled_cost_model(base, 0.0)
    assert scaled.buy_commission == 0.0
    assert scaled.sell_commission == 0.0
    assert scaled.sell_tax == 0.0
    assert scaled.half_spread == 0.0


def test_scaled_cost_model_scales_every_component():
    base = CostModel()
    scaled = scaled_cost_model(base, 2.0)
    assert scaled.buy_commission == base.buy_commission * 2.0
    assert scaled.sell_commission == base.sell_commission * 2.0
    assert scaled.sell_tax == base.sell_tax * 2.0
    assert scaled.half_spread == base.half_spread * 2.0


def test_scaled_cost_model_preserves_spread_mode():
    base = CostModel(spread_mode="tick_floor")
    scaled = scaled_cost_model(base, 1.5)
    assert scaled.spread_mode == "tick_floor"


# ---------------- sweep_costs / CostSweepResult -------------------------------

def test_sweep_costs_runs_one_point_per_multiplier():
    dfs = {f"T{i}.JK": _make_df(seed=i, drift=0.0012 + 0.0002 * i) for i in range(3)}
    result = sweep_costs(dfs, multipliers=(0.0, 1.0, 2.0), thresholds=(50.0, 60.0),
                         train_bars=200, test_bars=60, warmup_bars=30, min_train_trades=1)
    assert isinstance(result, CostSweepResult)
    assert [p.multiplier for p in result.points] == [0.0, 1.0, 2.0]
    for pt in result.points:
        assert isinstance(pt, CostSweepPoint)
        assert pt.report is not None


def test_sweep_costs_frictionless_ev_at_least_as_good_as_costly():
    """0x cost EV/trade must be >= a much higher multiplier's EV/trade for
    the SAME trades -- costs only ever subtract, never add, return."""
    dfs = {f"T{i}.JK": _make_df(seed=i, drift=0.0015) for i in range(2)}
    result = sweep_costs(dfs, multipliers=(0.0, 5.0), thresholds=(50.0, 60.0),
                         train_bars=200, test_bars=60, warmup_bars=30, min_train_trades=1)
    free, costly = result.points[0], result.points[1]
    assert free.ev_pct >= costly.ev_pct


def test_sweep_costs_respects_base_cfg_entry_threshold_baseline():
    dfs = {"A.JK": _make_df(n=300, seed=5)}
    base_cfg = Config()
    result = sweep_costs(dfs, base_cfg=base_cfg, multipliers=(1.0,),
                         thresholds=(60.0,), train_bars=150, test_bars=60,
                         warmup_bars=30, min_train_trades=1)
    assert result.points[0].report.baseline_threshold == base_cfg.backtest.score_entry_threshold


def test_breakeven_multiplier_none_when_ev_always_positive():
    result = CostSweepResult(points=[
        CostSweepPoint(0.0, CostModel(), _fake_report(ev=1.0)),
        CostSweepPoint(1.0, CostModel(), _fake_report(ev=0.5)),
    ])
    assert result.breakeven_multiplier() is None


def test_breakeven_multiplier_finds_first_nonpositive_crossing():
    result = CostSweepResult(points=[
        CostSweepPoint(0.0, CostModel(), _fake_report(ev=1.0)),
        CostSweepPoint(1.0, CostModel(), _fake_report(ev=0.2)),
        CostSweepPoint(2.0, CostModel(), _fake_report(ev=-0.3)),
        CostSweepPoint(3.0, CostModel(), _fake_report(ev=-1.0)),
    ])
    assert result.breakeven_multiplier() == 2.0


def test_summary_text_mentions_breakeven_or_never_crosses():
    result = CostSweepResult(points=[
        CostSweepPoint(0.0, CostModel(), _fake_report(ev=1.0)),
        CostSweepPoint(1.0, CostModel(), _fake_report(ev=-0.1)),
    ])
    text = result.summary_text()
    assert "Breakeven" in text
    assert "1.0x" in text


def _fake_report(ev: float):
    from kala.walkforward import WalkForwardReport
    return WalkForwardReport(
        folds=[], baseline_threshold=60.0,
        pooled_baseline={"n": 50, "ev_pct": ev, "t_stat": 2.5 if ev > 0 else -1.0},
        pooled_chosen={"n": 50, "ev_pct": ev, "t_stat": 2.5 if ev > 0 else -1.0},
    )
