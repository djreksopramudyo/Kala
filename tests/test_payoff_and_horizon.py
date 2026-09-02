"""Two numbers the P&L column hides, and one caveat that must travel with them.

"56% of my trades win" is not a result until you know what win rate the payoff
needed. On the live log those are 56.0% and 54.8% — a +1.2 point margin over 25
trades, which is break-even, not an edge.

And a strategy validated at a 60-bar horizon has not been run at all if nothing
was held that long. That one needs no statistics; it is a fact about the log.

The bucket table is the dangerous half. A stop-loss closes losers early by
construction, so longer buckets are pre-selected for trades that never hit the
stop, and a rising gradient is what that mechanism produces on its own. The
caveat is asserted here so it cannot be quietly dropped from the report.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kala.discipline import (  # noqa: E402
    format_horizon_and_payoff,
    holding_horizon_gap,
    payoff_arithmetic,
)


def _t(pnl, entry="2026-01-01", exit_="2026-01-08"):
    return {"ticker": "X.JK", "pnl_pct": pnl, "entry_date": entry, "date": exit_,
            "reason": "manual sell"}


def test_breakeven_win_rate_is_derived_not_assumed():
    """Payoff 1.0 needs 50%; payoff 0.5 needs 66.7%. Arithmetic, not a guess."""
    even = payoff_arithmetic([_t(5.0), _t(-5.0)])
    assert even.payoff == 1.0
    assert abs(even.breakeven_win_rate_pct - 50.0) < 1e-9

    skewed = payoff_arithmetic([_t(5.0), _t(-10.0)])
    assert skewed.payoff == 0.5
    assert abs(skewed.breakeven_win_rate_pct - 66.6667) < 1e-3


def test_expectancy_agrees_with_the_win_rate_and_payoff():
    p = payoff_arithmetic([_t(4.0), _t(4.0), _t(-2.0)])
    expected = (2 / 3) * 4.0 - (1 / 3) * 2.0
    assert abs(p.expectancy_pct - expected) < 1e-9
    assert p.margin_pts > 0            # 66.7% actual vs 33.3% break-even


def test_a_losing_book_reports_a_negative_margin():
    p = payoff_arithmetic([_t(1.0), _t(-9.0), _t(-9.0)])
    assert p.expectancy_pct < 0
    assert p.margin_pts < 0


def test_all_wins_or_all_losses_does_not_crash_or_invent_a_payoff():
    """No loss means no break-even line to compute; say nothing, not zero."""
    for log in ([_t(3.0), _t(4.0)], [_t(-3.0), _t(-4.0)]):
        p = payoff_arithmetic(log)
        assert p.n == 2
        assert p.payoff != p.payoff        # NaN, deliberately
        assert "PAYOFF" not in format_horizon_and_payoff(
            holding_horizon_gap(log), p)


def test_trades_without_pnl_are_excluded_not_counted_as_zero():
    p = payoff_arithmetic([_t(5.0), _t(-5.0), {"ticker": "Y.JK", "pnl_pct": None}])
    assert p.n == 2                        # the None is dropped, not scored flat


def test_reaching_the_horizon_is_counted_against_the_configured_rule():
    log = [_t(1.0, "2026-01-01", "2026-01-05"),    # 4 d
           _t(2.0, "2026-01-01", "2026-03-20")]    # 78 d
    assert holding_horizon_gap(log, rule_days=60).n_reached_rule == 1
    assert holding_horizon_gap(log, rule_days=90).n_reached_rule == 0
    assert holding_horizon_gap(log, rule_days=3).n_reached_rule == 2


def test_never_reaching_the_horizon_is_stated_outright():
    log = [_t(1.0, "2026-01-01", "2026-01-05")]
    g = holding_horizon_gap(log, rule_days=60)
    assert g.n_reached_rule == 0
    text = format_horizon_and_payoff(g, payoff_arithmetic(log))
    assert "NOT ONE trade reached" in text


def test_trades_missing_an_entry_date_are_not_silently_held_zero_days():
    log = [_t(1.0, "2026-01-01", "2026-01-05"), {"pnl_pct": 2.0, "date": "2026-01-09"}]
    g = holding_horizon_gap(log, rule_days=60)
    assert g.n_with_dates == 1             # not 2, and not a 0-day hold


def test_the_selection_caveat_always_travels_with_the_bucket_table():
    log = [_t(-4.0, "2026-01-01", "2026-01-03"),
           _t(6.0, "2026-01-01", "2026-01-25")]
    text = format_horizon_and_payoff(holding_horizon_gap(log, rule_days=60),
                                     payoff_arithmetic(log))
    assert "bucket" in text                # non-vacuity: the table IS there
    assert "NOT evidence that holding longer pays" in text
    assert "pre-selected" in text


def test_a_thin_margin_is_labelled_as_noise():
    """+1.2 pts over 25 trades must not read as 'slightly profitable'."""
    log = [_t(4.0)] * 14 + [_t(-4.8)] * 11
    text = format_horizon_and_payoff(holding_horizon_gap(log),
                                     payoff_arithmetic(log))
    assert "inside the noise" in text


def test_an_empty_log_produces_no_claims():
    text = format_horizon_and_payoff(holding_horizon_gap([]), payoff_arithmetic([]))
    assert text.strip() == ""


def test_discipline_report_prints_both_sections():
    src = (ROOT / "discipline_report.py").read_text(encoding="utf-8")
    assert "format_horizon_and_payoff(" in src
    assert "holding_horizon_gap(log, rule_days=holding)" in src
    assert "payoff_arithmetic(log)" in src
