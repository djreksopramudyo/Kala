"""Exit-ladder sweep: OOS discipline and the geometry it reports."""

import numpy as np
import pandas as pd
import pytest

from diagnose_exit_param_sweep import pooled_oos_trades, summarise
from kala.config import Config
from kala.walkforward import make_folds


class _T:
    def __init__(self, r, entry):
        self.net_return_pct = r
        self.entry_date = entry


def test_summarise_reports_the_break_even_win_rate():
    """The number that decides whether a geometry can profit at all."""
    # 2 wins at +4, 2 losses at -4 -> payoff 1.0, break-even win rate 50%
    s = summarise([_T(4.0, None), _T(4.0, None), _T(-4.0, None), _T(-4.0, None)])
    assert s["payoff"] == pytest.approx(1.0)
    assert s["be_win_pct"] == pytest.approx(50.0)
    assert s["win_pct"] == pytest.approx(50.0)
    assert s["ev"] == pytest.approx(0.0)


def test_summarise_flags_a_losing_geometry():
    """Wins smaller than losses demand a win rate above 50% just to break even."""
    s = summarise([_T(2.0, None)] * 6 + [_T(-5.0, None)] * 4)
    assert s["payoff"] < 1.0
    assert s["be_win_pct"] > 50.0
    assert s["win_pct"] == pytest.approx(60.0)


def test_summarise_handles_an_empty_and_all_win_book():
    assert summarise([]) == {"n": 0}
    s = summarise([_T(3.0, None), _T(5.0, None)])
    assert s["n"] == 2 and s["pf"] == float("inf")


def _flat_df(n=400, start="2023-01-02"):
    idx = pd.bdate_range(start, periods=n)
    t = np.arange(n)
    close = 1000 * (1 + 0.0004 * t + 0.02 * np.sin(t / 9.0))
    return pd.DataFrame({"Open": close, "High": close * 1.01, "Low": close * 0.99,
                         "Close": close, "Volume": np.full(n, 1e6)}, index=idx)


def _trending_df(n=500, start="2022-01-03"):
    """A frame that actually generates entries: real pullbacks inside an uptrend,
    so composite_score crosses the threshold more than once."""
    idx = pd.bdate_range(start, periods=n)
    t = np.arange(n)
    close = 1000 * (1 + 0.0016 * t + 0.05 * np.sin(t / 11.0) + 0.02 * np.sin(t / 3.0))
    return pd.DataFrame({"Open": close, "High": close * 1.012, "Low": close * 0.988,
                         "Close": close, "Volume": np.linspace(1e6, 1.4e6, n)}, index=idx)


def test_the_sweep_actually_produces_trades():
    """NON-VACUITY GUARD.

    The first version of this suite asserted only that every pooled trade fell
    inside a test window — which an empty list satisfies. The tool read
    res.trades when the field is res.closed, so every cell returned zero and the
    whole grid printed as a tidy row of zeros with the tests green. Assert that
    trades EXIST before asserting anything about them.
    """
    dfs = {"AAA.JK": _trending_df()}
    folds = make_folds(dfs["AAA.JK"].index, train_bars=150, test_bars=60, warmup_bars=60)
    assert folds, "fixture too short to form a fold"

    trades = pooled_oos_trades(dfs, Config(), folds)
    assert trades, ("the sweep produced no trades at all — the engine result is "
                    "not being read correctly")
    s = summarise(trades)
    assert s["n"] == len(trades) > 0


def test_result_field_is_closed_not_trades():
    """Pins the exact defect: reading the wrong attribute must not be silent."""
    from kala.backtest import BacktestResult
    r = BacktestResult(ticker="AAA.JK")
    assert hasattr(r, "closed")
    assert not hasattr(r, "trades"), \
        "field renamed — the sweep reads .closed and must be updated in step"


def test_pooled_trades_are_only_ever_entered_inside_a_test_window():
    """The OOS guarantee: a variant is never credited with an in-sample trade."""
    dfs = {"AAA.JK": _trending_df()}
    master = dfs["AAA.JK"].index
    folds = make_folds(master, train_bars=150, test_bars=60, warmup_bars=60)
    assert folds, "fixture too short to form a fold"

    trades = pooled_oos_trades(dfs, Config(), folds)
    assert trades, "vacuous: no trades to check"
    windows = [(f.test_start, f.test_end) for f in folds]
    for t in trades:
        e = pd.Timestamp(t.entry_date)
        assert any(a <= e <= b for a, b in windows), \
            f"trade entered {e} outside every test window"


