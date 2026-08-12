"""
One-shot probe: does Invezgo's financial-statement endpoint return REAL
historical periods, or just the latest snapshot?

Why this matters: kala/fundamental_screen.py is explicitly NOT walk-forward
validated and can't be, because yfinance only exposes CURRENT fundamentals
-- feeding today's P/E into a historical backtest is a look-ahead bug (see
that module's docstring). /analysis/financial-statement/{code}'s ``limit``
param (example value 8 in Invezgo's OpenAPI spec) suggests it might return
MULTIPLE historical periods per call -- if true, this could unblock a real
point-in-time fundamental-value strategy. If it only ever returns the
latest period regardless of ``limit``, that's a real, useful answer too
(rules the idea out cleanly instead of leaving it open).

Costs 1 API call (2 with --both). Confirmed params (real OpenAPI spec, no
market/investor/from/to needed for this endpoint, unlike the broker-flow
ones): code, statement (BS/IS/CF), type (FY/Q/Q1-4), limit (optional).

Usage:
    $env:KALA_INVEZGO_TOKEN = "your-token"
    python probe_financial_statement.py                    # BBCA, annual (FY), limit=8
    python probe_financial_statement.py --code ANTM --type Q --limit 8
    python probe_financial_statement.py --both              # FY and Q in one run (2 calls)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from kala.invezgo_fetch import InvezgoClient

OUT_DIR = Path("results")


def _probe_one(client: InvezgoClient, code: str, statement: str, type_: str, limit: int) -> None:
    data = client._get(
        f"/analysis/financial-statement/{code}",
        params={"statement": statement, "type": type_, "limit": limit},
    )
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"invezgo_probe_financial_statement_{statement}_{type_}.json"
    out_path.write_text(json.dumps(data, indent=2))

    n_periods = len(data) if isinstance(data, list) else (1 if data else 0)
    print(f"  {statement}/{type_}: saved {out_path}")
    print(f"    shape: {'array of ' + str(n_periods) + ' period(s)' if isinstance(data, list) else type(data).__name__}")
    if isinstance(data, list) and data and isinstance(data[0], dict):
        print(f"    first period keys: {list(data[0].keys())[:12]}"
             f"{' ...' if len(data[0].keys()) > 12 else ''}")
        # look for anything date/period-like so we can tell periods apart at a glance
        date_ish = {k: v for k, v in data[0].items()
                   if any(t in k.lower() for t in ("date", "period", "year", "quarter", "tahun"))}
        if date_ish:
            print(f"    date/period fields in first entry: {date_ish}")
        if n_periods > 1:
            others = [{k: v for k, v in row.items() if k in date_ish} for row in data[1:4]]
            print(f"    same fields, next {len(others)} entries: {others}")
            print("    -> MULTIPLE DISTINCT PERIODS: real history, worth building an adapter around.")
        else:
            print("    -> only one entry came back even with limit={} -- ".format(limit)
                 + "possibly latest-only despite the limit param.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--code", default="BBCA", help="bare IDX code (default BBCA)")
    ap.add_argument("--statement", default="IS", choices=["BS", "IS", "CF"],
                    help="BS=balance sheet, IS=income statement, CF=cash flow (default IS)")
    ap.add_argument("--type", default="FY", choices=["FY", "Q", "Q1", "Q2", "Q3", "Q4"],
                    help="FY=annual, Q=quarterly, Q1-Q4=specific quarter (default FY)")
    ap.add_argument("--limit", type=int, default=8, help="periods requested (default 8)")
    ap.add_argument("--both", action="store_true",
                    help="probe both FY and Q for --statement in one run (2 calls total)")
    args = ap.parse_args()

    try:
        client = InvezgoClient()
        if not client.token:
            raise RuntimeError
    except Exception:
        print("No KALA_INVEZGO_TOKEN set — export/$env: it before running.", file=sys.stderr)
        return 1

    print(f"Probing financial-statement for {args.code} ({args.statement}, "
         f"limit={args.limit})...")
    try:
        _probe_one(client, args.code, args.statement, args.type, args.limit)
        if args.both:
            other = "Q" if args.type == "FY" else "FY"
            _probe_one(client, args.code, args.statement, other, args.limit)
    except Exception as e:
        print(f"  call failed: {e}", file=sys.stderr)
        return 1

    print("\nDone. Send the results/invezgo_probe_financial_statement_*.json file(s) back.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
