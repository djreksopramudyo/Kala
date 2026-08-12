"""run_walkforward.fetch(): the min_price tier filter used to isolate
whether cheap stocks are dragging the pooled OOS edge down under honest
(tick-floored) spread costs -- see HOW_IT_WORKS.md's validation section."""

import numpy as np
import pandas as pd

import run_walkforward as rw


def _df(price, n=450):
    closes = np.full(n, price, dtype=float)
    return pd.DataFrame(
        {"Open": closes, "High": closes * 1.01, "Low": closes * 0.99,
         "Close": closes, "Volume": np.full(n, 1_000_000.0)},
        index=pd.bdate_range("2022-01-03", periods=n))


def test_fetch_default_min_price_matches_module_constant(monkeypatch):
    """No min_price passed -> behaves exactly as before this change (the
    original MIN_PRICE=50 listing-quality floor)."""
    raw = {"CHEAP.JK": _df(40.0), "OK.JK": _df(60.0)}   # 40 < 50 default floor
    monkeypatch.setattr(rw.yf, "download", lambda *a, **k: raw)
    dfs = rw.fetch(["CHEAP.JK", "OK.JK"], "5y")
    assert "CHEAP.JK" not in dfs and "OK.JK" in dfs


def test_fetch_min_price_isolates_a_price_tier(monkeypatch):
    """Raising --min-price excludes everything below it, regardless of the
    default MIN_PRICE constant -- this is the mechanism the price-tier
    diagnosis (flat vs tick-spread, cheap vs expensive) depends on."""
    raw = {"CHEAP.JK": _df(300.0), "MID.JK": _df(800.0), "EXPENSIVE.JK": _df(3000.0)}
    monkeypatch.setattr(rw.yf, "download", lambda *a, **k: raw)
    dfs = rw.fetch(["CHEAP.JK", "MID.JK", "EXPENSIVE.JK"], "5y", min_price=500.0)
    assert set(dfs) == {"MID.JK", "EXPENSIVE.JK"}


def test_fetch_still_applies_min_bars_and_liquidity_filters(monkeypatch):
    short = _df(1000.0, n=100)     # below MIN_BARS
    dead = _df(1000.0)
    dead["Volume"] = 0.0           # fully untraded
    ok = _df(1000.0)
    raw = {"SHORT.JK": short, "DEAD.JK": dead, "OK.JK": ok}
    monkeypatch.setattr(rw.yf, "download", lambda *a, **k: raw)
    dfs = rw.fetch(["SHORT.JK", "DEAD.JK", "OK.JK"], "5y", min_price=0.0)
    assert set(dfs) == {"OK.JK"}
