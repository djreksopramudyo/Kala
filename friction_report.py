"""
How much has trading itself cost you? Reads paper_state.json and reports the
rupiah total, plus how much of your reported P&L is an accounting illusion.

NO NETWORK NEEDED — this is pure arithmetic on your own state file, so it
runs instantly anywhere. See kala/friction.py's module docstring for why the
manual-trade accounting gap exists and what the numbers mean.

Usage:
    python friction_report.py
    python friction_report.py --tick-spread     # honest IDX spread floor
    python friction_report.py --already-charged # if your fills embedded costs
    python friction_report.py --state other_state.json
"""

from __future__ import annotations

import argparse
import json
import sys

from kala.clock import now_wib
from kala.config import CostModel
from kala.friction import format_friction, friction_report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--state", default="paper_state.json")
    ap.add_argument("--tick-spread", action="store_true",
                    help="floor the half-spread at half an IDX tick instead of the "
                         "flat 0.10%% assumption. Cheap stocks cannot trade tighter "
                         "than their tick, so this is the more honest figure for a "
                         "book holding sub-1000-rupiah names.")
    ap.add_argument("--already-charged", action="store_true",
                    help="treat recorded fills as ALREADY cost-inclusive (true for "
                         "automated fills, false for manually recorded trades — the "
                         "default assumes manual, which is what /buy and /sell do).")
    args = ap.parse_args(argv)

    try:
        state = json.load(open(args.state))
    except FileNotFoundError:
        print(f"No state file at {args.state}.", file=sys.stderr)
        return 1
    except json.JSONDecodeError as e:
        print(f"{args.state} is not valid JSON: {e}", file=sys.stderr)
        return 1

    costs = CostModel(spread_mode="tick_floor" if args.tick_spread else "flat")
    # Close the pace window at TODAY, not at the last recorded trade: someone
    # who traded six times in a week and then stopped for a month has a much
    # lower real pace than that burst implies, and the burst figure would
    # badly overstate projected annual cost.
    report = friction_report(state, costs=costs, already_charged=args.already_charged,
                             today=now_wib().strftime("%Y-%m-%d"))
    print(format_friction(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
