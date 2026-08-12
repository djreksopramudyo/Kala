"""
Run the basket-SELECTION study on real data: if high correlation is why every
weighting/exposure overlay failed (see PROJECT_STATUS.md), can you fix it by
CHOOSING different stocks? Plus the holdings-count curve: how much does risk
actually fall as you hold more names, and where does it stop helping?

See kala/basket_selection.py's module docstring for the look-ahead trap this
avoids (selection uses TRAILING correlation only) and the honest prior
(trailing correlations are notoriously unstable out of sample).

Network access happens ONLY here (yfinance). Pure logic + math live in
kala.basket_selection and are unit-tested offline.

Usage:
    python selection_study.py --period 10y                    # both studies, IDX sharia sample
    python selection_study.py --tickers TLKM.JK UNVR.JK ...   # explicit universe
    python selection_study.py --k 8                           # basket size to select
    python selection_study.py --curve-only                    # just the holdings-count curve
    python selection_study.py --universe us
"""

from __future__ import annotations

import argparse
import sys

import pandas as pd
import yfinance as yf

from kala.basket_selection import (
    compare_selection,
    format_holdings_curve,
    format_selection,
    holdings_curve,
)
from kala.universe import ALL_SHARIA_STOCKS, US_SHARIA_STOCKS


def _fetch_closes(tickers: list[str], period: str) -> dict[str, pd.Series]:
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
    ap.add_argument("--tickers", nargs="*", default=None)
    ap.add_argument("--universe", default="idx", choices=["idx", "us"])
    ap.add_argument("--max-tickers", type=int, default=40,
                    help="universe size to select FROM (default 40)")
    ap.add_argument("--period", default="10y")
    ap.add_argument("--k", type=int, default=8, help="basket size to select (default 8)")
    ap.add_argument("--lookback", type=int, default=252,
                    help="trailing days for the correlation estimate (default 252 ≈ 1y)")
    ap.add_argument("--every-days", type=int, default=63,
                    help="re-selection cadence (default 63 ≈ quarterly)")
    ap.add_argument("--trials", type=int, default=200,
                    help="random draws for the baseline distribution (default 200)")
    ap.add_argument("--curve-only", action="store_true",
                    help="skip the selection comparison, just show the holdings curve")
    args = ap.parse_args(argv)

    if args.tickers:
        tickers = args.tickers
    else:
        base = US_SHARIA_STOCKS if args.universe == "us" else ALL_SHARIA_STOCKS
        step = max(1, len(base) // args.max_tickers)
        tickers = base[::step][:args.max_tickers]

    print(f"Fetching {len(tickers)} ticker(s), {args.period}...")
    closes = _fetch_closes(tickers, args.period)
    if len(closes) < 2:
        print("Not enough usable price history. Check network/tickers.", file=sys.stderr)
        return 1
    print(f"  {len(closes)} usable.\n")

    if not args.curve_only:
        cmp = compare_selection(closes, k=args.k, lookback=args.lookback,
                                every_days=args.every_days, n_random_trials=args.trials)
        print(format_selection(cmp))
        print()

    curve = holdings_curve(closes, n_trials=max(50, args.trials // 2))
    print(format_holdings_curve(curve))
    return 0


if __name__ == "__main__":
    sys.exit(main())
