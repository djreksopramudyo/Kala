"""
Checks whether the fold-10 giveback seen in diagnose_bear_folds.py -- a real
bull-run quarter (IHSG +9.6%) where entries.py's guardrails blocked 79% of
candidates and gave back about a third of that quarter's edge -- can be
recovered by loosening roc20_parabolic / min_volume_ratio, WITHOUT overfitting
to that one fold.

This uses the SAME walk-forward discipline the project already applies to
score_entry_threshold (see kala.walkforward.sweep_thresholds /
pick_threshold): on each fold's TRAIN window, sweep a coarse grid, pick the
pooled-EV winner subject to a minimum-trade-count guard (so a lucky handful
of trades can't win the sweep), FREEZE that choice, and only then evaluate it
on the fold's untouched TEST window. score_entry_threshold stays fixed at the
production baseline (60) throughout -- this isolates ONLY the two entry-guard
parameters from everything already tested.

Grid is deliberately coarse (same reasoning as DEFAULT_THRESHOLDS in
walkforward.py: a fine grid on a noisy objective is just another way to
overfit) -- a handful of meaningfully different points, not a fine mesh:

    (roc20_parabolic, min_volume_ratio) in {
        (25, 1.5),   # current defaults -- always a candidate, so "no change"
        (35, 1.5), (45, 1.5),              # loosen parabolic only
        (25, 1.2), (25, 1.0),              # loosen volume confirmation only
        (35, 1.2), (35, 1.0), (45, 1.2), (45, 1.0),   # loosen both
    }

Usage (same universe/period as the other diagnostics):
    python diagnose_entry_param_sweep.py --period 5y --train-bars 252 --test-bars 63

This can take a few minutes -- it's 9 combos x N folds x N tickers of
backtesting on the TRAIN side alone.
"""

from __future__ import annotations

import argparse
import sys
from types import SimpleNamespace

import pandas as pd
import yfinance as yf

from diagnose_bear_folds import run_fold
from kala.config import BacktestConfig, Config, EntryConfig
from kala.universe import ALL_SHARIA_STOCKS
from kala.walkforward import make_folds, trade_stats
from run_walkforward import BENCHMARK, fetch

DEFAULT_ROC20_PARABOLIC = 25.0
DEFAULT_MIN_VOLUME_RATIO = 1.5

GRID = [
    (DEFAULT_ROC20_PARABOLIC, DEFAULT_MIN_VOLUME_RATIO),  # defaults -- must always be a candidate
    (35.0, DEFAULT_MIN_VOLUME_RATIO), (45.0, DEFAULT_MIN_VOLUME_RATIO),
    (DEFAULT_ROC20_PARABOLIC, 1.2), (DEFAULT_ROC20_PARABOLIC, 1.0),
    (35.0, 1.2), (35.0, 1.0), (45.0, 1.2), (45.0, 1.0),
]


def _cfg_for(roc20_parabolic: float, min_volume_ratio: float, threshold: float) -> Config:
    return Config(
        backtest=BacktestConfig(score_entry_threshold=threshold, apply_entry_vetoes=True),
        entries=EntryConfig(roc20_parabolic=roc20_parabolic, min_volume_ratio=min_volume_ratio),
    )


def sweep_entry_params(dfs, bench, train_start, train_end, threshold: float):
    """Pooled trade stats per grid point, TRAIN window only."""
    pseudo_fold = SimpleNamespace(test_start=train_start, test_end=train_end)
    out = {}
    for rp, mv in GRID:
        cfg = _cfg_for(rp, mv, threshold)
        returns, _, _, _ = run_fold(dfs, bench, pseudo_fold, cfg)
        out[(rp, mv)] = trade_stats(returns)
    return out


def pick_entry_params(sweep: dict, min_trades: int = 30):
    """Highest-EV grid point among those with enough TRAIN trades to be
    believed; falls back to the defaults if nothing clears the bar -- 'not
    enough evidence to deviate' is the correct conservative answer."""
    eligible = {k: s for k, s in sweep.items() if s["n"] >= min_trades}
    if not eligible:
        return (DEFAULT_ROC20_PARABOLIC, DEFAULT_MIN_VOLUME_RATIO)
    return max(eligible.items(), key=lambda kv: kv[1]["ev_pct"])[0]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tickers", nargs="*", default=None)
    ap.add_argument("--max-tickers", type=int, default=60)
    ap.add_argument("--period", default="5y")
    ap.add_argument("--train-bars", type=int, default=252)
    ap.add_argument("--test-bars", type=int, default=63)
    ap.add_argument("--threshold", type=float, default=60.0,
                    help="score_entry_threshold, held fixed throughout (default: production baseline, 60)")
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

    default_cfg = _cfg_for(DEFAULT_ROC20_PARABOLIC, DEFAULT_MIN_VOLUME_RATIO, args.threshold)

    print(f"{len(dfs)} tickers, {len(folds)} folds, fixed threshold={args.threshold:.0f}, "
          f"grid={len(GRID)} points, min_train_trades={args.min_train_trades}\n")
    header = (f"{'fold':<5}{'test window':<26}{'chosen (roc20,vol)':<20}"
             f"{'EV default':>11}{'EV chosen':>11}{'n def':>6}{'n chos':>7}{'IHSG%':>8}")
    print(header)
    print("-" * len(header))

    pooled_default: list[float] = []
    pooled_chosen: list[float] = []

    for fold in folds:
        sweep = sweep_entry_params(dfs, bench, fold.train_start, fold.train_end, args.threshold)
        rp, mv = pick_entry_params(sweep, args.min_train_trades)
        chosen_cfg = _cfg_for(rp, mv, args.threshold)

        ret_def, *_ = run_fold(dfs, bench, fold, default_cfg)
        ret_chosen, *_ = run_fold(dfs, bench, fold, chosen_cfg)
        stats_def = trade_stats(ret_def)
        stats_chosen = trade_stats(ret_chosen)
        pooled_default.extend(ret_def)
        pooled_chosen.extend(ret_chosen)

        b = bench["Close"]
        b = b.loc[(b.index >= fold.test_start) & (b.index <= fold.test_end)]
        bench_ret = float((b.iloc[-1] / b.iloc[0] - 1.0) * 100.0) if len(b) >= 2 else float("nan")

        win = f"{fold.test_start.date()}..{fold.test_end.date()}"
        chosen_label = f"({rp:.0f},{mv:.2f})"
        print(f"{fold.fold_id:<5}{win:<26}{chosen_label:<20}{stats_def['ev_pct']:>+10.2f}%"
             f"{stats_chosen['ev_pct']:>+10.2f}%{stats_def['n']:>6}{stats_chosen['n']:>7}{bench_ret:>+7.1f}%")

    print("-" * len(header))
    s_def, s_chosen = trade_stats(pooled_default), trade_stats(pooled_chosen)
    print(f"POOLED, defaults ({DEFAULT_ROC20_PARABOLIC:.0f}, {DEFAULT_MIN_VOLUME_RATIO:.2f}) fixed all folds: "
         f"trades={s_def['n']}  EV/trade={s_def['ev_pct']:+.2f}%  win={s_def['win_rate_pct']:.0f}%  "
         f"PF={s_def['profit_factor']:.2f}  t={s_def['t_stat']:.2f}")
    print(f"POOLED, walk-forward-chosen params per fold:                     "
         f"trades={s_chosen['n']}  EV/trade={s_chosen['ev_pct']:+.2f}%  win={s_chosen['win_rate_pct']:.0f}%  "
         f"PF={s_chosen['profit_factor']:.2f}  t={s_chosen['t_stat']:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
