"""
GARCH volatility-sizing CLI — the "skill" wrapper around kala.volatility.

Fetches a ticker's recent history, fits GARCH(1,1) to its daily returns,
forecasts near-term volatility, and prints the risk_pct multiplier that
forecast implies against a reference volatility (default: the stock's own
long-run/unconditional GARCH volatility, so "calmer than usual" scales up
and "more volatile than usual" scales down).

This is a sizing CALCULATOR, not a signal — it does not decide whether to
buy anything. Feed its suggested risk_pct into an existing call to
PaperTrader.size_position(risk_pct=...) if you want to try it live.

Usage:
    python garch_size.py --ticker BBCA.JK
    python garch_size.py --ticker BBCA.JK --base-risk-pct 2.0 --period 2y
"""

from __future__ import annotations

import argparse
import sys

import yfinance as yf

from kala.volatility import fit_garch11, forecast_volatility, scaled_risk_pct


def main() -> int:
    ap = argparse.ArgumentParser(description="GARCH(1,1) volatility-scaled risk_pct for one ticker")
    ap.add_argument("--ticker", required=True, help="e.g. BBCA.JK")
    ap.add_argument("--period", default="2y", help="yfinance period (default 2y)")
    ap.add_argument("--base-risk-pct", type=float, default=2.0,
                    help="the flat risk_pct you'd otherwise use (default 2.0)")
    ap.add_argument("--min-scale", type=float, default=0.5)
    ap.add_argument("--max-scale", type=float, default=1.5)
    args = ap.parse_args()

    df = yf.download(args.ticker, period=args.period, auto_adjust=True, progress=False)
    if df is None or len(df) < 90:
        print(f"Not enough history for {args.ticker} (need >= 90 bars).", file=sys.stderr)
        return 1
    if hasattr(df.columns, "get_level_values"):
        df.columns = df.columns.get_level_values(0)

    returns = df["Close"].pct_change().dropna().to_numpy()
    params = fit_garch11(returns)
    if params is None:
        print(f"Could not fit GARCH(1,1) for {args.ticker} "
             "(insufficient history or zero-variance series).", file=sys.stderr)
        return 1

    forecast_vol = forecast_volatility(returns, params)
    reference_vol = (params.long_run_var ** 0.5)
    suggested = scaled_risk_pct(args.base_risk_pct, forecast_vol, reference_vol,
                                min_scale=args.min_scale, max_scale=args.max_scale)

    print(f"{args.ticker}: GARCH(1,1) alpha={params.alpha:.2f} beta={params.beta:.2f} "
         f"(persistence={params.alpha + params.beta:.2f})")
    print(f"  forecast daily vol : {forecast_vol * 100:.2f}%")
    print(f"  long-run daily vol : {reference_vol * 100:.2f}%")
    print(f"  base risk_pct      : {args.base_risk_pct:.2f}%")
    print(f"  scaled risk_pct    : {suggested:.2f}%  "
         f"({'more volatile than usual -> sized down' if forecast_vol > reference_vol else 'calmer than usual -> sized up'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
