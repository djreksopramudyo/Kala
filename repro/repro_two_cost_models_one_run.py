#!/usr/bin/env python3
"""One daily run, two cost models: the dearer one reports, the cheaper one books.

Run it:  python repro/repro_two_cost_models_one_run.py

THE TWO LINES
-------------
``daily_run.py``, weekly friction report::

    friction_report(raw, costs=CostModel(spread_mode="tick_floor"), ...)

``daily_run.py``, the config the PAPER TRADER books its fills through::

    trade_cfg = config_for_profile(cfg.get("exit_profile"))   # costs = default

The default ``CostModel()`` is ``spread_mode="flat"`` — a constant 0.10%
half-spread at every price. ``tick_floor`` floors it at half an IDX tick, which
a cheap stock cannot trade inside of.

So the same run tells the user what their trading costs under the honest model
and records those trades at the optimistic one. Every validated number in this
project was measured with ``--tick-spread``, i.e. tick_floor.

WHICH WAY IT POINTS
-------------------
Flat is never dearer. The live book is systematically cheaper than the backtest
it will be compared against — so the forward test, the one piece of evidence
this project has never had, is biased toward "live is beating the model" before
a single trade is placed.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for candidate in (ROOT, ROOT.parent):
    if (candidate / "kala").is_dir():
        sys.path.insert(0, str(candidate))
        break
else:
    raise SystemExit(
        "cannot find the kala package next to this script — run it from "
        "the project root: python repro/repro_two_cost_models_one_run.py")

from kala.config import CostModel, config_from_settings  # noqa: E402

# This account's nine open positions, at their booked entry prices.
HOLDINGS = [
    ("KBLI.JK", 323), ("BSML.JK", 519), ("STAA.JK", 1104), ("SRTG.JK", 1721),
    ("CASS.JK", 1923), ("AUTO.JK", 2794), ("INDF.JK", 7061),
    ("ICBP.JK", 7211), ("AADI.JK", 9064),
]

FLAT = CostModel()
TICK = CostModel(spread_mode="tick_floor")


def round_trip(costs: CostModel, price: float) -> float:
    """Round-trip drag as a percentage of the raw price."""
    return (1 - costs.sell_multiplier(price) / costs.buy_multiplier(price)) * 100


def main() -> int:
    print("=" * 70)
    print("WHAT THE BOOK CHARGED vs WHAT THE MEASUREMENT CHARGED")
    print("=" * 70)
    print(f"\n{'ticker':<10}{'entry IDR':>11}{'booked':>9}{'measured':>10}{'gap':>8}")
    print("-" * 48)
    gaps = []
    for t, px in HOLDINGS:
        f, k = round_trip(FLAT, px), round_trip(TICK, px)
        gaps.append(k - f)
        print(f"{t:<10}{px:>11,}{f:>8.2f}%{k:>9.2f}%{k - f:>7.2f}%")
    print("-" * 48)
    mean = sum(gaps) / len(gaps)
    print(f"{'mean gap':<10}{'':>11}{'':>9}{'':>10}{mean:>7.2f}%")

    print("\n  Every gap is positive — flat is never the dearer model, so this")
    print(f"  is a bias, not noise. {mean:.2f} points per trade, always in the")
    print("  direction that makes the live account look better than the")
    print("  backtest. The measured excess is +1.71%/trade, so this is about")
    print(f"  {mean / 1.71 * 100:.0f}% of the headline it will be compared against.")

    print(f"\n{'=' * 70}\nWORST WHERE THE TICK BITES HARDEST\n{'=' * 70}")
    for px in (67, 150, 350, 519, 1500, 6000):
        f, k = round_trip(FLAT, px), round_trip(TICK, px)
        print(f"  IDR {px:>6,}   booked {f:.2f}%   measured {k:.2f}%   "
              f"gap {k - f:+.2f}%")
    print("\n  A 67-rupiah stock has a 1-rupiah tick. It cannot trade inside a")
    print("  0.10% spread; the flat assumption understates it several-fold.")

    print(f"\n{'=' * 70}\nTHE SETTING\n{'=' * 70}")
    for settings, label in (
            ({}, "as shipped — nothing set"),
            ({"costs_spread_mode": "tick_floor"}, 'costs_spread_mode set'),
    ):
        cfg = config_from_settings(settings)
        px = 519
        print(f"\n  {label}")
        print(f"    spread_mode  : {cfg.costs.spread_mode}")
        print(f"    BSML @ 519   : round trip {round_trip(cfg.costs, px):.2f}%")

    print("\n  The default is deliberately unchanged: flipping it would rewrite")
    print("  a live book's arithmetic without being asked. The measurement now")
    print("  records which model it used, and the daily expectation block")
    print("  refuses to quote a tick-floored figure at a flat-booked account.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
