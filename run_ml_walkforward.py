"""
Fits a small ridge-regression scorer (kala.ml_scoring) fresh on each
fold's TRAIN window and compares its OOS performance against the hand-tuned
composite_score — the flagged upgrade path: replace hand-tuned score weights
with a fitted model that predicts forward returns.

Both arms use apply_entry_vetoes=True (the realism fix already validated in
diagnose_bear_folds.py — the strongest baseline established so far). The
ONLY thing that differs between the two columns is which function produces
the entry score:

  baseline:  composite_score's hand-tuned 40/30/30 blend, threshold fixed
             at the production default (60)
  ml:        ml_scoring.RidgeScorer, fit fresh per fold on that fold's TRAIN
             window only, entry threshold chosen by the SAME train-then-
             freeze discipline walkforward.py already uses for
             score_entry_threshold (sweep on train, pick by pooled EV with a
             minimum-trade guard, freeze BEFORE touching the test window)

The ridge regularization strength (alpha) and forward-return horizon are
fixed, not swept — sweeping them too would just move the overfitting search
up a level. Weights are printed per fold so the fit is auditable rather than
a black box: you can see which indicators the data actually rewarded, vs.
composite_score's guesses.

Usage:
    python run_ml_walkforward.py --period 5y --train-bars 252 --test-bars 63

    # robustness check: same grid, one different pre-committed (horizon, alpha)
    # pair. Not a search -- if the conclusion (positive pooled EV, t well above
    # 2, roc_10's coefficient staying negative) survives this, that's real
    # evidence; if it collapses, the first run was a favorable draw.
    python run_ml_walkforward.py --period 5y --train-bars 252 --test-bars 63 \
        --horizon 15 --alpha 20

This can take a few minutes — it fits 14 separate models (one per fold) and
sweeps 8 threshold candidates for each on top of that.

ML_THRESHOLD_GRID was widened from (0.0..3.0) to (0.0..5.0) after the first
run showed 8 of 14 folds pinning their chosen threshold at the OLD ceiling
(3.0) -- a sweep landing on the edge of its search space is evidence the
space was too narrow, not that the edge value is optimal.
"""

from __future__ import annotations

import argparse
import sys

import pandas as pd
import yfinance as yf

from diagnose_bear_folds import _window_slice, run_fold
from kala.backtest import backtest_ticker
from kala.config import BacktestConfig, Config
from kala.ml_scoring import fit_ridge_scorer
from kala.universe import ALL_SHARIA_STOCKS
from kala.walkforward import make_folds, trade_stats
from run_walkforward import BENCHMARK, fetch

ML_THRESHOLD_GRID = (0.0, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0)  # predicted forward-return-%, not 0-100
BASELINE_THRESHOLD = 60.0


def _baseline_cfg() -> Config:
    return Config(backtest=BacktestConfig(score_entry_threshold=BASELINE_THRESHOLD,
                                          apply_entry_vetoes=True))


def _ml_cfg(threshold: float) -> Config:
    return Config(backtest=BacktestConfig(score_entry_threshold=threshold,
                                          apply_entry_vetoes=True))


def _train_slice(df: pd.DataFrame, train_start, train_end, warmup_bars: int = 60) -> pd.DataFrame:
    idx = df.index
    lo = max(0, int(idx.searchsorted(train_start)) - warmup_bars)
    hi = int(idx.searchsorted(train_end, side="right"))
    return df.iloc[lo:hi]


def run_fold_ml(dfs, bench, fold, scorer, threshold: float, warmup_bars: int = 60):
    cfg = _ml_cfg(threshold)
    exit_grace = cfg.backtest.holding_max_days + 5
    returns: list[float] = []
    for ticker, df in dfs.items():
        window = _window_slice(df, fold.test_start, fold.test_end, warmup_bars, exit_grace)
        if len(window) < warmup_bars // 2:
            continue
        score = scorer.score(window)
        res = backtest_ticker(ticker, window, benchmark=bench, cfg=cfg, score_override=score)
        returns.extend(t.net_return_pct for t in res.closed
                       if fold.test_start <= pd.Timestamp(t.entry_date) <= fold.test_end)
    return returns


