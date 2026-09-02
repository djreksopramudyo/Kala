#!/usr/bin/env python3
"""Reinsert each defect; a test suite that stays green has not tested anything.

Run it from anywhere:  python repro/mutate_position_ageing.py

Targets the max-holding-period path — the one exit rule that still runs under
the ``forward_test`` profile, and therefore the only thing standing between a
position and being held forever.

The hardest mutation to catch here is the original one: M1 restores the exact
date match, which does not raise, does not warn, and produces a report that
looks exactly like a healthy day. If M1 survived, nothing in this repository
would be testing the finding.
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _mutation_guard import run_mutations  # noqa: E402

_HERE = Path(__file__).resolve().parent
AUG = next(c for c in (_HERE.parent, _HERE.parent / "aug")
           if (c / "kala").is_dir())

TESTS = ("tests/test_max_holding_is_always_checked.py",)
WITH_OLD = TESTS + ("tests/test_papertrade.py", "tests/test_telegram_bot.py")

PT = "kala/papertrade.py"
TB = "telegram_bot.py"

MUTATIONS = [
    # ---- the original defect ----------------------------------------------
    ("M1 back to exact date equality", PT,
     '''        pos = int(days.searchsorted(key, side="left"))
        return int(len(idx) - 1 - pos), None''',
     '''        mask = days == key
        if not mask.any():
            return None, "not a trading bar"
        return int(len(idx) - 1 - mask.argmax()), None'''),

    ("M2 an unageable position is skipped silently again", PT,
     '''                if held is None:''',
     '''                if False:''', WITH_OLD),

    ("M3 the skip note omits the reason", PT,
     '''                        f"{t}: max-holding rule NOT checked — {why}")''',
     '''                        f"{t}: max-holding rule NOT checked")'''),

    ("M4 the skip note stops naming the ticker", PT,
     '''                    report["unevaluated"].append(
                        f"{t}: max-holding rule NOT checked — {why}")''',
     '''                    report["unevaluated"].append(
                        f"max-holding rule NOT checked — {why}")'''),

    # ---- what must still be refused ---------------------------------------
    ("M5 a pre-window entry is snapped forward anyway", PT,
     '''        if key < days[0]:
            return None, (f"entry {key.date()} predates this history window "
                          f"(starts {days[0].date()})")''',
     ''''''),

    ("M6 a future entry date is accepted", PT,
     '''        if key > days[-1]:
            return None, (f"entry {key.date()} is after the last bar "
                          f"({days[-1].date()})")''',
     ''''''),

    ("M7 an unparseable date returns a bare None", PT,
     '''    except (ValueError, TypeError):
        return None, f"entry date {entry_date!r} is not a date"''',
     '''    except (ValueError, TypeError):
        return None, None'''),

    ("M8 NaT passes the date check", PT,
     '''    if key is pd.NaT or pd.isna(key):
        return None, f"entry date {entry_date!r} is not a date"''',
     ''''''),

    # ---- the exit rule itself still has to work ---------------------------
    ("M9 the max-holding exit never fires", PT,
     '''                elif held >= max_days:''',
     '''                elif False:''', WITH_OLD),

    ("M10 off-by-one: the limit becomes exclusive", PT,
     '''                elif held >= max_days:''',
     '''                elif held > max_days:''', WITH_OLD),

    # ---- /review carried the same guard -----------------------------------
    ("M11 review goes back to a bare HOLD", TB,
     '''        elif urgency == "NONE" and bars_held is None:''',
     '''        elif False:'''),

    ("M12 review's note omits the reason", TB,
     '''            reason = f"max-holding rule NOT checked — {held_why}"''',
     '''            reason = "max-holding rule NOT checked"'''),

    ("M13 review's note fires on healthy positions too", TB,
     '''        elif urgency == "NONE" and bars_held is None:''',
     '''        elif urgency == "NONE":'''),
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
