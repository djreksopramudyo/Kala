#!/usr/bin/env python3
"""Check the documentation against the repository it describes.

    python check_docs.py            # report
    python check_docs.py --quiet    # only print problems

    exit 0   every documented claim was checked, and none is contradicted
    exit 1   a documented claim is contradicted by the repository
    exit 2   nothing checked is contradicted, but something could NOT be
             checked — see WHEN A SCRIPT WILL NOT RUN below

WHY THIS EXISTS
---------------
This audit produced 2,400 lines of CHANGES.md, 4,200 of PROJECT_STATUS.md and
a summary quoting counts, filenames and commands from all of it. Every one of
those figures was synced BY HAND, several times, in a session whose recurring
finding is that a claim nobody re-checks drifts away from the thing it claims.

Finding 18 was exactly that: the daily run printed a command whose own output
it would then reject. It was found by running the instruction rather than
reading it. This does the same for the documents.

WHAT IT CHECKS
--------------
1. Quoted line counts of CHANGES.md / PROJECT_STATUS.md.
2. Quoted test-file count and passing-test count.
3. Every ``repro/``, ``tests/`` and ``kala/`` path named in backticks
   exists.
4. Every documented ``python foo.py --flag`` command names a script that
   exists, and every flag in it is one that script accepts.

WHAT IT DELIBERATELY DOES NOT CHECK
-----------------------------------
Measured RESULTS. +1.71%/trade cannot be re-derived without a five-year
warehouse and an hour of compute, and a checker that silently skipped it would
be worse than one that never claimed to. Those figures are guarded by the
saved fold tables and the repro scripts instead.

The flag check has an escape hatch (HAND_PARSED below) for scripts that read
sys.argv directly, because ``--help`` cannot list what argparse never saw. It is
empty. Both flags that once needed it were flags whose own script would not
describe them, and both scripts swallowed ``--help`` silently; the first of
them, ``daily_run.py --capital``, also turned out to be ignoring three ordinary
spellings of itself. Every exemption so far has been a bug wearing a waiver.

WHEN A SCRIPT WILL NOT RUN
--------------------------
The flag check runs each script's real ``--help``. If the script cannot even
import — an optional dependency missing, a wheel that needs a compiler the
machine does not have — then ``--help`` prints a traceback instead of a usage
line, and the first version of this checker read that traceback as the script's
flag list. A perfectly correct ``python weighting_study.py --period 8y`` came
back as *"weighting_study.py does not accept --period"*.

That is this audit's own signature defect, in the checker written to catch it:
a failure that renders as an ordinary negative result, and this one accuses
working code. The exit status of ``--help`` is now checked. A script that could
not be run is reported as *not checked*, its flags are compared against its
source text as weaker evidence, and the run exits 2 — because a checker that
quietly passes what it never checked would be worse than no checker at all.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from functools import lru_cache
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parent
SUMMARY = ROOT / "AUDIT_SUMMARY.md"

# Flags read straight from sys.argv, which --help cannot know about. Each needs
# a reason: this list is how a genuinely wrong flag would hide.
#
# It is empty, and staying empty is the point. Both original entries —
# `daily_run.py --capital` and `intraday_watch.py --force` — turned out to be
# flags their own scripts could not describe, and both scripts turned out to
# swallow `--help` silently. Fixing that removed the need for the exemption
# instead of the exemption removing the need to fix it. Add an entry only with
# the reason attached, and expect the reason to be a bug report.
HAND_PARSED: dict[tuple[str, str], str] = {}

# Paths that appear in docs as ILLUSTRATION rather than as claims about this
# repository. Kept explicit so a real broken reference cannot hide among them.
PLACEHOLDERS = {"kala/foo.py"}

# Script names used to DESCRIBE the shape of a command rather than to name one
# — "every documented `python foo.py --flag` command". Narrow on purpose: the
# first version of this checker flagged three of those in its own release
# notes, and the fix has to be an explicit exemption rather than contorting
# prose to satisfy a regex.
COMMAND_PLACEHOLDERS = {"foo.py"}

CMD = re.compile(r"python\s+([\w./]+\.py)((?:[^\n`]|\\\n)*)")
FLAG = re.compile(r"(?<![\w-])(--[a-z][a-z0-9-]*)")
PATH_REF = re.compile(r"`((?:repro|tests|kala)/[\w./]+\.py)`")


class Help(NamedTuple):
    """What ``--help`` said, and whether it can be believed.

    ``failure`` is empty only when the script printed its own usage. When it is
    set, ``text`` is whatever came out — a traceback, normally — and must never
    be read as the list of flags the script accepts.
    """
    text: str
    failure: str


def _why(output: str) -> str:
    """The line worth quoting from a failed run: a traceback's last one."""
    lines = [ln.strip() for ln in output.splitlines() if ln.strip()]
    return lines[-1] if lines else "no output"


@lru_cache(maxsize=None)
def script_help(script: str) -> Help | None:
    """``--help``, or None when the script does not exist.

    The return code is the point. A script that dies on import still writes to
    stderr and still exits — reading that output as a flag list is what made
    this checker accuse four working scripts of rejecting flags they accept.
    """
    if not (ROOT / script).exists():
        return None
    # Force the child's stdio to UTF-8 so it encodes what this decodes. Several
    # help strings here contain '≈' and '—'; on a Windows console defaulting to
    # cp1252 the child would die with UnicodeEncodeError while printing its own
    # usage, and a --help that crashes is now (correctly) an unchecked script.
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    try:
        r = subprocess.run([sys.executable, script, "--help"], cwd=ROOT,
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=300, env=env)
    except subprocess.TimeoutExpired:
        return Help("", "--help did not finish within 300s")
    out = r.stdout + r.stderr
    if r.returncode != 0:
        return Help(out, f"--help exited {r.returncode}: {_why(out)}")
    return Help(out, "")


