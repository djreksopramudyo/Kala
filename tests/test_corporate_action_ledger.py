"""Rescaling for a split must not destroy the fill ledger it exists to keep.

apply_corporate_action_adjustment used to dump the whole lot-rounding drift
onto the LAST fill. When that fill was smaller than the drift it went
negative, position_fills() dropped it, the share total stopped matching
pos.shares — and the ledger was discarded as out-of-sync, taking its
per-fill dates and "costed" markers with it. Exactly the outcome the
rescaling was written to prevent.
"""

import pytest

from kala.papertrade import PaperPosition, apply_corporate_action_adjustment, position_fills


def _position(n_fills, shares_each=100.0):
    return PaperPosition(
        ticker="X.JK", entry_price=1000.0, shares=int(n_fills * shares_each),
        entry_date="2026-01-02", peak_price=1000.0,
        fills=[{"date": f"2026-01-{i + 2:02d}", "shares": shares_each,
                "price": 1000.0} for i in range(n_fills)])


@pytest.mark.parametrize("n_fills,ratio", [
    (5, 3.5),      # the original repro: last fill smaller than the drift
    (8, 3.9),
    (6, 0.25),
    (3, 2.4),
    (2, 10.0),
    (1, 2.0),
])
def test_ledger_survives_rescaling(n_fills, ratio):
    pos = _position(n_fills)
    apply_corporate_action_adjustment(pos, ratio)

    fills = position_fills(pos)
    assert len(fills) == n_fills, "a fill was zeroed and dropped"
    assert abs(sum(f["shares"] for f in fills) - pos.shares) < 1e-6


def test_every_fill_stays_positive():
    pos = _position(5)
    apply_corporate_action_adjustment(pos, 3.5)
    assert all(f["shares"] > 0 for f in pos.fills)


def test_costed_markers_survive():
    """The markers drive the friction split; losing them silently reclassifies
    costed shares as legacy raw-price ones."""
    pos = _position(5)
    for f in pos.fills:
        f["costed"] = True
    apply_corporate_action_adjustment(pos, 3.5)
    assert all(f.get("costed") for f in position_fills(pos))


def test_position_value_is_preserved():
    """A split changes price and share count inversely; total value must not
    move (bar the deliberate lot rounding on shares)."""
    pos = _position(4)
    before = pos.entry_price * pos.shares
    apply_corporate_action_adjustment(pos, 2.0)
    after = pos.entry_price * pos.shares
    assert after == pytest.approx(before, rel=0.02)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
