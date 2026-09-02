"""Reinsert each defect; a test suite that stays green has not tested anything.

Run it from anywhere:  python repro/mutate_config_registry.py

Targets the config-key registry — the thing that decides whether preflight
tells the user a setting works or tells them it does nothing.

M1 and M2 are the original defects, restored: drop each missing key back out of
the registry. Neither raises. Both produce a confident, specific, wrong warning
about a setting that works — one of them about the audit's headline
recommendation, the other about a circuit-breaker safety toggle.
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _mutation_guard import run_mutations  # noqa: E402

_HERE = Path(__file__).resolve().parent
AUG = next(c for c in (_HERE.parent, _HERE.parent / "aug")
           if (c / "kala").is_dir())

TESTS = ("tests/test_config_keys_are_registered.py",)
PF = "kala/preflight.py"

MUTATIONS = [
    ("M1 the veto key leaves the registry", PF,
     "    _ENTRY_VETO_KEY,\n",
     ""),

    ("M2 the breaker key leaves the registry", PF,
     '    "breaker_preserve_halt_when_unreadable",\n',
     ""),

    ("M3 the registry keeps its own copy of the veto key", PF,
     "    _ENTRY_VETO_KEY,",
     '    "disabled_entry_vetoes",'),

    ("M4 the import is dropped for a literal", PF,
     "from .entry_settings import CONFIG_KEY as _ENTRY_VETO_KEY",
     '_ENTRY_VETO_KEY = "disabled_entry_vetoes"'),

    ("M5 every unknown key is accepted", PF,
     "    unknown = sorted(set(cfg) - set(known))",
     "    unknown = []"),

    ("M6 the warning stops saying the setting is inert", PF,
     '            f"\'{key}\' is not read by any code{hint} It is silently ignored, so "\n'
     '            f"whatever you set it to is having no effect."',
     '            f"\'{key}\' is unrecognised.{hint}"'),
]


def failing_tests(tests=TESTS) -> list[str]:
    out = subprocess.run([sys.executable, "-m", "pytest", *tests, "-q", "--no-header",
                          "-p", "no:cacheprovider"],
                         cwd=AUG, capture_output=True, text=True)
    return [ln.split("::")[-1].split()[0]
            for ln in out.stdout.splitlines() if ln.startswith("FAILED")]


def main() -> int:
    return run_mutations(AUG, MUTATIONS, failing_tests, TESTS)


if __name__ == "__main__":
    raise SystemExit(main())
