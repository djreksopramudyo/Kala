#!/usr/bin/env python3
"""Compare saved walk-forward fold tables, on the RIGHT column.

    python run_walkforward.py ... --strategy momentum       --save-folds results/f_mom.json
    python run_walkforward.py ... --strategy mean_reversion --save-folds results/f_mr.json
    python compare_folds.py results/f_mom.json results/f_mr.json

WHY THIS EXISTS
---------------
Two mistakes this session came from comparing runs by eye across pasted
terminal output.

The first was correlating the RAW per-fold EV of two strategies, finding +0.86,
and concluding a hidden common factor was driving both. Two long-only baskets
drawn from one universe rise together when the index rises; that correlation is
mechanical. The EXCESS column is the one that can say whether two signals share
anything beyond the market, and it was not being printed at all.

The second was reading a fold table from a run whose warehouse had been
refreshed in between, so the fold boundaries had moved by a day and the trade
counts differed. Nothing in the pasted text said so.

This script only reads saved runs, so both failures are structurally
impossible: it reports raw AND excess correlations side by side, and refuses to
compare runs whose fold calendars do not line up.
"""

from __future__ import annotations

import argparse
import json
import statistics as st
from pathlib import Path


def load(path: str) -> dict:
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    for key in ("strategy", "folds"):
        if key not in d:
            raise SystemExit(f"{path}: not a saved fold table (no '{key}')")
    return d


def corr(a: list, b: list) -> float:
    pairs = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    if len(pairs) < 3:
        return float("nan")
    xs, ys = [p[0] for p in pairs], [p[1] for p in pairs]
    mx, my = st.mean(xs), st.mean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = (sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys)) ** 0.5
    return num / den if den else float("nan")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("runs", nargs="+", help="two or more saved fold-table JSONs")
    ap.add_argument("--allow-misaligned", action="store_true",
                    help="compare anyway when the fold calendars differ. Off by "
                         "default: a warehouse refresh between runs shifts fold "
                         "boundaries, and correlating misaligned folds is "
                         "comparing different quarters.")
    args = ap.parse_args()

    runs = [load(p) for p in args.runs]
    for r, path in zip(runs, args.runs):
        r["_path"] = path              # so a refusal can name the FILE
    if len(runs) < 2:
        print("Need at least two saved runs.")
        return 1

    print(f"{'file':<34}{'strategy':<18}{'base':>6}{'folds':>7}{'first fold':>26}")
    print("-" * 91)
    for r in runs:
        first = r["folds"][0] if r["folds"] else {}
        win = f"{first.get('start', '?')}..{first.get('end', '?')}"
        print(f"{Path(r['_path']).name:<34}{r['strategy']:<18}"
              f"{r.get('baseline_threshold', float('nan')):>6.0f}"
              f"{len(r['folds']):>7}{win:>26}")

    # Alignment: same number of folds AND same windows. A warehouse refresh
    # moves boundaries by a day or two, which is invisible in pasted output.
    # Report by FILE, not by strategy name. Comparing three runs of the same
    # strategy printed "FOLD CALENDARS DIFFER from momentum: momentum", which
    # names neither the reference nor the offender — the one thing the reader
    # needs in order to know which run to repeat.
    ref = [(f["start"], f["end"]) for f in runs[0]["folds"]]
    ref_name = Path(runs[0]["_path"]).name
    misaligned = [r for r in runs[1:]
                  if [(f["start"], f["end"]) for f in r["folds"]] != ref]
    if misaligned:
        print(f"\nFOLD CALENDARS DIFFER from {ref_name}:")
        for r in misaligned:
            f0 = r["folds"][0] if r["folds"] else {}
            r0 = runs[0]["folds"][0] if runs[0]["folds"] else {}
            print(f"  {Path(r['_path']).name:<34}"
                  f"fold 0 = {f0.get('start', '?')}..{f0.get('end', '?')}")
        print(f"  {ref_name:<34}fold 0 = "
              f"{r0.get('start', '?')}..{r0.get('end', '?')}   <- the reference")
        print("\n  A warehouse refresh between runs shifts fold boundaries, and")
        print("  different strategies need different warmup. Correlating these")
        print("  compares different quarters to each other.")
        print(f"\n  FIX: re-run {ref_name} (or the offender(s) above) so every")
        print("  saved table comes from one warehouse state, then compare again.")
        if not args.allow_misaligned:
            print("  Refusing to correlate. Pass --allow-misaligned to override.")
            return 1
        print("  --allow-misaligned given; correlating anyway. Read with care.")

    print(f"\n{'pair':<44}{'RAW corr':>10}{'EXCESS corr':>13}")
    print("-" * 68)
    for i, a in enumerate(runs):
        for b in runs[i + 1:]:
            ra = [f["ev_pct"] for f in a["folds"]]
            rb = [f["ev_pct"] for f in b["folds"]]
            ea = [f.get("excess_pct") for f in a["folds"]]
            eb = [f.get("excess_pct") for f in b["folds"]]
            n = min(len(ra), len(rb))
            label = f"{Path(a['_path']).stem} / {Path(b['_path']).stem}"
            print(f"{label:<44}{corr(ra[:n], rb[:n]):>+10.3f}"
                  f"{corr(ea[:n], eb[:n]):>+13.3f}")

    print()
    print("Read the EXCESS column. A high RAW correlation between two long-only")
    print("strategies is mechanical — both are long the same market. Only the")
    print("excess correlation can say whether they share something beyond it.")

    # Each run against its own benchmark: the regime-conditionality check.
    print(f"\n{'strategy':<22}{'excess vs IHSG':>16}{'up folds':>11}{'down folds':>13}")
    print("-" * 62)
    for r in runs:
        ex = [f.get("excess_pct") for f in r["folds"]]
        bm = [f.get("benchmark_pct") for f in r["folds"]]
        up = [e for e, m in zip(ex, bm) if e is not None and m is not None and m >= 0]
        dn = [e for e, m in zip(ex, bm) if e is not None and m is not None and m < 0]
        up_s = f"{st.mean(up):+.2f}% ({len(up)})" if up else "n/a"
        dn_s = f"{st.mean(dn):+.2f}% ({len(dn)})" if dn else "n/a"
        print(f"{Path(r['_path']).stem:<22}{corr(ex, bm):>+16.3f}{up_s:>11}{dn_s:>13}")
    print()
    print("A strategy whose excess is large in up folds and ~zero in down folds")
    print("has a REGIME-CONDITIONAL edge, not an unconditional one — and nothing")
    print("in this system tells you which regime you are in ahead of time.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
