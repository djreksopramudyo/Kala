#!/usr/bin/env python3
"""Reinsert each defect; a test suite that stays green has not tested anything.

Run it from anywhere:  python repro/mutate_state_durability.py

Each mutation is applied to a real source file, the targeted test file is run,
and the file is restored in a finally block. Nothing is left modified even if
pytest itself dies.
"""
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _mutation_guard import run_mutations  # noqa: E402

_HERE = Path(__file__).resolve().parent
AUG = next(c for c in (_HERE.parent, _HERE.parent / "aug")
           if (c / "kala").is_dir())
TESTS = "tests/test_state_files_are_durable.py"

MUTATIONS = [
    ("M1 watchlist.save non-atomic", "kala/watchlist.py",
     lambda s: s.replace(
         """        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, self.path)""",
         """        self.path.write_text(payload, encoding="utf-8")""")),

    ("M2 positions.save non-atomic", "kala/positions.py",
     lambda s: s.replace(
         """        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, self.path)""",
         """        self.path.write_text(payload, encoding="utf-8")""")),

    ("M3 absent watchlist leaves no note", "kala/watchlist.py",
     lambda s: s.replace(
         """            store = cls(path)
            store.load_note = f"no file at {path.resolve()}"
            return store""",
         """            return cls(path)""")),

    ("M4 load_or_report swallows the damage", "kala/watchlist.py",
     lambda s: re.sub(
         r"    warn = warn or \(lambda msg: print\(msg, file=sys\.stderr\)\)",
         "    warn = warn or (lambda msg: print(msg, file=sys.stderr))\n"
         "    warn = lambda msg: None  # noqa: E731 - MUTATION",
         s)),

    ("M5 default_universe swallows both reads", "kala/universe_sources.py",
     lambda s: s.replace(
         """    for note in u.notes:
        warn(f"WARNING: {note} — that source contributed 0 tickers to this run.")""",
         """    u.notes = []
    for note in u.notes:
        warn(f"WARNING: {note} — that source contributed 0 tickers to this run.")""")),

    ("M6 archiver path back to cwd-relative", "archive_sentiment.py",
     lambda s: s.replace('WATCHLIST_PATH = ROOT / "watchlist.json"',
                         'WATCHLIST_PATH = "watchlist.json"')),

    ("M7 compose drops the watchlist mount", "docker-compose.yml",
     lambda s: s.replace("      - ./watchlist.json:/app/watchlist.json\n", "")),

    ("M8 DOCKER.md seeds with touch", "DOCKER.md",
     lambda s: s.replace(
         "for f in runner_config.json watchlist.json; do",
         "touch paper_state.json runner_config.json watchlist.json\n"
         "for f in runner_config.json watchlist.json; do")),
]


def failing_tests(tests=TESTS) -> list[str]:
    out = subprocess.run([sys.executable, "-m", "pytest", TESTS, "-q", "--no-header",
                          "-p", "no:cacheprovider"],
                         cwd=AUG, capture_output=True, text=True)
    return [ln.split("::")[-1].split()[0]
            for ln in out.stdout.splitlines() if ln.startswith("FAILED")]


def main() -> int:
    return run_mutations(AUG, MUTATIONS, failing_tests, TESTS)


if __name__ == "__main__":
    raise SystemExit(main())
