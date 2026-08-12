"""
Run the weighting-scheme study on real data: does an OPTIMIZED weighting
(min-variance, inverse-vol) of a fixed basket beat naive equal weight (1/N)
out of sample, after costs? See kala/weighting_backtest.py's module docstring
for why 1/N is the honest thing to beat (DeMiguel-Garlappi-Uppal 2009) and
why the expected result is "lower vol, not better Sharpe."

Network access happens ONLY here (yfinance). Pure logic + math live in
kala.weighting_backtest and are unit-tested offline.

Usage:
    python weighting_study.py                                  # default IDX sharia sample, 10y, quarterly
    python weighting_study.py --tickers TLKM.JK ICBP.JK KLBF.JK ANTM.JK
    python weighting_study.py --universe us --cost-preset us_equity
    python weighting_study.py --every-days 21    # monthly rebalance
    python weighting_study.py --lookback 252     # estimate weights from 12mo instead of 6mo
    python weighting_study.py --cost-rate 0      # frictionless (dishonest, for comparison)
"""

from __future__ import annotations

import argparse
import sys

import pandas as pd
import yfinance as yf

from kala.config import CostModel, us_equity_costs
from kala.universe import ALL_SHARIA_STOCKS, US_SHARIA_STOCKS
from kala.weighting_backtest import compare_weighting, format_weighting_comparison


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


def _one_leg_cost_rate(preset: str) -> float:
    """Approximate one-leg transaction cost fraction from the project's cost
    model — same derivation as rebalance_study.py, so the two studies share
    honest cost assumptions."""
    costs = us_equity_costs() if preset == "us_equity" else CostModel()
    hs = costs.half_spread
    buy_leg = costs.buy_commission + hs
    sell_leg = costs.sell_total + hs
    return (buy_leg + sell_leg) / 2.0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tickers", nargs="*", default=None,
                    help="explicit basket; default = an even sample of the chosen universe")
    ap.add_argument("--universe", default="idx", choices=["idx", "us"])
    ap.add_argument("--max-tickers", type=int, default=12,
                    help="basket size when sampling a universe (default 12)")
    ap.add_argument("--period", default="10y", help="yfinance history period (default 10y)")
    ap.add_argument("--every-days", type=int, default=63,
                    help="rebalance cadence in trading days (default 63 ≈ quarterly)")
    ap.add_argument("--lookback", type=int, default=126,
                    help="trailing days used to estimate weights (default 126 ≈ 6mo)")
    ap.add_argument("--cost-preset", default="idx", choices=["idx", "us_equity"])
    ap.add_argument("--cost-rate", type=float, default=None,
                    help="override the per-leg cost fraction directly (e.g. 0 for frictionless)")
    ap.add_argument("--capital", type=float, default=100_000_000.0)
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

    cmp = compare_weighting(closes, capital=args.capital, every_days=args.every_days,
                            lookback=args.lookback, cost_rate=cost_rate)
    print(format_weighting_comparison(cmp, cost_rate=cost_rate))
    return 0


if __name__ == "__main__":
    sys.exit(main())
