"""The untagged count must match the UNKNOWN bucket it describes.

Two different things are untaggable and both land in the 'UNKNOWN' bucket:
an entry before the benchmark's first bar (regime_at -> None) and an entry
inside the benchmark's SMA50 warm-up (the string 'UNKNOWN'). n_untagged
counted only the first, so the footer disagreed with the table's own UNKNOWN
row and understated how much of the run had no regime attribution at all --
in a report whose entire job is deciding whether the edge is regime-conditional.
"""

import numpy as np
import pandas as pd

from kala.regime import classify_market_regime, regime_at
from kala.regime_breakdown import RegimeBreakdownResult


def _bench(n=120):
    idx = pd.bdate_range("2024-06-03", periods=n)
    return pd.DataFrame({"Close": np.linspace(100, 200, n)}, index=idx)


def test_both_untaggable_routes_exist_and_are_distinct():
    reg = classify_market_regime(_bench())
    idx = _bench().index
    assert regime_at(reg, pd.Timestamp("2024-01-15")) is None   # before the series
    assert regime_at(reg, idx[10]) == "UNKNOWN"                 # inside warm-up
    assert regime_at(reg, idx[60]) in ("BULLISH", "MODERATE_BULL", "NEUTRAL",
                                       "BEARISH", "MODERATE_BEAR")


def test_untagged_total_equals_the_unknown_bucket():
    r = RegimeBreakdownResult(
        by_regime={"BULLISH": {"n": 10, "ev_pct": 1.0, "win_rate_pct": 60.0, "t_stat": 1.2},
                   "UNKNOWN": {"n": 7, "ev_pct": 0.5, "win_rate_pct": 50.0, "t_stat": 0.3}},
        n_trades_total=17, n_untagged=7, n_before_benchmark=3, n_in_warmup=4)
    assert r.n_untagged == r.by_regime["UNKNOWN"]["n"]
    assert r.n_before_benchmark + r.n_in_warmup == r.n_untagged


def test_summary_reports_both_routes():
    r = RegimeBreakdownResult(
        by_regime={"BULLISH": {"n": 90, "ev_pct": 1.0, "win_rate_pct": 60.0, "t_stat": 2.0},
                   "UNKNOWN": {"n": 10, "ev_pct": 0.0, "win_rate_pct": 0.0, "t_stat": 0.0}},
        n_trades_total=100, n_untagged=10, n_before_benchmark=6, n_in_warmup=4)
    text = r.summary_text()
    assert "no regime tag: 10" in text
    assert "6 before the benchmark starts" in text
    assert "4 inside its SMA50 warm-up" in text


def test_heavy_untagged_share_is_flagged():
    """A run that mostly could not be attributed must say so, not print a
    confident-looking per-regime table."""
    r = RegimeBreakdownResult(
        by_regime={"BULLISH": {"n": 60, "ev_pct": 1.0, "win_rate_pct": 60.0, "t_stat": 2.0},
                   "UNKNOWN": {"n": 40, "ev_pct": 0.0, "win_rate_pct": 0.0, "t_stat": 0.0}},
        n_trades_total=100, n_untagged=40, n_before_benchmark=10, n_in_warmup=30)
    assert "WARNING" in r.summary_text()


def test_clean_run_is_not_flagged():
    r = RegimeBreakdownResult(
        by_regime={"BULLISH": {"n": 100, "ev_pct": 1.0, "win_rate_pct": 60.0, "t_stat": 2.0}},
        n_trades_total=100, n_untagged=0, n_before_benchmark=0, n_in_warmup=0)
    text = r.summary_text()
    assert "WARNING" not in text
    assert "no regime tag: 0" in text


def test_zero_trades_does_not_divide_by_zero():
    assert "no regime tag: 0" in RegimeBreakdownResult().summary_text()
