#!/usr/bin/env python3
"""Run the exit-profile comparison over the LOCAL price cache, offline.

WHAT THIS IS FOR
----------------
The decisive comparison is the two full-universe runs:

    python run_walkforward.py --max-tickers 615 --period 5y ... --exit-profile legacy
    python run_walkforward.py --max-tickers 615 --period 5y ... --exit-profile forward_test

Those need a long download. This script runs the SAME harness over whatever is
already in ``results/price_cache/``, so two questions can be answered before
paying for that download:

  1. does ``--exit-profile forward_test`` actually change the trades, or is the
     flag inert? (It passed unit tests once while ``main()`` ignored it.)
  2. which direction does the result move on data already on disk?

WHAT THIS IS NOT
----------------
NOT a universe result. The cache holds whatever past runs happened to fetch —
open positions, watchlist names, scan candidates — so it is a selected sample,
and every name in it exists today, which is survivorship exposure of unknown
size. Treat the numbers as a smoke test with a direction, not as evidence.
"""

from __future__ import annotations

import argparse
import glob
from pathlib import Path

import pandas as pd

from kala.config import config_for_profile
from kala.walkforward import walk_forward

CACHE = Path(__file__).resolve().parent / "results" / "price_cache"
BENCHMARK_TICKER = "^JKSE"


def load_cache(min_bars: int, exclude: set[str]) -> tuple[dict, pd.DataFrame | None]:
    dfs, bench = {}, None
    for f in sorted(glob.glob(str(CACHE / "*.pkl"))):
        name = Path(f).stem
        try:
            d = pd.read_pickle(f)
        except Exception as e:  # noqa: BLE001 - reported, not swallowed
            print(f"  {name}: unreadable ({e})")
            continue
        if name == BENCHMARK_TICKER:
            bench = d
            continue
        if name in exclude or len(d) < min_bars:
            continue
        dfs[name] = d
    return dfs, bench


def _need(d: dict, key: str, where: str):
    """Read a stat by key, refusing to substitute a default.

    The first version of this script used .get(key, nan) with the WRONG key
    names (trade_stats returns ev_pct/t_stat, not mean/t). Every cell printed
    NaN and the table still looked orderly. A missing key is a bug in this
    script, not a missing measurement, and it must say so.
    """
    if key not in d:
        raise KeyError(f"{where}: no '{key}' in {sorted(d)} — fix this script, "
                       f"do not print a default")
    return d[key]


def block(label: str, rep) -> None:
    pe = rep.pooled_excess_chosen or {}
    pc = rep.pooled_chosen or {}
    print(f"\n{'=' * 70}\n{label}\n{'=' * 70}")
    print(f"  folds                 {len(rep.folds)}")
    print(f"  pooled OOS trades     {_need(pc, 'n', label)}")
    print(f"  pooled OOS EV         {_need(pc, 'ev_pct', label):+.3f}%")
    print(f"  median trade          {_need(pc, 'median_pct', label):+.3f}%")
    print(f"  win rate              {_need(pc, 'win_rate_pct', label):.1f}%")
    print(f"  EXCESS vs benchmark   {_need(pe, 'ev_pct', label):+.3f}%"
          f"   n={_need(pe, 'n', label)}")
    print(f"  plain t               {_need(pe, 't_stat', label):+.2f}")
    print(f"  clustered t           {rep.pooled_excess_clustered_t:+.2f}")
    print(f"  deflated Sharpe P(>0) {rep.pooled_excess_dsr:.3f}"
          f"   over {rep.dsr_n_trials} trial(s)")


def rank_by_turnover(dfs: dict) -> list[str]:
    """Tickers ordered most- to least-liquid by MEDIAN daily turnover.

    Turnover, not price: survivorship exposure tracks how much of a name
    actually trades, and an expensive but barely-traded stock belongs in the
    thin half. Median rather than mean so one frantic week cannot promote it.
    A frame without Volume ranks last rather than aborting the run — the cache
    holds whatever past runs happened to fetch.

    Same definition diagnose_exit_param_sweep.py uses, so the two are
    comparable.
    """
    turnover = {}
    for tk, d in dfs.items():
        try:
            turnover[tk] = float((d["Close"] * d["Volume"]).median())
        except Exception:  # noqa: BLE001 - a name without volume ranks last
            turnover[tk] = 0.0
    return sorted(turnover, key=turnover.get, reverse=True)


