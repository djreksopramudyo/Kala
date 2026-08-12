"""Portfolio analytics tests: concentration (HHI/effective-N), pairwise
correlation, sector rollup, and the bundled analyze_portfolio() report."""

import numpy as np
import pandas as pd
import pytest

from kala.portfolio_analytics import (
    PortfolioAnalysis,
    allocation_drift,
    analyze_portfolio,
    correlation_matrix,
    effective_n_positions,
    herfindahl_index,
    high_correlation_pairs,
    position_weights,
    positions_vs_benchmark,
    sector_weights,
)


def _price_series(n=100, seed=0, drift=0.0005, level=1000.0):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2024-01-02", periods=n)
    close = level * np.exp(np.cumsum(rng.normal(drift, 0.01, n)))
    return pd.Series(close, index=idx)


# ---------------- position_weights --------------------------------------------

def test_position_weights_sum_to_100():
    shares = {"A.JK": 100, "B.JK": 200}
    prices = {"A.JK": 1000.0, "B.JK": 500.0}
    weights = position_weights(shares, prices)
    assert sum(weights.values()) == pytest.approx(100.0)
    assert weights["A.JK"] == pytest.approx(50.0)   # 100k vs 100k -> 50/50
    assert weights["B.JK"] == pytest.approx(50.0)


def test_position_weights_skips_unpriced_tickers():
    shares = {"A.JK": 100, "B.JK": 200}
    prices = {"A.JK": 1000.0}   # B has no price
    weights = position_weights(shares, prices)
    assert set(weights) == {"A.JK"}
    assert weights["A.JK"] == pytest.approx(100.0)


def test_position_weights_empty_when_no_prices():
    assert position_weights({"A.JK": 100}, {}) == {}


# ---------------- herfindahl_index / effective_n_positions --------------------

def test_hhi_single_position_is_one():
    assert herfindahl_index({"A.JK": 100.0}) == pytest.approx(1.0)


def test_hhi_equal_five_way_split():
    weights = {f"T{i}.JK": 20.0 for i in range(5)}
    assert herfindahl_index(weights) == pytest.approx(0.20)
    assert effective_n_positions(weights) == pytest.approx(5.0)


def test_hhi_skewed_book_has_lower_effective_n_than_nominal_count():
    weights = {"BIG.JK": 60.0, "B.JK": 10.0, "C.JK": 10.0, "D.JK": 10.0, "E.JK": 10.0}
    eff_n = effective_n_positions(weights)
    assert eff_n < 5.0


def test_hhi_empty_is_zero():
    assert herfindahl_index({}) == 0.0
    assert effective_n_positions({}) == 0.0


# ---------------- correlation_matrix / high_correlation_pairs -----------------

def test_correlation_matrix_identical_series_is_perfectly_correlated():
    s = _price_series(n=100, seed=1)
    corr = correlation_matrix({"A.JK": s, "B.JK": s.copy()})
    assert corr.loc["A.JK", "B.JK"] == pytest.approx(1.0, abs=1e-9)


def test_correlation_matrix_too_few_tickers_is_empty():
    s = _price_series(n=100)
    assert correlation_matrix({"A.JK": s}).empty


def test_correlation_matrix_too_little_overlap_is_empty():
    a = _price_series(n=100, seed=1)
    b = _price_series(n=100, seed=2)
    b.index = pd.bdate_range("2030-01-02", periods=100)   # no overlapping dates at all
    assert correlation_matrix({"A.JK": a, "B.JK": b}).empty


def test_high_correlation_pairs_finds_identical_series():
    s = _price_series(n=100, seed=1)
    corr = correlation_matrix({"A.JK": s, "B.JK": s.copy(), "C.JK": _price_series(n=100, seed=99)})
    pairs = high_correlation_pairs(corr, threshold=0.9)
    assert any({a, b} == {"A.JK", "B.JK"} for a, b, _ in pairs)


