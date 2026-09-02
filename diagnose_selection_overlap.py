#!/usr/bin/env python3
"""Do six "different" signals pick the same stocks?

WHY THIS EXISTS
---------------
Re-tested without the exit ladder, six strategies all returned positive OOS
excess — including momentum and mean_reversion, which are near-opposites. Their
per-fold EV correlates 0.86 to 0.97 pairwise. Six independent edges do not
behave like that; one shared thing measured six times does.

Two explanations fit the pooled numbers equally well and the fold table cannot
separate them:

  A. the six selections overlap heavily — they are one basket with six names;
  B. the six selections are largely disjoint, and something else common to all
     of them (a filter, a regime, a data artefact) is doing the work.

This script measures the overlap directly, so the choice stops being a guess.
It reads whatever is in results/price_cache/, needs no network, and reports
Jaccard overlap between each pair of selections on a grid of dates.

WHAT IT CANNOT TELL YOU
-----------------------
It is a SELECTION diagnostic, not a return one. High overlap explains the
correlation; low overlap does not prove six edges — it only moves the question
to what else the six share. And the cache is a selected subset of the universe,
so treat the level of the numbers loosely and the CONTRAST between pairs as the
signal.
"""

from __future__ import annotations

import argparse
import glob
import importlib
from pathlib import Path

import pandas as pd

from kala.strategies import get_strategy, list_strategies

CACHE = Path(__file__).resolve().parent / "results" / "price_cache"
BENCHMARK_TICKER = "^JKSE"

# Registration is by import side-effect; without these the registry holds
# only momentum and the script would silently compare one strategy to itself.
for _m in ("strategy_mean_reversion", "strategy_support_resistance",
           "strategy_dividend_yield", "strategy_low_volatility",
           "strategy_multihorizon_trend", "strategy_foreign_flow"):
    try:
        importlib.import_module(f"kala.{_m}")
    except Exception:  # noqa: BLE001 - an optional strategy that will not import
        pass


def load_cache(min_bars: int) -> dict:
    out = {}
    for f in sorted(glob.glob(str(CACHE / "*.pkl"))):
        name = Path(f).stem
        if name == BENCHMARK_TICKER:
            continue
        try:
            d = pd.read_pickle(f)
        except Exception as e:  # noqa: BLE001 - reported, not swallowed
            print(f"  {name}: unreadable ({e})")
            continue
        if len(d) >= min_bars:
            out[name] = d
    return out


def selections(dfs: dict, names: list[str], asof_frac: float, top_n: int,
               bottom: bool = False) -> dict:
    """{strategy: set(tickers)} — each strategy's top_n by its own score.

    Ranking by top_n rather than by each strategy's own threshold is
    deliberate: thresholds live on different scales, so a threshold-based
    comparison would measure the scales, not the selections.
    """
    picks: dict[str, set] = {}
    for name in names:
        s = get_strategy(name)
        scored = {}
        for tk, df in dfs.items():
            try:
                feats = s.compute_features(df)
                series = s.score(feats)
            except Exception:  # noqa: BLE001 - a strategy that cannot score this name
                continue
            if series is None or len(series) == 0:
                continue
            i = min(int(len(series) * asof_frac), len(series) - 1)
            v = series.iloc[i]
            if v == v:                      # not NaN
                scored[tk] = float(v)
        if len(scored) < top_n:
            print(f"  {name}: only {len(scored)} scorable names, skipping")
            continue
        ranked = sorted(scored, key=scored.get, reverse=not bottom)
        picks[name] = set(ranked[:top_n])
    return picks


def jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if (a or b) else float("nan")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--min-bars", type=int, default=800)
    ap.add_argument("--top-n", type=int, default=15,
                    help="size of each strategy's basket (default 15)")
    ap.add_argument("--dates", type=int, default=5,
                    help="how many as-of points across the history (default 5)")
    ap.add_argument("--bottom", action="store_true",
                    help="compare each strategy's WORST-scored basket instead of "
                         "its best. If the six share what they AVOID rather than "
                         "what they pick, the bottom baskets overlap while the "
                         "top ones do not — which would make the measured excess "
                         "an exclusion effect, not stock selection.")
    args = ap.parse_args()

    dfs = load_cache(args.min_bars)
    print(f"cached universe: {len(dfs)} ticker(s) with >= {args.min_bars} bars")
    if len(dfs) < args.top_n * 2:
        print("Too few names for a meaningful overlap. Aborting rather than "
              "printing a tidy table of noise.")
        return 1

    names = [n for n in sorted(list_strategies()) if n != "foreign_flow"]
    print(f"strategies: {', '.join(names)}")
    print(f"basket size: {'BOTTOM' if args.bottom else 'top'} {args.top_n} "
          f"by each strategy's own score\n")

    # Random-overlap baseline: two independent picks of top_n from N names.
    expected = args.top_n / (2 * len(dfs) - args.top_n)
    print(f"expected Jaccard for two INDEPENDENT picks of {args.top_n} "
          f"from {len(dfs)}: {expected:.3f}")
    print("  ^ compare every number below against this, not against zero.\n")

    totals: dict[tuple, list] = {}
    for k in range(args.dates):
        frac = 0.5 + 0.5 * (k + 1) / args.dates      # spread over the 2nd half
        picks = selections(dfs, names, frac, args.top_n, bottom=args.bottom)
        got = sorted(picks)
        for i, a in enumerate(got):
            for b in got[i + 1:]:
                totals.setdefault((a, b), []).append(jaccard(picks[a], picks[b]))

    if not totals:
        print("No comparable selections were produced.")
        return 1

    print(f"{'pair':<44}{'mean Jaccard':>14}{'vs random':>12}")
    print("-" * 70)
    for (a, b), vals in sorted(totals.items(), key=lambda kv: -sum(kv[1]) / len(kv[1])):
        m = sum(vals) / len(vals)
        print(f"{a + ' / ' + b:<44}{m:>14.3f}{m / expected:>11.1f}x")

    allv = [v for vals in totals.values() for v in vals]
    mean_all = sum(allv) / len(allv)
    print("-" * 70)
    print(f"{'MEAN over all pairs':<44}{mean_all:>14.3f}{mean_all / expected:>11.1f}x")
    print()
    if mean_all > 4 * expected:
        print("HIGH overlap. The six 'different' signals are largely picking the")
        print("same names, which explains the 0.86-0.97 fold correlation without")
        print("needing six separate edges. Treat them as ONE observation.")
    elif mean_all < 2 * expected:
        print("LOW overlap. The selections really are different, so the shared")
        print("fold pattern is NOT explained by picking the same stocks. Whatever")
        print("is common to them is something else and must be named before any")
        print("of this is traded.")
    else:
        print("MIDDLING overlap. Not decisive either way — read the pairs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
