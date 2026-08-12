"""
Support/resistance strategy tests.

The headline test here is ``test_score_at_bar_t_is_unchanged_by_future_bars``.
Pivot detection is inherently forward-looking (a swing low is only a swing low
once the market has turned back up), so the ONLY thing separating this from a
look-ahead-biased backtest is the confirmation lag. If that regresses, the
strategy manufactures an edge it could never capture live, and every other
test here would still pass. Everything else verifies the folk rules were
implemented as stated: zones not lines, repeat touches required, broken levels
dropped.
"""

import numpy as np
import pandas as pd

from kala.strategies import get_strategy
from kala.strategy_support_resistance import (
    MIN_TOUCHES,
    NEAR_PCT,
    PIVOT_K,
    _cluster_zones,
    compute_features_support_resistance,
    score_support_resistance,
)


def _frame(closes, lows=None, highs=None):
    n = len(closes)
    closes = np.asarray(closes, dtype=float)
    lows = np.asarray(lows if lows is not None else closes * 0.99, dtype=float)
    highs = np.asarray(highs if highs is not None else closes * 1.01, dtype=float)
    idx = pd.bdate_range("2020-01-01", periods=n)
    return pd.DataFrame({"Open": closes, "High": highs, "Low": lows,
                         "Close": closes, "Volume": np.full(n, 1_000_000.0)}, index=idx)


def _sawtooth(cycles=12, period=40, base=1000.0, amp=60.0):
    """A repeating V pattern: clean, repeated swing lows at ~the same price,
    which is exactly the shape the strategy is supposed to recognize."""
    out = []
    for _ in range(cycles):
        half = period // 2
        out.extend(np.linspace(base + amp, base, half))
        out.extend(np.linspace(base, base + amp, period - half))
    return np.array(out)


# ---------------- the look-ahead guard (most important test here) -----------------

def test_score_at_bar_t_is_unchanged_by_future_bars():
    """Truncating the series at bar t must not change bar t's features.

    If pivot confirmation were not lagged, a pivot at bar t-1 (whose status
    depends on bars t..t+K) would leak into bar t's score on the full series
    but be absent on the truncated one, and these would differ."""
    closes = _sawtooth(cycles=14, period=40)
    df = _frame(closes)
    full = compute_features_support_resistance(df)

    # check a spread of late bars, where plenty of pivot history exists
    for t in (300, 350, 400, 450, 500):
        if t >= len(df):
            continue
        truncated = compute_features_support_resistance(df.iloc[:t + 1])
        a = full["sr_dist"].iloc[t]
        b = truncated["sr_dist"].iloc[t]
        assert (pd.isna(a) and pd.isna(b)) or abs(a - b) < 1e-12, (
            f"bar {t}: full={a} truncated={b} -- future data leaked into the score")
        a_t = full["sr_touches"].iloc[t]
        b_t = truncated["sr_touches"].iloc[t]
        assert (pd.isna(a_t) and pd.isna(b_t)) or a_t == b_t


def test_a_pivot_is_not_used_before_its_confirmation_bar():
    """A fresh swing low must be invisible for PIVOT_K bars after it prints."""
    # long flat run, one sharp dip, then recovery -- the dip is the only pivot
    closes = np.concatenate([
        np.full(300, 1000.0),
        [900.0],                 # the dip (single pivot low)
        np.full(60, 1000.0),
    ])
    df = _frame(closes, lows=closes)
    feats = compute_features_support_resistance(df)
    dip_pos = 300
    # within the confirmation lag the dip cannot be part of any zone
    for t in range(dip_pos, dip_pos + PIVOT_K):
        touched = feats["sr_touches"].iloc[t]
        assert pd.isna(touched) or touched < MIN_TOUCHES


# ---------------- zone clustering ------------------------------------------------

def test_cluster_groups_nearby_prices_and_counts_touches():
    zones = _cluster_zones([100.0, 100.5, 101.0, 200.0, 201.0], zone_pct=0.02)
    levels = sorted(round(level) for level, _ in zones)
    assert levels == [100, 200]
    counts = sorted(n for _, n in zones)
    assert counts == [2, 3]


def test_cluster_bounds_zone_width_instead_of_chaining():
    """A long chain of near-neighbours must not collapse into one wide zone:
    each zone stays within zone_pct of its own lowest member."""
    prices = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0]
    zones = _cluster_zones(prices, zone_pct=0.02)
    assert len(zones) > 1
    for level, _ in zones:
        assert 99.0 <= level <= 106.0


def test_cluster_handles_empty_and_single():
    assert _cluster_zones([], 0.02) == []
    assert _cluster_zones([50.0], 0.02) == [(50.0, 1)]


# ---------------- the stated folk rules ------------------------------------------

def test_single_touch_zone_is_not_traded():
    """'At least two touches' -- a level hit once must not produce a score."""
    feats = pd.DataFrame({"sr_dist": [0.0], "sr_touches": [1.0]})
    assert score_support_resistance(feats).iloc[0] == 0.0


def test_more_touches_scores_higher_at_equal_distance():
    feats = pd.DataFrame({"sr_dist": [0.0, 0.0], "sr_touches": [2.0, 5.0]})
    s = score_support_resistance(feats)
    assert s.iloc[1] > s.iloc[0]


