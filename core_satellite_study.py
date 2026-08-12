"""
Run the core-satellite study on real data: does a concentrated hand-picked
satellite sleeve earn its keep next to a broad index core, or would that
money have been better off in the core too?

This follows from the holdings-count curve (see PROJECT_STATUS.md): risk kept
falling as the number of names held rose and had not flattened by K=16, which
is prior evidence a ~8-name sleeve carries real extra risk. Whether it PAYS
for that risk is what this measures. See kala/core_satellite_backtest.py's
module docstring for the arms, the rolling-window robustness check, and the
short-history caveat (IDX index ETFs are young — if the core has less history
than the satellites, the study shortens and says so loudly).

Network access happens ONLY here (yfinance). Pure logic + math live in
kala.core_satellite_backtest and are unit-tested offline.

Usage:
    # the user's actual allocation: XIJI core + the 8 verified-sharia satellites
    python core_satellite_study.py --core XIJI.JK \
        --satellites TLKM.JK UNVR.JK ICBP.JK KLBF.JK ANTM.JK INDF.JK BRIS.JK SMGR.JK

    # if XIJI's history is too short, try a longer-lived IDX index proxy:
    python core_satellite_study.py --core ^JKSE --satellites TLKM.JK UNVR.JK ...

    python core_satellite_study.py --core-weight 0.5    # 50/50 instead of 73/27
"""

from __future__ import annotations

import argparse
import sys

import pandas as pd
import yfinance as yf

from kala.core_satellite_backtest import (
    compare_core_satellite,
    format_core_satellite,
    format_sizing_sweep,
    sweep_core_weight,
)


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


def _diagnose(name: str, s: pd.Series) -> None:
    """Print the raw shape of a price series: date range, start/end price, and
    year-by-year return. A "core index" that underperforms its own individual
    constituents by a wide margin for years running is unusual enough to check
    for a data artifact (a bad split adjustment, a flat/stale backfill before
    real listing, thin/no trading) BEFORE trusting the comparison it feeds —
    the same discipline this project already applied to the min-price
    look-ahead bug. This is inspection only; it doesn't change the backtest."""
    s = s.dropna()
    if s.empty:
        print(f"  {name}: no data")
        return
    print(f"  {name}: {s.index[0].date()} ({s.iloc[0]:.2f}) -> "
          f"{s.index[-1].date()} ({s.iloc[-1]:.2f}), {len(s)} bars")
    by_year = s.groupby(s.index.year)
    yearly = []
    for yr, grp in by_year:
        if len(grp) < 2:
            continue
        ret = grp.iloc[-1] / grp.iloc[0] - 1.0
        yearly.append(f"{yr}:{ret * 100:+.0f}%")
    print(f"    year-over-year: {'  '.join(yearly)}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--core", default="XIJI.JK",
                    help="broad index/ETF ticker for the core (default XIJI.JK)")
    ap.add_argument("--satellites", nargs="+", required=True,
                    help="the concentrated satellite names")
    ap.add_argument("--core-weight", type=float, default=0.73,
                    help="core share of the EQUITY sleeve (default 0.73 = the user's "
                         "55%% XIJI vs 20%% satellites, normalized within equity)")
    ap.add_argument("--period", default="10y")
    ap.add_argument("--subwindow-days", type=int, default=504,
                    help="rolling window length for the win-rate check (default 504 ≈ 2y)")
    ap.add_argument("--sweep", action="store_true",
                    help="also sweep the core weight 0%%..100%% to show the shape of the "
                         "sizing tradeoff (NOT for picking an optimum -- see the output)")
    args = ap.parse_args(argv)

    all_tickers = [args.core] + list(args.satellites)
    print(f"Fetching core '{args.core}' + {len(args.satellites)} satellite(s), "
          f"{args.period}...")
    data = _fetch(all_tickers, args.period)
    if args.core not in data:
        print(f"No usable history for the core ticker '{args.core}'. "
              f"Check it exists on yfinance (IDX ETFs are often thin/young); "
              f"try --core ^JKSE as an index proxy.", file=sys.stderr)
        return 1
    sats = {t: s for t, s in data.items() if t != args.core}
    if not sats:
        print("No usable satellite history.", file=sys.stderr)
        return 1
    print(f"  core + {len(sats)} satellite(s) usable.\n")

    print("DATA DIAGNOSTIC — check the core's own shape before trusting the "
          "comparison it feeds:")
    _diagnose(args.core, data[args.core])
    for t, s in sats.items():
        _diagnose(t, s)
    print()

    cmp = compare_core_satellite(data[args.core], sats,
                                 core_weight=args.core_weight,
                                 subwindow_days=args.subwindow_days,
                                 core_ticker=args.core)
    print(format_core_satellite(cmp))
    if args.sweep:
        print()
        print(format_sizing_sweep(sweep_core_weight(data[args.core], sats,
                                                    core_ticker=args.core)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
