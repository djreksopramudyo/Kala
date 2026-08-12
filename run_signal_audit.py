"""
Grade a signal service's calls the way run_walkforward grades your own edge.

Feed it a CSV/JSON log of published signals — ideally logged FORWARD, the day
each was posted, before you knew the outcome — and it resolves every one
against real price history, net of IDX costs, benchmark-relative, counting
the losers and the never-filled ones the ad quietly drops.

CSV columns (header required): ticker,date,entry,take_profit,stop_loss
  BBRI.JK,2026-07-14,4200,4500,4000
  KOBX.JK,2026-07-15,340,375,318
JSON: a list of {"ticker","date","entry","take_profit","stop_loss"} objects.

Ticker must be the yfinance symbol (append .JK for IDX). Date is the
PUBLICATION date; the signal is acted on the next bar (no look-ahead).

Usage:
    python run_signal_audit.py signals.csv
    python run_signal_audit.py signals.csv --tick-spread --service "Zeta AI IDX"
    python run_signal_audit.py signals.json --period 1y --max-hold 20

Network access happens ONLY here — kala.signal_audit is pure logic.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys

import pandas as pd
import yfinance as yf

from kala.config import Config, CostModel
from kala.signal_audit import Signal, audit_signals

BENCHMARK = "^JKSE"


def load_signals(path: str) -> list[Signal]:
    if path.lower().endswith(".json"):
        with open(path, encoding="utf-8") as fh:
            rows = json.load(fh)
    else:
        with open(path, newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
    out = []
    for r in rows:
        out.append(Signal(ticker=str(r["ticker"]).strip(),
                          date=str(r["date"]).strip(),
                          entry=float(r["entry"]),
                          take_profit=float(r["take_profit"]),
                          stop_loss=float(r["stop_loss"])))
    return out


def fetch(tickers: list[str], period: str) -> dict[str, pd.DataFrame]:
    raw = yf.download(tickers, period=period, group_by="ticker",
                      auto_adjust=True, progress=False, threads=True)
    dfs: dict[str, pd.DataFrame] = {}
    for t in tickers:
        try:
            df = raw[t].dropna(subset=["Close"]) if len(tickers) > 1 else raw.dropna(subset=["Close"])
        except KeyError:
            continue
        if len(df):
            dfs[t] = df[["Open", "High", "Low", "Close", "Volume"]]
    return dfs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("signals", help="CSV or JSON log of published signals")
    ap.add_argument("--period", default="1y", help="yfinance history to fetch (default 1y)")
    ap.add_argument("--service", default="signal service", help="name for the report header")
    ap.add_argument("--tick-spread", action="store_true",
                    help="tick-floored spread costs (honest for cheap stocks)")
    ap.add_argument("--fill-window", type=int, default=3,
                    help="bars the limit entry stays live before NO_FILL (default 3)")
    ap.add_argument("--max-hold", type=int, default=20,
                    help="bars to hold before EXPIRED if neither TP nor SL hits (default 20)")
    args = ap.parse_args()

    signals = load_signals(args.signals)
    if not signals:
        print("No signals in the file.", file=sys.stderr)
        return 1

    tickers = sorted({s.ticker for s in signals})
    print(f"Auditing {len(signals)} signal(s) across {len(tickers)} ticker(s), "
          f"spread={'tick-floored' if args.tick_spread else 'flat 0.10%'}...")
    dfs = fetch(tickers, args.period)
    if not dfs:
        print("No usable price data — check tickers / network / period.", file=sys.stderr)
        return 1

    bench = yf.download(BENCHMARK, period=args.period, auto_adjust=True, progress=False)
    if isinstance(bench.columns, pd.MultiIndex):
        bench.columns = bench.columns.get_level_values(0)
    bench = bench.dropna(subset=["Close"]) if len(bench) else None

    cfg = Config(costs=CostModel(spread_mode="tick_floor" if args.tick_spread else "flat"))
    report = audit_signals(signals, dfs, cfg=cfg, benchmark=bench,
                           fill_window_bars=args.fill_window, max_hold_bars=args.max_hold)
    print()
    print(report.summary_text(service=args.service))
    return 0


if __name__ == "__main__":
    sys.exit(main())
