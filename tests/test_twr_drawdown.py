"""Max drawdown must not be measured on the realized-only equity curve.

The realized curve only steps when a trade CLOSES. A position that fell 45%
while held and was then closed flat produces a perfectly straight line, and
the drawdown reads 0.00% — reassuringly, and always in the flattering
direction. A drawdown figure is precisely the number someone checks before
abandoning a plan during a bad stretch, so this one had to be fixed rather
than documented.
"""

import pytest

from kala.dashboard import _drawdown_basis_note
from kala.twr import compute_time_weighted_return

# One position bought and later closed flat. Nothing was ever realized as a
# loss, so the realized-only curve is a straight line.
FLAT_ROUND_TRIP = [
    {"date": "2026-06-01", "ticker": "X.JK", "entry": 1000.0, "exit": 1000.0,
     "shares": 100_000, "pnl_pct": 0.0},
]

# ...but day by day, the book was down 45% at the trough.
MTM_CURVE = [
    ("2026-01-02", 100_000_000.0),
    ("2026-03-02", 55_000_000.0),     # -45%
    ("2026-06-01", 100_000_000.0),
]


def test_realized_only_curve_reports_a_drawdown_that_never_happened():
    """Characterises the old behaviour so the regression is unmistakable."""
    r = compute_time_weighted_return(FLAT_ROUND_TRIP, [],
                                     100_000_000.0, 100_000_000.0)
    assert r.max_drawdown_pct == pytest.approx(0.0)
    # ...and must therefore refuse to call itself the real figure
    assert r.drawdown_basis == "realized-only"
    assert r.drawdown_is_real is False


def test_mark_to_market_curve_reports_the_real_drawdown():
    r = compute_time_weighted_return(FLAT_ROUND_TRIP, [],
                                     100_000_000.0, 100_000_000.0,
                                     equity_points=MTM_CURVE)
    assert r.max_drawdown_pct == pytest.approx(-45.0, abs=0.01)
    assert r.drawdown_basis == "mark-to-market"
    assert r.drawdown_is_real is True


def test_supplying_equity_points_does_not_change_the_twr_itself():
    """Only the drawdown is affected; chain-linking is a separate calculation
    and must stay byte-identical, or this 'fix' silently restates returns."""
    without = compute_time_weighted_return(FLAT_ROUND_TRIP, [],
                                           100_000_000.0, 110_000_000.0)
    with_mtm = compute_time_weighted_return(FLAT_ROUND_TRIP, [],
                                            100_000_000.0, 110_000_000.0,
                                            equity_points=MTM_CURVE)
    assert without.twr_pct == pytest.approx(with_mtm.twr_pct)
    assert without.n_sub_periods == with_mtm.n_sub_periods
    assert without.equity_curve == with_mtm.equity_curve


def test_empty_equity_points_falls_back_and_says_so():
    """A failed price fetch hands back []; that must degrade to the realized
    curve WITH the honest label, not silently claim mark-to-market."""
    r = compute_time_weighted_return(FLAT_ROUND_TRIP, [],
                                     100_000_000.0, 100_000_000.0,
                                     equity_points=[])
    assert r.drawdown_basis == "realized-only"


def test_deposits_still_chain_link_with_a_supplied_curve():
    log = [{"date": "2026-03-01", "ticker": "A.JK", "entry": 100.0,
            "exit": 110.0, "shares": 10_000, "pnl_pct": 10.0}]
    deposits = [{"date": "2026-02-01", "amount": 50_000_000.0}]
    r = compute_time_weighted_return(log, deposits, 100_000_000.0,
                                     160_000_000.0, equity_points=MTM_CURVE)
    assert r.n_sub_periods == 2
    assert r.drawdown_basis == "mark-to-market"


def test_dashboard_caption_warns_on_the_fallback_and_not_otherwise():
    real = compute_time_weighted_return(FLAT_ROUND_TRIP, [], 1e8, 1e8,
                                        equity_points=MTM_CURVE)
    fallback = compute_time_weighted_return(FLAT_ROUND_TRIP, [], 1e8, 1e8)
    assert "worse" in _drawdown_basis_note(fallback)
    assert "worse" not in _drawdown_basis_note(real)
    assert "mark-to-market" in _drawdown_basis_note(real)


# --- a partially-priced curve must not pass itself off as complete ---------

def test_partial_curve_is_tagged_and_not_called_complete():
    """mark_to_market_points holds a lot with no price history flat AT COST.
    That flattens exactly the troughs a drawdown exists to expose, so a curve
    carrying warnings must not be presented with full confidence."""
    r = compute_time_weighted_return(
        FLAT_ROUND_TRIP, [], 100_000_000.0, 100_000_000.0,
        equity_points=MTM_CURVE,
        equity_points_warnings=["valued at cost (no price history): ZZZ.JK"])
    assert r.drawdown_basis == "mark-to-market-partial"
    assert r.drawdown_is_real is True         # still market-based...
    assert r.drawdown_is_complete is False    # ...but not the whole picture
    assert "ZZZ.JK" in " ".join(r.drawdown_warnings)


def test_partial_caption_names_the_ticker_and_warns():
    r = compute_time_weighted_return(
        FLAT_ROUND_TRIP, [], 1e8, 1e8, equity_points=MTM_CURVE,
        equity_points_warnings=["valued at cost (no price history): ZZZ.JK"])
    caption = _drawdown_basis_note(r)
    assert "ZZZ.JK" in caption
    assert "worse" in caption


def test_warnings_without_a_curve_do_not_upgrade_the_fallback():
    """No points means realized-only, whatever warnings say."""
    r = compute_time_weighted_return(FLAT_ROUND_TRIP, [], 1e8, 1e8,
                                     equity_points=[],
                                     equity_points_warnings=["something"])
    assert r.drawdown_basis == "realized-only"
    assert r.drawdown_warnings == []


def test_clean_curve_stays_complete():
    r = compute_time_weighted_return(FLAT_ROUND_TRIP, [], 1e8, 1e8,
                                     equity_points=MTM_CURVE,
                                     equity_points_warnings=[])
    assert r.drawdown_is_complete is True
    assert _drawdown_basis_note(r) == "daily mark-to-market"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
