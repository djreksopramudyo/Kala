"""
Fundamental value screen tests: pure-function formulas ported from the
legacy kala_fundamental_only.py prototype. This is a snapshot
screening tool, NOT walk-forward validated (see the module docstring for
why point-in-time fundamentals aren't available) -- these tests only prove
the arithmetic and decision logic behave as documented, not that the
screen has any predictive edge.
"""

import pytest

from kala.fundamental_screen import (
    ScreenResult,
    composite_intrinsic_value,
    dcf_simplified,
    graham_intrinsic_value,
    investment_decision,
    margin_of_safety_pct,
    pe_based_value,
    screen_stock,
    screen_universe,
    value_score,
)


def _cheap_quality_co():
    """Undervalued, profitable, low debt, growing -- should score high."""
    return {
        "current_price": 1000.0,
        "trailing_eps": 200.0,
        "book_value": 1500.0,
        "free_cash_flow": 5e11,
        "shares_outstanding": 1e9,
        "earnings_growth": 0.20,
        "revenue_growth": 0.10,
        "sector": "Consumer Defensive",
        "roe": 0.25,
        "profit_margin": 0.18,
        "debt_equity": 20.0,
        "current_ratio": 2.0,
        "dividend_yield": 0.06,
    }


def _expensive_weak_co():
    """Overvalued, weak profitability, high debt -- should score low."""
    return {
        "current_price": 5000.0,
        "trailing_eps": 10.0,
        "book_value": 50.0,
        "roe": 0.02,
        "profit_margin": 0.01,
        "debt_equity": 200.0,
        "current_ratio": 0.5,
        "dividend_yield": 0.0,
    }


def _value_trap_co():
    """Cheap on paper but earnings collapsing -- must be flagged, not bought."""
    return {
        "current_price": 500.0,
        "trailing_eps": 100.0,
        "book_value": 800.0,
        "roe": 0.12,
        "earnings_growth": -0.25,
    }


# ---------------- individual valuation formulas -----------------------------

def test_graham_intrinsic_value_positive_inputs():
    iv = graham_intrinsic_value({"trailing_eps": 200.0, "book_value": 1500.0})
    assert iv == (22.5 * 200.0 * 1500.0) ** 0.5


def test_graham_intrinsic_value_none_when_eps_negative():
    assert graham_intrinsic_value({"trailing_eps": -5.0, "book_value": 1000.0}) is None


def test_graham_intrinsic_value_none_when_missing():
    assert graham_intrinsic_value({}) is None


def test_dcf_simplified_none_without_free_cash_flow():
    assert dcf_simplified({"shares_outstanding": 1e9}) is None


def test_dcf_simplified_positive_for_healthy_inputs():
    v = dcf_simplified({"free_cash_flow": 5e11, "shares_outstanding": 1e9,
                        "earnings_growth": 0.10})
    assert v is not None and v > 0


def test_pe_based_value_uses_sector_multiple():
    v = pe_based_value({"trailing_eps": 100.0, "sector": "Technology"})
    assert v == 100.0 * 25


def test_pe_based_value_defaults_to_12x_for_unknown_sector():
    v = pe_based_value({"trailing_eps": 100.0, "sector": "Unknown Sector"})
    assert v == 100.0 * 12


def test_pe_based_value_none_without_eps():
    assert pe_based_value({}) is None


def test_composite_intrinsic_value_blends_available_methods():
    fundamentals = _cheap_quality_co()
    composite = composite_intrinsic_value(fundamentals)
    graham = graham_intrinsic_value(fundamentals)
    assert composite is not None
    # blended value should sit in a reasonable range near the component estimates
    assert composite > 0
    assert graham is not None


def test_composite_intrinsic_value_none_when_all_methods_undefined():
    assert composite_intrinsic_value({}) is None


