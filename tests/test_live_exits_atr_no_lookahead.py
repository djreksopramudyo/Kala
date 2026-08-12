"""backtest_live_exits.py carried the same ATR look-ahead as backtest.py.

This module's entire reason to exist is comparing against backtest.py on
IDENTICAL entries (see its module docstring — it produced the numbers behind
exits.py v3.3's "+0.37%/trade vs -0.21%/trade" history). It had its own copy
of `entry_atr = atr_arr[i + 1]`, untouched by the backtest.py fix because the
two files don't share this code path.

Same fixture technique as test_entry_atr_no_lookahead.py: a signal-bar ATR
small enough to let the ATR stop bind, then a fill bar with a huge range that
would inflate it past the -5% hard floor if leaked, then a close that sits
between the two candidate stops.
"""

import numpy as np
import pandas as pd
import pytest

import kala.backtest_live_exits as ble
from kala.config import BacktestConfig, Config
from kala.scoring import compute_features


def _discriminating_frame():
    n = 60
    price = 1000.0
    idx = pd.bdate_range("2021-01-01", periods=n)
    o = np.full(n, price)
    h = np.full(n, price * 1.002)
    lo = np.full(n, price * 0.998)
    c = np.full(n, price)

    entry_i = 40
    h[entry_i] = price * 1.10          # fill-bar range spike -> inflates ATR
    lo[entry_i] = price * 0.90
    c[entry_i] = price

    c[entry_i + 1] = price * 0.97      # between the two candidate stops
    lo[entry_i + 1] = price * 0.969
    h[entry_i + 1] = price * 1.001

    return pd.DataFrame({"Open": o, "High": h, "Low": lo, "Close": c,
                         "Volume": np.full(n, 5e6)}, index=idx), entry_i


def test_entry_atr_comes_from_the_signal_bar(monkeypatch):
    df, entry_i = _discriminating_frame()
    cfg = Config(backtest=BacktestConfig(score_entry_threshold=50.0,
                                         apply_entry_vetoes=False))
    atr = compute_features(df)["atr"]

    # Force a BUY signal exactly one bar before the fill, without needing a
    # real momentum setup — this module has no score_override, so patch the
    # scorer it calls internally.
    score = pd.Series(0.0, index=df.index)
    score.iloc[entry_i - 1] = 100.0
    monkeypatch.setattr(ble, "composite_score", lambda feats: score)

    from kala.exits import governing_stop
    entry = df["Open"].iloc[entry_i]
    stop_signal, _, _ = governing_stop(entry, entry, float(atr.iloc[entry_i - 1]), cfg.risk)
    stop_fill, _, _ = governing_stop(entry, entry, float(atr.iloc[entry_i]), cfg.risk)
    breach = df["Close"].iloc[entry_i + 1]
    assert stop_signal > stop_fill, "fixture failed to separate the two stops"
    assert stop_fill < breach <= stop_signal, "fixture close is not between them"

    result = ble.backtest_ticker_live_exits("T.JK", df, cfg=cfg)
    assert result.n_signals == 1
    assert result.closed, (
        "the position was never stopped out — its stop was sized from the "
        "fill bar's inflated ATR, i.e. entry_atr is being read from bar i+1")
    assert "stop" in result.closed[0].exit_reason.lower()


def test_matches_backtest_py_atr_choice_on_identical_entries():
    """The module's own stated purpose: identical entries to backtest.py. If
    the two pick a different bar for entry_atr, that purpose is defeated even
    when neither individually looks buggy."""
    import inspect

    import kala.backtest as bt

    src_bt = inspect.getsource(bt.backtest_ticker)
    src_live = inspect.getsource(ble.backtest_ticker_live_exits)
    assert "atr_arr[i]" in src_bt
    assert "atr_arr[i]" in src_live
    assert "atr_arr[i + 1]" not in src_bt
    assert "atr_arr[i + 1]" not in src_live


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
