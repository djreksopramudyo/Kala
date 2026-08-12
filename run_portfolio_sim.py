"""
Portfolio-level capacity study: how much of the validated per-trade edge does
a real account with N slots actually capture?

Everything validated so far is per-trade EV; this replays the SAME rules
(composite_score >= 60, entries.py vetoes, backtest.py fills/exits/costs/ARB)
through a portfolio with finite cash, max_positions slots, risk-based sizing,
lot rounding and the 5%-of-ADV liquidity cap — the constraints your paper
trader actually lives under (see kala/portfolio_sim.py for the fidelity
contract, which is unit-tested against backtest_ticker).

READ THE OUTPUT LIKE THIS
-------------------------
The grid is reported in full, on purpose: picking the single best-returning
max_positions in-sample would be the same selection trap as any other sweep.
Instead look for a ROBUST region — neighbouring grid points that agree, and
whose first-half/second-half returns tell the same story. If 8 and 10 slots
both beat 5 in both halves, that's evidence; if only 10 wins and only in one
half, that's noise. Also weigh max drawdown: a higher return with a much
deeper drawdown is not free money, it's a different risk appetite.

Usage:
    python run_portfolio_sim.py --period 5y --max-tickers 150
    python run_portfolio_sim.py --grid 3 5 8 10 15 --capital 10000000
"""

from __future__ import annotations

import argparse
import sys

import pandas as pd
import yfinance as yf

from kala.config import BacktestConfig, Config
from kala.portfolio_sim import run_grid
from kala.universe import ALL_SHARIA_STOCKS
from kala.walkforward import trade_stats
from run_walkforward import BENCHMARK, fetch


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tickers", nargs="*", default=None)
    ap.add_argument("--max-tickers", type=int, default=150)
    ap.add_argument("--period", default="5y")
    ap.add_argument("--capital", type=float, default=10_000_000,
                    help="starting capital, IDR (default 10jt)")
    ap.add_argument("--grid", nargs="*", type=int, default=[3, 5, 8, 10, 15],
                    help="max_positions values to simulate")
    ap.add_argument("--risk-pct", type=float, default=2.0)
    ap.add_argument("--threshold", type=float, default=60.0)
    ap.add_argument("--no-vetoes", action="store_true",
                    help="disable entries.py gating (diagnostic only)")
    args = ap.parse_args()

    if args.tickers:
        tickers = args.tickers
    else:
        step = max(1, len(ALL_SHARIA_STOCKS) // args.max_tickers)
        tickers = ALL_SHARIA_STOCKS[::step][:args.max_tickers]

    dfs = fetch(tickers, args.period)
    if not dfs:
        print("No usable data -- check network / period.", file=sys.stderr)
        return 1

    bench = yf.download(BENCHMARK, period=args.period, auto_adjust=True, progress=False)
    if isinstance(bench.columns, pd.MultiIndex):
        bench.columns = bench.columns.get_level_values(0)
    bench = bench.dropna(subset=["Close"])

    cfg = Config(backtest=BacktestConfig(score_entry_threshold=args.threshold))
    print(f"\n{len(dfs)} tickers, capital={args.capital:,.0f} IDR, risk={args.risk_pct}%/trade, "
          f"threshold={args.threshold:.0f}, vetoes={'OFF' if args.no_vetoes else 'ON'}")
    print("Simulating grid (one shared signal/veto pass)...\n")

    results = run_grid(dfs, benchmark=bench, cfg=cfg, start_capital=args.capital,
                       grid=tuple(args.grid), risk_pct=args.risk_pct,
                       apply_entry_vetoes=not args.no_vetoes)

    span = results[0].equity_curve.index
    b = bench["Close"]
    b = b.loc[(b.index >= span[0]) & (b.index <= span[-1])]
    ihsg = float((b.iloc[-1] / b.iloc[0] - 1.0) * 100.0) if len(b) >= 2 else float("nan")

    header = (f"{'slots':>6}{'total%':>9}{'half1%':>9}{'half2%':>9}{'maxDD%':>8}"
             f"{'expo%':>7}{'trades':>8}{'EV%':>7}{'win%':>6}{'no-slot':>9}")
    print(header)
    print("-" * len(header))
    for r in results:
        stats = trade_stats([t.net_return_pct for t in r.trades])
        h1, h2 = r.half_split()
        print(f"{r.max_positions:>6}{r.total_return_pct:>+8.1f}%{h1:>+8.1f}%{h2:>+8.1f}%"
             f"{r.max_drawdown_pct:>+7.1f}%{r.avg_exposure_pct:>6.0f}%{len(r.trades):>8}"
             f"{stats['ev_pct']:>+6.2f}%{stats['win_rate_pct']:>5.0f}%{r.n_no_slot:>9}")
    print("-" * len(header))
    print(f"IHSG buy & hold over the same span: {ihsg:+.1f}%")
    print(f"(signals cleared threshold: {results[0].n_signals}, vetoed: {results[0].n_vetoed} "
         f"-- identical across grid points by construction)")
    print("\nRemember: prefer the ROBUST region (neighbours + both halves agree), "
         "not the single best row.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
