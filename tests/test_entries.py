"""Entry-guardrail tests — including a PTPW-shaped regression case."""

import numpy as np
import pandas as pd

from kala.config import EntryConfig
from kala.entries import evaluate_entry


def make_df(closes, vols=None):
    closes = np.asarray(closes, dtype=float)
    n = len(closes)
    vols = np.asarray(vols, dtype=float) if vols is not None else np.full(n, 1_000_000.0)
    return pd.DataFrame(
        {
            "Open": closes,
            "High": closes * 1.005,
            "Low": closes * 0.995,
            "Close": closes,
            "Volume": vols,
        },
        index=pd.bdate_range("2024-01-02", periods=n),
    )


def test_clean_breakout_is_allowed():
    # healthy uptrend WITH real pullbacks: positive drift, calm RSI, rising volume
    t = np.arange(45)
    closes = 1000 * (1 + 0.0018 * t + 0.025 * np.sin(t / 2.0))
    vols = np.linspace(1_000_000, 1_300_000, 45)
    d = evaluate_entry(make_df(closes, vols), market_status="NEUTRAL")
    assert d.allowed, d.vetoes
    assert not d.vetoes


def test_parabolic_run_is_vetoed():
    closes = np.concatenate([np.full(20, 1000.0), np.linspace(1000, 1300, 22)])  # +28% over last 20
    d = evaluate_entry(make_df(closes), market_status="NEUTRAL")
    assert not d.allowed
    assert any("extended" in v for v in d.vetoes)


def test_overbought_is_vetoed():
    closes = np.concatenate([np.full(30, 1000.0), np.linspace(1000, 1120, 12)])  # sharp pop -> RSI hot
    d = evaluate_entry(make_df(closes), market_status="NEUTRAL")
    assert not d.allowed
    assert any("overbought" in v for v in d.vetoes)


def test_thin_volume_surge_is_vetoed():
    # a clear >15% surge but recent volume DRYING UP vs baseline
    closes = np.concatenate([np.full(20, 1000.0), np.linspace(1000, 1180, 22)])  # +18% over last 20
    vols = np.concatenate([np.full(37, 2_000_000.0), np.full(5, 500_000.0)])  # recent volume drying up
    d = evaluate_entry(make_df(closes, vols), market_status="NEUTRAL")
    assert not d.allowed
    assert any("volume" in v for v in d.vetoes)


def test_distribution_divergence_is_vetoed():
    # net price up over last 10 bars, but down-days carry the big volume -> OBV falls
    closes = np.array([1000, 1010, 990, 1005, 985, 1012, 992, 1015, 996, 1018, 1030], dtype=float)
    closes = np.concatenate([np.full(20, 1000.0), closes])  # pad for warmup
    vols = np.full(len(closes), 500_000.0)
    # huge volume on the down prints inside the lookback window
    for i in range(len(closes) - 11, len(closes)):
        if closes[i] < closes[i - 1]:
            vols[i] = 5_000_000.0
    d = evaluate_entry(make_df(closes, vols), market_status="NEUTRAL",
                       cfg=EntryConfig(veto_parabolic=False, veto_overbought=False, veto_thin_volume=False))
    assert not d.allowed
    assert any("distribution" in v.lower() for v in d.vetoes)


def test_cheap_stock_is_vetoed():
    """2026-07-20: the >= IDR 1,000 tier is the only one with a confirmed OOS
    edge under honest tick-floor costs (see kala/edge.py) -- a clean
    breakout below that price must still be rejected on price alone."""
    t = np.arange(45)
    closes = 500 * (1 + 0.0018 * t + 0.025 * np.sin(t / 2.0))   # same healthy shape, just cheap
    vols = np.linspace(1_000_000, 1_300_000, 45)
    d = evaluate_entry(make_df(closes, vols), market_status="NEUTRAL")
    assert not d.allowed
    assert any("price too low" in v for v in d.vetoes)
    assert d.metrics["price"] < 1000.0


def test_cheap_stock_veto_can_be_disabled():
    t = np.arange(45)
    closes = 500 * (1 + 0.0018 * t + 0.025 * np.sin(t / 2.0))
    vols = np.linspace(1_000_000, 1_300_000, 45)
    d = evaluate_entry(make_df(closes, vols), market_status="NEUTRAL",
                       cfg=EntryConfig(veto_cheap_stock=False))
    assert d.allowed, d.vetoes


def test_min_price_idr_is_configurable():
    t = np.arange(45)
    closes = 1500 * (1 + 0.0018 * t + 0.025 * np.sin(t / 2.0))   # clears the 1,000 default
    vols = np.linspace(1_000_000, 1_300_000, 45)
    d = evaluate_entry(make_df(closes, vols), market_status="NEUTRAL",
                       cfg=EntryConfig(min_price_idr=2000.0))
    assert not d.allowed
    assert any("price too low" in v for v in d.vetoes)


def test_bear_market_blocks_buy():
    base = np.linspace(1000, 1080, 40)
    noise = np.tile([1.0, 0.997, 1.002, 0.998, 1.001], 8)
    d = evaluate_entry(make_df(base * noise), market_status="BEARISH")
    assert not d.allowed
    assert any("regime" in v for v in d.vetoes)


def test_ranging_stock_veto_is_off_by_default():
    """A tight, choppy sideways grind (low ADX) must NOT be vetoed unless
    veto_ranging_stock is explicitly enabled -- default backtest numbers
    stay unchanged."""
    rng = np.random.default_rng(3)
    closes = 1000.0 + np.cumsum(rng.normal(0.0, 0.4, 60))
    closes = np.clip(closes, 990.0, 1010.0)
    vols = np.full(60, 1_000_000.0)
    d = evaluate_entry(make_df(closes, vols), market_status="NEUTRAL")
    assert not any("range-bound" in v for v in d.vetoes)


def test_ranging_stock_is_vetoed_when_enabled():
    rng = np.random.default_rng(3)
    closes = 1000.0 + np.cumsum(rng.normal(0.0, 0.4, 60))
    closes = np.clip(closes, 990.0, 1010.0)
    vols = np.full(60, 1_000_000.0)
    d = evaluate_entry(make_df(closes, vols), market_status="NEUTRAL",
                       cfg=EntryConfig(veto_cheap_stock=False, veto_ranging_stock=True))
    assert not d.allowed
    assert any("range-bound" in v for v in d.vetoes)
    assert d.metrics["adx"] == d.metrics["adx"]  # not NaN when the veto is on


def test_trending_stock_is_not_vetoed_by_ranging_filter():
    t = np.arange(45)
    closes = 1500 * (1 + 0.0018 * t + 0.025 * np.sin(t / 2.0))
    vols = np.linspace(1_000_000, 1_300_000, 45)
    d = evaluate_entry(make_df(closes, vols), market_status="NEUTRAL",
                       cfg=EntryConfig(veto_ranging_stock=True))
    assert not any("range-bound" in v for v in d.vetoes)


def test_ptpw_shaped_candidate_is_rejected():
    """The real failure: a parabolic, overbought, thin-volume surge in a bearish
    tape. Must be rejected on MULTIPLE independent grounds, not squeak through."""
    closes = np.concatenate([np.full(20, 950.0), np.linspace(950, 1390, 22)])  # ~+46% blow-off
    vols = np.concatenate([np.full(37, 3_000_000.0), np.full(5, 1_000_000.0)])  # thinning into the top
    d = evaluate_entry(make_df(closes, vols), market_status="BEARISH")
    assert not d.allowed
    assert len(d.vetoes) >= 3, d.vetoes