def test_closer_to_the_zone_scores_higher_at_equal_strength():
    feats = pd.DataFrame({"sr_dist": [0.0, NEAR_PCT * 0.5], "sr_touches": [4.0, 4.0]})
    s = score_support_resistance(feats)
    assert s.iloc[0] > s.iloc[1]


def test_far_from_any_zone_scores_zero():
    feats = pd.DataFrame({"sr_dist": [NEAR_PCT * 3], "sr_touches": [4.0]})
    assert score_support_resistance(feats).iloc[0] == 0.0


def test_no_qualifying_zone_yields_nan_not_zero():
    """NaN means 'no entry'; 0.0 would be a real (bad) score. The distinction
    matters because the harness treats them differently."""
    feats = pd.DataFrame({"sr_dist": [np.nan], "sr_touches": [np.nan]})
    assert pd.isna(score_support_resistance(feats).iloc[0])


def test_broken_support_far_above_price_is_excluded():
    """Price well BELOW an old level means that level broke -- it must not be
    scored as nearby support ('when a level slices, delete it')."""
    closes = np.concatenate([
        np.tile(np.concatenate([np.linspace(1060, 1000, 20),
                                np.linspace(1000, 1060, 20)]), 8),   # zone at ~1000
        np.full(40, 700.0),                                          # collapse far below
    ])
    df = _frame(closes, lows=closes)
    feats = compute_features_support_resistance(df)
    tail = feats["sr_dist"].iloc[-1]
    # either no zone qualifies, or the one found is genuinely near 700 -- never
    # the broken 1000 zone (which would show dist ~ -0.43)
    assert pd.isna(tail) or tail > -NEAR_PCT


def test_flat_price_stretch_invents_no_support_zone():
    """A stock that simply DIDN'T MOVE must not manufacture a strong level.

    Regression test for a real bug: with lows all equal, every bar trivially
    satisfies 'is the window minimum', so a dead-flat illiquid name produced a
    zone with dozens of 'touches' and scored as maximum-strength support --
    built from zero actual swings. Common in this universe, not exotic.
    """
    closes = np.full(300, 1000.0)
    df = _frame(closes, lows=closes, highs=closes * 1.01)   # steady intraday range
    feats = compute_features_support_resistance(df)
    assert feats["sr_touches"].isna().all(), (
        "flat price stretch produced phantom support touches")
    assert score_support_resistance(feats).isna().all()


def test_two_adjacent_bars_at_the_same_low_count_as_one_touch():
    """One swing counted twice would inflate the strength measure."""
    from kala.strategy_support_resistance import _separate_pivots
    kept = _separate_pivots(np.array([10, 11, 12, 40, 41, 80]), PIVOT_K)
    assert list(kept) == [10, 40, 80]


def test_recognizes_a_repeatedly_touched_support_zone():
    """Positive control: on a clean sawtooth the strategy must actually FIRE,
    otherwise every null result would be meaningless (a signal that never
    trades trivially 'has no edge')."""
    closes = _sawtooth(cycles=14, period=40)
    df = _frame(closes, lows=closes)
    feats = compute_features_support_resistance(df)
    scores = score_support_resistance(feats)
    assert scores.max() > 50.0, "strategy never fires on its ideal pattern"
    assert (feats["sr_touches"].dropna() >= MIN_TOUCHES).all()


# ---------------- registration + harness contract --------------------------------

def test_registered_in_the_zoo():
    strat = get_strategy("support_resistance")
    assert strat.name == "support_resistance"
    assert strat.warmup_bars > 252      # needs a full lookback of pivots
    # Result recorded 2026-08-03 (see PROJECT_STATUS.md): confidently
    # negative, not untested -- the description must say so plainly rather
    # than leaving a stale "UNTESTED" claim once a real verdict exists.
    assert "NEGATIVE" in strat.description
    assert "Do not trade" in strat.description


def test_features_return_all_original_columns():
    """The harness passes the frame on to the backtest, which needs OHLCV."""
    df = _frame(_sawtooth(cycles=8, period=40))
    feats = compute_features_support_resistance(df)
    for col in ("Open", "High", "Low", "Close", "Volume"):
        assert col in feats.columns
    assert len(feats) == len(df)


def test_short_history_produces_no_signal_rather_than_crashing():
    df = _frame(np.linspace(100, 110, 20))
    feats = compute_features_support_resistance(df)
    assert feats["sr_dist"].isna().all()
    assert score_support_resistance(feats).isna().all()


def test_handles_nan_and_zero_prices_without_crashing():
    closes = _sawtooth(cycles=10, period=40)
    closes[150] = np.nan
    closes[151] = 0.0
    df = _frame(np.nan_to_num(closes, nan=1000.0))
    df.loc[df.index[150], "Close"] = np.nan
    df.loc[df.index[151], "Close"] = 0.0
    feats = compute_features_support_resistance(df)
    assert pd.isna(feats["sr_dist"].iloc[150])
    assert pd.isna(feats["sr_dist"].iloc[151])
