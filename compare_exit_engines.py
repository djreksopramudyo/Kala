"""
A/B: the VALIDATED exit rules vs the LIVE exit engine, on identical entries.

Arm A (validated): backtest.backtest_ticker — take-profit, governing stop,
    death-cross event, max holding period. These four rules produced every
    validated number in this project (walk-forward t=3.06, portfolio sim).
Arm B (live):      backtest_live_exits.backtest_ticker_live_exits —
    exits.evaluate_exit + papertrade.step's queueing rule, exactly as the
    live paper trader manages your real positions.

HISTORY: the first run of this A/B (2026-07, 55 tickers / 5y) measured the
pre-v3.3 live engine at -0.21%/trade vs +0.37% for the validated rules — the
never-validated MACD-reversal rule alone caused 63% of exits. exits.py v3.3
demoted the unvalidated rules to ADVISORY and papertrade gained the missing
max-hold exit. Since this script models the CURRENT live path, re-running it
now is the regression check: B should track A closely (identical rule set;
only fill-time ARB mechanics differ slightly).

Both arms use the identical entry rule (composite_score >= threshold, entry
vetoes ON, same regime source) and identical costs/ARB mechanics. Entry
RULE, not entry timestamps: once the arms' exits diverge, so does when each
is flat and able to re-enter — that feedback is part of the engine being
measured, not a flaw in the comparison.

How to read the output:
  * EV/trade is the headline, as always. If B's EV is clearly lower, the
    live engine's extra rules are bleeding validated edge (likely shaking
    out winners before the +8% target) and the live exit set should be
    simplified toward A. If B is clearly higher, the extra rules earn their
    keep and A's numbers UNDERSTATE your live system. If they're close,
    the divergence doesn't matter much in practice — also an answer.
  * eod-tagged trades (couldn't finish before the data ended) are counted
    separately per arm; B has no max-hold so it strands more. If eod counts
    are large relative to n, treat the comparison as weaker.
  * This is a FIXED-config A/B — nothing is fitted, so there is no
    train/test split to worry about. But it is still one historical draw:
    prefer a decisive gap over a small one before changing the live engine.

Usage:
    python compare_exit_engines.py --period 5y --max-tickers 60
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter

import pandas as pd
import yfinance as yf

from kala.backtest import backtest_ticker
from kala.backtest_live_exits import backtest_ticker_live_exits
from kala.config import BacktestConfig, Config, CostModel
from kala.edge import reason_bucket as _reason_bucket  # shared with /edge
from kala.universe import ALL_SHARIA_STOCKS
from kala.walkforward import trade_stats
from run_walkforward import BENCHMARK, fetch


def _arm_stats(results) -> dict:
    trades = [t for r in results for t in r.closed]
    eod = [t for t in trades if "(eod)" in t.exit_reason]
    live = [t for t in trades if "(eod)" not in t.exit_reason]
    stats = trade_stats([t.net_return_pct for t in live])
    hold_days = [(pd.Timestamp(t.exit_date) - pd.Timestamp(t.entry_date)).days
                 for t in live]
    stats["avg_hold_days"] = (sum(hold_days) / len(hold_days)) if hold_days else 0.0
    stats["n_eod_excluded"] = len(eod)
    stats["reasons"] = Counter(_reason_bucket(t.exit_reason) for t in live)
    return stats


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tickers", nargs="*", default=None)
    ap.add_argument("--max-tickers", type=int, default=60)
    ap.add_argument("--period", default="5y")
    ap.add_argument("--threshold", type=float, default=60.0)
    ap.add_argument("--tick-spread", action="store_true",
                    help="floor the half-spread at half of one IDX tick at the fill "
                         "price (honest costs for cheap stocks) instead of the flat "
                         "0.10%% assumption every historical number used")
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

    cfg = Config(backtest=BacktestConfig(score_entry_threshold=args.threshold,
                                         apply_entry_vetoes=True),
                 costs=CostModel(spread_mode="tick_floor" if args.tick_spread else "flat"))

    print(f"\n{len(dfs)} tickers, threshold={args.threshold:.0f}, vetoes ON, "
          f"spread={'tick-floored' if args.tick_spread else 'flat 0.10%'}, "
          f"full {args.period} history, identical entry rule in both arms.\n")

    print("Running arm A (validated 4-rule exits)...")
    res_a = [backtest_ticker(t, df, benchmark=bench, cfg=cfg) for t, df in dfs.items()]
    print("Running arm B (live 8-rule exit engine, URGENT/CONSIDER) — slower...")
    res_b = [backtest_ticker_live_exits(t, df, benchmark=bench, cfg=cfg)
             for t, df in dfs.items()]

    a, b = _arm_stats(res_a), _arm_stats(res_b)

    header = f"{'':<28}{'A: validated':>15}{'B: live engine':>16}"
    print("\n" + header)
    print("-" * len(header))
    for label, key, fmt in (("trades", "n", "{:d}"),
                            ("EV/trade", "ev_pct", "{:+.2f}%"),
                            ("median", "median_pct", "{:+.2f}%"),
                            ("win rate", "win_rate_pct", "{:.0f}%"),
                            ("profit factor", "profit_factor", "{:.2f}"),
                            ("t-stat", "t_stat", "{:.2f}"),
                            ("avg hold (calendar days)", "avg_hold_days", "{:.1f}"),
                            ("eod-stranded (excluded)", "n_eod_excluded", "{:d}")):
        print(f"{label:<28}{fmt.format(a[key]):>15}{fmt.format(b[key]):>16}")
    print("-" * len(header))
    print("Exit reasons, arm A:", dict(a["reasons"].most_common()))
    print("Exit reasons, arm B:", dict(b["reasons"].most_common()))
    print("\nRead §'How to read the output' in this file's docstring before acting.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
