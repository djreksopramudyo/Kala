"""
Structural diagnostic: does wiring entries.py's guardrails (RSI overbought,
parabolic ROC20, OBV distribution, thin volume, and the bear-regime block)
into the backtest change out-of-sample results -- especially in the most
recent, sharply bearish folds?

This does NOT touch score_entry_threshold, score weights, or any stop/target
percentage -- both runs use the identical fixed threshold, so the ONLY thing
that differs is BacktestConfig.apply_entry_vetoes. That isolates the effect
of one structural realism fix (the live bot already runs every BUY candidate
through entries.evaluate_entry; the backtest historically did not) instead of
mixing it with a parameter search.

Usage (same universe/period as a normal walk-forward run):
    python diagnose_bear_folds.py --period 5y --train-bars 252 --test-bars 63
    python diagnose_bear_folds.py --max-tickers 150 --period 5y

Network access happens only here, same as run_walkforward.py.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter

import pandas as pd
import yfinance as yf

from kala.backtest import backtest_ticker
from kala.config import BacktestConfig, Config
from kala.universe import ALL_SHARIA_STOCKS
from kala.walkforward import make_folds, trade_stats
from run_walkforward import BENCHMARK, fetch


def _window_slice(df: pd.DataFrame, entry_start, entry_end, warmup_bars: int, exit_grace_bars: int):
    idx = df.index
    lo = max(0, int(idx.searchsorted(entry_start)) - warmup_bars)
    hi = min(len(idx), int(idx.searchsorted(entry_end, side="right")) + exit_grace_bars)
    return df.iloc[lo:hi]


def run_fold(dfs, bench, fold, cfg: Config, warmup_bars: int = 60):
    """Pooled OOS returns + veto diagnostics for one fold's TEST window."""
    exit_grace = cfg.backtest.holding_max_days + 5
    returns: list[float] = []
    veto_counts: Counter = Counter()
    n_signals = 0
    n_vetoed = 0
    for ticker, df in dfs.items():
        window = _window_slice(df, fold.test_start, fold.test_end, warmup_bars, exit_grace)
        if len(window) < warmup_bars // 2:
            continue
        res = backtest_ticker(ticker, window, benchmark=bench, cfg=cfg)
        returns.extend(t.net_return_pct for t in res.closed
                       if fold.test_start <= pd.Timestamp(t.entry_date) <= fold.test_end)
        n_signals += res.n_signals
        n_vetoed += res.n_vetoed
        veto_counts.update(res.veto_counts)
    return returns, n_signals, n_vetoed, veto_counts


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tickers", nargs="*", default=None)
    ap.add_argument("--max-tickers", type=int, default=60)
    ap.add_argument("--period", default="5y")
    ap.add_argument("--train-bars", type=int, default=252)
    ap.add_argument("--test-bars", type=int, default=63)
    ap.add_argument("--threshold", type=float, default=60.0,
                    help="fixed entry threshold used for BOTH runs -- isolates the veto effect (default: production baseline, 60)")
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

    master = pd.DatetimeIndex(sorted(set().union(*[set(df.index) for df in dfs.values()])))
    folds = make_folds(master, args.train_bars, args.test_bars, warmup_bars=60)
    if not folds:
        print("Not enough history for even one fold -- shorten --train-bars/--test-bars or lengthen --period.", file=sys.stderr)
        return 1

    cfg_off = Config(backtest=BacktestConfig(score_entry_threshold=args.threshold, apply_entry_vetoes=False))
    cfg_on = Config(backtest=BacktestConfig(score_entry_threshold=args.threshold, apply_entry_vetoes=True))

    print(f"{len(dfs)} tickers, {len(folds)} folds, fixed threshold={args.threshold:.0f} "
          f"(only apply_entry_vetoes differs between the two columns)\n")
    header = f"{'fold':<5}{'test window':<26}{'EV off':>9}{'EV on':>9}{'n off':>7}{'n on':>7}{'IHSG%':>8}"
    print(header)
    print("-" * len(header))

    pooled_off: list[float] = []
    pooled_on: list[float] = []

    for fold in folds:
        ret_off, sig_off, vet_off, cats_off = run_fold(dfs, None, fold, cfg_off)
        ret_on, sig_on, vet_on, cats_on = run_fold(dfs, bench, fold, cfg_on)
        stats_off = trade_stats(ret_off)
        stats_on = trade_stats(ret_on)
        pooled_off.extend(ret_off)
        pooled_on.extend(ret_on)

        b = bench["Close"]
        b = b.loc[(b.index >= fold.test_start) & (b.index <= fold.test_end)]
        bench_ret = float((b.iloc[-1] / b.iloc[0] - 1.0) * 100.0) if len(b) >= 2 else float("nan")

        win = f"{fold.test_start.date()}..{fold.test_end.date()}"
        print(f"{fold.fold_id:<5}{win:<26}{stats_off['ev_pct']:>+8.2f}%{stats_on['ev_pct']:>+8.2f}%"
             f"{stats_off['n']:>7}{stats_on['n']:>7}{bench_ret:>+7.1f}%")
        if cats_on:
            fired = ", ".join(f"{k}={v}" for k, v in cats_on.most_common())
            print(f"      vetoed {vet_on}/{sig_on} candidates this fold ({fired})")

    print("-" * len(header))
    s_off, s_on = trade_stats(pooled_off), trade_stats(pooled_on)
    print(f"POOLED, vetoes OFF (what you already ran): trades={s_off['n']}  "
         f"EV/trade={s_off['ev_pct']:+.2f}%  win={s_off['win_rate_pct']:.0f}%  "
         f"PF={s_off['profit_factor']:.2f}  t={s_off['t_stat']:.2f}")
    print(f"POOLED, vetoes ON  (entries.py guardrails applied): trades={s_on['n']}  "
         f"EV/trade={s_on['ev_pct']:+.2f}%  win={s_on['win_rate_pct']:.0f}%  "
         f"PF={s_on['profit_factor']:.2f}  t={s_on['t_stat']:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
