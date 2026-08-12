"""
Time-weighted return tests: chain-linking around deposit dates must
neutralize cash-flow distortion, unlike a naive (current_equity /
original_capital - 1) simple return.
"""

from datetime import date

import pytest

from kala.twr import TWRResult, compute_time_weighted_return


def test_no_trades_no_deposits_twr_is_zero():
    result = compute_time_weighted_return([], [], original_capital=10_000_000.0,
                                          current_equity=10_000_000.0)
    assert isinstance(result, TWRResult)
    assert result.twr_pct == pytest.approx(0.0)
    assert result.n_sub_periods == 1


def test_twr_matches_simple_return_with_no_deposits():
    """With no cash flows, TWR IS just the simple return -- sanity check
    the two methods agree in the trivial case."""
    log = [{"date": "2026-06-01", "entry": 1000.0, "exit": 1100.0, "shares": 100}]
    result = compute_time_weighted_return(log, [], original_capital=10_000_000.0,
                                          current_equity=10_100_000.0)
    assert result.twr_pct == pytest.approx(1.0)   # +100,000 on 10,000,000 = +1%


def test_twr_neutralizes_a_deposit_right_before_a_rally():
    """A deposit placed right before strong realized gains must NOT make
    TWR look inflated by the deposit's timing -- the deposit itself
    contributes 0% return, only what happens to money already at risk (or
    newly deployed) counts."""
    original_capital = 10_000_000.0
    # Account grows 10% before any deposit
    log_before = [{"date": "2026-05-01", "entry": 1000.0, "exit": 1100.0, "shares": 10_000}]
    # a large deposit on 2026-06-01
    deposits = [{"date": "2026-06-01", "amount": 50_000_000.0}]
    # then flat afterwards (no further gains)
    current_equity = original_capital + 1_000_000.0 + 50_000_000.0   # +10% then flat

    result = compute_time_weighted_return(log_before, deposits, original_capital,
                                          current_equity)
    # TWR should reflect ONLY the +10% pre-deposit move (second period flat)
    assert result.twr_pct == pytest.approx(10.0, abs=0.5)


def test_naive_simple_return_would_be_diluted_by_the_deposit_but_twr_is_not():
    original_capital = 10_000_000.0
    log_before = [{"date": "2026-05-01", "entry": 1000.0, "exit": 1100.0, "shares": 10_000}]
    deposits = [{"date": "2026-06-01", "amount": 50_000_000.0}]
    current_equity = original_capital + 1_000_000.0 + 50_000_000.0

    result = compute_time_weighted_return(log_before, deposits, original_capital, current_equity)

    # naive (current_equity / (original_capital + deposits)) - 1 massively
    # understates the true trading performance because the denominator
    # includes money that was never at risk during the winning trade
    naive_pct = (current_equity / (original_capital + 50_000_000.0) - 1.0) * 100.0
    assert result.twr_pct > naive_pct


def test_two_sub_periods_from_one_deposit():
    result = compute_time_weighted_return(
        log=[], capital_additions=[{"date": "2026-06-01", "amount": 1_000_000.0}],
        original_capital=10_000_000.0, current_equity=11_000_000.0)
    assert result.n_sub_periods == 2


def test_max_drawdown_is_negative_or_zero():
    log = [
        {"date": "2026-05-01", "entry": 1000.0, "exit": 1200.0, "shares": 100},  # +20,000
        {"date": "2026-05-15", "entry": 1000.0, "exit": 700.0, "shares": 100},   # -30,000
    ]
    result = compute_time_weighted_return(log, [], original_capital=1_000_000.0,
                                          current_equity=990_000.0)
    assert result.max_drawdown_pct <= 0.0
    assert result.max_drawdown_pct < -1.0   # a real drawdown occurred


def test_max_drawdown_zero_when_curve_only_rises():
    log = [{"date": "2026-05-01", "entry": 1000.0, "exit": 1100.0, "shares": 100}]
    result = compute_time_weighted_return(log, [], original_capital=1_000_000.0,
                                          current_equity=1_010_000.0)
    assert result.max_drawdown_pct == pytest.approx(0.0)


def test_cagr_none_without_account_start_date():
    result = compute_time_weighted_return([], [], 10_000_000.0, 11_000_000.0)
    assert result.cagr_pct is None


def test_cagr_computed_with_account_start_date():
    result = compute_time_weighted_return(
        [], [], original_capital=10_000_000.0, current_equity=12_100_000.0,
        account_start_date="2025-07-21", today=date(2026, 7, 21))
    # +21% over exactly 1 year -> CAGR ~= TWR for a 1-year window
    assert result.cagr_pct == pytest.approx(21.0, abs=0.5)


def test_cagr_annualizes_correctly_for_shorter_window():
    """A doubling in 6 months annualizes to well above 100%."""
    result = compute_time_weighted_return(
        [], [], original_capital=10_000_000.0, current_equity=20_000_000.0,
        account_start_date="2026-01-21", today=date(2026, 7, 21))
    assert result.cagr_pct > 100.0


def test_cagr_none_for_malformed_start_date():
    result = compute_time_weighted_return(
        [], [], 10_000_000.0, 11_000_000.0, account_start_date="not-a-date")
    assert result.cagr_pct is None


def test_equity_curve_starts_at_original_capital():
    result = compute_time_weighted_return([], [], 5_000_000.0, 5_500_000.0)
    assert result.equity_curve[0] == ("start", 5_000_000.0)


def test_zero_original_capital_does_not_crash():
    result = compute_time_weighted_return([], [], original_capital=0.0, current_equity=0.0)
    assert result.twr_pct == 0.0
