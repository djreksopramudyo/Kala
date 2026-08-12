"""A holding whose exit rules did not run must say so, loudly.

step() skips exit evaluation when a position has no price history, or fewer
than 60 bars. It used to skip silently: the ticker simply vanished from the
daily message, which reads identically to "no exit signal today". The stop,
the trailing stop and the max-holding rule had all gone unchecked.
"""

import pandas as pd
import pytest

from kala.notify import format_daily_message
from kala.papertrade import PaperTrader


def _history(n=120, close=1000.0):
    idx = pd.bdate_range("2025-09-01", periods=n)
    return pd.DataFrame({"Open": [close] * n, "High": [close * 1.01] * n,
                         "Low": [close * 0.99] * n, "Close": [close] * n},
                        index=idx)


def _trader(tmp_path, tickers):
    pt = PaperTrader.load(tmp_path / "s.json", 100_000_000)
    for t in tickers:
        pt.manual_buy(t, 1000, 1000.0, date="2026-01-02")
    return pt


def test_missing_history_is_reported_not_swallowed(tmp_path):
    pt = _trader(tmp_path, ["AAA.JK", "BBB.JK"])
    report = pt.step({"AAA.JK": _history()}, [], today="2026-01-06")

    assert any("BBB.JK" in u for u in report["unevaluated"])
    assert not any("AAA.JK" in u for u in report["unevaluated"])


def test_short_history_is_reported_with_the_bar_count(tmp_path):
    """A recent listing has data, just not enough — a different cause with
    the same consequence, so it must be named differently but flagged too."""
    pt = _trader(tmp_path, ["CCC.JK"])
    report = pt.step({"CCC.JK": _history(30)}, [], today="2026-01-06")

    assert len(report["unevaluated"]) == 1
    assert "30 bars" in report["unevaluated"][0]


def test_fully_priced_book_reports_nothing_unevaluated(tmp_path):
    """Guard against crying wolf on every run."""
    pt = _trader(tmp_path, ["AAA.JK", "BBB.JK"])
    report = pt.step({"AAA.JK": _history(), "BBB.JK": _history()}, [],
                     today="2026-01-06")

    assert report["unevaluated"] == []


def test_the_daily_message_says_not_checked(tmp_path):
    pt = _trader(tmp_path, ["AAA.JK", "BBB.JK"])
    report = pt.step({"AAA.JK": _history()}, [], today="2026-01-06")
    text = format_daily_message(report)

    assert "NOT CHECKED TODAY" in text
    assert "BBB.JK" in text


def test_the_warning_is_not_truncated_like_skipped(tmp_path):
    """"skipped" shows only the first five. An unchecked stop is not a
    footnote, so every affected holding must appear."""
    tickers = [f"T{i}.JK" for i in range(8)]
    pt = _trader(tmp_path, tickers)
    report = pt.step({}, [], today="2026-01-06")
    text = format_daily_message(report)

    assert len(report["unevaluated"]) == 8
    for t in tickers:
        assert t in text


def test_a_clean_message_has_no_warning_block(tmp_path):
    pt = _trader(tmp_path, ["AAA.JK"])
    report = pt.step({"AAA.JK": _history()}, [], today="2026-01-06")
    assert "NOT CHECKED" not in format_daily_message(report)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