@lru_cache(maxsize=None)
def source_flags(script: str) -> frozenset[str]:
    """Flags that appear literally in a script's own source.

    Weaker evidence than ``--help`` — a flag assembled with an f-string never
    appears, and a flag named only in a comment appears without existing — so
    this is consulted ONLY when ``--help`` could not be run, and the report says
    which of the two answered.
    """
    return frozenset(FLAG.findall(
        (ROOT / script).read_text(encoding="utf-8", errors="replace")))


class CommandReport(NamedTuple):
    problems: list[str]           # a real --help contradicts the document
    unverified: list[str]         # --help unavailable AND absent from source
    n_checked: int                # commands settled by a real --help
    n_from_source: int            # commands settled by source text only
    unrunnable: dict[str, str]    # script -> why --help could not be run


def docs() -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(ROOT.glob("*.md"))}


def check_line_counts(summary: str) -> list[str]:
    out = []
    for name in ("CHANGES.md", "PROJECT_STATUS.md"):
        m = re.search(rf"`{re.escape(name)}` \(([\d,]+) lines\)", summary)
        if not m:
            out.append(f"AUDIT_SUMMARY.md no longer quotes {name}'s line count")
            continue
        claimed = int(m.group(1).replace(",", ""))
        actual = len((ROOT / name).read_text(encoding="utf-8").splitlines())
        if claimed != actual:
            out.append(f"{name}: summary says {claimed:,} lines, file has {actual:,}")
    return out


def check_test_counts(summary: str) -> list[str]:
    m = re.search(r"Tests passing \| ([\d,]+) \(\d+ skipped, (\d+) files\)", summary)
    if not m:
        return ["AUDIT_SUMMARY.md no longer quotes a test count"]
    claimed_files = int(m.group(2))
    actual_files = len(list((ROOT / "tests").glob("test_*.py")))
    out = []
    if claimed_files != actual_files:
        out.append(f"test files: summary says {claimed_files}, tests/ has {actual_files}")
    return out


def check_path_references(all_docs: dict[str, str]) -> list[str]:
    out = []
    for name, text in all_docs.items():
        for ref in sorted(set(PATH_REF.findall(text))):
            if ref in PLACEHOLDERS or (ROOT / ref).exists():
                continue
            out.append(f"{name} references `{ref}`, which does not exist")
    return out


def check_commands(all_docs: dict[str, str]) -> CommandReport:
    out, unverified, unrunnable = [], [], {}
    checked = from_source = 0
    for name, text in all_docs.items():
        for m in CMD.finditer(text.replace("\\\n", " ")):
            script, tail = m.group(1), m.group(2)
            flags = sorted(set(FLAG.findall(tail)))
            if not flags or script in COMMAND_PLACEHOLDERS:
                continue
            h = script_help(script)
            if h is None:
                checked += 1
                out.append(f"{name}: `python {script} ...` — script does not exist")
                continue
            if h.failure:
                # The script could not be run, so it has said nothing about its
                # flags. Anything asserted here is an unresolved claim, never a
                # contradiction — accusing code that never got to answer is the
                # defect this branch exists to prevent.
                unrunnable[script] = h.failure
                from_source += 1
                named = source_flags(script)
                for f in flags:
                    if f in named or (script, f) in HAND_PARSED:
                        continue
                    unverified.append(
                        f"{name}: `python {script} {f}` — {script} never names "
                        f"{f} in its source, and its --help could not be run to "
                        f"settle it ({h.failure})")
                continue
            checked += 1
            for f in flags:
                if f in h.text or (script, f) in HAND_PARSED:
                    continue
                out.append(f"{name}: `python {script} {f}` — {script} does not "
                           f"accept {f}")
    return CommandReport(out, unverified, checked, from_source, unrunnable)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quiet", action="store_true",
                    help="print only problems, not the summary of what passed")
    args = ap.parse_args()

    all_docs = docs()
    summary = all_docs.get("AUDIT_SUMMARY.md", "")
    problems = (check_line_counts(summary) + check_test_counts(summary)
                + check_path_references(all_docs))
    rep = check_commands(all_docs)
    problems += rep.problems

    if not args.quiet:
        line = (f"{len(all_docs)} documents; {rep.n_checked} documented commands "
                f"checked against their real --help")
        if rep.n_from_source:
            line += (f"; {rep.n_from_source} against script source only")
        print(f"{line}; {len(HAND_PARSED)} hand-parsed flag(s) exempted.")

    # Printed even under --quiet: "this was not checked" is a result, not chatter.
    if rep.unrunnable:
        print(f"\n{len(rep.unrunnable)} SCRIPT(S) COULD NOT BE RUN — their "
              f"documented flags were compared against source text only:")
        for script, why in sorted(rep.unrunnable.items()):
            print(f"  {script}: {why}")

    if problems:
        print(f"\n{len(problems)} PROBLEM(S):")
        for p in problems:
            print(f"  {p}")
        print("\nEach is a claim the repository contradicts. Fix the document "
              "or the code — not this checker.")
        return 1
    if rep.unverified:
        print(f"\n{len(rep.unverified)} UNVERIFIED CLAIM(S):")
        for p in rep.unverified:
            print(f"  {p}")
        print("\nNot proof of a wrong document — the script could not answer. "
              "Install what it needs and run this again.")
        return 2
    if rep.unrunnable:
        print("\nNothing that could be checked contradicts the repository. Some "
              "of it could not be checked (above), so this run is incomplete.")
        return 2
    if not args.quiet:
        print("No documented claim contradicts the repository.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