def test_high_correlation_pairs_empty_below_threshold():
    corr = correlation_matrix({"A.JK": _price_series(seed=1), "B.JK": _price_series(seed=2)})
    pairs = high_correlation_pairs(corr, threshold=0.9999)
    assert pairs == [] or all(abs(c) >= 0.9999 for _, _, c in pairs)


# ---------------- sector_weights -----------------------------------------------

def test_sector_weights_rolls_up_correctly():
    weights = {"BBCA.JK": 30.0, "BMRI.JK": 20.0, "TLKM.JK": 50.0}
    sectors = {"BBCA.JK": "Financial Services", "BMRI.JK": "Financial Services",
              "TLKM.JK": "Communication Services"}
    rolled = sector_weights(weights, sectors)
    assert rolled["Financial Services"] == pytest.approx(50.0)
    assert rolled["Communication Services"] == pytest.approx(50.0)


def test_sector_weights_unmapped_ticker_goes_to_unknown():
    rolled = sector_weights({"X.JK": 100.0}, {})
    assert rolled["UNKNOWN"] == pytest.approx(100.0)


# ---------------- analyze_portfolio (bundled report) ---------------------------

def test_analyze_portfolio_returns_full_report():
    shares = {"A.JK": 100, "B.JK": 100}
    prices = {"A.JK": 1000.0, "B.JK": 1000.0}
    s = _price_series(n=100, seed=1)
    histories = {"A.JK": s, "B.JK": s.copy()}
    result = analyze_portfolio(shares, prices, price_histories=histories,
                               sector_map={"A.JK": "Banks", "B.JK": "Banks"})
    assert isinstance(result, PortfolioAnalysis)
    assert result.weights_pct
    assert result.hhi > 0
    assert result.sector_weights_pct["Banks"] == pytest.approx(100.0)
    assert len(result.high_corr_pairs) >= 1


def test_analyze_portfolio_no_histories_skips_correlation():
    shares = {"A.JK": 100}
    prices = {"A.JK": 1000.0}
    result = analyze_portfolio(shares, prices)
    assert result.high_corr_pairs == []


def test_summary_text_no_positions():
    result = PortfolioAnalysis()
    assert "No priced open positions" in result.summary_text()


def test_summary_text_includes_key_sections():
    shares = {"A.JK": 100, "B.JK": 100}
    prices = {"A.JK": 1000.0, "B.JK": 1000.0}
    s = _price_series(n=100, seed=1)
    result = analyze_portfolio(shares, prices, price_histories={"A.JK": s, "B.JK": s.copy()},
                               sector_map={"A.JK": "Banks", "B.JK": "Banks"})
    text = result.summary_text()
    assert "PORTFOLIO CONCENTRATION" in text
    assert "HHI" in text
    assert "By sector" in text


# ---------------- positions_vs_benchmark ----------------------------------------

class _FakePos:
    def __init__(self, entry_price, entry_date, shares=100, peak_price=None):
        self.entry_price = entry_price
        self.entry_date = entry_date
        self.shares = shares
        self.peak_price = peak_price if peak_price is not None else entry_price


def _benchmark_series(n=100, start="2026-01-02", level=1000.0, drift=0.0005):
    idx = pd.bdate_range(start, periods=n)
    close = level * np.exp(np.cumsum(np.full(n, drift)))
    return pd.Series(close, index=idx)


def test_positions_vs_benchmark_computes_return_and_alpha():
    bench = _benchmark_series(n=100)
    entry_date = bench.index[10].date().isoformat()
    positions = {"A.JK": _FakePos(entry_price=1000.0, entry_date=entry_date)}
    current_prices = {"A.JK": 1200.0}   # +20% since entry

    rows = positions_vs_benchmark(positions, current_prices, bench)
    assert len(rows) == 1
    r = rows[0]
    assert r["ticker"] == "A.JK"
    assert r["return_pct"] == pytest.approx(20.0)
    assert r["benchmark_return_pct"] is not None
    assert r["alpha_pct"] == pytest.approx(r["return_pct"] - r["benchmark_return_pct"])


