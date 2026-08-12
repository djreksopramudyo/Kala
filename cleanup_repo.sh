#!/usr/bin/env bash
#
# cleanup_repo.sh — tidy the Kala repo WITHOUT deleting your data.
#
# What it does:
#   1. Deletes the stray top-level universe.py (the live one is kala/universe.py).
#   2. Stops tracking generated junk (results/, __pycache__/, .pytest_cache/) in git,
#      but LEAVES the files on disk — `git rm --cached` only updates the index.
#   3. Stages the new .gitignore so the junk stays out from now on.
#
# It does NOT commit and does NOT touch git history. Review `git status`, then
# commit yourself. Run from the repo root.
#
# Note: history bloat (your ~10 MB .git, mostly old results/ blobs) is a SEPARATE
# step — see the comment at the bottom — because it rewrites history and is
# destructive to clones. This script deliberately stops short of that.

set -euo pipefail

if [ ! -d .git ]; then
  echo "error: run this from the repo root (no .git/ here)." >&2
  exit 1
fi

echo "==> 1. Removing stray top-level universe.py (duplicate of kala/universe.py)"
if [ -f universe.py ]; then
  git rm --quiet universe.py 2>/dev/null || rm -f universe.py
  echo "    removed universe.py"
else
  echo "    (already gone)"
fi

echo "==> 2. Untracking generated junk (files stay on disk)"
# --cached = unstage/untrack only; -r = recursive; --ignore-unmatch = don't error if absent
git rm -r --cached --quiet --ignore-unmatch \
  results/ \
  __pycache__/ \
  kala/__pycache__/ \
  tests/__pycache__/ \
  .pytest_cache/ \
  '*.pyc' >/dev/null 2>&1 || true
echo "    untracked results/, all __pycache__/, .pytest_cache/, *.pyc"

echo "==> 3. Staging .gitignore"
git add .gitignore
echo "    staged .gitignore"

echo
echo "Done. Nothing was committed and no local files were deleted (except the"
echo "stray universe.py). Review and commit:"
echo
echo "    git status"
echo "    git commit -m \"chore: add .gitignore, untrack generated output, drop stray universe.py\""
echo
echo "Optional, LATER — shrink .git history (DESTRUCTIVE, rewrites history):"
echo "    pip install git-filter-repo"
echo "    git filter-repo --path results/ --invert-paths"
echo "  Only do this on a repo you can force-push, and tell collaborators first."
