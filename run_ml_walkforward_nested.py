"""
Nested-CV version of run_ml_walkforward.py.

The earlier version fixed (horizon, alpha) by hand -- I picked (10, 10),
then re-ran once with a different pre-committed pair (15, 20) as a
robustness check. That check FAILED: pooled t collapsed from +2.92 to
-0.12. The honest conclusion was that (10, 10) was a favorable draw, not a
real finding -- because the hyperparameters were chosen by guessing, then
validated by guessing again, never by held-out data.

This version fixes that structurally: for each OUTER fold (identical
train/test split to run_ml_walkforward.py), the outer TRAIN window is
itself split chronologically into an inner-train slice and an inner-val
slice. A small, pre-committed (horizon, alpha) grid is fit on inner-train
and scored on inner-val; the winner (by pooled EV, subject to a minimum-
trade guard) is what actually gets used for that fold -- chosen by data,
not by hand. The OUTER test window is never touched by this selection.

Per outer fold:
  1. inner-train / inner-val = 80/20 chronological split of the outer TRAIN
     window (never shuffled -- these are time series).
  2. Sweep HORIZON_GRID x ALPHA_GRID: fit on inner-train, evaluate pooled EV
     on inner-val at a FIXED threshold (0.0 -- "trade when predicted return
     is positive"). This is the ONLY use of inner-val data. The inner-val
     backtest slice STOPS EXACTLY at the outer fold's train_end -- no grace
     tail is allowed to extend into outer-test (see run_inner_val).
  3. Refit a scorer with the winning (horizon, alpha) on the FULL outer-train
     window, then choose the entry threshold via the same train-then-freeze
     sweep as run_ml_walkforward.py (ML_THRESHOLD_GRID, outer-train only).
  4. Evaluate the fully-frozen (scorer, threshold) on outer-test.

This costs roughly 2x per fold vs. the single-config version (9 inner
fit+backtest passes on top of the usual threshold sweep), so it's meant to
be run with MORE tickers than the default 60-sample -- more cross-sectional
breadth is the intended way to get "more data" here, not a longer period.
Pre-2019 IDX data is structurally less relevant, so stretching
--period further back trades relevance for sample size; widening --max-tickers
doesn't have that problem.

Usage (this is slow -- sanity-check small before committing to a big run):
    python run_ml_walkforward_nested.py --max-tickers 60 --period 5y    # sanity check
    python run_ml_walkforward_nested.py --max-tickers 200 --period 5y   # the real run
"""

from __future__ import annotations

import argparse
import sys

import pandas as pd
import yfinance as yf

from diagnose_bear_folds import run_fold
from kala.backtest import backtest_ticker
from kala.ml_scoring import fit_ridge_scorer
from kala.universe import ALL_SHARIA_STOCKS
from kala.walkforward import make_folds, trade_stats
from run_ml_walkforward import (
    ML_THRESHOLD_GRID,
    _baseline_cfg,
    _ml_cfg,
    _train_slice,
    pick_ml_threshold,
    run_fold_ml,
)
from run_walkforward import BENCHMARK, fetch

HORIZON_GRID = (5, 10, 20)
ALPHA_GRID = (5.0, 20.0, 50.0)
INNER_VAL_FRAC = 0.2
INNER_SELECT_THRESHOLD = 0.0   # fixed, not swept -- isolates the (horizon, alpha) choice
MIN_INNER_VAL_TRADES = 20
FALLBACK_HORIZON, FALLBACK_ALPHA = 10, 10.0  # used only if no grid point clears the guard


def inner_split(train_start: pd.Timestamp, train_end: pd.Timestamp,
                val_frac: float = INNER_VAL_FRAC) -> pd.Timestamp:
    """Chronological split point inside [train_start, train_end]. Everything
    before this is inner-train; everything from here to train_end is
    inner-val. Never shuffled -- these are time series."""
    span = train_end - train_start
    return train_start + span * (1.0 - val_frac)


def run_inner_val(dfs, bench, inner_val_start, train_end, scorer, threshold: float,
                  warmup_bars: int = 60) -> list[float]:
    """Pooled OOS-within-train returns for inner-val, evaluated with a
    scorer that only ever saw inner-train.

    Critically, this slices EXACTLY to train_end with NO exit-grace tail
    past it (unlike run_fold_ml's outer-window evaluation, which
    deliberately lets exits complete slightly past a window edge). Any
    position still open when the slice runs out just never closes and is
    silently excluded -- conservative, but leak-free: nothing here can ever
    see a single bar of the outer TEST window.
    """
    cfg = _ml_cfg(threshold)
    returns: list[float] = []
    for ticker, df in dfs.items():
        window = _train_slice(df, inner_val_start, train_end, warmup_bars)
        if len(window) < warmup_bars // 2:
            continue
        score = scorer.score(window)
        res = backtest_ticker(ticker, window, benchmark=bench, cfg=cfg, score_override=score)
        returns.extend(t.net_return_pct for t in res.closed
                       if inner_val_start <= pd.Timestamp(t.entry_date) <= train_end)
    return returns


