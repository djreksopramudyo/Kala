"""
Score your REAL trades against simply holding the benchmark — the alpha check
applied to actual money instead of history.

Reads paper_state.json (open positions + the closed-trade log), fetches
current prices and the benchmark's history, and measures each trade against
what the benchmark did over THAT TRADE'S OWN holding window. See
kala/live_scorecard.py's module docstring for why the per-window comparison
matters, and for the small-sample warning that applies to every result here.

Network access happens ONLY in this file. The scoring logic lives in
kala.live_scorecard and is unit-tested offline.

Usage:
    python live_scorecard.py                          # vs XIJI, IDX round-trip costs
    python live_scorecard.py --benchmark ^JKSE        # vs IHSG instead
    python live_scorecard.py --cost-rate 0            # gross, no friction (flattering)
    python live_scorecard.py --open-only              # ignore closed trades
    python live_scorecard.py --state some_state.json
"""

from __future__ import annotations

import argparse
import json
import sys

import yfinance as yf

from kala.live_scorecard import fetch_benchmark, format_scorecard, round_trip_cost, score_live


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--state", default="paper_state.json")
    ap.add_argument("--benchmark", default="XIJI.JK",
                    help="what you'd otherwise have held (default XIJI.JK)")
    ap.add_argument("--period", default="1y",
                    help="benchmark history to fetch (default 1y; must cover your "
                         "earliest entry date)")
    ap.add_argument("--cost-rate", type=float, default=None,
                    help="round-trip friction as a fraction; default = the project's "
                         "IDX cost model. Pass 0 for a gross (flattering) comparison.")
    ap.add_argument("--open-only", action="store_true",
                    help="score only currently-open positions, skipping closed trades")
    args = ap.parse_args(argv)

    try:
        state = json.load(open(args.state))
    except FileNotFoundError:
        print(f"No state file at {args.state}.", file=sys.stderr)
        return 1

    tickers = sorted(state.get("positions", {}) or {})
    if not tickers and args.open_only:
        print("No open positions to score.", file=sys.stderr)
        return 1

    cost_rate = args.cost_rate if args.cost_rate is not None else round_trip_cost()

    print(f"Fetching {len(tickers)} held ticker(s) + benchmark '{args.benchmark}'...")
    prices: dict[str, float] = {}
    if tickers:
        try:
            raw = yf.download(tickers, period="5d", group_by="ticker",
                              auto_adjust=True, progress=False, threads=True)
            for t in tickers:
                try:
                    s = (raw[t]["Close"] if len(tickers) > 1 else raw["Close"]).dropna()
                    if len(s):
                        prices[t] = float(s.iloc[-1])
                except (KeyError, IndexError):
                    continue
        except Exception as e:
            print(f"Price download failed: {e}", file=sys.stderr)

    missing = [t for t in tickers if t not in prices]
    if missing:
        print(f"  WARNING: no current price for {', '.join(missing)} — "
              f"these are EXCLUDED from the scorecard, so the totals below "
              f"cover only the priced subset.", file=sys.stderr)

    bench = fetch_benchmark(args.benchmark, args.period)
    if bench is None or not len(bench):
        print(f"  WARNING: no data for benchmark '{args.benchmark}' — every trade's "
              f"benchmark column will read 0.0 and the comparison is MEANINGLESS. "
              f"Check the ticker before trusting anything below.", file=sys.stderr)

    print(f"  {len(prices)}/{len(tickers)} priced; friction "
          f"{cost_rate * 100:.2f}%/round trip.\n")

    sc = score_live(state, prices, benchmark_series=bench,
                    benchmark_name=args.benchmark, cost_rate=cost_rate,
                    include_closed=not args.open_only)
    print(format_scorecard(sc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
