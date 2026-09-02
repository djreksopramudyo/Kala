"""The position cap must bind hardest when it is already exceeded.

This was live. The scan's guard read:

    slots = max(0, max_pos - len(held))
    ...
    if shown >= slots and slots > 0:
        ...withhold this candidate...

`/maxpositions` rejects n <= 0, so `slots == 0` can only mean "already at or
over the cap". But `and slots > 0` made the condition False for EVERY candidate
in exactly that case, so the scan proposed its entire buy list to an account
that was over its own limit — while the same message printed the limit.

A real account was 17 positions open against a cap of 10.

The same inversion appeared a second time in the header count:
`min(slots, len(buys)) or len(buys)` — where `0 or N` is N, so a legitimate
zero was rendered as the full count.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _apply_guard(max_pos: int, held: int, n_candidates: int) -> tuple[int, int]:
    """Re-implements the guard's ARITHMETIC to pin the boundary behaviour.

    Kept in the test rather than imported because the live call needs network,
    a paper-trader state file and a signal feed. The source-level assertion
    below is what ties this arithmetic to the shipped code — the two together
    are the check; neither alone would be.
    """
    slots = max(0, max_pos - held)
    shown = 0
    withheld = 0
    for _ in range(n_candidates):
        if shown >= slots:
            withheld += 1
            continue
        shown += 1
    return shown, withheld


def test_an_account_over_the_cap_gets_nothing_proposed():
    """The reported failure: 17 held, cap 10."""
    shown, withheld = _apply_guard(max_pos=10, held=17, n_candidates=8)
    assert shown == 0, f"proposed {shown} new buys while 7 positions over the cap"
    assert withheld == 8


def test_an_account_exactly_at_the_cap_gets_nothing_proposed():
    """The boundary. Under the old logic this was the first broken case."""
    shown, _ = _apply_guard(max_pos=10, held=10, n_candidates=8)
    assert shown == 0


def test_an_account_one_under_the_cap_gets_exactly_one():
    """Non-vacuity: returning 0 always would satisfy the two tests above."""
    shown, withheld = _apply_guard(max_pos=10, held=9, n_candidates=8)
    assert shown == 1
    assert withheld == 7


@pytest.mark.parametrize("held,expect", [(0, 8), (2, 8), (5, 5), (8, 2), (9, 1),
                                         (10, 0), (11, 0), (17, 0)])
def test_the_number_proposed_is_monotone_and_never_exceeds_the_headroom(held, expect):
    """It must decrease to zero and STAY there, not wrap around."""
    shown, _ = _apply_guard(max_pos=10, held=held, n_candidates=8)
    assert shown == expect
    assert shown <= max(0, 10 - held)


def test_the_shipped_guard_has_no_slots_greater_than_zero_clause():
    """Ties the arithmetic above to the code that actually runs.

    Without this the test file would happily pass while the live guard kept the
    clause — the arithmetic here is a model, not the shipped path.
    """
    src = (ROOT / "telegram_bot.py").read_text(encoding="utf-8")
    assert "if shown >= slots and slots > 0:" not in src, (
        "the inverted cap clause is back")
    assert "if shown >= slots:" in src


def test_the_header_count_does_not_turn_a_legitimate_zero_into_everything():
    """`min(slots, n) or n` renders 0 as n. The early return replaces it."""
    src = (ROOT / "telegram_bot.py").read_text(encoding="utf-8")
    assert "or len(r['buys'])} shown" not in src, (
        "the `0 or N` inversion is back in the header count")


def test_being_over_the_cap_is_reported_not_just_silently_empty():
    """An empty list reads as 'no signals today'. It is not the same thing.

    Withholding every candidate without saying why would swap one invisible
    failure for another: the user would conclude the market offered nothing,
    when in fact the scan found signals and suppressed them.

    Asserted by CALLING position_cap_notice. The first version of this test
    grepped telegram_bot.py for the strings, and survived a mutation that made
    the entire block unreachable — the text was still in the file.
    """
    from telegram_bot import position_cap_notice

    msg = position_cap_notice(slots=0, held=17, max_pos=10, n_signals=8)
    assert msg is not None
    assert "17" in msg and "10" in msg, "the notice must name the actual numbers"
    assert "8 BUY signal(s)" in msg, "the withheld count must be stated"
    assert "/maxpositions" in msg, "the notice must say how to change it"
    assert "NOT 'no signals'" in msg


def test_the_cap_notice_is_absent_when_there_is_headroom():
    """Non-vacuity: returning the notice unconditionally would pass the above."""
    from telegram_bot import position_cap_notice

    assert position_cap_notice(slots=1, held=9, max_pos=10, n_signals=8) is None
    assert position_cap_notice(slots=10, held=0, max_pos=10, n_signals=8) is None


def test_the_cap_notice_fires_at_exactly_zero_headroom():
    """The boundary is the whole bug: 0 must mean 'none', not 'unlimited'."""
    from telegram_bot import position_cap_notice

    assert position_cap_notice(slots=0, held=10, max_pos=10, n_signals=3) is not None
    assert position_cap_notice(slots=-3, held=13, max_pos=10, n_signals=3) is not None