def test_positions_vs_benchmark_missing_price_gives_none_return():
    bench = _benchmark_series(n=50)
    entry_date = bench.index[5].date().isoformat()
    positions = {"A.JK": _FakePos(entry_price=1000.0, entry_date=entry_date)}
    rows = positions_vs_benchmark(positions, {}, bench)
    assert rows[0]["return_pct"] is None
    assert rows[0]["alpha_pct"] is None


def test_positions_vs_benchmark_entry_before_benchmark_history_gives_none_alpha():
    bench = _benchmark_series(n=50, start="2026-03-01")
    positions = {"A.JK": _FakePos(entry_price=1000.0, entry_date="2020-01-06")}
    rows = positions_vs_benchmark(positions, {"A.JK": 1100.0}, bench)
    assert rows[0]["return_pct"] == pytest.approx(10.0)
    assert rows[0]["benchmark_return_pct"] is None
    assert rows[0]["alpha_pct"] is None


def test_positions_vs_benchmark_empty_positions():
    bench = _benchmark_series(n=20)
    assert positions_vs_benchmark({}, {}, bench) == []


def test_positions_vs_benchmark_sorted_by_ticker():
    bench = _benchmark_series(n=50)
    entry_date = bench.index[5].date().isoformat()
    positions = {
        "Z.JK": _FakePos(1000.0, entry_date),
        "A.JK": _FakePos(1000.0, entry_date),
    }
    rows = positions_vs_benchmark(positions, {"Z.JK": 1100.0, "A.JK": 1100.0}, bench)
    assert [r["ticker"] for r in rows] == ["A.JK", "Z.JK"]


def test_positions_vs_benchmark_beats_index_when_alpha_positive():
    """Sanity check the sign convention: a stock up 20% while the index is
    only up ~a few percent must show POSITIVE alpha."""
    bench = _benchmark_series(n=50, drift=0.0002)   # mild benchmark drift
    entry_date = bench.index[5].date().isoformat()
    positions = {"A.JK": _FakePos(entry_price=1000.0, entry_date=entry_date)}
    rows = positions_vs_benchmark(positions, {"A.JK": 1200.0}, bench)
    assert rows[0]["alpha_pct"] > 0


# ---------------- allocation_drift -----------------------------------------------

def test_allocation_drift_on_target_within_threshold():
    rows = allocation_drift({"A.JK": 32.0}, {"A.JK": 30.0}, threshold_pp=5.0)
    assert rows[0]["flag"] == "ON TARGET"
    assert rows[0]["drift_pp"] == pytest.approx(2.0)


def test_allocation_drift_flags_over():
    rows = allocation_drift({"A.JK": 45.0}, {"A.JK": 30.0}, threshold_pp=5.0)
    assert rows[0]["flag"] == "OVER"
    assert rows[0]["drift_pp"] == pytest.approx(15.0)


def test_allocation_drift_flags_under():
    rows = allocation_drift({"A.JK": 10.0}, {"A.JK": 30.0}, threshold_pp=5.0)
    assert rows[0]["flag"] == "UNDER"
    assert rows[0]["drift_pp"] == pytest.approx(-20.0)


def test_allocation_drift_held_but_no_target_reads_as_fully_over():
    rows = allocation_drift({"X.JK": 25.0}, {}, threshold_pp=5.0)
    assert rows[0]["target_pct"] == 0.0
    assert rows[0]["flag"] == "OVER"


def test_allocation_drift_targeted_but_not_held_reads_as_fully_under():
    rows = allocation_drift({}, {"Y.JK": 20.0}, threshold_pp=5.0)
    assert rows[0]["actual_pct"] == 0.0
    assert rows[0]["flag"] == "UNDER"


def test_allocation_drift_sorted_by_absolute_drift_descending():
    rows = allocation_drift(
        {"SMALL.JK": 12.0, "BIG.JK": 50.0}, {"SMALL.JK": 10.0, "BIG.JK": 10.0})
    assert rows[0]["ticker"] == "BIG.JK"


def test_allocation_drift_empty_inputs():
    assert allocation_drift({}, {}) == []
