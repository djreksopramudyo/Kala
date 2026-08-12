"""Share counts must never be guessed at.

/buy and /sell used to parse shares by stripping '.' and ',' unconditionally.
That silently mangles the format an Indonesian broker screen actually prints:
'1.000,00' — one thousand shares — became 100000. A hundredfold error, booked
without a warning whenever the account had enough cash to cover it.

parse_price already draws the decimal-vs-thousands distinction carefully;
this brings shares up to the same standard, except that shares are whole
units so anything with a decimal part is rejected rather than interpreted.
"""

import pytest

from telegram_bot import parse_shares


@pytest.mark.parametrize("text,expected", [
    ("200", 200),
    ("1000", 1000),
    ("1.000", 1000),          # Indonesian thousands separator
    ("1,000", 1000),          # English thousands separator
    ("12.345.000", 12345000),
    ("12,345,000", 12345000),
    ("100", 100),
])
def test_accepts_whole_counts_and_thousands_grouping(text, expected):
    assert parse_shares(text) == expected


@pytest.mark.parametrize("text", [
    "1.000,00",   # the repro: Stockbit's display format for 1,000 shares
    "2.500,00",
    "20.0",       # would have become 200 — a tenfold error
    "10.5",
    "1,5",
    "0.5",
])
def test_rejects_anything_with_a_decimal_part(text):
    """Rejecting costs one clarifying message. Guessing costs a wrong
    position that /report, /rebalance and TWR all inherit."""
    assert parse_shares(text) is None


@pytest.mark.parametrize("text", ["", "   ", "abc", "12abc", "-100", "1..000",
                                  "1.00", "1.0000", None])
def test_rejects_junk(text):
    assert parse_shares(text) is None


def test_rejects_zero():
    assert parse_shares("0") is None


def test_tolerates_surrounding_spaces():
    assert parse_shares("  1.000  ") == 1000


def test_the_hundredfold_error_is_gone():
    """Characterises the old behaviour so the regression is unmistakable."""
    old = int("1.000,00".replace(",", "").replace(".", ""))
    assert old == 100_000                    # what it used to record
    assert parse_shares("1.000,00") is None  # what it does now


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
