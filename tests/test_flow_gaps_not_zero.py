"""A broker-flow day we failed to fetch is not a zero-flow day.

Two halves of one defect:

  * invezgo_fetch retried only 429. A 5xx or timeout escaped, the per-day
    handler logged and skipped it, and the day vanished. covered_range only
    checks the first and last stored date, so a hole-riddled archive reports
    as fully covered and get_or_fetch never re-fetches it.
  * strategy_foreign_flow summed missing days as 0 and published the result
    whenever the window held >= 1 real observation — four fabricated zeros and
    one real day produced a number indistinguishable from five measured days.
"""

import numpy as np
import pandas as pd
import pytest
import requests

from kala import invezgo_fetch as ivz
from kala.invezgo_fetch import InvezgoClient
from kala.strategy_foreign_flow import (
    CUM_WINDOW,
    FLOW_COLUMN,
    MIN_WINDOW_OBS,
    compute_features_foreign_flow,
    score_foreign_flow,
)


def _ohlcv(n):
    idx = pd.bdate_range("2025-01-01", periods=n)
    return pd.DataFrame({"Open": 1000.0, "High": 1010.0, "Low": 990.0,
                         "Close": 1000.0, "Volume": 1e6}, index=idx)


# ---------------- the fetcher must not lose days to transient faults --------

class _Resp:
    def __init__(self, status, payload=None):
        self.status_code = status
        self.headers = {}
        self._payload = payload if payload is not None else []

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))

    def json(self):
        return self._payload


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_transient_5xx_is_retried_not_lost(monkeypatch, status):
    calls = []

    def fake_get(*a, **k):
        calls.append(1)
        return _Resp(status) if len(calls) == 1 else _Resp(200, [{"net_value": "5"}])

    monkeypatch.setattr(ivz.requests, "get", fake_get)
    monkeypatch.setattr(ivz.time, "sleep", lambda s: None)

    got = InvezgoClient(token="t").broker_summary("BBCA", "2025-01-02", "2025-01-02")
    assert len(calls) == 2, f"{status} was not retried — that day becomes a silent gap"
    assert got == [{"net_value": "5"}]


@pytest.mark.parametrize("exc", [requests.Timeout, requests.ConnectionError])
def test_transient_network_error_is_retried(monkeypatch, exc):
    calls = []

    def fake_get(*a, **k):
        calls.append(1)
        if len(calls) == 1:
            raise exc("boom")
        return _Resp(200, [{"net_value": "5"}])

    monkeypatch.setattr(ivz.requests, "get", fake_get)
    monkeypatch.setattr(ivz.time, "sleep", lambda s: None)

    assert InvezgoClient(token="t").broker_summary("BBCA", "2025-01-02", "2025-01-02")
    assert len(calls) == 2


def test_429_behavior_is_unchanged(monkeypatch):
    calls = []

    def fake_get(*a, **k):
        calls.append(1)
        r = _Resp(429) if len(calls) == 1 else _Resp(200, [{"net_value": "1"}])
        if len(calls) == 1:
            r.headers = {"Retry-After": "7"}
        return r

    sleeps = []
    monkeypatch.setattr(ivz.requests, "get", fake_get)
    monkeypatch.setattr(ivz.time, "sleep", lambda s: sleeps.append(s))

    InvezgoClient(token="t").broker_summary("BBCA", "2025-01-02", "2025-01-02")
    assert sleeps == [7.0]      # Retry-After still wins


def test_persistent_failure_still_raises(monkeypatch):
    monkeypatch.setattr(ivz.requests, "get", lambda *a, **k: _Resp(500))
    monkeypatch.setattr(ivz.time, "sleep", lambda s: None)
    with pytest.raises(requests.HTTPError):
        InvezgoClient(token="t", max_retries=2).broker_summary("B", "2025-01-02", "2025-01-02")