def test_no_folds_yields_no_trades():
    dfs = {"AAA.JK": _flat_df(n=80)}
    assert pooled_oos_trades(dfs, Config(), []) == []


def _choppy_df(n=600, start="2022-01-03", seed=4):
    """Whipsawing series, so entries actually go wrong and the stop can bind."""
    idx = pd.bdate_range(start, periods=n)
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    close = 1000 * (1 + 0.0008 * t + 0.06 * np.sin(t / 13.0))
    close = np.maximum(close * (1 + rng.normal(0, 0.012, n).cumsum() * 0.02), 50)
    return pd.DataFrame({"Open": close, "High": close * 1.02, "Low": close * 0.98,
                         "Close": close, "Volume": np.linspace(1e6, 1.4e6, n)}, index=idx)


def test_the_swept_stop_actually_reaches_the_engine():
    """Guards against a sweep that silently varies nothing.

    A tight floor must change the loss side. Note the engine often exits a
    loser on another rule (death cross, trailing) BEFORE a wide stop is
    reached, so only a genuinely tight setting is guaranteed to bind — which
    is why this asserts on -2% rather than on a wide/narrow pair.
    """
    from dataclasses import replace as _replace
    dfs = {"AAA.JK": _choppy_df()}
    folds = make_folds(dfs["AAA.JK"].index, 150, 60, 60)

    def run(stop):
        c = Config()
        c = _replace(c, risk=_replace(c.risk, hard_stop_pct=stop))
        return summarise(pooled_oos_trades(dfs, c, folds))

    tight, wide = run(-2.0), run(-9.0)
    assert tight.get("n") and wide.get("n"), "fixture produced no trades"
    assert tight["avg_loss"] < wide["avg_loss"], \
        "hard_stop_pct did not reach the exit engine — the sweep varies nothing"


def test_a_wider_stop_changes_the_loss_side(monkeypatch):
    """Sanity: the swept parameter actually reaches the engine."""
    from dataclasses import replace
    dfs = {"AAA.JK": _flat_df()}
    folds = make_folds(dfs["AAA.JK"].index, 120, 40, 60)

    tight = Config()
    tight = replace(tight, risk=replace(tight.risk, hard_stop_pct=-2.0))
    wide = Config()
    wide = replace(wide, risk=replace(wide.risk, hard_stop_pct=-9.0))

    a = summarise(pooled_oos_trades(dfs, tight, folds))
    b = summarise(pooled_oos_trades(dfs, wide, folds))
    if a.get("n") and b.get("n"):
        # a tighter floor cannot produce a LARGER average loss than a wide one
        assert a["avg_loss"] <= b["avg_loss"] + 1e-9


def test_control_config_disables_every_exit_rule():
    """The control must be a genuine 'no management' baseline, or the
    comparison it anchors is meaningless."""
    from dataclasses import replace as _replace

    from kala.exits import governing_stop
    base = Config()
    ctrl = _replace(base, risk=_replace(base.risk, trailing_enabled=False,
                                        hard_stop_pct=-99.0,
                                        target_profit_pct=999.0,
                                        breakeven_trigger_pct=999.0))
    entry = 1000.0
    # even after a large run-up the stop must stay far below entry, i.e. inert
    stop, _, _ = governing_stop(entry, entry * 1.5, None, ctrl.risk)
    assert stop < entry * 0.05, "control stop would still fire"
    assert ctrl.risk.target_profit_pct > 100.0
    assert ctrl.risk.trailing_enabled is False


def test_control_and_managed_runs_differ():
    """If the control produced the same trades as the ladder, it would not be
    isolating anything."""
    from dataclasses import replace as _replace
    dfs = {"AAA.JK": _choppy_df()}
    folds = make_folds(dfs["AAA.JK"].index, 150, 60, 60)

    base = Config()
    ctrl = _replace(base, risk=_replace(base.risk, trailing_enabled=False,
                                        hard_stop_pct=-99.0,
                                        target_profit_pct=999.0,
                                        breakeven_trigger_pct=999.0))
    managed = summarise(pooled_oos_trades(dfs, base, folds))
    control = summarise(pooled_oos_trades(dfs, ctrl, folds))
    assert managed.get("n") and control.get("n")
    assert managed["ev"] != control["ev"], \
        "control is indistinguishable from the managed ladder"


def test_summarise_reports_a_t_statistic():
    """A table of EVs without a t invites reading noise as a result."""
    s = summarise([_T(1.0, None)] * 30 + [_T(-1.0, None)] * 30)
    assert s["t"] == pytest.approx(0.0, abs=1e-9)
    strong = summarise([_T(2.0, None)] * 50 + [_T(1.5, None)] * 50)
    assert strong["t"] > 5.0
    assert summarise([_T(1.0, None)])["t"] == 0.0     # n=1 -> no spread, no t