def pick_ml_threshold(dfs, bench, scorer, fold, min_train_trades: int) -> float:
    """Sweep ML_THRESHOLD_GRID on the fold's TRAIN window only, using the
    frozen scorer -- mirrors walkforward.pick_threshold exactly, just against
    a different scorer/units."""
    best_thr, best_ev = None, -1e18
    for thr in ML_THRESHOLD_GRID:
        cfg = _ml_cfg(thr)
        exit_grace = cfg.backtest.holding_max_days + 5
        pooled: list[float] = []
        for ticker, df in dfs.items():
            window = _window_slice(df, fold.train_start, fold.train_end, 60, exit_grace)
            if len(window) < 30:
                continue
            score = scorer.score(window)
            res = backtest_ticker(ticker, window, benchmark=bench, cfg=cfg, score_override=score)
            pooled.extend(t.net_return_pct for t in res.closed
                          if fold.train_start <= pd.Timestamp(t.entry_date) <= fold.train_end)
        stats = trade_stats(pooled)
        if stats["n"] >= min_train_trades and stats["ev_pct"] > best_ev:
            best_thr, best_ev = thr, stats["ev_pct"]
    if best_thr is None:
        return ML_THRESHOLD_GRID[0]  # not enough evidence -- conservative fallback
    return best_thr


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tickers", nargs="*", default=None)
    ap.add_argument("--max-tickers", type=int, default=60)
    ap.add_argument("--period", default="5y")
    ap.add_argument("--train-bars", type=int, default=252)
    ap.add_argument("--test-bars", type=int, default=63)
    ap.add_argument("--horizon", type=int, default=10, help="forward-return label horizon, bars")
    ap.add_argument("--alpha", type=float, default=10.0, help="ridge regularization strength (fixed, not swept)")
    ap.add_argument("--min-train-trades", type=int, default=30)
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

    print(f"{len(dfs)} tickers, {len(folds)} folds, horizon={args.horizon}, alpha={args.alpha}, "
          f"baseline threshold={BASELINE_THRESHOLD:.0f} (fixed), ML threshold grid={ML_THRESHOLD_GRID}\n")
    header = f"{'fold':<5}{'test window':<26}{'ML thr':>7}{'EV base':>10}{'EV ml':>9}{'n base':>7}{'n ml':>6}{'IHSG%':>8}"
    print(header)
    print("-" * len(header))

    pooled_base: list[float] = []
    pooled_ml: list[float] = []
    skipped_folds = 0

    for fold in folds:
        train_dfs = {t: _train_slice(df, fold.train_start, fold.train_end) for t, df in dfs.items()}
        train_dfs = {t: d for t, d in train_dfs.items() if len(d) > 80}

        scorer = fit_ridge_scorer(train_dfs, horizon=args.horizon, alpha=args.alpha)
        if scorer is None:
            print(f"{fold.fold_id:<5}{'(not enough train data to fit -- skipped)':<26}")
            skipped_folds += 1
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
        print(f"{fold.fold_id:<5}{win:<26}{thr:>6.1f}%{stats_base['ev_pct']:>+9.2f}%"
             f"{stats_ml['ev_pct']:>+8.2f}%{stats_base['n']:>7}{stats_ml['n']:>6}{bench_ret:>+7.1f}%")
        weights = ", ".join(f"{k}={v:+.3f}" for k, v in scorer.weights_by_feature().items())
        print(f"      fit on {scorer.n_train_rows} train rows: {weights}")

    print("-" * len(header))
    if skipped_folds:
        print(f"({skipped_folds} fold(s) skipped -- not enough train data to fit)")
    s_base, s_ml = trade_stats(pooled_base), trade_stats(pooled_ml)
    print(f"POOLED, baseline composite_score (thr={BASELINE_THRESHOLD:.0f} fixed): "
         f"trades={s_base['n']}  EV/trade={s_base['ev_pct']:+.2f}%  win={s_base['win_rate_pct']:.0f}%  "
         f"PF={s_base['profit_factor']:.2f}  t={s_base['t_stat']:.2f}")
    print(f"POOLED, fitted RidgeScorer (threshold walk-forward-chosen per fold): "
         f"trades={s_ml['n']}  EV/trade={s_ml['ev_pct']:+.2f}%  win={s_ml['win_rate_pct']:.0f}%  "
         f"PF={s_ml['profit_factor']:.2f}  t={s_ml['t_stat']:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
