"""Reinsert each defect; a test suite that stays green has not tested anything.

Run it from anywhere:  python repro/mutate_live_threshold.py

Targets the live BUY cutoff — the number that decides which trades happen at
all, and which the daily log had been misreporting on every run.

M1 is the original defect: put the hardcoded ``Config()`` back. It raises
nothing, logs nothing, and produces a scan that looks entirely normal.
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _mutation_guard import run_mutations  # noqa: E402

_HERE = Path(__file__).resolve().parent
AUG = next(c for c in (_HERE.parent, _HERE.parent / "aug")
           if (c / "kala").is_dir())

TESTS = ("tests/test_live_entry_threshold.py",)
CFG = "kala/config.py"
DT = "kala_daily_trader.py"

MUTATIONS = [
    ("M1 back to the hardcoded legacy default", DT,
     "        buy_threshold = _live_config().backtest.score_entry_threshold",
     "        from kala.config import Config as _C\n"
     "        buy_threshold = _C().backtest.score_entry_threshold"),

    ("M2 the resolver ignores the profile", CFG,
     '    return replace(config_for_profile(settings.get("exit_profile")),\n'
     '                   costs=live_costs(settings))',
     "    return Config()"),

    ("M3 an unreadable config raises instead of falling back", CFG,
     '''    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Config()''',
     '    settings = json.loads(path.read_text(encoding="utf-8"))'),

    # The non-dict guard used to live in live_config AND in the resolver.
    # Deleting either one changed nothing — an untestable branch, which is the
    # same thing as dead code. The duplicate is gone; this targets the one
    # that remains.
    ("M4 a non-dict config is passed straight through", CFG,
     "    settings = settings if isinstance(settings, dict) else {}",
     "    pass"),

    ("M5 an unknown profile falls back silently", CFG,
     '''    raise ValueError(
        f"unknown exit_profile {profile!r} — use 'legacy' or 'forward_test'")''',
     "    return Config()"),

    # ---- the band ladder --------------------------------------------------
    ("M6 the buy cutoff is ignored by the ladder", DT,
     "    if score >= buy_threshold:\n        return 'BUY'",
     "    if score >= 60:\n        return 'BUY'"),

    ("M7 strong is allowed below the buy cutoff", DT,
     "    strong = max(float(strong_threshold), float(buy_threshold))",
     "    strong = float(strong_threshold)"),

    ("M8 the buy cutoff becomes exclusive", DT,
     "    if score >= buy_threshold:",
     "    if score > buy_threshold:"),

    ("M9 unsafe stocks are scored normally", DT,
     """    if not is_safe:
        return 'AVOID'""",
     ''''''),

    ("M10 the HOLD floor swallows the SELL band", DT,
     "    if score >= 50:\n        return 'HOLD'",
     "    if score >= 0:\n        return 'HOLD'"),
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
