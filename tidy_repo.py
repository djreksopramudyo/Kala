"""
Tidy the working tree — safely, on Windows, without touching anything live.

Complements cleanup_repo.sh (which handles the GIT side: untracking junk,
.gitignore). This handles the DISK side that accumulates day to day:

  1. results/ output older than --age-days (default 30) -> results/archive/
     (daily_run.log and the .walkforward_done_* / .backtest_done_* marker
     files are never moved — the scheduler reads them).
  2. Stray root artifacts -> results/archive/ : walkforward_result.txt,
     *.patch, paper_state_backup_*.json.
  3. __pycache__/ and .pytest_cache/ deleted (regenerated on next run).

NEVER touched: paper_state.json, runner_config.json, watchlist.json, any
.py/.md/.ps1/.txt source or doc at the root (except the known artifacts
above), and anything already inside results/archive/.

Default is a DRY RUN that prints the plan. Nothing moves until --apply.

Usage:
    python tidy_repo.py             # show what would happen
    python tidy_repo.py --apply     # actually do it
    python tidy_repo.py --age-days 60 --apply
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent

KEEP_IN_RESULTS = ("daily_run.log",)
KEEP_PREFIXES = (".walkforward_done_", ".backtest_done_")
ROOT_ARTIFACTS = ("walkforward_result.txt",)
ROOT_ARTIFACT_GLOBS = ("*.patch", "paper_state_backup_*.json")


def plan_tidy(root: Path, now_ts: float | None = None, age_days: int = 30) -> list[tuple]:
    """Return the full action plan as (kind, src, dst) tuples, where kind is
    'archive' (move) or 'delete' (cache dirs only). Pure — no filesystem
    writes — so it's directly testable and exactly what --apply executes."""
    now_ts = time.time() if now_ts is None else now_ts
    archive = root / "results" / "archive"
    plan: list[tuple] = []

    results = root / "results"
    if results.is_dir():
        cutoff = now_ts - age_days * 86400
        for f in sorted(results.iterdir()):
            if not f.is_file():
                continue
            if f.name in KEEP_IN_RESULTS or f.name.startswith(KEEP_PREFIXES):
                continue
            if f.stat().st_mtime < cutoff:
                plan.append(("archive", f, archive / f.name))

    for name in ROOT_ARTIFACTS:
        f = root / name
        if f.is_file():
            plan.append(("archive", f, archive / f.name))
    for pattern in ROOT_ARTIFACT_GLOBS:
        for f in sorted(root.glob(pattern)):
            if f.is_file():
                plan.append(("archive", f, archive / f.name))

    for cache in sorted(root.rglob("__pycache__")) + [root / ".pytest_cache"]:
        if cache.is_dir() and ".venv" not in cache.parts:
            plan.append(("delete", cache, None))

    return plan


def apply_plan(plan: list[tuple]) -> None:
    for kind, src, dst in plan:
        if kind == "archive":
            dst.parent.mkdir(parents=True, exist_ok=True)
            target = dst
            n = 1
            while target.exists():        # never overwrite an archived file
                target = dst.with_name(f"{dst.stem}_{n}{dst.suffix}")
                n += 1
            shutil.move(str(src), str(target))
        elif kind == "delete":
            shutil.rmtree(src, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="execute the plan (default: dry run)")
    ap.add_argument("--age-days", type=int, default=30,
                    help="archive results/ files older than this (default 30)")
    args = ap.parse_args()

    plan = plan_tidy(ROOT, age_days=args.age_days)
    if not plan:
        print("Nothing to tidy — already clean.")
        return 0

    n_arch = sum(1 for k, *_ in plan if k == "archive")
    n_del = sum(1 for k, *_ in plan if k == "delete")
    print(f"{'APPLYING' if args.apply else 'DRY RUN'} — {n_arch} file(s) to archive, "
          f"{n_del} cache dir(s) to delete:\n")
    for kind, src, dst in plan:
        rel = src.relative_to(ROOT)
        if kind == "archive":
            print(f"  archive  {rel}  ->  {dst.relative_to(ROOT)}")
        else:
            print(f"  delete   {rel}/")

    if args.apply:
        apply_plan(plan)
        print("\nDone. Archived files are in results/archive/ (moved, not deleted).")
    else:
        print("\nDry run only — re-run with --apply to execute.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
