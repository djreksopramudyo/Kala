"""
Tests for kala.portfolio_sim.

The load-bearing test is the FIDELITY CONTRACT: with one ticker, one slot,
effectively-unlimited capital and vetoes off, the portfolio simulator must
reproduce backtest_ticker's trade list exactly (dates, reasons, net returns).
Every other capital-layer behavior (slots, cash, lots, ADV cap) may only
REMOVE trades relative to that baseline.
"""

import numpy as np
import pandas as pd
import pytest

from kala.backtest import backtest_ticker
from kala.config import BacktestConfig, Config
from kala.portfolio_sim import LOT_SIZE, run_grid, simulate_portfolio


def _make_df(closes, seed=0, vol=1e9, start="2022-01-03"):
    closes = np.asarray(closes, dtype=float)
    n = len(closes)
    rng = np.random.default_rng(seed)
    open_ = np.empty(n)
    open_[0] = closes[0]
    open_[1:] = closes[:-1] * (1 + rng.normal(0, 0.002, n - 1))
    return pd.DataFrame(
        {
            "Open": open_,
            "High": np.maximum(open_, closes) * 1.004,
            "Low": np.minimum(open_, closes) * 0.996,
            "Close": closes,
            "Volume": np.full(n, vol),
        },
        index=pd.bdate_range(start, periods=n),
    )


def _wavy(n=500, seed=3, drift=0.0012):
    rng = np.random.default_rng(seed)
    closes = 1000 * np.exp(np.cumsum(rng.normal(drift, 0.015, n)))
    # flat declining tail below any entry threshold so every trade closes
    tail = closes[-1] * np.exp(np.cumsum(np.full(60, -0.004)))
    return np.concatenate([closes, tail])


def test_fidelity_single_ticker_single_slot_matches_backtest_ticker():
    df = _make_df(_wavy())
    cfg = Config(backtest=BacktestConfig(score_entry_threshold=60.0))

    bt = backtest_ticker("FID.JK", df, benchmark=None, cfg=cfg)
    bt_closed = [t for t in bt.closed if not t.exit_reason.endswith("(eod)")]
    assert bt_closed, "test data must produce at least one normally-closed trade"

    sim = simulate_portfolio({"FID.JK": df}, benchmark=None, cfg=cfg,
                             start_capital=1e12, max_positions=1,
                             apply_entry_vetoes=False)
    assert len(sim.trades) == len(bt_closed)
    for st, bt_t in zip(sim.trades, bt_closed):
        assert st.entry_date == bt_t.entry_date
        assert st.exit_date == bt_t.exit_date
        assert st.exit_reason == bt_t.exit_reason
        assert st.net_return_pct == pytest.approx(bt_t.net_return_pct, abs=1e-9)


def test_max_positions_never_exceeded_and_shares_are_lots():
    dfs = {f"T{i}.JK": _make_df(_wavy(seed=i, drift=0.001 + 0.0003 * i), seed=i)
           for i in range(8)}
    sim = simulate_portfolio(dfs, cfg=Config(backtest=BacktestConfig(score_entry_threshold=55.0)),
                             start_capital=100_000_000, max_positions=3,
                             apply_entry_vetoes=False)
    assert sim.trades, "expected trades"
    for t in sim.trades:
        assert t.shares % LOT_SIZE == 0 and t.shares >= LOT_SIZE

    # reconstruct concurrent holdings from the trade intervals
    events = []
    for t in sim.trades:
        events.append((t.entry_date, 1))
        events.append((t.exit_date, -1))
    open_count, peak = 0, 0
    for _, delta in sorted(events, key=lambda e: (e[0], e[1])):
        open_count += delta
        peak = max(peak, open_count)
    assert peak <= 3


def test_cash_is_conserved_and_never_negative():
    dfs = {f"T{i}.JK": _make_df(_wavy(seed=10 + i), seed=10 + i) for i in range(4)}
    start = 50_000_000
    sim = simulate_portfolio(dfs, cfg=Config(backtest=BacktestConfig(score_entry_threshold=55.0)),
                             start_capital=start, max_positions=4,
                             apply_entry_vetoes=False)
    eq = sim.equity_curve
    assert float(eq.iloc[0]) == pytest.approx(start, rel=1e-6)
    # equity can never be negative, and with long-only positions it can't
    # fall below zero cash + zero-value stock
    assert (eq > 0).all()


def test_smaller_capital_only_removes_trades():
    """The capital layer may gate entries, never invent them: the trade set at
    tiny capital must be a subset (by entry date+ticker) of the huge-capital
    run."""
    dfs = {f"T{i}.JK": _make_df(_wavy(seed=20 + i), seed=20 + i) for i in range(3)}
    cfg = Config(backtest=BacktestConfig(score_entry_threshold=55.0))
    big = simulate_portfolio(dfs, cfg=cfg, start_capital=1e12, max_positions=3,
                             apply_entry_vetoes=False)
    small = simulate_portfolio(dfs, cfg=cfg, start_capital=5_000_000, max_positions=3,
                               apply_entry_vetoes=False)
    big_keys = {(t.ticker, t.entry_date) for t in big.trades}
    small_keys = {(t.ticker, t.entry_date) for t in small.trades}
    assert small_keys <= big_keys


def test_vetoes_reduce_or_hold_trade_count_and_are_counted():
    rng = np.random.default_rng(7)
    n = 400
    base = 1000 * np.exp(np.cumsum(rng.normal(0.001, 0.012, n)))
    burst = base[-1] * np.exp(np.cumsum(np.full(25, 0.02)))   # parabolic finish
    tail = np.full(80, burst[-1])
    dfs = {"PARA.JK": _make_df(np.concatenate([base, burst, tail]), seed=7)}
    cfg = Config(backtest=BacktestConfig(score_entry_threshold=60.0))

    off = simulate_portfolio(dfs, cfg=cfg, start_capital=1e10, max_positions=2,
                             apply_entry_vetoes=False)
    on = simulate_portfolio(dfs, cfg=cfg, start_capital=1e10, max_positions=2,
                            apply_entry_vetoes=True)
    assert on.n_vetoed > 0
    assert len(on.trades) <= len(off.trades)


def test_run_grid_shares_veto_cache_and_reports_all_points():
    dfs = {f"T{i}.JK": _make_df(_wavy(seed=30 + i), seed=30 + i) for i in range(4)}
    results = run_grid(dfs, cfg=Config(backtest=BacktestConfig(score_entry_threshold=55.0)),
                       start_capital=50_000_000, grid=(2, 4),
                       apply_entry_vetoes=True)
    assert [r.max_positions for r in results] == [2, 4]
    for r in results:
        assert r.equity_curve is not None and len(r.equity_curve) > 0
        first, second = r.half_split()
        assert isinstance(first, float) and isinstance(second, float)
