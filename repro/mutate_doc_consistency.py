"""Reinsert each defect; a test suite that stays green has not tested anything.

Run it from anywhere:  python repro/mutate_doc_consistency.py

Three targets:

  * ``check_docs.py`` — the checker that compares documented claims against the
    repository. A checker that cannot fail is the most reassuring kind of
    nothing, so every one of its checks is disabled in turn — including the
    newest one, which stops it accusing a script that could not be run of
    rejecting flags it accepts.
  * ``daily_run.parse_capital_override`` — the flag that needed an exemption
    from that checker, and turned out to be silently ignorable in three
    ordinary spellings, on a script that would not answer ``--help``.
  * ``intraday_watch.parse_args`` — the other exemption, and the same defect:
    ``--forse`` ran unforced, and a closed market exits silently, so the
    mistyped run and the successful one looked identical.
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _mutation_guard import run_mutations  # noqa: E402

_HERE = Path(__file__).resolve().parent
AUG = next(c for c in (_HERE.parent, _HERE.parent / "aug")
           if (c / "kala").is_dir())

TESTS = ("tests/test_docs_match_the_repo.py",)
CD = "check_docs.py"
DR = "daily_run.py"
IW = "intraday_watch.py"

MUTATIONS = [
    # ---- the checker's four checks ----------------------------------------
    ("M1 line counts are never compared", CD,
     "        if claimed != actual:\n"
     '            out.append(f"{name}: summary says {claimed:,} lines, '
     'file has {actual:,}")',
     "        if False:\n"
     '            out.append(f"{name}: summary says {claimed:,} lines, '
     'file has {actual:,}")'),

    ("M2 a missing line-count claim counts as satisfied", CD,
     '            out.append(f"AUDIT_SUMMARY.md no longer quotes {name}\'s line count")',
     "            pass"),

    ("M3 the test-file count is never compared", CD,
     "    if claimed_files != actual_files:",
     "    if False:"),

    ("M4 a missing test-count claim counts as satisfied", CD,
     '        return ["AUDIT_SUMMARY.md no longer quotes a test count"]',
     "        return []"),

    ("M5 broken path references are ignored", CD,
     '            out.append(f"{name} references `{ref}`, which does not exist")',
     "            pass"),

    ("M6 every path reference is treated as a placeholder", CD,
     "            if ref in PLACEHOLDERS or (ROOT / ref).exists():",
     "            if True:"),

    ("M7 unknown flags in documented commands are ignored", CD,
     "                if f in h.text or (script, f) in HAND_PARSED:",
     "                if True:"),

    ("M8 a documented command for a missing script is ignored", CD,
     '                out.append(f"{name}: `python {script} ...` '
     '— script does not exist")',
     "                pass"),

    ("M9 the hand-parsed exemption becomes script-wide", CD,
     "                if f in h.text or (script, f) in HAND_PARSED:",
     "                if f in h.text or any(s == script for s, _ in HAND_PARSED):"),

    ("M10 the command extractor matches nothing", CD,
     r'CMD = re.compile(r"python\s+([\w./]+\.py)((?:[^\n`]|\\\n)*)")',
     r'CMD = re.compile(r"zzzz\s+([\w./]+\.py)((?:[^\n`]|\\\n)*)")'),

    # ---- the flag that was silently ignorable -----------------------------
    ("M17 the illustrative-name exemption goes script-wide", CD,
     "            if not flags or script in COMMAND_PLACEHOLDERS:",
     "            if not flags or script.endswith('.py'):"),

    # ---- the checker accusing code that never got to answer ---------------
    ("M18 a crashing --help is read as the flag list", CD,
     """    out = r.stdout + r.stderr
    if r.returncode != 0:
        return Help(out, f"--help exited {r.returncode}: {_why(out)}")
    return Help(out, "")""",
     """    out = r.stdout + r.stderr
    return Help(out, "")"""),

    ("M19 a --help that times out is an empty flag list", CD,
     '        return Help("", "--help did not finish within 300s")',
     '        return Help("", "")'),

    ("M20 an unrunnable script's flags become contradictions", CD,
     "            if h.failure:",
     "            if False:"),

    ("M21 unverified claims exit 0 like a clean run", CD,
     "    if rep.unverified:",
     "    if False:"),

    ("M22 a run that checked nothing exits 0", CD,
     """    if rep.unrunnable:
        print("\\nNothing that could be checked contradicts the repository. Some "
              "of it could not be checked (above), so this run is incomplete.")
        return 2""",
     "    if False:\n        return 2"),

    ("M23 the reason a script would not run is not reported", CD,
     """    if rep.unrunnable:
        print(f"\\n{len(rep.unrunnable)} SCRIPT(S) COULD NOT BE RUN — their "
              f"documented flags were compared against source text only:")""",
     """    if False:
        print(f"\\n{len(rep.unrunnable)} SCRIPT(S) COULD NOT BE RUN — their "
              f"documented flags were compared against source text only:")"""),

    # ---- the two scripts that would not describe their own flags ----------
    ("M24 daily_run swallows --help again", DR,
     """        if arg in ("-h", "--help"):
            print(USAGE, end="")
            raise SystemExit(0)""",
     "        if False:\n            pass"),

    ("M25 intraday --force back to the silent 'in sys.argv' check", IW,
     "    return ap.parse_args(sys.argv[1:] if argv is None else argv)",
     "    return type('A', (), {'force': '--force' in "
     "(sys.argv[1:] if argv is None else argv)})()",
     ("tests/test_intraday_watch.py",)),

    ("M11 back to the silent 'in sys.argv' check", DR,
     """    argv = list(argv)
    value = None
    i = 0""",
     """    argv = list(argv)
    if "--capital" in argv:
        return float(argv[argv.index("--capital") + 1])
    return None
    value = None
    i = 0"""),

    ("M12 an unknown option is ignored again", DR,
     """        elif arg.startswith("-"):
            raise BadArgument(""",
     """        elif False:
            raise BadArgument("""),

    ("M13 the equals form is dropped", DR,
     '        elif arg.startswith("--capital="):',
     "        elif False:"),

    ("M14 a non-numeric amount is accepted as zero", DR,
     """        try:
            value = float(raw)
        except ValueError:
            raise BadArgument(f"--capital {raw!r} is not a number") from None""",
     """        try:
            value = float(raw)
        except ValueError:
            value = 0.0"""),

    ("M15 a non-positive amount is accepted", DR,
     "        if value <= 0:",
     "        if False:"),

    ("M16 a missing amount reads past the end", DR,
     """            if i + 1 >= len(argv):
                raise BadArgument("--capital needs an amount, e.g. --capital 3000000")""",
     """            if False:
                raise BadArgument("--capital needs an amount, e.g. --capital 3000000")"""),
]


def failing_tests(tests=TESTS) -> list[str]:
    out = subprocess.run([sys.executable, "-m", "pytest", *tests, "-q", "--no-header",
                          "-p", "no:cacheprovider"],
                         cwd=AUG, capture_output=True, text=True, encoding="utf-8",
                         errors="replace")
    return [ln.split("::")[-1].split()[0]
            for ln in out.stdout.splitlines() if ln.startswith("FAILED")]


def main() -> int:
    return run_mutations(AUG, MUTATIONS, failing_tests, TESTS)


if __name__ == "__main__":
    raise SystemExit(main())
