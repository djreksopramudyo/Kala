"""
Tests for the (opt-in) entries.py wiring into backtest_ticker.

Historically the backtest scored candidates purely on composite_score and
never ran them through entries.evaluate_entry — the guardrails (RSI
overbought, parabolic ROC20, OBV distribution, thin volume, bear-regime
block) applied on the live/papertrade path only. BacktestConfig.apply_entry_vetoes
closes that gap. It defaults to False (see test_system.py / test_walkforward.py,
which assert exact behavior of the un-gated engine and must keep passing
unmodified), so every test here turns it on explicitly.
"""

import numpy as np
import pandas as pd

from kala.backtest import backtest_ticker
from kala.config import BacktestConfig, Config, EntryConfig, RiskConfig


def _make_df(closes, vols=None, start="2023-01-02"):
    closes = np.asarray(closes, dtype=float)
    n = len(closes)
    return pd.DataFrame(
        {
            "Open": closes,
            "High": closes * 1.005,
            "Low": closes * 0.995,
            "Close": closes,
            "Volume": np.asarray(vols, dtype=float) if vols is not None else np.full(n, 1e6),
        },
        index=pd.bdate_range(start, periods=n),
    )


def _parabolic_series(n_base=100, base_drift=0.001, n_burst=20, burst_drift=0.02,
                      n_tail=40):
    """Gentle uptrend (gets composite_score warm and trending) followed by a
    sharp 20-bar burst that trips ROC20-parabolic and RSI-overbought, then a
    flat tail so any position that DOES open has room to hit holding_max_days
    and actually close (backtest_ticker never force-closes an open position
    at end-of-data unless a real exit condition fires first)."""
    base = 1000 * np.exp(np.cumsum(np.full(n_base, base_drift)))
    burst = base[-1] * np.exp(np.cumsum(np.full(n_burst, burst_drift)))
    tail = np.full(n_tail, burst[-1])
    return np.concatenate([base, burst, tail])


def _bear_benchmark(n, drift=-0.01):
    closes = 1000 * np.exp(np.cumsum(np.full(n, drift)))
    return _make_df(closes)


def _permissive_cfg(apply_entry_vetoes: bool) -> Config:
    """Loose risk config so an opened position doesn't distort trade counts
    the test isn't asserting on — only entry gating matters here. holding_max_days
    is bounded (not disabled) so any entry that does happen actually closes
    within the synthetic series instead of running off the end unclosed."""
    return Config(
        risk=RiskConfig(trailing_enabled=False, atr_stop_multiple=99.0,
                        hard_stop_pct=-90.0, target_profit_pct=999.0),
        backtest=BacktestConfig(score_entry_threshold=60.0, holding_max_days=15,
                                apply_entry_vetoes=apply_entry_vetoes),
        entries=EntryConfig(),
    )


def test_vetoes_off_by_default_records_signals_but_never_blocks():
    df = _make_df(_parabolic_series())
    cfg = _permissive_cfg(apply_entry_vetoes=False)
    res = backtest_ticker("PARA.JK", df, benchmark=None, cfg=cfg)
    assert res.n_signals > 0
    assert res.n_vetoed == 0
    assert res.veto_counts == {}


def test_parabolic_and_overbought_veto_blocks_the_chase():
    df = _make_df(_parabolic_series())
    cfg_off = _permissive_cfg(apply_entry_vetoes=False)
    cfg_on = _permissive_cfg(apply_entry_vetoes=True)

    res_off = backtest_ticker("PARA.JK", df, benchmark=None, cfg=cfg_off)
    res_on = backtest_ticker("PARA.JK", df, benchmark=None, cfg=cfg_on)

    assert res_off.closed, "sanity: the un-gated backtest should have bought the surge"
    assert res_on.n_vetoed > 0
    assert ("parabolic" in res_on.veto_counts) or ("overbought" in res_on.veto_counts)
    # every vetoed candidate must have been reachable only via a real signal
    assert res_on.n_vetoed <= res_on.n_signals
    # the guardrail must have prevented at least the earliest chase entry
    assert len(res_on.closed) <= len(res_off.closed)


def test_bear_regime_veto_blocks_entries_when_benchmark_is_bearish():
    rng = np.random.default_rng(5)
    closes = 1000 * np.exp(np.cumsum(rng.normal(0.004, 0.004, 160)))
    closes = np.concatenate([closes, np.full(40, closes[-1])])  # flat tail, room to close
    df = _make_df(closes)
    bench = _bear_benchmark(200)

    cfg_off = _permissive_cfg(apply_entry_vetoes=False)
    cfg_on = _permissive_cfg(apply_entry_vetoes=True)

    res_off = backtest_ticker("BULL.JK", df, benchmark=bench, cfg=cfg_off)
    res_on = backtest_ticker("BULL.JK", df, benchmark=bench, cfg=cfg_on)

    assert res_off.closed, "sanity: the stock itself is a clean uptrend and should have traded"
    assert res_on.veto_counts.get("bear_regime", 0) > 0
    assert len(res_on.closed) < len(res_off.closed)


def test_cheap_price_veto_blocks_entries_below_min_price_idr():
    """2026-07-20: the >= IDR 1,000 tier is the only one with a confirmed OOS
    edge under honest tick-floor costs (see kala/edge.py) -- backtest_ticker
    must apply that same gate when apply_entry_vetoes is on."""
    closes = 500 * np.exp(np.cumsum(np.full(160, 0.004)))   # healthy uptrend, cheap
    closes = np.concatenate([closes, np.full(40, closes[-1])])
    df = _make_df(closes)
    cfg_off = _permissive_cfg(apply_entry_vetoes=False)
    cfg_on = _permissive_cfg(apply_entry_vetoes=True)

    res_off = backtest_ticker("CHEAP.JK", df, benchmark=None, cfg=cfg_off)
    res_on = backtest_ticker("CHEAP.JK", df, benchmark=None, cfg=cfg_on)

    assert res_off.closed, "sanity: the un-gated backtest should have bought the uptrend"
    assert res_on.veto_counts.get("cheap_price", 0) > 0
    assert len(res_on.closed) < len(res_off.closed)


def test_no_benchmark_supplied_bear_veto_cannot_fire_but_others_still_can():
    """Without a benchmark, market_status is always None -> block_buys_in_bear
    can never trigger, but the price/volume-only vetoes still apply."""
    df = _make_df(_parabolic_series())
    cfg_on = _permissive_cfg(apply_entry_vetoes=True)
    res_on = backtest_ticker("PARA.JK", df, benchmark=None, cfg=cfg_on)
    assert "bear_regime" not in res_on.veto_counts
    assert res_on.n_vetoed > 0
