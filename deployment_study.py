"""
Run the deployment study on real data: lump sum vs DCA (nyicil). Given money
you have NOW and a basket you've already chosen, is it better to buy it all
today or spread it over N months? See kala/deployment_backtest.py's module
docstring for why the honest verdict reports BOTH the average-case winner and
the worst-case protection (a return-only answer would be misleading).

Network access happens ONLY here (yfinance). Pure logic + math live in
kala.deployment_backtest and are unit-tested offline.

Usage:
    python deployment_study.py --tickers TLKM.JK UNVR.JK ICBP.JK KLBF.JK ANTM.JK INDF.JK BRIS.JK SMGR.JK --period 10y
    python deployment_study.py --dca-months 6            # 6 monthly slices instead of 12
    python deployment_study.py --horizon-days 1260       # 5-year holding period
    python deployment_study.py --cash-yield 0.04         # idle cash earns 4%/yr (DCA's best case)
    python deployment_study.py --universe us --cost-preset us_equity
"""

from __future__ import annotations

import argparse
import sys

import pandas as pd
import yfinance as yf

from kala.config import CostModel, us_equity_costs
from kala.deployment_backtest import compare_deployment, format_deployment
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


def _one_leg_cost_rate(preset: str) -> float:
    costs = us_equity_costs() if preset == "us_equity" else CostModel()
    hs = costs.half_spread
    return costs.buy_commission + hs        # deployment is buy-side only


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tickers", nargs="*", default=None)
    ap.add_argument("--universe", default="idx", choices=["idx", "us"])
    ap.add_argument("--max-tickers", type=int, default=12)
    ap.add_argument("--period", default="10y")
    ap.add_argument("--horizon-days", type=int, default=756,
                    help="holding period after deployment starts (default 756 ≈ 3y)")
    ap.add_argument("--dca-months", type=int, default=12,
                    help="number of equal monthly slices for the DCA arm (default 12)")
    ap.add_argument("--cash-yield", type=float, default=0.0,
                    help="annual return on not-yet-deployed cash (default 0.0; "
                         "set positive to give DCA its fair best case)")
    ap.add_argument("--step-days", type=int, default=5,
                    help="spacing between rolling start dates (default 5 = weekly)")
    ap.add_argument("--cost-preset", default="idx", choices=["idx", "us_equity"])
    ap.add_argument("--cost-rate", type=float, default=None)
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
    if not closes:
        print("Not enough usable price history. Check network/tickers.", file=sys.stderr)
        return 1
    print(f"  {len(closes)} usable; running study (buy cost {cost_rate * 100:.2f}%)...\n")

    cmp = compare_deployment(closes, horizon_days=args.horizon_days,
                             dca_months=args.dca_months, cost_rate=cost_rate,
                             cash_yield_annual=args.cash_yield,
                             step_days=args.step_days)
    print(format_deployment(cmp, cost_rate=cost_rate))
    return 0


if __name__ == "__main__":
    sys.exit(main())
