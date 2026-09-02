"""A position opened by hand must carry an ATR, or its stop is silently flat.

exits.governing_stop treats a missing entry_atr as "use the hard floor", so
atr_stop_multiple never binds and every position runs the same flat stop
regardless of volatility. /buy passed no ATR, so in live use the volatility-
sized stop had never once been active — and nothing in the output said so.
"""

import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from kala.config import RiskConfig
from kala.exits import governing_stop
from kala.papertrade import PaperTrader

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """`/buy` reads `runner_config.json`, which is gitignored.

    These two tests passed only on a machine that happened to have one. Run
    from a fresh clone — or from the zip this repository ships as — they failed
    with `FileNotFoundError`, which is the last thing a test about ATR should
    be reporting. Where the file did exist they were reading the operator's
    real capital and position limits, so what they exercised depended on
    personal settings that are not in version control either way.

    Found by running the suite from the *extracted zip* rather than the working
    tree — the check that finding 20 put in place.
    """
    cfg = tmp_path / "runner_config.json"
    shutil.copyfile(ROOT / "runner_config.json.example", cfg)
    import telegram_bot as tb
    monkeypatch.setattr(tb, "CONFIG_PATH", cfg)
    return cfg


def _frame(n=60, price=1000.0, atr_pct=1.0):
    """OHLC with a controlled true range, so ATR is predictable."""
    idx = pd.bdate_range("2025-01-01", periods=n)
    close = np.full(n, price)
    band = price * atr_pct / 100.0
    return pd.DataFrame({"Open": close, "High": close + band / 2,
                         "Low": close - band / 2, "Close": close,
                         "Volume": np.full(n, 1e6)}, index=idx)


# ---- the mechanism the missing ATR disabled -------------------------------

def test_missing_atr_collapses_the_stop_onto_the_hard_floor():
    cfg = RiskConfig()
    entry = 1000.0
    flat, _, _ = governing_stop(entry, entry, None, cfg)
    assert flat == pytest.approx(entry * (1 + cfg.hard_stop_pct / 100.0))


def test_a_supplied_atr_tightens_the_stop_for_a_calm_stock():
    """A low-volatility name should stop out inside the hard floor, not on it."""
    cfg = RiskConfig()
    entry = 1000.0
    calm_atr = entry * 0.01                       # 2 x ATR = 2% < 5% floor
    stop, _, _ = governing_stop(entry, entry, calm_atr, cfg)
    floor = entry * (1 + cfg.hard_stop_pct / 100.0)
    assert stop > floor, "ATR stop did not bind for a calm stock"
    assert stop == pytest.approx(entry - cfg.atr_stop_multiple * calm_atr)


def test_a_volatile_stock_still_gets_the_floor_not_a_wider_stop():
    """The floor is a floor: ATR may tighten the stop, never widen it."""
    cfg = RiskConfig()
    entry = 1000.0
    wild_atr = entry * 0.10                       # 2 x ATR = 20% >> 5% floor
    stop, _, _ = governing_stop(entry, entry, wild_atr, cfg)
    assert stop == pytest.approx(entry * (1 + cfg.hard_stop_pct / 100.0))


# ---- the store must actually persist it -----------------------------------

def test_manual_buy_persists_the_atr(tmp_path):
    pt = PaperTrader.load(tmp_path / "s.json", start_capital=10_000_000)
    pt.manual_buy("AAA.JK", shares=100, price=1000.0, atr=12.5)
    assert pt.positions["AAA.JK"].entry_atr == pytest.approx(12.5)


def test_manual_buy_without_atr_is_recorded_as_absent_not_zero(tmp_path):
    """None must not become 0.0 — a zero ATR would pin the stop AT entry."""
    pt = PaperTrader.load(tmp_path / "s.json", start_capital=10_000_000)
    pt.manual_buy("AAA.JK", shares=100, price=1000.0)
    assert pt.positions["AAA.JK"].entry_atr is None


def test_atr_survives_a_reload(tmp_path):
    p = tmp_path / "s.json"
    pt = PaperTrader.load(p, start_capital=10_000_000)
    pt.manual_buy("AAA.JK", shares=100, price=1000.0, atr=9.0)
    assert PaperTrader.load(p, 10_000_000).positions["AAA.JK"].entry_atr == pytest.approx(9.0)


# ---- the /buy command must supply one --------------------------------------

def test_buy_command_passes_an_atr_through(monkeypatch, tmp_path, isolated_config):
    """The regression: /buy used to call manual_buy with no atr at all."""
    import telegram_bot as tb

    seen = {}

    from kala.papertrade import PaperTrader as PT

    def spy(self, ticker, shares, price, date=None, atr=None):
        seen["atr"] = atr
        return price

    monkeypatch.setattr(PT, "manual_buy", spy)
    monkeypatch.setattr(tb, "STATE_PATH", str(tmp_path / "s.json"))
    monkeypatch.setattr(tb, "_entry_atr", lambda t: 7.25)
    monkeypatch.setattr(tb, "_last_close", lambda t: 1000.0)

    tb.cmd_buy("AAA 100 1000")
    assert seen.get("atr") == pytest.approx(7.25), \
        "/buy did not pass an ATR — stops fall back to the flat floor"


def test_buy_reply_flags_a_missing_atr(monkeypatch, tmp_path, isolated_config):
    import telegram_bot as tb
    from kala.papertrade import PaperTrader as PT

    monkeypatch.setattr(PT, "manual_buy",
                        lambda self, ticker, shares, price, date=None, atr=None: price)
    monkeypatch.setattr(tb, "STATE_PATH", str(tmp_path / "s.json"))
    monkeypatch.setattr(tb, "_entry_atr", lambda t: None)
    monkeypatch.setattr(tb, "_last_close", lambda t: 1000.0)

    out = tb.cmd_buy("AAA 100 1000")
    assert "No ATR" in out, "a degraded stop was not disclosed"