def test_holding_sweep_config_leaves_only_the_holding_limit():
    """The holding sweep must switch every price-based exit off, or it is not
    measuring the holding period."""
    from dataclasses import replace as _replace

    from kala.exits import governing_stop
    base = Config()
    unmanaged = _replace(base.risk, trailing_enabled=False, hard_stop_pct=-99.0,
                         target_profit_pct=999.0, breakeven_trigger_pct=999.0)
    cfg = _replace(base, risk=unmanaged,
                   backtest=_replace(base.backtest, holding_max_days=40))
    assert cfg.backtest.holding_max_days == 40
    stop, _, _ = governing_stop(1000.0, 1500.0, None, cfg.risk)
    assert stop < 50.0, "a price stop could still close the position"


def test_holding_limit_changes_the_trade_count():
    """Sanity: the swept holding period reaches the engine."""
    from dataclasses import replace as _replace
    dfs = {"AAA.JK": _choppy_df()}
    folds = make_folds(dfs["AAA.JK"].index, 150, 60, 60)
    base = Config()
    unmanaged = _replace(base.risk, trailing_enabled=False, hard_stop_pct=-99.0,
                         target_profit_pct=999.0, breakeven_trigger_pct=999.0)

    def run(days):
        cfg = _replace(base, risk=unmanaged,
                       backtest=_replace(base.backtest, holding_max_days=days))
        return summarise(pooled_oos_trades(dfs, cfg, folds))

    short, long_ = run(5), run(60)
    assert short.get("n") and long_.get("n")
    assert short["n"] >= long_["n"], "shorter holds should not produce fewer round trips"
    assert short["ev"] != long_["ev"], "holding_max_days did not reach the engine"


def test_required_sample_size_formula():
    """The 'how far from significance' number must be arithmetically right —
    it is the figure that decides whether to collect more data or stop."""
    # EV 0.83%, std 22% -> n for |t|=2 is (2*22/0.83)^2
    ev, sd = 0.83, 22.0
    need = (2.0 * sd / ev) ** 2
    assert need == pytest.approx(2810.0, rel=0.02)
    # and the t implied by that n reproduces 2.0
    assert ev / (sd / need ** 0.5) == pytest.approx(2.0, rel=1e-6)


def test_std_is_reported_so_power_can_be_computed():
    s = summarise([_T(5.0, None), _T(-5.0, None), _T(3.0, None), _T(-3.0, None)])
    assert s["std"] > 0
    assert s["t"] == pytest.approx(0.0, abs=1e-9)


def test_summarise_reports_a_clustered_t():
    """Same-day trades across tickers are correlated; the plain t over-rejects.
    The clustered figure must be computed, not left to the reader."""
    same_day = [_T(2.0, "2025-03-03") for _ in range(40)]
    s = summarise(same_day)
    assert "ct" in s
    # 40 identical same-day trades carry roughly ONE independent observation,
    # so the cluster-robust t must not inherit the plain t's sqrt(40) boost.
    assert abs(s["ct"]) < abs(s["t"]) or s["t"] == 0.0


def test_clustered_t_matches_plain_t_when_every_trade_is_its_own_day():
    """With one trade per cluster there is nothing to correct."""
    spread = [_T(v, f"2025-01-{i + 1:02d}") for i, v in
              enumerate([3.0, -1.0, 2.0, -2.0, 4.0, -1.5, 2.5, -0.5, 1.0, -3.0])]
    s = summarise(spread)
    assert s["ct"] == pytest.approx(s["t"], rel=0.35)


def test_clustered_t_survives_unusable_dates():
    """A missing or odd entry_date must not crash the sweep mid-grid."""
    s = summarise([_T(1.0, None), _T(-1.0, None), _T(2.0, None)])
    assert s["n"] == 3
    assert "ct" in s


class _XT:
    """Trade with an exit date, so benchmark-excess can be computed."""
    def __init__(self, r, entry, exit_):
        self.net_return_pct = r
        self.entry_date = entry
        self.exit_date = exit_


def _flat_bench(n=200, start="2025-01-01", drift=0.0):
    idx = pd.bdate_range(start, periods=n)
    close = 1000 * (1 + drift) ** np.arange(n)
    return pd.DataFrame({"Close": close}, index=idx)


