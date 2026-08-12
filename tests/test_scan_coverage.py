"""A scan that saw nothing must not read as "the market offered nothing".

live_trading_dashboard() used to `return` (None) when every download failed.
daily_run collects it as `... or []`, so a total data outage arrived as an
empty BUY list with NO stage error — and the daily message said "No new
orders for tomorrow", which is what a genuinely quiet market looks like.

Two states were indistinguishable in the output:
  * the market offered nothing
  * the scanner never ran

Total failure now raises into stage()'s error list. The partial case — a
short but plausible-looking BUY list drawn from a fraction of the watchlist
— is covered by degraded_scan_warning().
"""

import pytest

import daily_run
import kala_daily_trader as dt


def test_total_download_failure_raises_instead_of_returning_none(monkeypatch):
    """The regression. `return None` was swallowed by `or []` upstream."""
    monkeypatch.setattr(dt, "batch_download_prices", lambda w: {})
    monkeypatch.setattr(dt, "check_market_health", lambda: {"status": "UNKNOWN"})

    with pytest.raises(RuntimeError) as exc:
        dt.live_trading_dashboard()

    msg = str(exc.value)
    assert "no usable data" in msg
    # must say what it is NOT, since that is the whole point
    assert "not 'no opportunities today'" in msg.lower()


def test_stage_records_the_failure_so_the_message_shows_it(monkeypatch):
    monkeypatch.setattr(dt, "batch_download_prices", lambda w: {})
    monkeypatch.setattr(dt, "check_market_health", lambda: {"status": "UNKNOWN"})

    errors = []
    signals = daily_run.stage("buy_scan", dt.live_trading_dashboard, errors) or []

    assert signals == []
    assert errors, "a total data outage must reach the daily message"
    assert "buy_scan" in errors[0]


# ------------------------------------------------------- partial degradation

def test_warns_when_coverage_is_below_the_floor():
    cov = {"attempted": 600, "analysed": 60, "no_data": 540, "coverage_pct": 10.0}
    warning = daily_run.degraded_scan_warning(cov, min_pct=50.0)

    assert warning is not None
    assert "60/600" in warning
    assert "not evidence" in warning


def test_silent_when_coverage_is_healthy():
    """Must not cry wolf on every run — a few dead tickers is normal."""
    cov = {"attempted": 600, "analysed": 580, "no_data": 20, "coverage_pct": 96.7}
    assert daily_run.degraded_scan_warning(cov, min_pct=50.0) is None


def test_boundary_is_not_a_warning():
    cov = {"attempted": 100, "analysed": 50, "no_data": 50, "coverage_pct": 50.0}
    assert daily_run.degraded_scan_warning(cov, min_pct=50.0) is None


@pytest.mark.parametrize("cov", [None, {}, {"attempted": 10}])
def test_missing_coverage_data_is_not_a_warning(cov):
    """An older scan, or one that never set the field, must not produce a
    scary message on no information."""
    assert daily_run.degraded_scan_warning(cov) is None


def test_coverage_is_recorded_after_a_successful_scan(monkeypatch):
    """The field daily_run reads must actually be populated, or the partial
    check silently never fires."""
    import numpy as np
    import pandas as pd

    # Must look like a LIVE stock: flat prices and constant volume trip the
    # suspension detector, the signal is dropped, and the scan then raises
    # for having found nothing — which is not what this test is about.
    n = 90
    rng = np.random.default_rng(1)
    close = 1000 * np.exp(np.cumsum(rng.normal(0.001, 0.012, n)))
    idx = pd.bdate_range("2025-01-01", periods=n)
    frame = pd.DataFrame({"Open": close * 0.999, "High": close * 1.01,
                          "Low": close * 0.99, "Close": close,
                          "Volume": rng.integers(2e6, 8e6, n).astype(float)},
                         index=idx)

    monkeypatch.setattr(dt, "WATCHLIST", ["AAA.JK", "BBB.JK"])
    monkeypatch.setattr(dt, "batch_download_prices", lambda w: {"AAA.JK": frame})
    monkeypatch.setattr(dt, "check_market_health", lambda: {"status": "NEUTRAL"})
    monkeypatch.setattr(dt, "LAST_SCAN_COVERAGE", None)

    dt.live_trading_dashboard()

    cov = dt.LAST_SCAN_COVERAGE
    assert cov is not None
    assert cov["attempted"] == 2
    assert cov["no_data"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
