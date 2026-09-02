"""
One-shot Invezgo endpoint probe — run this ONCE on a machine that has the
API token, to lock down the two response shapes the adapter couldn't be
written against blind (see BROKER_FLOW_DATA_SPEC.md "WHAT'S ASSUMED").

It makes at most 3 real API calls for a single ticker and dumps each raw
JSON response to results/ so the exact field names are on record. Nothing
here writes to the archive or trades — it's purely diagnostic.

Setup:
    $env:KALA_INVEZGO_TOKEN = "your-token"      # PowerShell
    python probe_invezgo.py                       # defaults to BBCA
    python probe_invezgo.py --code ANTM --date 2024-12-02

Then send the three results/invezgo_probe_*.json files back so the adapter
can be confirmed (or corrected) against real field names instead of the
one assumption fetch_daily_foreign_net currently makes.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from kala.invezgo_fetch import InvezgoClient

OUT_DIR = Path("results")


def _dump(name: str, payload) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"invezgo_probe_{name}.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    shape = (f"array of {len(payload)} item(s)" if isinstance(payload, list)
             else f"object with keys {list(payload.keys())}"
             if isinstance(payload, dict) else type(payload).__name__)
    first_keys = (list(payload[0].keys()) if isinstance(payload, list) and payload
                  and isinstance(payload[0], dict) else None)
    print(f"  saved {path}  ({shape})")
    if first_keys:
        print(f"    first item keys: {first_keys}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--code", default="BBCA", help="bare IDX code (default BBCA)")
    ap.add_argument("--date", default="2024-12-02",
                    help="single trading day to probe, YYYY-MM-DD (default 2024-12-02)")
    args = ap.parse_args()

    try:
        client = InvezgoClient()
    except Exception as e:  # pragma: no cover - trivial
        print(f"Could not build client: {e}", file=sys.stderr)
        return 1

    d = args.date
    print(f"Probing Invezgo for {args.code} on {d} (3 calls)...")

    # 1. investor=foreign on the same summary endpoint we already know for
    #    investor=all -- THE key unknown: does foreign come per-broker or as
    #    one aggregate row?
    try:
        _dump("summary_foreign", client.broker_summary(args.code, d, d, investor="foreign"))
    except Exception as e:
        print(f"  investor=foreign call failed: {e}", file=sys.stderr)

    # 2. investor=all for the same single day, so we can compare foreign-vs-all
    #    side by side on identical inputs.
    try:
        _dump("summary_all", client.broker_summary(args.code, d, d, investor="all"))
    except Exception as e:
        print(f"  investor=all call failed: {e}", file=sys.stderr)

    # 3. inventory-chart -- the accumulation-over-time endpoint we have zero
    #    samples for. Raw pass-through since we don't know its shape at all.
    try:
        raw = client._get(f"/analysis/inventory-chart/stock/{args.code}")
        _dump("inventory_chart", raw)
    except Exception as e:
        print(f"  inventory-chart call failed: {e}", file=sys.stderr)

    print("Done. Send the results/invezgo_probe_*.json files back.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