def _run(dfs, bench, profile: str, holding_days: int):
    cfg = config_for_profile(profile)
    if profile == "forward_test":
        cfg.backtest.holding_max_days = holding_days
    return walk_forward(dfs, cfg=cfg, benchmark=bench)


def sweep_holding(dfs, bench, holds: list[int]) -> int:
    """Holding period vs excess return, exits off.

    Two columns because they answer different questions. Excess PER TRADE rises
    with the holding period almost by construction — hold longer, accumulate
    more — so it cannot say which horizon is efficient. Excess PER DAY HELD
    divides that out and is the honest comparison of capital-time.

    Read the SHAPE, not the argmax. Picking the best of N points on one sample
    is the overfitting this project has spent sixteen hypotheses avoiding; a
    smooth hump with every point positive says far more than its peak does.
    """
    print(f"\n{'=' * 70}\nHOLDING PERIOD SWEEP — all exit rules OFF"
          f"\n{'=' * 70}")
    header = (f"  {'bars':>6}{'trades':>8}{'excess%':>10}{'clust t':>9}"
              f"{'DSR':>7}{'ex/day':>9}")
    print(header)
    print("  " + "-" * (len(header) - 2))
    rows = []
    for hold in sorted(holds):
        cfg = config_for_profile("forward_test")
        cfg.backtest.holding_max_days = hold
        rep = walk_forward(dfs, cfg=cfg, benchmark=bench)
        pe = rep.pooled_excess_chosen or {}
        n = _need(pe, "n", f"hold={hold}")
        ev = _need(pe, "ev_pct", f"hold={hold}")
        rows.append((hold, n, ev, ev / hold))
        print(f"  {hold:>6}{n:>8}{ev:>+10.3f}"
              f"{rep.pooled_excess_clustered_t:>+9.2f}"
              f"{rep.pooled_excess_dsr:>7.3f}{ev / hold:>9.4f}")

    if len(rows) < 3:
        print("\n  Too few points to read a shape.")
        return 0
    best = max(rows, key=lambda r: r[3])
    negatives = [r for r in rows if r[2] <= 0]
    print(f"\n  Highest excess per day held: {best[0]} bars "
          f"({best[3]:.4f}%/day).")
    if negatives:
        print(f"  {len(negatives)} of {len(rows)} horizons are NOT positive — "
              f"the effect is not\n  present across the range, so treat the peak "
              f"as noise.")
    else:
        print(f"  All {len(rows)} horizons are positive. That is the finding; "
              f"the peak is not.\n  Do not read the argmax of a "
              f"{len(rows)}-point sweep on one sample as an\n  optimum — it is "
              f"a best-of-N pick, which is exactly what deflated Sharpe\n  "
              f"exists to discount.")
    return 0