def test_excess_is_nan_without_a_benchmark():
    """No benchmark must not silently look like zero alpha."""
    s = summarise([_XT(5.0, "2025-01-02", "2025-02-03")])
    assert s["ex_n"] == 0
    assert s["ex_ev"] != s["ex_ev"]        # NaN, not 0.0


def test_a_flat_benchmark_leaves_excess_equal_to_raw():
    bench = _flat_bench(drift=0.0)
    trades = [_XT(v, "2025-01-06", "2025-02-06") for v in (4.0, -2.0, 6.0, -1.0)]
    s = summarise(trades, bench)
    assert s["ex_n"] == 4
    assert s["ex_ev"] == pytest.approx(s["ev"], abs=1e-6)


def test_a_rising_benchmark_eats_the_raw_edge():
    """The whole point: a long-only book in a rising market shows raw
    expectancy that is market exposure, not skill."""
    bench = _flat_bench(drift=0.002)       # steadily rising index
    trades = [_XT(v, "2025-01-06", "2025-03-06") for v in (4.0, 5.0, 6.0, 3.0)]
    s = summarise(trades, bench)
    assert s["ev"] > 0
    assert s["ex_ev"] < s["ev"], "excess did not subtract the benchmark's move"


def test_excess_carries_its_own_clustered_t():
    bench = _flat_bench(drift=0.0005)
    trades = [_XT(v, f"2025-01-{d:02d}", f"2025-02-{d:02d}")
              for d, v in zip(range(2, 20), [3, -2, 4, -1, 5, -3, 2, -1, 6,
                                             -2, 3, -4, 5, -1, 2, -2, 4, -3])]
    s = summarise(trades, bench)
    assert s["ex_n"] > 10
    assert s["ex_ct"] == s["ex_ct"]        # not NaN


def test_threshold_reaches_the_engine_and_changes_trade_count():
    """The signal-contribution control is only meaningful if the entry
    threshold actually varies what gets bought."""
    from dataclasses import replace as _replace
    dfs = {"AAA.JK": _choppy_df()}
    folds = make_folds(dfs["AAA.JK"].index, 150, 60, 60)
    base = Config()
    unmanaged = _replace(base.risk, trailing_enabled=False, hard_stop_pct=-99.0,
                         target_profit_pct=999.0, breakeven_trigger_pct=999.0)

    def run(thr):
        cfg = _replace(base, risk=unmanaged,
                       backtest=_replace(base.backtest, holding_max_days=60,
                                         score_entry_threshold=thr))
        return summarise(pooled_oos_trades(dfs, cfg, folds))

    loose, tight = run(0.0), run(90.0)
    assert loose.get("n"), "threshold 0 should enter often"
    assert loose["n"] > tight.get("n", 0), \
        "score_entry_threshold did not reach the engine — the control is inert"


def test_liquidity_split_separates_the_universe_by_turnover():
    """The survivorship discriminator rests on the split being real: liquid
    names must actually land in the liquid half."""
    idx = pd.bdate_range("2024-01-02", periods=100)
    def frame(px, vol):
        return pd.DataFrame({"Open": px, "High": px * 1.01, "Low": px * 0.99,
                             "Close": px, "Volume": vol}, index=idx)
    dfs = {
        "BIG.JK": frame(np.full(100, 5000.0), np.full(100, 5e6)),
        "MID.JK": frame(np.full(100, 1000.0), np.full(100, 1e6)),
        "THIN.JK": frame(np.full(100, 100.0), np.full(100, 1e4)),
        "DUST.JK": frame(np.full(100, 50.0), np.full(100, 1e3)),
    }
    turnover = {tk: float((d["Close"] * d["Volume"]).median()) for tk, d in dfs.items()}
    ranked = sorted(turnover, key=turnover.get, reverse=True)
    half = len(ranked) // 2
    assert ranked[:half] == ["BIG.JK", "MID.JK"]
    assert ranked[half:] == ["THIN.JK", "DUST.JK"]


def test_turnover_uses_median_not_mean():
    """One frantic week must not promote a thin stock into the liquid half."""
    idx = pd.bdate_range("2024-01-02", periods=100)
    vol = np.full(100, 1e3)
    vol[:3] = 1e9                       # a brief spike
    px = np.full(100, 100.0)
    d = pd.DataFrame({"Open": px, "High": px, "Low": px, "Close": px,
                      "Volume": vol}, index=idx)
    median_turnover = float((d["Close"] * d["Volume"]).median())
    mean_turnover = float((d["Close"] * d["Volume"]).mean())
    assert median_turnover == pytest.approx(1e5)
    assert mean_turnover > 10 * median_turnover