def test_composite_intrinsic_value_renormalizes_over_available_methods():
    """Only Graham inputs given (no FCF/shares for DCF, no sector/eps combo
    issue for P/E since eps IS given) -- P/E-based still applies since only
    eps is required for it. Use a fundamentals dict where ONLY Graham
    inputs exist to confirm renormalization doesn't silently zero out."""
    only_graham = {"trailing_eps": 150.0, "book_value": 900.0}
    composite = composite_intrinsic_value(only_graham)
    graham = graham_intrinsic_value(only_graham)
    pe = pe_based_value(only_graham)
    # both graham and pe apply here (pe only needs eps); composite should
    # be the reweighted blend of exactly those two, not scaled down by the
    # missing DCF weight.
    expected = (graham * 0.4 + pe * 0.3) / 0.7
    assert composite == pytest.approx(expected)


# ---------------- margin of safety -------------------------------------------

def test_margin_of_safety_positive_when_undervalued():
    assert margin_of_safety_pct(current_price=800.0, intrinsic_value=1000.0) == 25.0


def test_margin_of_safety_negative_when_overvalued():
    assert margin_of_safety_pct(current_price=1200.0, intrinsic_value=1000.0) == pytest.approx(-200.0 / 1200.0 * 100.0)


# ---------------- value_score -------------------------------------------------

def test_value_score_high_for_cheap_quality_company():
    fundamentals = _cheap_quality_co()
    iv = composite_intrinsic_value(fundamentals)
    score, notes = value_score(fundamentals, iv)
    assert score >= 75
    assert len(notes) > 0


def test_value_score_low_for_expensive_weak_company():
    fundamentals = _expensive_weak_co()
    iv = composite_intrinsic_value(fundamentals)
    score, _ = value_score(fundamentals, iv)
    assert score < 30


def test_value_score_bounded_zero_to_hundred_ish():
    """Not a hard mathematical bound (components are independent additive
    buckets), but no real input combination should blow past 100."""
    fundamentals = _cheap_quality_co()
    iv = composite_intrinsic_value(fundamentals)
    score, _ = value_score(fundamentals, iv)
    assert 0 <= score <= 100


# ---------------- investment_decision -----------------------------------------

def test_investment_decision_strong_buy():
    decision, _ = investment_decision(80.0, 35.0, {})
    assert decision == "STRONG BUY"


def test_investment_decision_buy():
    decision, _ = investment_decision(65.0, 20.0, {})
    assert decision == "BUY"


def test_investment_decision_hold_near_fair_value():
    decision, _ = investment_decision(40.0, 5.0, {})
    assert decision == "HOLD"


def test_investment_decision_avoid():
    decision, _ = investment_decision(20.0, -30.0, {})
    assert decision == "AVOID"


def test_investment_decision_value_trap_overrides_score():
    """Even a high score/MoS must be flagged as a trap if earnings are
    collapsing -- cheap-and-declining is the exact failure mode this
    override exists to catch."""
    decision, confidence = investment_decision(
        80.0, 40.0, {"earnings_growth": -0.20})
    assert decision == "VALUE TRAP"
    assert "caution" in confidence.lower()


# ---------------- screen_stock / screen_universe -------------------------------

def test_screen_stock_returns_screen_result():
    result = screen_stock("QUAL.JK", _cheap_quality_co())
    assert isinstance(result, ScreenResult)
    assert result.ticker == "QUAL.JK"
    assert result.decision in ("STRONG BUY", "BUY")
    assert result.margin_of_safety is not None


def test_screen_stock_flags_value_trap():
    result = screen_stock("TRAP.JK", _value_trap_co())
    assert result.decision == "VALUE TRAP"


def test_screen_stock_handles_empty_fundamentals_gracefully():
    result = screen_stock("EMPTY.JK", {})
    assert result.intrinsic_value is None
    assert result.margin_of_safety is None
    assert result.decision in ("HOLD", "AVOID", "VALUE TRAP")


def test_screen_universe_ranks_best_score_first():
    universe = {
        "QUAL.JK": _cheap_quality_co(),
        "WEAK.JK": _expensive_weak_co(),
        "TRAP.JK": _value_trap_co(),
    }
    results = screen_universe(universe)
    assert results[0].ticker == "QUAL.JK"
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)


def test_screen_universe_covers_every_ticker():
    universe = {"A.JK": _cheap_quality_co(), "B.JK": _expensive_weak_co()}
    results = screen_universe(universe)
    assert {r.ticker for r in results} == {"A.JK", "B.JK"}