def split_liquidity(dfs, bench, args) -> int:
    """Run both profiles on the liquid and illiquid halves separately.

    Median daily turnover over the whole sample, as a stand-in for how exposed
    a name is to being delisted or dropped from the index. Median rather than
    mean so one frantic week cannot promote a thin stock. Same definition
    diagnose_exit_param_sweep.py uses, so the two are comparable.
    """
    ranked = rank_by_turnover(dfs)
    half = len(ranked) // 2

    print(f"\n{'=' * 70}\nSURVIVORSHIP DISCRIMINATOR — by median daily turnover"
          f"\n{'=' * 70}")
    header = (f"  {'half':<10}{'profile':<14}{'n':>7}{'excess%':>10}"
              f"{'clust t':>9}{'DSR':>7}")
    print(header)
    print("  " + "-" * (len(header) - 2))

    deltas = {}
    for label, names in (("LIQUID", ranked[:half]), ("ILLIQUID", ranked[half:])):
        sub = {k: dfs[k] for k in names}
        row = {}
        for profile in ("legacy", "forward_test"):
            rep = _run(sub, bench, profile, args.holding_days)
            pe = rep.pooled_excess_chosen or {}
            n = _need(pe, "n", f"{label}/{profile}")
            ev = _need(pe, "ev_pct", f"{label}/{profile}")
            row[profile] = ev
            print(f"  {label:<10}{profile:<14}{n:>7}{ev:>+10.3f}"
                  f"{rep.pooled_excess_clustered_t:>+9.2f}"
                  f"{rep.pooled_excess_dsr:>7.3f}")
        deltas[label] = row["forward_test"] - row["legacy"]

    print(f"\n  gap (forward_test - legacy):  "
          f"LIQUID {deltas['LIQUID']:+.3f} pts   "
          f"ILLIQUID {deltas['ILLIQUID']:+.3f} pts")
    if deltas["LIQUID"] > 0 and deltas["ILLIQUID"] > 0:
        print("\n  Present in BOTH halves. Survivorship is concentrated in names "
              "that COULD\n  have been delisted — the thin end — so a gap that "
              "also appears among the\n  liquid names is not produced by that "
              "bias. It does NOT bound the bias's\n  size, and this is still a "
              "selected sample of 60-odd tickers.")
    elif deltas["ILLIQUID"] > 0 >= deltas["LIQUID"]:
        print("\n  ONLY in the illiquid half. That is what survivorship bias "
              "looks like.\n  Treat the headline gap as unproven.")
    else:
        print("\n  Not present in the illiquid half. Unexpected shape — read the "
              "rows, not\n  this sentence.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--min-bars", type=int, default=800,
                    help="skip short histories (default 800 ~ 3.2y)")
    ap.add_argument("--holding-days", type=int, default=60)
    ap.add_argument("--split-liquidity", action="store_true",
                    help="SURVIVORSHIP DISCRIMINATOR. Split the cached universe "
                         "into liquid and illiquid halves by median daily "
                         "turnover and run both profiles on each. Large, liquid "
                         "names rarely delist, so their survivorship exposure is "
                         "low; thin names carry most of it. A gap present in both "
                         "halves is not produced by the bias. A gap that lives "
                         "only in the illiquid half most likely is.")
    ap.add_argument("--sweep-holding", type=int, nargs="*", default=None,
                    metavar="BARS",
                    help="with all exit rules OFF, sweep holding_max_days over "
                         "these values (e.g. --sweep-holding 10 20 30 45 60 90 "
                         "120). Reports excess PER TRADE and PER DAY HELD; the "
                         "per-trade column rises mechanically with the holding "
                         "period, so the per-day column is the one that says "
                         "anything about efficiency.")
    args = ap.parse_args()

    dfs, bench = load_cache(args.min_bars, exclude={BENCHMARK_TICKER})
    print(f"cached universe: {len(dfs)} ticker(s) with >= {args.min_bars} bars")
    if bench is None:
        print(f"WARNING: no {BENCHMARK_TICKER} in the cache — the excess/alpha "
              f"columns will be empty, which is the number that matters.")
    if len(dfs) < 10:
        print("Too few tickers to say anything. Aborting rather than printing "
              "a tidy table of noise.")
        return 1
    spans = [(d.index.min(), d.index.max()) for d in dfs.values()]
    print(f"span: {min(s[0] for s in spans).date()} -> "
          f"{max(s[1] for s in spans).date()}")

    if args.sweep_holding:
        return sweep_holding(dfs, bench, args.sweep_holding)
    if args.split_liquidity:
        return split_liquidity(dfs, bench, args)

    results = {}
    for profile in ("legacy", "forward_test"):
        cfg = config_for_profile(profile)
        if profile == "forward_test":
            cfg.backtest.holding_max_days = args.holding_days
        rep = walk_forward(dfs, cfg=cfg, benchmark=bench)
        results[profile] = rep
        block(f"{profile.upper()}  "
              f"(holding_max_days={cfg.backtest.holding_max_days}, "
              f"trailing={cfg.risk.trailing_enabled}, "
              f"stop={cfg.risk.hard_stop_pct}, target={cfg.risk.target_profit_pct})",
              rep)

    a, b = results["legacy"], results["forward_test"]
    print(f"\n{'=' * 70}\nIS THE FLAG DOING ANYTHING?\n{'=' * 70}")
    na = _need(a.pooled_chosen, "n", "legacy")
    nb = _need(b.pooled_chosen, "n", "forward_test")
    ma = _need(a.pooled_excess_chosen, "ev_pct", "legacy excess")
    mb = _need(b.pooled_excess_chosen, "ev_pct", "forward_test excess")
    print(f"  trades   legacy {na}   forward_test {nb}")
    print(f"  excess   legacy {ma:+.3f}%   forward_test {mb:+.3f}%")
    if na == nb and abs(ma - mb) < 1e-9:
        print("\n  IDENTICAL. The profile is not reaching the engine — do NOT "
              "spend a\n  download on the full run until this is fixed.")
        return 1
    print(f"\n  Different, so the flag reaches the engine. Delta "
          f"{mb - ma:+.3f} pts/trade\n  on this cached sample.")
    print("\n  This is a SELECTED sample of names that all still exist. It is a "
          "smoke\n  test with a direction, not evidence. The full-universe run "
          "is still the\n  measurement.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