def test_lost_days_are_reported(monkeypatch, capsys):
    """A holey backfill must not read as a clean one."""
    monkeypatch.setattr(InvezgoClient, "broker_summary",
                        lambda self, code, f, t, **k:
                            [] if f == "2025-01-02" else
                            (_ for _ in ()).throw(RuntimeError("boom"))
                            if f == "2025-01-03" else [{"net_value": "5"}])
    ivz.fetch_daily_foreign_net("AAA.JK", "2025-01-01", "2025-01-08",
                                client=InvezgoClient(token="t"))
    assert "GAPS, not zero-flow days" in capsys.readouterr().out


# ---------------- the strategy must not score a mostly-fabricated window ----

def test_sparse_window_does_not_publish_a_number():
    df = _ohlcv(40)
    flow = np.full(40, 5e9)
    holey = pd.Series(flow, index=df.index)
    holey.iloc[10:] = np.nan
    holey.iloc[14] = 5e9          # exactly ONE real observation in that window
    df[FLOW_COLUMN] = holey

    feats = compute_features_foreign_flow(df)
    assert pd.isna(feats["flow_cum"].iloc[14]), (
        "a window with 1 real day and 4 fabricated zeros published a number")
    assert pd.isna(score_foreign_flow(feats).iloc[14])


def test_window_at_the_coverage_floor_still_scores():
    df = _ohlcv(40)
    s = pd.Series(np.full(40, 5e9), index=df.index)
    s.iloc[20] = np.nan
    s.iloc[22] = np.nan           # 3 of 5 real -> at the floor, still usable
    df[FLOW_COLUMN] = s
    feats = compute_features_foreign_flow(df)
    assert not pd.isna(feats["flow_cum"].iloc[24])


def test_fully_covered_data_is_unaffected():
    """The floor must be a no-op on complete archives."""
    df = _ohlcv(60)
    rng = np.random.default_rng(0)
    df[FLOW_COLUMN] = np.concatenate([rng.normal(0, 1e6, 45), np.full(15, 5e8)])
    feats = compute_features_foreign_flow(df)
    assert feats["flow_cum"].iloc[CUM_WINDOW:].notna().all()
    assert score_foreign_flow(feats).iloc[-1] > 0


def test_gaps_do_not_systematically_understate_flow():
    """The reproduction, stated as the property that actually broke.

    Summing a window with missing days filled as 0 shrinks the total in
    proportion to how much is missing. flow_z then compares that against a
    20-day norm built mostly from fully-covered windows, so a COVERAGE
    artefact is read as a change in FLOW. Measured on a 40%-holey series the
    old estimator came in at 0.61x the true cumulative flow; the estimate must
    be unbiased instead.
    """
    n = 400
    idx = pd.bdate_range("2024-01-01", periods=n)
    rng = np.random.default_rng(7)
    truth = pd.Series(rng.normal(5e9, 5e8, n), index=idx)

    holey = truth.copy()
    holey.iloc[sorted(rng.choice(n, size=int(n * 0.4), replace=False))] = np.nan

    df = _ohlcv(n); df[FLOW_COLUMN] = holey.values
    est = compute_features_foreign_flow(df)["flow_cum"]

    truth_df = _ohlcv(n); truth_df[FLOW_COLUMN] = truth.values
    ref = compute_features_foreign_flow(truth_df)["flow_cum"]

    both = est.notna() & ref.notna()
    assert both.sum() > 100, "too few comparable bars to judge"
    ratio = (est[both] / ref[both]).mean()
    assert 0.95 <= ratio <= 1.05, (
        f"cumulative flow is biased at {ratio:.3f}x the truth on a holey archive")


def test_a_real_surge_is_still_detected_through_gaps():
    """Withholding thin windows must not cost us the signal itself."""
    n = 80
    rng = np.random.default_rng(3)
    flow = np.concatenate([rng.normal(0, 1e6, 55), np.full(25, 5e8)])
    holey = pd.Series(flow)
    holey.iloc[sorted(rng.choice(n, size=int(n * 0.3), replace=False))] = np.nan

    df = _ohlcv(n); df[FLOW_COLUMN] = holey.values
    score = score_foreign_flow(compute_features_foreign_flow(df))
    assert score.iloc[55:].max() > 60, "the surge stopped being detectable"


def test_min_window_obs_is_a_real_floor():
    assert 1 < MIN_WINDOW_OBS <= CUM_WINDOW
