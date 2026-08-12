"""
Walk-forward harness tests. Everything runs on synthetic data — no network.

The invariants that matter:
  * trade_stats: EV is the headline; profit factor / t-stat computed correctly.
  * Folds tile the calendar: test windows never overlap, so pooled OOS stats
    never double-count a day.
  * evaluate_window confines ENTRIES strictly to the window (no leakage from
    the warm-up head, the grace tail, or positions carried in from before).
  * pick_threshold refuses to be seduced by a tiny-sample outlier.
  * Input frames are never mutated (same contract as compute_features).
"""

import numpy as np
import pandas as pd
import pytest

from kala.backtest import Trade
from kala.config import Config
from kala.walkforward import (
    evaluate_window,
    excess_returns,
    make_folds,
    pick_threshold,
    trade_stats,
    walk_forward,
)

# ---------------------------------------------------------------------------
# synthetic data helpers
# ---------------------------------------------------------------------------

def _make_df(n=500, seed=0, drift=0.001, vol=0.015, start="2022-01-03"):
    """Random-walk OHLCV with mild upward drift so entries actually fire."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(start, periods=n)
    rets = rng.normal(drift, vol, n)
    close = 1000.0 * np.exp(np.cumsum(rets))
    open_ = np.empty(n)
    open_[0] = close[0]
    open_[1:] = close[:-1] * (1 + rng.normal(0, 0.003, n - 1))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.004, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.004, n)))
    vol_ = rng.integers(1_000_000, 5_000_000, n).astype(float)
    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": vol_},
        index=idx,
    )


def _universe(k=4, n=500):
    return {f"SYN{i}.JK": _make_df(n=n, seed=i, drift=0.0012 + 0.0002 * i)
            for i in range(k)}


# ---------------------------------------------------------------------------
# trade_stats
# ---------------------------------------------------------------------------

def test_trade_stats_ev_is_arithmetic_mean_and_pf_correct():
    s = trade_stats([2.0, -1.0, 3.0, -2.0])
    assert s["n"] == 4
    assert s["ev_pct"] == pytest.approx(0.5)
    assert s["win_rate_pct"] == pytest.approx(50.0)
    assert s["profit_factor"] == pytest.approx(5.0 / 3.0)
    # compounded: 1.02*0.99*1.03*0.98 - 1
    assert s["total_compounded_pct"] == pytest.approx(
        (1.02 * 0.99 * 1.03 * 0.98 - 1) * 100, rel=1e-9)


def test_trade_stats_ev_beats_winrate_framing():
    """The coin-toss lesson: 25%-win/fat-winner book has HIGHER EV than a
    75%-win/fat-loser book. The stats must expose that, not hide it."""
    fat_winners = [35.0, -1.0, -1.0, -1.0]          # win rate 25%, EV +8
    fat_losers = [1.0, 1.0, 1.0, -35.0]             # win rate 75%, EV -8
    assert trade_stats(fat_winners)["ev_pct"] > 0 > trade_stats(fat_losers)["ev_pct"]
    assert trade_stats(fat_winners)["win_rate_pct"] < trade_stats(fat_losers)["win_rate_pct"]


def test_trade_stats_empty_is_safe():
    s = trade_stats([])
    assert s["n"] == 0 and s["ev_pct"] == 0.0


# ---------------------------------------------------------------------------
# fold generation
# ---------------------------------------------------------------------------

def test_folds_tile_without_overlap():
    idx = pd.bdate_range("2022-01-03", periods=500)
    folds = make_folds(idx, train_bars=252, test_bars=63, warmup_bars=60)
    assert len(folds) >= 2
    for a, b in zip(folds, folds[1:]):
        # consecutive test windows are adjacent, never overlapping
        assert a.test_end < b.test_start
        pos_after_a = idx.get_loc(a.test_end) + 1
        assert idx[pos_after_a] == b.test_start
    # every fold's train ends strictly before its test begins
    for f in folds:
        assert f.train_end < f.test_start


def test_folds_respect_warmup_reserve():
    idx = pd.bdate_range("2022-01-03", periods=500)
    folds = make_folds(idx, 252, 63, warmup_bars=60)
    assert folds[0].train_start == idx[60]


def test_no_fold_when_history_too_short():
    idx = pd.bdate_range("2022-01-03", periods=200)
    assert make_folds(idx, 252, 63, 60) == []


# ---------------------------------------------------------------------------
# window evaluation — the leakage guards
# ---------------------------------------------------------------------------

def test_entries_confined_to_window():
    """Trades from the warm-up head or grace tail must never leak into the
    window's stats. We verify by intercepting backtest_ticker's real output."""
    df = _make_df(n=500, seed=7)
    cfg = Config()
    cfg.backtest.score_entry_threshold = 40.0   # low bar -> plenty of trades
    idx = df.index
    entry_start, entry_end = idx[200], idx[300]

    from kala.backtest import backtest_ticker as real_bt
    lo = max(0, idx.searchsorted(entry_start) - 60)
    hi = min(len(idx), idx.searchsorted(entry_end, side="right")
             + cfg.backtest.holding_max_days + 5)
    from kala.walkforward import _with_threshold
    full = real_bt("SYN.JK", df.iloc[lo:hi], cfg=_with_threshold(cfg, 40.0))
    inside = [t for t in full.closed
              if entry_start <= pd.Timestamp(t.entry_date) <= entry_end]
    outside = [t for t in full.closed
               if not (entry_start <= pd.Timestamp(t.entry_date) <= entry_end)]

    rets = evaluate_window("SYN.JK", df, entry_start, entry_end, 40.0, cfg)
    assert sorted(rets) == sorted(t.net_return_pct for t in inside)
    # the guard is only meaningful if there was something to exclude
    assert len(outside) > 0 or len(full.closed) == len(inside)


def test_exit_grace_lets_late_entries_close():
    """A trade entered near the window's last day should still appear —
    its exit completes in the grace tail instead of being dropped."""
    df = _make_df(n=500, seed=3)
    cfg = Config()
    cfg.backtest.score_entry_threshold = 40.0
    idx = df.index
    with_grace = evaluate_window("S", df, idx[150], idx[350], 40.0, cfg)
    without = evaluate_window("S", df, idx[150], idx[350], 40.0, cfg,
                              exit_grace_bars=0)
    assert len(with_grace) >= len(without)


def test_evaluate_window_does_not_mutate_input():
    df = _make_df(n=400, seed=1)
    before = df.copy()
    evaluate_window("S", df, df.index[100], df.index[300], 55.0, Config())
    pd.testing.assert_frame_equal(df, before)


def test_evaluate_window_short_history_returns_empty():
    df = _make_df(n=40, seed=2)
    assert evaluate_window("S", df, df.index[10], df.index[30], 50.0, Config()) == []


def test_evaluate_window_return_trades_gives_same_returns_as_default():
    """return_trades=True must be a strict superset of information, not a
    different computation -- the derived net_return_pct list must match the
    default float-list return exactly."""
    df = _make_df(n=400, seed=4)
    cfg = Config()
    cfg.backtest.score_entry_threshold = 40.0
    rets = evaluate_window("S", df, df.index[100], df.index[300], 40.0, cfg)
    trades = evaluate_window("S", df, df.index[100], df.index[300], 40.0, cfg,
                             return_trades=True)
    assert sorted(rets) == sorted(t.net_return_pct for t in trades)


# ---------------------------------------------------------------------------
# excess_returns — the alpha-vs-beta diagnostic
# ---------------------------------------------------------------------------

def _trade(entry_date, exit_date, net_return_pct):
    return Trade(ticker="T.JK", entry_date=entry_date, entry_price=1000.0,
                exit_date=exit_date, exit_price=1000.0 * (1 + net_return_pct / 100),
                exit_reason="test", net_return_pct=net_return_pct)


def _flat_bench(start, n, level=1000.0):
    return pd.DataFrame({"Close": np.full(n, level)}, index=pd.bdate_range(start, periods=n))


def test_excess_returns_zero_when_stock_only_tracks_benchmark():
    """Pure beta: the stock's return over the window EXACTLY equals the
    benchmark's return over the same window -> excess must be ~0, even
    though the raw return is clearly positive."""
    idx = pd.bdate_range("2022-01-03", periods=100)
    bench = pd.DataFrame({"Close": 1000 * np.exp(np.cumsum(np.full(100, 0.01)))}, index=idx)
    entry, exit_ = idx[10], idx[40]
    bench_move_pct = (float(bench["Close"].asof(exit_)) /
                      float(bench["Close"].asof(entry)) - 1.0) * 100.0
    trades = [_trade(entry, exit_, net_return_pct=bench_move_pct)]   # rode the index exactly
    exc = excess_returns(trades, bench)
    assert exc == pytest.approx([0.0], abs=1e-9)


def test_excess_returns_positive_when_stock_beats_benchmark():
    idx = pd.bdate_range("2022-01-03", periods=100)
    bench = pd.DataFrame({"Close": 1000 * np.exp(np.cumsum(np.full(100, 0.01)))}, index=idx)
    entry, exit_ = idx[10], idx[40]
    bench_move_pct = (float(bench["Close"].asof(exit_)) /
                      float(bench["Close"].asof(entry)) - 1.0) * 100.0
    trades = [_trade(entry, exit_, net_return_pct=bench_move_pct + 5.0)]   # beat it by 5pp
    exc = excess_returns(trades, bench)
    assert exc == pytest.approx([5.0], abs=1e-9)


def test_excess_returns_none_benchmark_gives_empty_list():
    trades = [_trade(pd.Timestamp("2022-01-03"), pd.Timestamp("2022-02-03"), 3.0)]
    assert excess_returns(trades, None) == []


def test_excess_returns_skips_trades_outside_benchmark_coverage():
    """A trade whose window the benchmark doesn't cover must be SKIPPED, not
    zero-filled -- a silent zero would understate the true excess-return
    sample, the opposite of what this diagnostic is for."""
    bench = _flat_bench("2022-06-01", n=30)             # short window
    inside = _trade(pd.Timestamp("2022-06-05"), pd.Timestamp("2022-06-20"), 4.0)
    outside = _trade(pd.Timestamp("2019-01-01"), pd.Timestamp("2019-02-01"), 4.0)
    exc = excess_returns([inside, outside], bench)
    assert len(exc) == 1     # only the covered trade survives


# ---------------------------------------------------------------------------
# threshold picking — the anti-overfit guard
# ---------------------------------------------------------------------------

def test_pick_threshold_ignores_tiny_sample_outlier():
    sweep = {
        70.0: {"n": 4, "ev_pct": 6.0},     # lucky handful — must NOT win
        60.0: {"n": 80, "ev_pct": 1.2},
        50.0: {"n": 150, "ev_pct": 0.4},
    }
    assert pick_threshold(sweep, baseline=60.0, min_trades=30) == 60.0


def test_pick_threshold_falls_back_to_baseline_when_starved():
    sweep = {70.0: {"n": 2, "ev_pct": 9.0}, 60.0: {"n": 5, "ev_pct": 1.0}}
    assert pick_threshold(sweep, baseline=60.0, min_trades=30) == 60.0


# ---------------------------------------------------------------------------
# end-to-end walk on synthetic universe
# ---------------------------------------------------------------------------

def test_walk_forward_end_to_end():
    dfs = _universe(k=4, n=500)
    cfg = Config()
    report = walk_forward(dfs, cfg=cfg, train_bars=200, test_bars=60,
                          warmup_bars=60, thresholds=(45.0, 55.0, 65.0),
                          min_train_trades=10)
    assert len(report.folds) >= 2
    # pooled counts equal the sum over folds (no double counting)
    assert report.pooled_chosen["n"] == sum(f.oos_chosen["n"] for f in report.folds)
    assert report.pooled_baseline["n"] == sum(f.oos_baseline["n"] for f in report.folds)
    # every chosen threshold came from the sweep grid or the baseline
    for f in report.folds:
        assert f.chosen_threshold in (45.0, 55.0, 65.0, cfg.backtest.score_entry_threshold)
    # summary renders and leads with EV
    text = report.summary_text()
    assert "EV/trade" in text and "VERDICT" in text


def test_walk_forward_alpha_check_zero_when_pure_beta():
    """A ticker whose price is a pure scalar multiple of the benchmark (zero
    idiosyncratic component -- % returns are scale-invariant, so it behaves
    exactly like the index on a GROSS basis) must show an EXCESS EV that
    collapses to roughly minus its own round-trip transaction cost -- NOT
    exactly zero -- even though its RAW EV clearly tracks the benchmark's
    positive drift. This is the same diagnostic, in miniature, that caught
    the project's actual 2026-07 finding: an apparent edge concentrated in
    rally windows turned out to be market exposure, not stock selection.

    Why not exactly zero: Trade.net_return_pct is NET of costs (commission +
    tax + spread, ~0.64pp round trip under the default flat CostModel) while
    the benchmark side of excess_returns() is a pure, cost-free price return.
    A perfectly beta-tracking stock therefore has to show excess EV near
    -round_trip%, not 0 -- "beats the index net of realistic trading costs"
    is the actually meaningful bar, and a wash before costs is a loss after
    them. The bound below is round_trip plus headroom for next-open fill
    timing drift (entry/exit execute a bar after the signal date used to
    look up the benchmark price)."""
    n = 500
    idx = pd.bdate_range("2022-01-03", periods=n)
    rng = np.random.default_rng(11)
    bench_close = 1000 * np.exp(np.cumsum(rng.normal(0.0015, 0.012, n)))
    bench = pd.DataFrame({"Close": bench_close}, index=idx)

    def _beta_df(scale):
        close = bench_close * scale
        open_ = np.empty(n)
        open_[0] = close[0]
        open_[1:] = close[:-1]
        high = np.maximum(open_, close) * 1.004
        low = np.minimum(open_, close) * 0.996
        return pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close,
                             "Volume": np.full(n, 2_000_000.0)}, index=idx)

    dfs = {f"BETA{i}.JK": _beta_df(1.0 + 0.1 * i) for i in range(3)}
    cfg = Config()
    cfg.backtest.score_entry_threshold = 45.0
    report = walk_forward(dfs, cfg=cfg, benchmark=bench, train_bars=200, test_bars=60,
                          warmup_bars=60, thresholds=(45.0,), min_train_trades=5)

    assert report.pooled_baseline["n"] > 0
    assert report.pooled_excess_baseline["n"] > 0
    assert report.pooled_baseline["ev_pct"] > 0            # tracks benchmark drift
    round_trip_pct = cfg.costs.round_trip * 100.0
    exc_ev = report.pooled_excess_baseline["ev_pct"]
    # collapses vs benchmark: no meaningful positive excess, and the negative
    # side is bounded by round-trip costs (not an unbounded loss)
    assert exc_ev < 0.2
    assert exc_ev > -(round_trip_pct + 1.0)

    text = report.summary_text()
    assert "ALPHA CHECK" in text and "ALPHA VERDICT" in text
    assert "BETA, NOT ALPHA" in text


def test_walk_forward_no_alpha_section_without_benchmark():
    """The alpha check is additive and opt-in: no benchmark supplied ->
    no ALPHA section at all, and existing raw-return fields are untouched."""
    dfs = _universe(k=2, n=400)
    report = walk_forward(dfs, train_bars=200, test_bars=60, warmup_bars=60,
                          thresholds=(45.0,), min_train_trades=5)
    assert report.pooled_excess_baseline.get("n", 0) == 0
    assert "ALPHA" not in report.summary_text()


def test_walk_forward_oos_trades_only_from_test_windows():
    dfs = _universe(k=2, n=500)
    report = walk_forward(dfs, train_bars=200, test_bars=60, warmup_bars=60,
                          thresholds=(45.0,), min_train_trades=1)
    for fr in report.folds:
        # re-derive the fold's OOS trades independently and compare
        expected = []
        for t, df in dfs.items():
            expected.extend(evaluate_window(t, df, fr.fold.test_start,
                                            fr.fold.test_end,
                                            fr.chosen_threshold, Config()))
        assert sorted(fr.oos_returns_chosen) == sorted(expected)


def test_walk_forward_benchmark_reaches_entry_vetoes_when_enabled():
    """A benchmark passed into walk_forward must actually gate entries when
    apply_entry_vetoes is on (regression guard for the benchmark=None that
    used to be hardcoded inside evaluate_window)."""
    from kala.config import BacktestConfig

    dfs = _universe(k=3, n=400)
    bench = pd.DataFrame(
        {"Close": 1000 * np.exp(np.cumsum(np.full(400, -0.01)))},
        index=pd.bdate_range("2022-01-03", periods=400),
    )

    cfg_off = Config(backtest=BacktestConfig(score_entry_threshold=45.0,
                                             apply_entry_vetoes=False))
    cfg_on = Config(backtest=BacktestConfig(score_entry_threshold=45.0,
                                            apply_entry_vetoes=True))

    report_off = walk_forward(dfs, cfg=cfg_off, benchmark=bench,
                              train_bars=150, test_bars=60, warmup_bars=60,
                              thresholds=(45.0,), min_train_trades=1)
    report_on = walk_forward(dfs, cfg=cfg_on, benchmark=bench,
                             train_bars=150, test_bars=60, warmup_bars=60,
                             thresholds=(45.0,), min_train_trades=1)

    # a permanently bearish benchmark should suppress most/all OOS entries
    # once vetoes are wired through, vs. the un-gated baseline
    assert report_on.pooled_chosen["n"] < report_off.pooled_chosen["n"]
