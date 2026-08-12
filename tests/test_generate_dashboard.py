"""generate_dashboard.py tests: build_dashboard() is the extracted, reusable
core (main() is now a thin CLI wrapper around it) so telegram_bot.py's
/report can produce the same real dashboard on demand. yfinance is mocked
throughout -- no network in tests -- exercising the graceful-degrade paths
(fetch failure -> fall back to peak_price / skip the correlation panel)
rather than needing realistic OHLCV fixtures."""

import json

import pytest

import generate_dashboard as gd
from kala.papertrade import PaperTrader


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Every test in this file: yfinance always fails/empty, so histories
    degrade to {} and callers fall back to peak_price -- proves
    build_dashboard() doesn't need real network to produce a valid report."""
    monkeypatch.setattr(gd.yf, "download", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no net")))


def _empty_state(tmp_path, monkeypatch, config: dict | None = None):
    statefile = tmp_path / "paper_state.json"
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps(config or {"start_capital_idr": 10_000_000}))
    return str(statefile), str(cfgfile)


def test_build_dashboard_with_no_positions_degrades_cleanly(tmp_path, monkeypatch):
    state_path, config_path = _empty_state(tmp_path, monkeypatch)
    result = gd.build_dashboard(state_path, config_path, days=7)

    assert "html" in result and len(result["html"]) > 0
    assert result["n_positions"] == 0
    assert result["twr_result"] is not None
    assert result["drift_rows"] == []
    assert result["total_dividends"] == 0.0


def test_build_dashboard_reports_total_dividends(tmp_path, monkeypatch):
    state_path, config_path = _empty_state(tmp_path, monkeypatch)
    pt = PaperTrader.load(state_path, start_capital=10_000_000)
    pt.record_dividend("ANTM.JK", 50_000)
    pt.record_dividend("BBCA.JK", 25_000)

    result = gd.build_dashboard(state_path, config_path, days=7)
    assert result["total_dividends"] == pytest.approx(75_000)


def test_build_dashboard_with_open_position_uses_peak_price_fallback(tmp_path, monkeypatch):
    state_path, config_path = _empty_state(tmp_path, monkeypatch)
    pt = PaperTrader.load(state_path, start_capital=10_000_000)
    pt.manual_buy("ANTM.JK", 100, 1500.0)

    result = gd.build_dashboard(state_path, config_path, days=7)

    assert result["n_positions"] == 1
    assert "ANTM" in result["html"]
    # summary computed off SOME price for ANTM (peak_price fallback since
    # yfinance is mocked to fail) -- proves it didn't just crash/omit it.
    assert result["summary"]["equity"] > 0


def test_build_dashboard_respects_configured_target_allocation(tmp_path, monkeypatch):
    state_path, config_path = _empty_state(tmp_path, monkeypatch, config={
        "start_capital_idr": 10_000_000,
        "target_allocation": {"ANTM.JK": 50.0, "BBCA.JK": 50.0},
    })
    pt = PaperTrader.load(state_path, start_capital=10_000_000)
    pt.manual_buy("ANTM.JK", 100, 1500.0)

    result = gd.build_dashboard(state_path, config_path, days=7)

    # ANTM is 100% of actual holdings but only 50% target -> should show up
    # as drift (OVER), and BBCA (targeted, unheld) as fully under-target.
    tickers_in_drift = {row["ticker"] for row in result["drift_rows"]}
    assert "ANTM.JK" in tickers_in_drift
    assert "BBCA.JK" in tickers_in_drift


def test_main_writes_html_file(tmp_path, monkeypatch):
    state_path, config_path = _empty_state(tmp_path, monkeypatch)
    out_path = tmp_path / "out.html"
    monkeypatch.setattr("sys.argv", ["generate_dashboard.py", "--state", state_path,
                                     "--config", config_path, "--out", str(out_path)])
    rc = gd.main()
    assert rc == 0
    assert out_path.exists()
    assert len(out_path.read_text()) > 0
