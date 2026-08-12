"""
Run the rebalancing POLICY study on real sharia data: does periodically
rebalancing a fixed basket back to equal weight beat just buying and holding
it? See kala/rebalance_backtest.py's module docstring for why this is an
honest policy test, NOT another (failed) market-timing attempt.

Network access happens ONLY here (yfinance). Pure logic + math live in
kala.rebalance_backtest and are unit-tested offline.

Usage:
    python rebalance_study.py                                  # default IDX sharia sample, 10y, quarterly
    python rebalance_study.py --tickers ANTM.JK BBCA.JK TLKM.JK
    python rebalance_study.py --universe us --cost-preset us_equity
    python rebalance_study.py --every-days 21    # monthly instead of quarterly
    python rebalance_study.py --cost-rate 0      # frictionless upper bound (dishonest, for comparison)
"""

from __future__ import annotations

import argparse
import sys

import pandas as pd
import yfinance as yf

from kala.config import CostModel, us_equity_costs
from kala.rebalance_backtest import compare_rebalancing, format_comparison
from kala.universe import ALL_SHARIA_STOCKS, US_SHARIA_STOCKS


def _fetch_closes(tickers: list[str], period: str) -> dict[str, pd.Series]:
    """Best-effort Close history per ticker; a name that fails to download is
    simply dropped (the study runs on whatever overlapping history exists)."""
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


def _one_leg_cost_rate(preset: str) -> float:
    """Approximate one-leg transaction cost fraction from the project's cost
    model, so the study's friction matches the rest of the project. Uses a
    mid-tier price for the spread leg (the study trades a basket, not one
    known price)."""
    costs = us_equity_costs() if preset == "us_equity" else CostModel()
    # buy leg ~ commission + half-spread; sell leg ~ fee+tax + half-spread.
    # average the two for a single "per-leg" rate.
    hs = costs.half_spread          # flat-mode half spread (both presets are flat here)
    buy_leg = costs.buy_commission + hs
    sell_leg = costs.sell_total + hs
    return (buy_leg + sell_leg) / 2.0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tickers", nargs="*", default=None,
                    help="explicit basket; default = an even sample of the chosen universe")
    ap.add_argument("--universe", default="idx", choices=["idx", "us"],
                    help="built-in sharia universe to sample when --tickers not given")
    ap.add_argument("--max-tickers", type=int, default=15,
                    help="basket size when sampling a universe (default 15)")
    ap.add_argument("--period", default="10y", help="yfinance history period (default 10y)")
    ap.add_argument("--every-days", type=int, default=63,
                    help="rebalance cadence in trading days (default 63 ≈ quarterly; 21 ≈ monthly)")
    ap.add_argument("--cost-preset", default="idx", choices=["idx", "us_equity"],
                    help="which cost model sets the per-rebalance friction (default idx)")
    ap.add_argument("--cost-rate", type=float, default=None,
                    help="override the per-leg cost fraction directly (e.g. 0 for frictionless)")
    ap.add_argument("--capital", type=float, default=100_000_000.0,
                    help="notional starting capital (only scales absolute cost figures)")
    args = ap.parse_args(argv)

    if args.tickers:
        tickers = args.tickers
    else:
        base = US_SHARIA_STOCKS if args.universe == "us" else ALL_SHARIA_STOCKS
        step = max(1, len(base) // args.max_tickers)
        tickers = base[::step][:args.max_tickers]

    cost_rate = args.cost_rate if args.cost_rate is not None else _one_leg_cost_rate(args.cost_preset)

    print(f"Fetching {len(tickers)} ticker(s), {args.period}...")
    closes = _fetch_closes(tickers, args.period)
    if len(closes) < 2:
        print("Not enough usable price history (need >= 2 names). Check network/tickers.",
              file=sys.stderr)
        return 1
    print(f"  {len(closes)} usable; running study (cost {cost_rate * 100:.2f}%/leg)...\n")

    cmp = compare_rebalancing(closes, capital=args.capital,
                              every_days=args.every_days, cost_rate=cost_rate)
    print(format_comparison(cmp, every_days=args.every_days, cost_rate=cost_rate))
    return 0


if __name__ == "__main__":
    sys.exit(main())
