"""
get_quotes() tests -- the yfinance boundary for intraday_watch.py.

The bug this guards against: yfinance can return NaN for the newest bar's
Close/High before it's actually posted (e.g. right after a calendar day
rolls over with no trades yet, or an illiquid name). A NaN price used to
flow straight into Quote and get silently turned into a fake "0% from
stop" by position_stop_status -- which read as a false stop-hit alarm on
every affected position. get_quotes() must instead OMIT that ticker,
exactly like it already does for "not enough history" / a fetch exception,
so the caller's existing "couldn't get a fresh quote" fallback handles it
honestly instead of lying with a fabricated number.
"""

import math
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest
import yfinance

import intraday_watch as iw


def _bars(closes, highs=None):
    closes = np.asarray(closes, dtype=float)
    highs = np.asarray(highs, dtype=float) if highs is not None else closes
    return pd.DataFrame({"Close": closes, "High": highs,
                         "Open": closes, "Low": closes,
                         "Volume": np.full(len(closes), 1e6)},
                        index=pd.bdate_range("2026-07-15", periods=len(closes)))


def _patch_history(monkeypatch, frame_by_ticker: dict):
    # get_quotes() does `import yfinance as yf` LOCALLY inside the function,
    # so it binds to this same module object each call -- patch it here.
    def _fake_ticker(t):
        m = MagicMock()
        m.history.return_value = frame_by_ticker.get(t)
        return m
    monkeypatch.setattr(yfinance, "Ticker", _fake_ticker)


def test_get_quotes_normal_bar_is_included(monkeypatch):
    _patch_history(monkeypatch, {"A.JK": _bars([1000, 1010], highs=[1005, 1015])})
    q = iw.get_quotes({"A.JK"})
    assert "A.JK" in q
    assert q["A.JK"].price == pytest.approx(1010.0)
    assert q["A.JK"].prev_close == pytest.approx(1000.0)


def test_get_quotes_omits_nan_close(monkeypatch):
    _patch_history(monkeypatch, {"A.JK": _bars([1000, math.nan], highs=[1005, 1015])})
    q = iw.get_quotes({"A.JK"})
    assert "A.JK" not in q


def test_get_quotes_omits_nan_high(monkeypatch):
    _patch_history(monkeypatch, {"A.JK": _bars([1000, 1010], highs=[1005, math.nan])})
    q = iw.get_quotes({"A.JK"})
    assert "A.JK" not in q


def test_get_quotes_omits_zero_or_negative_price(monkeypatch):
    _patch_history(monkeypatch, {"A.JK": _bars([1000, 0.0], highs=[1005, 5.0])})
    q = iw.get_quotes({"A.JK"})
    assert "A.JK" not in q


def test_get_quotes_omits_too_short_history(monkeypatch):
    _patch_history(monkeypatch, {"A.JK": _bars([1000])})   # only 1 row
    q = iw.get_quotes({"A.JK"})
    assert "A.JK" not in q


def test_get_quotes_one_bad_ticker_does_not_affect_others(monkeypatch):
    _patch_history(monkeypatch, {
        "GOOD.JK": _bars([1000, 1010], highs=[1005, 1015]),
        "BAD.JK": _bars([1000, math.nan], highs=[1005, 1015]),
    })
    q = iw.get_quotes({"GOOD.JK", "BAD.JK"})
    assert "GOOD.JK" in q
    assert "BAD.JK" not in q