def select_hyperparams(dfs, bench, train_start: pd.Timestamp, train_end: pd.Timestamp,
                       min_inner_val_trades: int = MIN_INNER_VAL_TRADES):
    """Inner-CV grid search for (horizon, alpha), using ONLY the outer
    fold's train window (split further into inner-train/inner-val here).
    Returns (horizon, alpha, diagnostic_dict_or_None)."""
    cutoff = inner_split(train_start, train_end)
    inner_train_dfs = {t: _train_slice(df, train_start, cutoff) for t, df in dfs.items()}
    inner_train_dfs = {t: d for t, d in inner_train_dfs.items() if len(d) > 80}

    best = None  # (horizon, alpha, ev, n)
    for horizon in HORIZON_GRID:
        for alpha in ALPHA_GRID:
            scorer = fit_ridge_scorer(inner_train_dfs, horizon=horizon, alpha=alpha)
            if scorer is None:
                continue
            returns = run_inner_val(dfs, bench, cutoff, train_end, scorer, INNER_SELECT_THRESHOLD)
            stats = trade_stats(returns)
            if stats["n"] >= min_inner_val_trades and (best is None or stats["ev_pct"] > best[2]):
                best = (horizon, alpha, stats["ev_pct"], stats["n"])

    if best is None:
        return FALLBACK_HORIZON, FALLBACK_ALPHA, None
    return best[0], best[1], {"inner_val_ev_pct": best[2], "inner_val_n": best[3]}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tickers", nargs="*", default=None)
    ap.add_argument("--max-tickers", type=int, default=60)
    ap.add_argument("--period", default="5y")
    ap.add_argument("--train-bars", type=int, default=252)
    ap.add_argument("--test-bars", type=int, default=63)
    ap.add_argument("--min-train-trades", type=int, default=30, help="outer-train threshold-sweep guard")
    ap.add_argument("--min-inner-val-trades", type=int, default=MIN_INNER_VAL_TRADES)
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
        print("Not enough history for even one fold.", file=sys.stderr)
        return 1

    print(f"{len(dfs)} tickers, {len(folds)} folds, inner grid={len(HORIZON_GRID) * len(ALPHA_GRID)} "
          f"(horizon x alpha) points, ML threshold grid={ML_THRESHOLD_GRID}\n")
    header = f"{'fold':<5}{'test window':<26}{'h*':>4}{'a*':>6}{'thr':>6}{'EV base':>10}{'EV ml':>9}{'n base':>7}{'n ml':>6}{'IHSG%':>8}"
    print(header)
    print("-" * len(header))

    pooled_base: list[float] = []
    pooled_ml: list[float] = []
    fallback_folds = 0

    for fold in folds:
        horizon, alpha, diag = select_hyperparams(dfs, bench, fold.train_start, fold.train_end,
                                                   args.min_inner_val_trades)
        if diag is None:
            fallback_folds += 1
            diag_str = f"no inner-val combo cleared {args.min_inner_val_trades} trades -- fell back to defaults"
        else:
            diag_str = f"inner-val EV={diag['inner_val_ev_pct']:+.2f}% on {diag['inner_val_n']} trades"

        train_dfs = {t: _train_slice(df, fold.train_start, fold.train_end) for t, df in dfs.items()}
        train_dfs = {t: d for t, d in train_dfs.items() if len(d) > 80}
        scorer = fit_ridge_scorer(train_dfs, horizon=horizon, alpha=alpha)
        if scorer is None:
            print(f"{fold.fold_id:<5}(could not refit on full outer-train -- skipped)")
            continue

        thr = pick_ml_threshold(dfs, bench, scorer, fold, args.min_train_trades)

        ret_base, *_ = run_fold(dfs, bench, fold, _baseline_cfg())
        ret_ml = run_fold_ml(dfs, bench, fold, scorer, thr)
        stats_base, stats_ml = trade_stats(ret_base), trade_stats(ret_ml)
        pooled_base.extend(ret_base)
        pooled_ml.extend(ret_ml)

        b = bench["Close"]
        b = b.loc[(b.index >= fold.test_start) & (b.index <= fold.test_end)]
        bench_ret = float((b.iloc[-1] / b.iloc[0] - 1.0) * 100.0) if len(b) >= 2 else float("nan")

        win = f"{fold.test_start.date()}..{fold.test_end.date()}"
        print(f"{fold.fold_id:<5}{win:<26}{horizon:>4}{alpha:>6.0f}{thr:>5.1f}%"
             f"{stats_base['ev_pct']:>+9.2f}%{stats_ml['ev_pct']:>+8.2f}%"
             f"{stats_base['n']:>7}{stats_ml['n']:>6}{bench_ret:>+7.1f}%")
        print(f"      inner-CV: {diag_str}")

    print("-" * len(header))
    if fallback_folds:
        print(f"({fallback_folds} of {len(folds)} folds fell back to default hyperparameters -- "
              f"not enough inner-val data to choose)")
    s_base, s_ml = trade_stats(pooled_base), trade_stats(pooled_ml)
    print(f"POOLED, baseline composite_score (thr=60 fixed): "
         f"trades={s_base['n']}  EV/trade={s_base['ev_pct']:+.2f}%  win={s_base['win_rate_pct']:.0f}%  "
         f"PF={s_base['profit_factor']:.2f}  t={s_base['t_stat']:.2f}")
    print(f"POOLED, nested-CV RidgeScorer (horizon/alpha chosen per fold by inner-val): "
         f"trades={s_ml['n']}  EV/trade={s_ml['ev_pct']:+.2f}%  win={s_ml['win_rate_pct']:.0f}%  "
         f"PF={s_ml['profit_factor']:.2f}  t={s_ml['t_stat']:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
