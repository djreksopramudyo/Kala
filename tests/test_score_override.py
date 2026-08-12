"""
Tests for backtest_ticker's score_override parameter — the hook that lets an
external scorer (e.g. kala.ml_scoring's RidgeScorer) replace
composite_score's hand-tuned blend without touching anything else (exits,
entry vetoes, cost model).
"""

import numpy as np
import pandas as pd

from kala.backtest import backtest_ticker
from kala.config import BacktestConfig, Config, RiskConfig


def _make_df(closes, start="2023-01-02"):
    closes = np.asarray(closes, dtype=float)
    n = len(closes)
    return pd.DataFrame(
        {
            "Open": closes,
            "High": closes * 1.005,
            "Low": closes * 0.995,
            "Close": closes,
            "Volume": np.full(n, 1e6),
        },
        index=pd.bdate_range(start, periods=n),
    )


def _cfg(threshold=0.0):
    return Config(
        risk=RiskConfig(trailing_enabled=False, atr_stop_multiple=99.0,
                        hard_stop_pct=-90.0, target_profit_pct=999.0),
        backtest=BacktestConfig(score_entry_threshold=threshold, holding_max_days=10),
    )


def test_score_override_all_below_threshold_blocks_every_trade():
    df = _make_df(1000 * np.exp(np.cumsum(np.full(150, 0.01))))  # would score high normally
    always_low = pd.Series(-999.0, index=df.index)
    res = backtest_ticker("T.JK", df, benchmark=None, cfg=_cfg(threshold=0.0),
                          score_override=always_low)
    assert res.closed == []
    assert res.n_signals == 0


def test_score_override_all_above_threshold_enters_immediately():
    df = _make_df(np.full(150, 1000.0))  # flat tape -- composite_score would never fire
    always_high = pd.Series(999.0, index=df.index)
    res = backtest_ticker("T.JK", df, benchmark=None, cfg=_cfg(threshold=0.0),
                          score_override=always_high)
    assert res.n_signals > 0
    assert res.closed, "override score should have driven an entry composite_score never would"


def test_score_override_in_arbitrary_units_compares_against_matching_threshold():
    """The override doesn't need to be 0-100 -- threshold just needs to be in
    the same units. A -2..+2 style score with threshold=1.0 should behave
    like a normal gate."""
    df = _make_df(np.full(150, 1000.0))
    idx = df.index
    score = pd.Series(0.0, index=idx)
    score.iloc[50] = 1.5  # single day clears a threshold of 1.0
    res = backtest_ticker("T.JK", df, benchmark=None, cfg=_cfg(threshold=1.0),
                          score_override=score)
    assert res.n_signals == 1
    assert len(res.closed) == 1


def test_score_override_none_falls_back_to_composite_score():
    """Sanity: omitting score_override must behave exactly as before (no
    behavior change for every existing caller)."""
    df = _make_df(1000 * np.exp(np.cumsum(np.full(150, 0.005))))
    cfg = _cfg(threshold=60.0)
    res_no_override = backtest_ticker("T.JK", df, benchmark=None, cfg=cfg)
    res_explicit_none = backtest_ticker("T.JK", df, benchmark=None, cfg=cfg, score_override=None)
    assert len(res_no_override.closed) == len(res_explicit_none.closed)
    for a, b in zip(res_no_override.closed, res_explicit_none.closed):
        assert a.entry_date == b.entry_date
        assert a.net_return_pct == b.net_return_pct
