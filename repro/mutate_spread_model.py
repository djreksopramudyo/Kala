"""Reinsert each defect; a test suite that stays green has not tested anything.

Run it from anywhere:  python repro/mutate_spread_model.py

Targets the cost model the live book charges — the number that scales every
P&L figure the forward test will be judged on.

M1 is the original defect: drop the cost model on the floor when resolving the
trading config, so the setting reaches the scanner and never the fills. It
raises nothing and every report still renders.
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _mutation_guard import run_mutations  # noqa: E402

_HERE = Path(__file__).resolve().parent
AUG = next(c for c in (_HERE.parent, _HERE.parent / "aug")
           if (c / "kala").is_dir())

TESTS = ("tests/test_live_spread_model.py",)
KEYS = ("tests/test_config_keys_are_registered.py",)
CFG = "kala/config.py"
EXP = "kala/expectation.py"
RUNNER = "run_walkforward.py"
DR = "daily_run.py"

MUTATIONS = [
    ("M1 the trading config drops the cost model", CFG,
     "    return replace(config_for_profile(settings.get(\"exit_profile\")),\n"
     "                   costs=live_costs(settings))",
     "    return config_for_profile(settings.get(\"exit_profile\"))"),

    ("M2 daily_run resolves the profile only", DR,
     "    trade_cfg = config_from_settings(cfg)",
     "    from kala.config import config_for_profile\n"
     "    trade_cfg = config_for_profile(cfg.get(\"exit_profile\"))"),

    ("M3 the setting is ignored", CFG,
     '    mode = (settings or {}).get("costs_spread_mode")',
     '    mode = None'),

    ("M4 an unknown spread mode is tolerated", CFG,
     """    if mode not in VALID_SPREAD_MODES:""",
     """    if False:"""),

    ("M5 the default silently becomes tick_floor", CFG,
     """    if mode is None:
        return CostModel()""",
     """    if mode is None:
        return CostModel(spread_mode="tick_floor")"""),

    # ---- the measurement has to say which model it charged ----------------
    ("M6 the saved table stops recording the spread model", RUNNER,
     '        "spread_mode": cfg.costs.spread_mode,\n',
     ""),

    ("M7 an unrecorded spread model is assumed to be flat", EXP,
     '        return self.raw.get("spread_mode")',
     '        return self.raw.get("spread_mode") or "flat"'),

    ("M8 the spread model stops being binding", EXP,
     '        ("spread_mode", m.spread_mode, live.spread_mode),\n',
     ""),

    ("M9 LiveSetup always reports flat", EXP,
     '            spread_mode=getattr(cfg.costs, "spread_mode", "flat"),',
     '            spread_mode="flat",'),

    # ---- the registry, both directions ------------------------------------
    ("M10 the dead 'costs' key comes back", "kala/preflight.py",
     '    "target_allocation", "charge_manual_costs",',
     '    "target_allocation", "costs", "charge_manual_costs",', KEYS),

    ("M11 the new key is unregistered", "kala/preflight.py",
     '    "costs_spread_mode",\n',
     "", KEYS + TESTS),
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
