"""A NaN open price must never reach the cash ledger.

yfinance returns NaN for an unposted or illiquid latest bar. NaN loses every
comparison, so `cost > self.cash` is False when cost is NaN — the
affordability check waves the order through, cash becomes NaN, and the
position is booked at a NaN entry price. Because step() saves, that state
persists: equity, TWR, the scorecard and every report read "nan" from then
on and do not recover on the next run.

telegram_bot._last_close already documents this exact failure mode ("a NaN
leaking into price math ... misfires <=/>= checks"). step() was the one path
that had no guard.
"""

import numpy as np
import pandas as pd
import pytest

from kala.papertrade import PaperTrader, PendingOrder


def _history(last_open):
    idx = pd.bdate_range("2026-01-02", periods=3)
    return pd.DataFrame({"Open": [1000.0, 1000.0, last_open],
                         "High": [1010.0, 1010.0, 1010.0],
                         "Low": [990.0, 990.0, 990.0],
                         "Close": [1000.0, 1000.0, 1000.0]}, index=idx)


def _trader(tmp_path, side="BUY", hold_first=False):
    pt = PaperTrader.load(tmp_path / "state.json", 10_000_000)
    if hold_first:
        pt.manual_buy("X.JK", 100, 1000.0, date="2026-01-02")
    pt.pending = [PendingOrder(ticker="X.JK", side=side, shares=100,
                               reason="test", queued="2026-01-05")]
    return pt


@pytest.mark.parametrize("bad", [np.nan, 0.0, -5.0])
def test_unusable_open_never_touches_cash(tmp_path, bad):
    pt = _trader(tmp_path)
    before = pt.cash
    pt.step({"X.JK": _history(bad)}, [], today="2026-01-06")

    assert pt.cash == before
    assert pt.cash == pt.cash          # not NaN
    assert not pt.positions            # nothing booked at a junk price


@pytest.mark.parametrize("bad", [np.nan, 0.0, -5.0])
def test_unusable_open_carries_the_order_rather_than_dropping_it(tmp_path, bad):
    """Carrying matches how a missing bar is already handled; dropping would
    silently cancel an order the user still expects to fill."""
    pt = _trader(tmp_path)
    report = pt.step({"X.JK": _history(bad)}, [], today="2026-01-06")

    assert len(pt.pending) == 1
    assert any("carried" in s for s in report["skipped"])


def test_sell_with_unusable_open_keeps_the_position(tmp_path):
    """The sell path reads the same open price. Popping the position and
    crediting NaN proceeds would destroy the holding AND the cash balance."""
    pt = _trader(tmp_path, side="SELL", hold_first=True)
    cash_before = pt.cash

    pt.step({"X.JK": _history(np.nan)}, [], today="2026-01-06")

    assert "X.JK" in pt.positions
    assert pt.cash == cash_before
    assert len(pt.pending) == 1


def test_a_normal_open_still_fills(tmp_path):
    """Guard against 'fixing' this by never filling anything."""
    pt = _trader(tmp_path)
    before = pt.cash
    report = pt.step({"X.JK": _history(1000.0)}, [], today="2026-01-06")

    assert "X.JK" in pt.positions
    assert pt.cash < before
    assert not pt.pending
    assert any("BOUGHT" in f for f in report["fills"])


def test_nan_state_is_not_persisted(tmp_path):
    """The reason this mattered: step() saves, so a poisoned balance outlives
    the bad data and every later report inherits it."""
    pt = _trader(tmp_path)
    pt.step({"X.JK": _history(np.nan)}, [], today="2026-01-06")

    reloaded = PaperTrader.load(tmp_path / "state.json", 10_000_000)
    assert reloaded.cash == reloaded.cash
    assert reloaded.equity({}) == 10_000_000


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
