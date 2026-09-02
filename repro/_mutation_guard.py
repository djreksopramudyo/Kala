"""Never leave a source file mutated, even if the harness is killed.

WHY THIS EXISTS
---------------
Every mutation harness here wrote a defect into a real source file, ran the
tests, and restored the original in a ``finally``. ``finally`` covers an
exception and a Ctrl-C. It does **not** cover SIGKILL, a timeout kill, a
container stop, or the harness process dying — and one of those happened:

    $ python repro/mutate_live_threshold.py     # killed at the 10-minute mark
    ...
    $ diff kala_daily_trader.py            # left carrying mutation M8
    <     if score > buy_threshold:
    ---
    >     if score >= buy_threshold:

The only symptom was one unrelated-looking test failing later. The file that
stayed mutated is the one that decides which stocks the live bot buys, and the
mutation left in it — an inclusive bound turned exclusive — is precisely the
kind that changes behaviour without looking like damage.

Worse than the test failure: a zip built from a tree in that state would ship a
mutated live trading file, and nothing would say so.

HOW IT WORKS
------------
Before a file is modified, its original bytes go into a sentinel written and
fsynced to disk. The sentinel is removed only after the file is restored. So at
every instant, either the file is intact or the sentinel holds what it was.

``restore_if_interrupted()`` runs at the start of every harness. It reports
loudly — a silently self-healing repair would hide the fact that a run was
killed, which is the same failure this whole audit is about.
"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path

SENTINEL_NAME = ".mutation_in_progress.json"


def sentinel_path(root: Path) -> Path:
    return Path(root) / SENTINEL_NAME


def _write_sentinel(root: Path, rel: str, original: str) -> None:
    p = sentinel_path(root)
    tmp = p.with_name(p.name + ".tmp")
    payload = json.dumps({"file": rel, "original": original}, ensure_ascii=False)
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(payload)
        f.flush()
        os.fsync(f.fileno())          # the point of the exercise
    os.replace(tmp, p)


def restore_if_interrupted(root: Path) -> str | None:
    """Undo a mutation a killed run left behind. Returns the file, or None.

    Reports rather than repairing quietly: a harness that silently tidied up
    after itself would leave no trace that a run had been killed, and "the
    tree was mutated for a while" is exactly the kind of fact this project
    keeps finding was never recorded.
    """
    p = sentinel_path(root)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        rel, original = data["file"], data["original"]
    except (OSError, ValueError, KeyError):
        raise SystemExit(
            f"{p} exists but cannot be read. A previous run was killed while a "
            f"source file was mutated and the record of the original is "
            f"damaged. Restore from git before running anything else.") from None
    target = Path(root) / rel
    changed = target.read_text(encoding="utf-8") != original
    target.write_text(original, encoding="utf-8")
    p.unlink()
    return f"{rel}{'' if changed else ' (already matched)'}"


@contextmanager
def mutated(root: Path, rel: str, new_text: str):
    """Apply ``new_text`` to ``rel``, restoring it whatever happens.

    The sentinel is on disk before the file is touched, so a kill at any point
    leaves the next run able to put it back.
    """
    target = Path(root) / rel
    original = target.read_text(encoding="utf-8")
    _write_sentinel(Path(root), rel, original)
    try:
        target.write_text(new_text, encoding="utf-8")
        yield
    finally:
        target.write_text(original, encoding="utf-8")
        sentinel_path(Path(root)).unlink(missing_ok=True)


def run_mutations(root: Path, mutations, failing_tests, default_tests) -> int:
    """Apply each mutation, run its tests, report, restore. Shared by every
    harness so the sentinel and the STALE/SURVIVED distinction exist once.

    ``mutations`` items are either

        (label, rel_path, old, new[, tests])   anchored text replacement
        (label, rel_path, transform[, tests])  a callable str -> str

    The callable form exists because some defects are not a single contiguous
    span. Both forms detect a no-op the same way — if the file comes back
    unchanged, the anchor is STALE and nothing was measured.
    """
    restored = restore_if_interrupted(root)
    if restored:
        print(f"NOTE: a previous run was killed while {restored} was mutated. "
              f"It has been restored.\n")

    def _tests_of(m):
        spec = m[2:]
        rest = spec[1:] if callable(spec[0]) else spec[2:]
        return rest[0] if rest else default_tests

    every = tuple(sorted({t for m in mutations for t in _tests_of(m)}))
    base = failing_tests(every)
    if base:
        print(f"BASELINE IS NOT GREEN: {base}")
        return 1
    print("baseline: green\n")

    survivors, stale = [], []
    for label, rel, *spec in mutations:
        if callable(spec[0]):
            transform, rest = spec[0], spec[1:]
        else:
            old, new = spec[0], spec[1]
            rest = spec[2:]
            def transform(s, _o=old, _n=new):
                return s.replace(_o, _n, 1)
        tests = rest[0] if rest else default_tests
        original = (Path(root) / rel).read_text(encoding="utf-8")
        changed = transform(original)
        if changed == original:
            # A mutation that never applied measured nothing in either
            # direction. Calling it "caught" would hide the gap completely.
            print(f"{label:<48} !!! STALE ANCHOR — nothing was measured")
            stale.append(label)
            continue
        with mutated(root, rel, changed):
            red = failing_tests(tests)
        if red:
            print(f"{label:<48} caught by {len(red)}: {', '.join(red[:2])}"
                  + (" ..." if len(red) > 2 else ""))
        else:
            print(f"{label:<48} *** SURVIVED — nothing tests this ***")
            survivors.append(label)

    print()
    if stale:
        print(f"{len(stale)} STALE anchor(s): {stale}")
        print("  Fix the anchors first — a stale anchor is not evidence.")
    if survivors:
        print(f"{len(survivors)} mutation(s) SURVIVED: {survivors}")
    if stale or survivors:
        return 1
    print(f"all {len(mutations)} mutations applied and caught")
    return 0
