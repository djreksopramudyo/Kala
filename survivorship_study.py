"""
Run the survivorship-bias check: was the core-satellite edge real, or just
hindsight in how the 8 satellite names were picked?

This is the test that can INVALIDATE the strongest finding in the project.
See kala/survivorship_check.py's module docstring for the logic and for the
bias this test explicitly CANNOT fix (the universe itself is today's ISSI
list, so dead companies are already missing from every arm).

Network access happens ONLY here (yfinance). Pure logic + math live in
kala.survivorship_check and are unit-tested offline.

Usage:
    # default: draw random baskets from a broad sharia sample, compare to XIJI,
    # and locate the user's real 8 inside that distribution
    python survivorship_study.py

    python survivorship_study.py --core ^JKSE           # index proxy instead of the ETF
    python survivorship_study.py --k 8 --n-random 500   # more draws, tighter distribution
    python survivorship_study.py --universe-size 60     # wider pool to draw from
"""

from __future__ import annotations

import argparse
import sys

import pandas as pd
import yfinance as yf

from kala.survivorship_check import check_survivorship, format_survivorship
from kala.universe import ALL_SHARIA_STOCKS

# The user's actual satellite sleeve — located inside the random distribution.
HANDPICKED = ["TLKM.JK", "UNVR.JK", "ICBP.JK", "KLBF.JK",
              "ANTM.JK", "INDF.JK", "BRIS.JK", "SMGR.JK"]


def _fetch(tickers: list[str], period: str) -> dict[str, pd.Series]:
    out: dict[str, pd.Series] = {}
    try:
        raw = yf.download(tickers, period=period, group_by="ticker",
                          auto_adjust=True, progress=False, threads=True)
    except Exception as e:
        print(f"Download failed: {e}", file=sys.stderr)
        return out
    for t in tickers:
        try:
            df = raw[t] if len(tickers) > 1 else raw
            s = df["Close"].dropna()
            if len(s):
                out[t] = s
        except (KeyError, IndexError):
            continue
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--core", default="XIJI.JK")
    ap.add_argument("--period", default="10y")
    ap.add_argument("--k", type=int, default=8, help="satellite basket size (default 8)")
    ap.add_argument("--n-random", type=int, default=300,
                    help="random baskets to draw (default 300)")
    ap.add_argument("--universe-size", type=int, default=50,
                    help="how many sharia names to draw FROM (default 50)")
    ap.add_argument("--core-weight", type=float, default=0.73)
    ap.add_argument("--universe", nargs="*", default=None,
                    help="explicit pool to draw from; default = a sample of ALL_SHARIA_STOCKS "
                         "plus the hand-picked 8 (so they're always in the pool)")
    args = ap.parse_args(argv)

    if args.universe:
        pool = list(dict.fromkeys(args.universe))
    else:
        step = max(1, len(ALL_SHARIA_STOCKS) // args.universe_size)
        sampled = ALL_SHARIA_STOCKS[::step][:args.universe_size]
        # ensure the hand-picked names are in the pool so the percentile is meaningful
        pool = list(dict.fromkeys(list(sampled) + HANDPICKED))

    all_tickers = [args.core] + pool
    print(f"Fetching core '{args.core}' + {len(pool)} universe name(s), {args.period}...")
    data = _fetch(all_tickers, args.period)
    if args.core not in data:
        print(f"No usable history for core '{args.core}'.", file=sys.stderr)
        return 1
    universe = {t: s for t, s in data.items() if t != args.core}
    if len(universe) <= args.k:
        print(f"Universe too small ({len(universe)} usable) for k={args.k}.", file=sys.stderr)
        return 1
    print(f"  core + {len(universe)} usable universe names.\n")

    r = check_survivorship(data[args.core], universe, handpicked=HANDPICKED,
                           k=args.k, n_random=args.n_random,
                           core_weight=args.core_weight)
    print(format_survivorship(r))
    return 0


if __name__ == "__main__":
    sys.exit(main())
