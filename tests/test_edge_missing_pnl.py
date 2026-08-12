"""A log entry with no pnl_pct is unscoreable, not a breakeven trade.

live_stats used to read `float(t.get("pnl_pct", 0.0))`. That default is a real
observation: it inflates n (which gates MIN_TRADES_FOR_VERDICT), pulls ev_pct
toward zero, shrinks the std the t-statistic divides by, and counts as a loss in
win_rate. The same function already skips entries with no entry_date when
averaging hold time — because that field only arrived in v3.4 — so this log's
schema demonstrably grows over time.
"""

from kala.edge import edge_report, live_stats

CFG = {"edge_expectations": {"validated": True, "ev_pct": 0.70}}


def _trades(values):
    return [{"date": "2026-01-05", "ticker": f"T{i}", "pnl_pct": v, "reason": "target"}
            for i, v in enumerate(values)]


def _unscoreable(n, **extra):
    return [{"date": "2026-01-06", "ticker": f"P{i}", "reason": "target", **extra}
            for i in range(n)]


def test_entries_without_pnl_are_not_counted_as_breakeven():
    real = _trades([3.1, -1.4, 2.2, -0.8])
    stats = live_stats(real + _unscoreable(4))
    baseline = live_stats(real)

    assert stats["n"] == baseline["n"] == 4, "phantom trades inflated the sample"
    assert stats["ev_pct"] == baseline["ev_pct"]
    assert stats["win_rate_pct"] == baseline["win_rate_pct"]
    assert stats["n_skipped_no_pnl"] == 4


def test_skipped_count_is_reported_so_the_gap_is_visible():
    assert live_stats(_trades([1.0, 2.0]))["n_skipped_no_pnl"] == 0
    assert live_stats(_unscoreable(3))["n_skipped_no_pnl"] == 3


def test_null_and_nan_pnl_are_also_unscoreable():
    real = _trades([3.1, -1.4])
    for bad in (None, float("nan"), "", "n/a"):
        stats = live_stats(real + _unscoreable(2, pnl_pct=bad))
        assert stats["n"] == 2, f"{bad!r} was scored as a trade"
        assert stats["n_skipped_no_pnl"] == 2


def test_string_numbers_still_score():
    # tolerated because JSON state has round-tripped through hand edits before
    assert live_stats(_unscoreable(1, pnl_pct="2.5"))["n"] == 1


def test_phantom_entries_cannot_reach_a_verdict_threshold():
    """9 real trades is below MIN_TRADES_FOR_VERDICT; padding must not cross it."""
    real = _trades([3.1, -1.4, 2.2, -0.8, 4.0, -2.1, 1.7, -1.1, 2.9])
    padded = edge_report(real + _unscoreable(6), CFG)
    assert padded["verdict"] == "TOO EARLY", padded["verdict_reason"]
    assert padded["live"]["n"] == 9


def test_real_trades_are_unaffected():
    """The fix must be a no-op on well-formed logs — every current writer
    populates pnl_pct, so no existing number may move."""
    real = _trades([3.1, -1.4, 2.2, -0.8, 4.0, -2.1, 1.7, -1.1, 2.9, -1.6, 3.3, -0.9])
    r = edge_report(real, CFG)
    assert r["live"]["n"] == 12
    assert r["live"]["n_skipped_no_pnl"] == 0
    assert round(r["live"]["ev_pct"], 3) == 0.775
    assert r["verdict"] == "ON TRACK"
