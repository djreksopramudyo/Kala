"""Edge tracker tests — live-vs-backtest comparison must be honest about
small samples (TOO EARLY, never a false alarm) and use the same stats
definitions as the A/B script."""

import math

import pytest

from kala.edge import (
    DEFAULT_EXPECTATIONS,
    MIN_TRADES_FOR_VERDICT,
    edge_report,
    live_stats,
    merged_expectations,
    reason_bucket,
    t_vs_expected,
)


def _trade(pnl, reason="manual sell", entry_date=None, date="2026-07-10"):
    t = {"date": date, "ticker": "T.JK", "entry": 1000.0, "exit": 1000.0 * (1 + pnl / 100),
         "shares": 100, "pnl_pct": pnl, "reason": reason}
    if entry_date is not None:
        t["entry_date"] = entry_date
    return t


def _sym_returns(mean: float, d: float, n: int) -> list[float]:
    """n returns, half at mean+d and half at mean-d: exact mean, and an
    exactly computable sample std = d*sqrt(n/(n-1)) — so tests can place the
    t statistic precisely inside a verdict band instead of near an edge."""
    assert n % 2 == 0
    return [mean + d] * (n // 2) + [mean - d] * (n // 2)


def _se(d: float, n: int) -> float:
    return d * math.sqrt(n / (n - 1)) / math.sqrt(n)


def _validated_cfg(**extra_expectations) -> dict:
    """The comparison machinery (TOO EARLY/ON TRACK/WATCH/DIVERGING) only
    runs when edge_expectations.validated is True — the 2026-07-20 default
    is False (see edge.py's module docstring: the apparent >= IDR 1,000
    edge was retracted after a point-in-time re-test came back negative).
    Tests of that machinery opt back in explicitly."""
    return {"edge_expectations": {"validated": True, **extra_expectations}}


# ---------------- reason bucketing ----------------

@pytest.mark.parametrize("reason,bucket", [
    ("manual sell", "manual"),
    ("target profit reached (+8.4%)", "take-profit"),
    ("governing stop hit: 940 <= 950 (trail, phase 3)", "stop"),
    ("[CONSIDER] max holding period (21 bars >= 20)", "max-hold"),
    ("DEATH CROSS today (fast crossed below slow)", "death-cross"),
    ("something unrecognisable", "other"),
    ("", "other"),
])
def test_reason_bucket(reason, bucket):
    assert reason_bucket(reason) == bucket


# ---------------- expectations merge ----------------

def test_merged_expectations_defaults_and_partial_override():
    assert merged_expectations(None) == DEFAULT_EXPECTATIONS
    m = merged_expectations({"edge_expectations": {"ev_pct": 0.5}})
    assert m["ev_pct"] == 0.5
    assert m["avg_hold_days"] == DEFAULT_EXPECTATIONS["avg_hold_days"]  # kept


def test_merged_expectations_ignores_unknown_keys():
    m = merged_expectations({"edge_expectations": {"made_up_metric": 99}})
    assert "made_up_metric" not in m


# ---------------- live stats ----------------

def test_live_stats_hold_days_only_from_entries_that_have_entry_date():
    log = [_trade(1.0, entry_date="2026-07-01", date="2026-07-11"),   # 10 days
           _trade(2.0)]                                               # legacy: no entry_date
    s = live_stats(log)
    assert s["n"] == 2
    assert s["n_with_hold"] == 1
    assert s["avg_hold_days"] == pytest.approx(10.0)


def test_live_stats_no_hold_data_at_all():
    s = live_stats([_trade(1.0), _trade(-1.0)])
    assert s["avg_hold_days"] is None and s["n_with_hold"] == 0


def test_live_stats_reason_mix():
    log = [_trade(1.0, reason="manual sell"),
           _trade(2.0, reason="target profit reached (+8%)"),
           _trade(-3.0, reason="governing stop hit: x")]
    s = live_stats(log)
    assert s["reasons"] == {"manual": 1, "take-profit": 1, "stop": 1}


# ---------------- t statistic ----------------

def test_t_vs_expected_none_when_uncomputable():
    assert t_vs_expected(1.0, 0.0, 12, 0.38) is None    # zero variance
    assert t_vs_expected(1.0, 2.0, 1, 0.38) is None     # n < 2


def test_t_vs_expected_sign_and_magnitude():
    # mean 1.38 vs expected 0.38, std 2, n 16 -> t = 1.0 / (2/4) = 2.0
    assert t_vs_expected(1.38, 2.0, 16, 0.38) == pytest.approx(2.0)
    assert t_vs_expected(-0.62, 2.0, 16, 0.38) == pytest.approx(-2.0)


# ---------------- unvalidated status (the 2026-07-20 default, again) -------

def test_default_is_unvalidated_after_the_min_price_edge_retraction():
    assert DEFAULT_EXPECTATIONS["validated"] is False
    assert merged_expectations(None) == DEFAULT_EXPECTATIONS


def test_default_short_circuits_regardless_of_trade_count_or_fit():
    """validated=False must short-circuit to UNVALIDATED even for a log that
    would otherwise read as a perfect ON TRACK match -- the point is that no
    comparison against the expected numbers happens at all while unvalidated."""
    exp = DEFAULT_EXPECTATIONS["ev_pct"]
    log = [_trade(p) for p in _sym_returns(exp, d=2.0, n=30)]
    r = edge_report(log)   # no cfg -> DEFAULT_EXPECTATIONS -> validated=False
    assert r["verdict"] == "UNVALIDATED"
    assert r["t_vs_expected"] is None
    assert "validated is False" in r["verdict_reason"]
    assert r["live"]["n"] == 30   # live stats still computed, just not compared


def test_default_with_too_few_trades_still_says_unvalidated_not_too_early():
    r = edge_report([_trade(5.0), _trade(-2.0)])
    assert r["verdict"] == "UNVALIDATED"


def test_entry_signal_warning_present_by_default():
    from kala.edge import entry_signal_warning
    w = entry_signal_warning()
    assert w is not None and "UNVALIDATED" in w


def test_entry_signal_warning_none_when_validated_override():
    from kala.edge import entry_signal_warning
    assert entry_signal_warning(_validated_cfg()) is None


def test_entry_signal_warning_tied_to_same_flag_as_edge_report():
    """One flag, not two independent switches -- flipping validated must
    silence the banner AND unlock the comparison machinery together."""
    from kala.edge import entry_signal_warning
    cfg = _validated_cfg()
    assert entry_signal_warning(cfg) is None
    log = [_trade(p) for p in _sym_returns(DEFAULT_EXPECTATIONS["ev_pct"], d=2.0, n=16)]
    assert edge_report(log, cfg)["verdict"] != "UNVALIDATED"


# ---------------- verdicts (once validated=True) ----------------------------

def test_verdict_too_early_below_min_trades():
    log = [_trade(5.0), _trade(-2.0), _trade(1.0)]
    r = edge_report(log, _validated_cfg())
    assert r["verdict"] == "TOO EARLY"
    assert str(len(log)) in r["verdict_reason"]


def test_verdict_too_early_on_zero_variance():
    log = [_trade(5.0)] * (MIN_TRADES_FOR_VERDICT + 2)
    r = edge_report(log, _validated_cfg())
    assert r["verdict"] == "TOO EARLY"
    assert "spread" in r["verdict_reason"]


def test_verdict_on_track_when_live_matches_backtest():
    exp = DEFAULT_EXPECTATIONS["ev_pct"]
    log = [_trade(p) for p in _sym_returns(exp, d=2.0, n=16)]   # t = 0 exactly
    r = edge_report(log, _validated_cfg())
    assert r["verdict"] == "ON TRACK"
    assert r["t_vs_expected"] == pytest.approx(0.0)


def test_verdict_watch_when_drifting():
    exp = DEFAULT_EXPECTATIONS["ev_pct"]
    n, d = 16, 2.0
    log = [_trade(p) for p in _sym_returns(exp + 1.5 * _se(d, n), d=d, n=n)]
    r = edge_report(log, _validated_cfg())
    assert r["t_vs_expected"] == pytest.approx(1.5)
    assert r["verdict"] == "WATCH"


def test_verdict_diverging_when_live_is_significantly_worse():
    exp = DEFAULT_EXPECTATIONS["ev_pct"]
    n, d = 16, 2.0
    log = [_trade(p) for p in _sym_returns(exp - 3.0 * _se(d, n), d=d, n=n)]
    r = edge_report(log, _validated_cfg())
    assert r["t_vs_expected"] == pytest.approx(-3.0)
    assert r["verdict"] == "DIVERGING"
    assert "WORSE" in r["verdict_reason"]


def test_edge_report_uses_config_override():
    # live mean == 5.0; default expectation 0.38 would call this DIVERGING,
    # but overriding the expectation to 5.0 must flip it to ON TRACK
    log = [_trade(p) for p in _sym_returns(5.0, d=2.0, n=16)]
    r = edge_report(log, _validated_cfg(ev_pct=5.0))
    assert r["verdict"] == "ON TRACK"
