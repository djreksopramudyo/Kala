#!/usr/bin/env python3
"""Walk-forward the holding period, then tabulate. One command, one table.

    python sweep_holding_walkforward.py --holds 20 30 45 60 90 \
        --max-tickers 615 --period 5y --tick-spread \
        --warehouse results/warehouse.db --min-price 0 --trust-short-cache \
        --exit-profile forward_test --strategy momentum --benchmark EQUAL_WEIGHT

WHY THIS EXISTS
---------------
`holding_max_days` is 60. That number was tuned while the exit ladder was still
in place, and the ladder was later measured to be significantly NEGATIVE and
removed. Nobody has swept the holding period since. It is the last parameter in
this system still carrying a value chosen under conditions that no longer hold.

`compare_exit_profiles_cached.py --sweep-holding` already sweeps it, but on the
locally cached subset — a few dozen tickers that still exist today, which is
close to a pure survivorship sample. This drives the real walk-forward over the
full warehouse instead.

WHY IT SHELLS OUT INSTEAD OF IMPORTING
--------------------------------------
Every run is `run_walkforward.py` itself, unchanged, with `--holding-days N`.
Re-implementing the measurement here would create a second code path that can
drift from the one every other result in this project came from — and a
comparison between two subtly different harnesses is worse than no comparison.
The cost is process startup per run; the benefit is that these numbers are
directly comparable with every saved fold table already on disk.

WHAT IT REFUSES TO DO
---------------------
It will not tabulate runs whose fold calendars differ. A warehouse refresh
between runs shifts fold boundaries, and comparing holding periods across
different quarters measures the quarters. Same rule `compare_folds.py` applies,
enforced here because a sweep is exactly where that mistake is easy to make.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from kala.expectation import excess_excluding_largest_fold

ROOT = Path(__file__).resolve().parent
RUNNER = ROOT / "run_walkforward.py"


def run_one(hold: int, out_path: Path, passthrough: list[str]) -> int:
    """One walk-forward at holding_max_days=hold. Returns the exit code."""
    cmd = [sys.executable, str(RUNNER), "--holding-days", str(hold),
           "--save-folds", str(out_path), *passthrough]
    print(f"\n{'=' * 72}\nHOLDING {hold} DAYS\n{'=' * 72}")
    print("  " + " ".join(cmd[1:]))
    proc = subprocess.run(cmd, cwd=str(ROOT), text=True, encoding="utf-8",
                          errors="replace")
    return proc.returncode


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def calendar(run: dict) -> list:
    return [(f["start"], f["end"]) for f in run.get("folds", [])]


def excess_excluding_best_fold(run: dict) -> tuple[float | None, int | None]:
    """Baseline-arm pooled excess with the largest-contributing fold removed.

    The arithmetic lives in ``kala.expectation`` because the daily run
    needs the same figure, and two copies of a concentration check is how two
    answers start to disagree.

    BASELINE arm specifically. The headline column of this table is the
    baseline arm, and the version of this function shipped in v76 decomposed it
    using the CHOSEN arm's per-fold excess — the only per-fold column the saved
    tables carried. Those arms pool to +1.71% and +1.27% over different trade
    counts, so the ex-best column was subtracting one arm's quarter from the
    other arm's total. It is the audit's own recurring defect, in the tool
    written to detect it, and the collapse verdict was read off it.

    Returns (None, None) for a table without the baseline column rather than
    falling back to the chosen arm. A fallback here is what produced the wrong
    number in the first place; "n/a" is the honest cell.
    """
    folds = run.get("folds", [])
    if not any(f.get("excess_baseline_pct") is not None for f in folds):
        return None, None
    return excess_excluding_largest_fold(folds, "n_baseline",
                                         "excess_baseline_pct")


def tabulate(runs: list[tuple[int, dict]]) -> None:
    print(f"\n{'=' * 78}\nHOLDING-PERIOD SWEEP\n{'=' * 78}")
    print(f"{'hold':>6}{'trades':>9}{'excess':>10}{'ex-best fold':>14}"
          f"{'clustered t':>13}{'defl. Sharpe':>14}{'folds<0':>9}")
    print("-" * 78)
    drops: list = []
    for hold, r in runs:
        base = r.get("pooled_excess_baseline") or {}
        n = base.get("n", 0)
        ev = base.get("ev_pct")
        ct = r.get("pooled_excess_baseline_clustered_t")
        dsr = r.get("pooled_excess_baseline_dsr")
        folds = r.get("folds", [])
        # Same arm as the headline, for the same reason as the ex-best column.
        neg_key = ("excess_baseline_pct"
                   if any(f.get("excess_baseline_pct") is not None for f in folds)
                   else "excess_pct")
        neg = sum(1 for f in folds
                  if f.get(neg_key) is not None and f[neg_key] < 0)
        ev_s = f"{ev:+.2f}%" if ev is not None else "n/a"
        ct_s = f"{ct:+.2f}" if ct is not None else "n/a"
        dsr_s = f"{dsr:.3f}" if dsr is not None else "n/a"
        xb, xb_fold = excess_excluding_best_fold(r)
        xb_s = f"{xb:+.2f}%" if xb is not None else "n/a"
        print(f"{hold:>6}{n:>9}{ev_s:>10}{xb_s:>14}{ct_s:>13}{dsr_s:>14}"
              f"{neg:>6}/{len(r.get('folds', []))}")
        drops.append((hold, ev, xb, xb_fold))
    print("-" * 78)
    print("ex-best fold = pooled excess with the single biggest-contributing fold")
    print("  removed. If that column is flat or negative while the headline climbs,")
    print("  the sweep is measuring one quarter, not the parameter.")
    if any(x is None for _, _, x, _ in drops):
        print("\n  'n/a' in that column means the fold table has no per-fold")
        print("  BASELINE excess — it was written before that column existed.")
        print("  The headline is the baseline arm, so decomposing it with the")
        print("  chosen arm's folds would subtract one arm from another. Re-run")
        print("  the sweep to get the column; the earlier ex-best figures from")
        print("  v76 were computed that wrong way and should not be carried over.")

    scored = [(r.get("pooled_excess_baseline", {}).get("ev_pct"), h)
              for h, r in runs]
    scored = [(e, h) for e, h in scored if e is not None]
    if not scored:
        print("No excess figures — was a benchmark supplied?")
        return
    best_ev, best_h = max(scored)
    print(f"\nBest excess: {best_h}d at {best_ev:+.2f}%/trade.")
    print("\nRead this as a SHAPE, not a pick. Choosing the best of N holding")
    print("periods is the same multiple-testing move the deflated Sharpe column")
    print("exists to discount — a smooth hump with a broad top is a finding, a")
    print("single spike between two bad neighbours is a coin flip that landed.")
    usable = [(h, ev, xb) for h, ev, xb in
              ((h, ev, xb) for h, ev, xb, _ in drops) if ev is not None and xb is not None]
    if usable and all(xb <= 0.25 for _, _, xb in usable):
        print("\nEVERY holding period collapses to <= +0.25%/trade once its biggest")
        print("fold is removed. The ramp in the headline column is that fold growing,")
        print("not the strategy improving. Do not read this sweep as a parameter choice.")

    ordered = sorted(runs, key=lambda hr: hr[0])
    evs = [(h, (r.get("pooled_excess_baseline") or {}).get("ev_pct"))
           for h, r in ordered]
    evs = [(h, e) for h, e in evs if e is not None]
    if len(evs) >= 3:
        peak = max(range(len(evs)), key=lambda i: evs[i][1])
        if peak in (0, len(evs) - 1):
            print(f"\nNOTE: the best value is at the EDGE of the swept range "
                  f"({evs[peak][0]}d). The\n  optimum may lie outside it — "
                  f"extend the sweep before concluding.")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--holds", type=int, nargs="+", required=True,
                    help="holding_max_days values to sweep, e.g. 20 30 45 60 90")
    ap.add_argument("--out-dir", default="results",
                    help="where the per-run fold tables are written")
    ap.add_argument("--prefix", default="f_hold",
                    help="fold-table filename prefix (default f_hold)")
    ap.add_argument("--reuse", action="store_true",
                    help="skip a holding value whose fold table already exists. "
                         "Use to resume an interrupted sweep — NOT to mix runs "
                         "from different warehouse states, which the calendar "
                         "check below will catch anyway.")
    ap.add_argument("--allow-misaligned", action="store_true",
                    help="tabulate even when fold calendars differ. Off by "
                         "default: a warehouse refresh mid-sweep shifts fold "
                         "boundaries, and comparing holding periods across "
                         "different quarters measures the quarters.")
    args, passthrough = ap.parse_known_args()

    if len(set(args.holds)) != len(args.holds):
        print("--holds contains duplicates; each value must appear once.",
              file=sys.stderr)
        return 1
    if any(h < 1 for h in args.holds):
        print("--holds values must be >= 1.", file=sys.stderr)
        return 1
    if any(a.startswith("--holding-days") or a.startswith("--save-folds")
           for a in passthrough):
        print("--holding-days and --save-folds are set per run by this script; "
              "remove them from the passthrough arguments.", file=sys.stderr)
        return 1

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    runs: list[tuple[int, dict]] = []
    for hold in sorted(args.holds):
        path = out_dir / f"{args.prefix}_{hold}.json"
        if args.reuse and path.exists():
            print(f"\n[reuse] {path} already exists — skipping the {hold}d run.")
        else:
            rc = run_one(hold, path, passthrough)
            if rc != 0:
                print(f"\nThe {hold}d run exited {rc}. Stopping rather than "
                      f"tabulating a partial sweep.", file=sys.stderr)
                return rc
        if not path.exists():
            print(f"\n{path} was not written. Stopping.", file=sys.stderr)
            return 1
        runs.append((hold, load(path)))

    ref = calendar(runs[0][1])
    bad = [h for h, r in runs[1:] if calendar(r) != ref]
    if bad:
        print(f"\nFOLD CALENDARS DIFFER for holding value(s): "
              f"{', '.join(map(str, bad))}", file=sys.stderr)
        print(f"  reference is {runs[0][0]}d, fold 0 = {ref[0] if ref else '?'}")
        print("  A warehouse refresh mid-sweep does this. Comparing these")
        print("  compares different quarters, not different holding periods.")
        if not args.allow_misaligned:
            print("  Refusing to tabulate. Re-run the sweep in one sitting, or "
                  "pass --allow-misaligned.", file=sys.stderr)
            return 1
        print("  --allow-misaligned given; tabulating anyway. Read with care.")

    tabulate(runs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
