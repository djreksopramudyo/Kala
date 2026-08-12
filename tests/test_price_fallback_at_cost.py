"""An unpriced holding must not be valued at its all-time high.

generate_dashboard fell back to pos.peak_price when a fetch missed. peak_price
is by definition the highest price that position ever saw, so it is the most
flattering substitute available: a name bought at 1000 that peaked at 1500 and
now trades at 800 was carried at 1500. Equity, weights and the whole drift
table inherited it, silently.

chart.mark_to_market_points had already faced the same choice and picked cost
— "wrong, but bounded and reported". This aligns the two.

The exposure grew rather than shrank with the datacache age bound: refusing a
stale cache means MORE holdings arrive unpriced, not fewer.
"""

import os
import tempfile

import pytest

from kala.papertrade import PaperTrader


def _trader():
    pt = PaperTrader.load(os.path.join(tempfile.mkdtemp(), "s.json"), 100_000_000)
    pt.manual_buy("AAA.JK", 10_000, 1000.0, date="2026-01-02")
    pt.manual_buy("BBB.JK", 10_000, 1000.0, date="2026-01-02")
    pt.positions["BBB.JK"].peak_price = 1500.0     # ran up, then fell back
    return pt


def _fallback_prices(pt, priced, use_cost=True):
    """Mirror generate_dashboard's fill-in step."""
    prices = dict(priced)
    used = []
    for t, pos in pt.positions.items():
        if t not in prices:
            prices[t] = pos.entry_price if use_cost else pos.peak_price
            used.append(t)
    return prices, used


def test_peak_price_fallback_inflates_equity():
    """Characterises the old behaviour so the size of it is on record."""
    pt = _trader()
    truth = pt.equity({"AAA.JK": 1000.0, "BBB.JK": 800.0})

    at_peak, _ = _fallback_prices(pt, {"AAA.JK": 1000.0}, use_cost=False)
    assert pt.equity(at_peak) > truth
    assert pt.equity(at_peak) - truth == pytest.approx(7_000_000, abs=1)


def test_cost_fallback_is_far_closer_to_the_truth():
    pt = _trader()
    truth = pt.equity({"AAA.JK": 1000.0, "BBB.JK": 800.0})

    at_cost, used = _fallback_prices(pt, {"AAA.JK": 1000.0})
    at_peak, _ = _fallback_prices(pt, {"AAA.JK": 1000.0}, use_cost=False)

    assert used == ["BBB.JK"]
    assert abs(pt.equity(at_cost) - truth) < abs(pt.equity(at_peak) - truth)


def test_cost_fallback_is_not_systematically_flattering():
    """The point isn't that cost is accurate — it isn't. It's that cost can
    err in EITHER direction, while peak can only ever err upward."""
    pt = _trader()
    pt.positions["BBB.JK"].peak_price = 1500.0

    at_cost, _ = _fallback_prices(pt, {"AAA.JK": 1000.0})
    # position is up on the day: cost UNDERstates
    up = pt.equity({"AAA.JK": 1000.0, "BBB.JK": 1200.0})
    assert pt.equity(at_cost) < up
    # position is down: cost OVERstates
    down = pt.equity({"AAA.JK": 1000.0, "BBB.JK": 800.0})
    assert pt.equity(at_cost) > down


def test_fully_priced_book_uses_no_fallback():
    pt = _trader()
    _, used = _fallback_prices(pt, {"AAA.JK": 1000.0, "BBB.JK": 800.0})
    assert used == []


def test_dashboard_reports_which_names_were_priced_at_cost():
    """The list has to reach the caller, or the caption can't warn."""
    import inspect

    import generate_dashboard as gd

    src = inspect.getsource(gd.build_dashboard)
    assert "price_fallbacks" in src
    assert "pos.entry_price" in src
    assert "pos.peak_price" not in src, "peak_price fallback is back"


def test_report_caption_warns_before_the_drift_line():
    """Drift is computed FROM those placeholder prices, so the warning has to
    come first or the drift reads as a reason to trade."""
    import inspect

    import telegram_bot

    src = inspect.getsource(telegram_bot.build_dashboard_document)
    warn_at = src.index("valued at COST")
    drift_at = src.index("Drifted from target")
    assert warn_at < drift_at


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
