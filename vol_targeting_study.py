"""
Run the volatility-targeting study on real data: does scaling total equity
exposure by recent realized volatility (Moreira-Muir) beat staying 100%
invested — in a sharia (de-risk-only, no leverage) form? See
kala/vol_targeting_backtest.py's module docstring for why the no-leverage
constraint is expected to strip most of the textbook benefit.

Network access happens ONLY here (yfinance). Pure logic + math live in
kala.vol_targeting_backtest and are unit-tested offline.

Usage:
    python vol_targeting_study.py                                 # default IDX sharia sample, 10y
    python vol_targeting_study.py --tickers TLKM.JK ICBP.JK KLBF.JK
    python vol_targeting_study.py --universe us --cost-preset us_equity
    python vol_targeting_study.py --target-vol 0.15 --vol-window 42
    python vol_targeting_study.py --cost-rate 0                   # frictionless (dishonest, comparison)
"""

from __future__ import annotations

import argparse
import sys

import pandas as pd
import yfinance as yf

from kala.config import CostModel, us_equity_costs
from kala.universe import ALL_SHARIA_STOCKS, US_SHARIA_STOCKS
from kala.vol_targeting_backtest import compare_vol_targeting, format_vol_targeting


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
    buy_leg = costs.buy_commission + hs
    sell_leg = costs.sell_total + hs
    return (buy_leg + sell_leg) / 2.0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tickers", nargs="*", default=None,
                    help="explicit basket; default = an even sample of the chosen universe")
    ap.add_argument("--universe", default="idx", choices=["idx", "us"])
    ap.add_argument("--max-tickers", type=int, default=12)
    ap.add_argument("--period", default="10y", help="yfinance history period (default 10y)")
    ap.add_argument("--target-vol", type=float, default=0.20,
                    help="annualized vol the overlay targets (default 0.20 = 20%%/yr)")
    ap.add_argument("--vol-window", type=int, default=21,
                    help="trailing days for realized-vol estimate (default 21 ≈ 1mo)")
    ap.add_argument("--cost-preset", default="idx", choices=["idx", "us_equity"])
    ap.add_argument("--cost-rate", type=float, default=None,
                    help="override per-exposure-change cost fraction (e.g. 0 for frictionless)")
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
    print(f"  {len(closes)} usable; running study (cost {cost_rate * 100:.2f}%/change)...\n")

    cmp = compare_vol_targeting(closes, target_vol=args.target_vol,
                                vol_window=args.vol_window, cost_rate=cost_rate)
    print(format_vol_targeting(cmp, cost_rate=cost_rate))
    return 0


if __name__ == "__main__":
    sys.exit(main())
