#!/usr/bin/env python3
"""Why did the warehouse re-download tickers it said were already covered?

    python diagnose_warehouse_churn.py --warehouse results/warehouse.db --period 5y

WHY THIS EXISTS
---------------
Two runs minutes apart, same day, nothing written in between:

    run A:  warehouse: 615/615 ticker(s) already covered, fetching 0
    run B:  warehouse: 1/615 ticker(s) already covered, fetching 614

That costs a full universe re-download — and this project has already been
rate-limited by Yahoo mid-study once. It also means two saved fold tables from
the same day were computed on different data, which is precisely what
compare_folds.py exists to prevent.

Both cache-hit paths in run_walkforward.fetch require

    warehouse.is_as_fresh_as_it_gets(ticker, end_iso)

which is true only when the recorded fetch ATTEMPT date equals end_iso. This
script prints, per ticker, the three facts that decide it — attempt date,
covered range, and the end_iso being asked for — so the answer stops being a
guess.
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

import pandas as pd

from kala.universe import ALL_SHARIA_STOCKS
from kala.warehouse import Warehouse
from run_walkforward import _freshness_target_iso, _period_to_start_iso


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--warehouse", default="results/warehouse.db")
    ap.add_argument("--period", default="5y")
    ap.add_argument("--max-tickers", type=int, default=615)
    ap.add_argument("--show", type=int, default=15, help="example rows to print")
    args = ap.parse_args()

    if not Path(args.warehouse).exists():
        print(f"no warehouse at {args.warehouse}")
        return 1

    end = pd.Timestamp.today().normalize()
    end_iso = end.strftime("%Y-%m-%d")
    start_iso = _period_to_start_iso(args.period, end)
    fresh_iso = _freshness_target_iso(end)

    print(f"today / end_iso   : {end_iso}")
    print(f"requested start   : {start_iso}   (period {args.period})")
    print(f"freshness target  : {fresh_iso}")
    print("  A cached ticker is trusted only if its recorded fetch ATTEMPT")
    print("  date == end_iso above. If attempt dates are from an earlier day,")
    print("  every ticker re-downloads — that is the churn.\n")

    wh = Warehouse(args.warehouse)
    tickers = list(ALL_SHARIA_STOCKS)[:args.max_tickers]

    attempts: Counter = Counter()
    reasons: Counter = Counter()
    examples: list = []
    for t in tickers:
        rec = wh.fetch_attempt(t)
        cov = wh.covered_range(t)
        attempted = rec[0] if rec else None
        newest = rec[1] if rec else None
        attempts[attempted] += 1

        if cov is None:
            reasons["never stored"] += 1
        else:
            spans = start_iso is None or cov[0] <= start_iso
            tail_fresh = cov[1] >= fresh_iso
            if spans and tail_fresh:
                reasons["covered outright"] += 1
            elif attempted == end_iso:
                reasons["covered via today's attempt marker"] += 1
            else:
                why = "too short" if not spans else "stale tail"
                reasons[f"REFETCH ({why}), attempt={attempted}"] += 1
                if len(examples) < args.show:
                    examples.append((t, cov, attempted, newest))

    print(f"{'fetch-attempt date':<28}{'tickers':>9}")
    for d, n in sorted(attempts.items(), key=lambda kv: (kv[0] is None, kv[0] or "")):
        mark = "  <- today" if d == end_iso else ""
        print(f"{str(d):<28}{n:>9}{mark}")

    print(f"\n{'outcome':<52}{'tickers':>9}")
    for r, n in reasons.most_common():
        print(f"{r:<52}{n:>9}")

    if examples:
        print(f"\nexamples that will re-download ({len(examples)} of many):")
        print(f"  {'ticker':<12}{'covered':<26}{'attempt':<13}{'newest seen'}")
        for t, cov, attempted, newest in examples:
            span = f"{cov[0]}..{cov[1]}"
            print(f"  {t:<12}{span:<26}{str(attempted):<13}{newest}")

    stale_attempts = sum(n for d, n in attempts.items() if d != end_iso)
    print()
    if stale_attempts > len(tickers) * 0.5:
        print(f"READ: {stale_attempts} of {len(tickers)} tickers carry a fetch-attempt")
        print("date that is NOT today. Every one of them re-downloads regardless of")
        print("what is cached. If those dates are yesterday's, the churn is simply")
        print("the day rolling over and is expected once per day. If they are from")
        print("EARLIER TODAY, the attempt marker is being lost or overwritten and")
        print("that is a bug worth chasing.")
    else:
        print("READ: attempt markers are mostly current, so the churn is not")
        print("explained by them. Look at the covered ranges above instead.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
