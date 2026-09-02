#!/usr/bin/env python3
"""Reinsert each defect; a test suite that stays green has not tested anything.

Run it from anywhere:  python repro/mutate_measured_expectation.py

Targets kala/expectation.py — the module that puts a measured expectation
next to the daily recommendation. Its whole job is to be silent about numbers
it cannot justify, and silence is the hardest behaviour to test: a broken
version of this module is one that helpfully prints something.

Each mutation is applied to the real source, the targeted tests are run, and
the file is restored — through repro/_mutation_guard.py, which puts the
original bytes in an fsynced sentinel BEFORE touching the file, so even a
SIGKILL leaves the next run able to put it back. An anchor that no longer
matches is reported as STALE, not as a result: a mutation that never applied
measured nothing in either direction.

DOCUMENTED EQUIVALENT MUTANT
----------------------------
Replacing the threshold comparison's epsilon with plain `!=` survives, and is
listed below as EQUIVALENT rather than as a gap. Every threshold reaching this
code is a small decimal that round-trips exactly through JSON, so `60 != 60.0`
is False either way. The epsilon is defensive against a value arriving from
somewhere that computed it; no test can distinguish the two, and writing one
that pretended to would be theatre.
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _mutation_guard import run_mutations  # noqa: E402

_HERE = Path(__file__).resolve().parent
AUG = next(c for c in (_HERE.parent, _HERE.parent / "aug")
           if (c / "kala").is_dir())
DEFAULT_TESTS = ("tests/test_expectation.py",)
SWEEP_TESTS = ("tests/test_sweep_holding_walkforward.py",)
TABLE_TESTS = ("tests/test_disable_individual_vetoes.py",)

SRC = "kala/expectation.py"
SWEEP = "sweep_holding_walkforward.py"
RUNNER = "run_walkforward.py"

MUTATIONS = [
    # ---- zero-vs-missing --------------------------------------------------
    ("M1 missing excess renders as 0.0", SRC,
     """        if not self.n_trades:
            return None
        return self.excess.get("ev_pct")""",
     """        if not self.n_trades:
            return 0.0
        return self.excess.get("ev_pct")"""),

    ("M2 a malformed table becomes an empty measurement", SRC,
     """    if not isinstance(raw, dict):
        return None""",
     """    if not isinstance(raw, dict):
        raw = {}"""),

    ("M3 the not-measured block drops the zero warning", SRC,
     """        "  That is NOT the same as an expectation of zero — it is an absence of",
        "  evidence, and it should be read as one.",""",
     """        "  (no data)","""),

    # ---- the veto-arm trap ------------------------------------------------
    ("M4 veto arm read from disabled_vetoes alone", SRC,
     """    applied = m.applies_vetoes
    if applied is None:
        return None
    if not applied:
        return tuple(sorted(VETO_NAMES))
    return tuple(sorted(m.disabled_vetoes))""",
     """    return tuple(sorted(m.disabled_vetoes))"""),

    ("M5 an unrecorded veto arm counts as agreement", SRC,
     """        if got is None:
            # A field the table never recorded cannot be shown to agree with
            # anything. "Not recorded" suppresses the number the same as a
            # difference does, because it is one — an unknown one.
            out.append((key, "not recorded", _fmt(want)))""",
     """        if got is None:
            pass"""),

    # ---- withholding ------------------------------------------------------
    ("M6 mismatches are warned about but the number still prints", SRC,
     """        head.extend(measure_command(live, m.path))
        return head""",
     """        head.extend(measure_command(live, m.path))"""),

    ("M7 the exit profile stops being binding", SRC,
     """        ("exit_profile", profile.strip().lower() if profile else None,
         (live.exit_profile or "legacy").strip().lower()),""",
     """"""),

    ("M8 the holding period stops being binding", SRC,
     """        ("holding_max_days", m.holding_max_days, live.holding_max_days),""",
     """"""),

    # ---- concentration ----------------------------------------------------
    ("M9 biggest fold picked by percentage not contribution", SRC,
     """    biggest = max(rows, key=lambda r: r[0] * r[1])""",
     """    biggest = max(rows, key=lambda r: r[1])"""),

    ("M10 the concentration line is dropped", SRC,
     """    xb, fold_id, arm = m.concentration
    if xb is not None and arm == "baseline":""",
     """    xb, fold_id, arm = m.concentration
    if False:"""),

    ("M11 a fold with no excess counts as zero", SRC,
     """    rows = [(n, e, i) for n, e, i in rows if e is not None and n]""",
     """    rows = [(n, e or 0.0, i) for n, e, i in rows if n]"""),

    # ---- staleness --------------------------------------------------------
    ("M12 age taken from the file mtime", SRC,
     """    stamp = m.measured_at
    if not stamp:
        return None""",
     """    import datetime as _dt
    return (today - _dt.date.fromtimestamp(m.path.stat().st_mtime)).days
    stamp = m.measured_at
    if not stamp:
        return None"""),

    ("M13 nothing is ever called stale", SRC,
     """        if age > STALE_DAYS:""",
     """        if False:"""),

    ("M14 a future stamp renders as a negative age", SRC,
     """    elif age < 0:""",
     """    elif False:"""),

    # ---- the verdict may not outrun its evidence --------------------------
    ("M15 sub-bar DSR on an old table goes unremarked", SRC,
     """    if (m.dsr is not None and m.dsr < DSR_CONFIDENT and not m.grid_size""",
     """    if (False and m.dsr is not None and m.dsr < DSR_CONFIDENT and not m.grid_size"""),

    ("M16 the deflation caveat fires unconditionally", SRC,
     """    if (m.dsr is not None and m.dsr < DSR_CONFIDENT and not m.grid_size
            and m.n_trades >= 30 and (m.excess_pct or 0) > 0
            and (m.clustered_t or stats.get("t_stat") or 0) >= T_CONFIDENT):""",
     """    if True:"""),

    ("M17 the grid size is never passed to the verdict", SRC,
     """    lines = ["VERDICT: " + edge_verdict(stats, clustered_t=m.clustered_t,
                                        dsr=m.dsr, n_trials=m.grid_size)]""",
     """    lines = ["VERDICT: " + edge_verdict(stats, clustered_t=m.clustered_t,
                                        dsr=m.dsr, n_trials=0)]"""),

    # ---- the live block ---------------------------------------------------
    ("M18 the live block stops naming the veto setting", SRC,
     """    return [describe_vetoes(ecfg), ""] + block(live, path=path, today=today)""",
     """    return block(live, path=path, today=today)"""),

    ("M19 an unknown veto name is tolerated in the live block", SRC,
     """    ecfg = entry_config_from(cfg or {})""",
     """    try:
        ecfg = entry_config_from(cfg or {})
    except Exception:
        from .config import EntryConfig
        ecfg = EntryConfig()"""),

    ("M20 the live block ignores the running exit profile", SRC,
     """    live = LiveSetup.from_config(trade_cfg, disabled,
                                 exit_profile=(cfg or {}).get("exit_profile"))""",
     """    live = LiveSetup.from_config(trade_cfg, disabled,
                                 exit_profile="forward_test")"""),

    # ---- the daily run has to emit it -------------------------------------
    ("M21 the daily run stops emitting the block", "daily_run.py",
     """    report_measured_expectation(cfg, trade_cfg)""",
     """    pass"""),

    ("M22 a reporting failure is swallowed", "daily_run.py",
     """        emit(f"MEASURED EXPECTATION: could not be reported — "
             f"{type(e).__name__}: {e}")""",
     """        pass"""),

    ("M23 the failure note omits what went wrong", "daily_run.py",
     """             f"{type(e).__name__}: {e}")""",
     """             f"")"""),

    # ---- the decomposition must decompose the number above it -------------
    ("M24 concentration silently falls back to the chosen arm", SRC,
     '        if self.has_baseline_folds:\n'
     '            value, fold_id = excess_excluding_largest_fold(\n'
     '                self.folds, "n_baseline", "excess_baseline_pct")\n',
     '        if False:\n'
     '            value, fold_id = excess_excluding_largest_fold(\n'
     '                self.folds, "n_baseline", "excess_baseline_pct")\n'),

    ("M25 the fallback is presented as the baseline arm", SRC,
     '        return value, fold_id, "chosen"\n',
     '        return value, fold_id, "baseline"\n'),

    ("M26 negative folds counted on the chosen arm regardless", SRC,
     '        key = "excess_baseline_pct" if self.has_baseline_folds else "excess_pct"\n',
     '        key = "excess_pct"\n'),

    ("M27 the saved table drops the baseline fold column", RUNNER,
     """        "n_baseline": (fr.oos_excess_baseline or {}).get("n", 0),
        "excess_baseline_pct": excess_ev(fr.oos_excess_baseline),""",
     """""", TABLE_TESTS),

    ("M28 the saved table drops the chosen arm's pooled excess", RUNNER,
     """        "pooled_excess_chosen": report.pooled_excess_chosen,""",
     """""", TABLE_TESTS),

    ("M29 the sweep falls back to the chosen arm", SWEEP,
     """    folds = run.get("folds", [])
    if not any(f.get("excess_baseline_pct") is not None for f in folds):
        return None, None
    return excess_excluding_largest_fold(folds, "n_baseline",
                                         "excess_baseline_pct")""",
     """    return excess_excluding_largest_fold(run.get("folds", []))""",
     SWEEP_TESTS),

    ("M30 the sweep counts negative folds on the chosen arm", SWEEP,
     """        neg_key = ("excess_baseline_pct"
                   if any(f.get("excess_baseline_pct") is not None for f in folds)
                   else "excess_pct")""",
     '        neg_key = "excess_pct"',
     SWEEP_TESTS),

    # ---- the printed instruction must produce an acceptable table ---------
    # Each of these makes the command describe a DIFFERENT configuration from
    # the one running, so following it produces a table this same block then
    # refuses. Only the round-trip test — generate, parse with the real CLI,
    # build the provenance, compare — can see that.
    ("M32 the command stops tracking the live setup", SRC,
     '    if live is not None:\n        args.append(f"--exit-profile {live.exit_profile}")',
     '    if False:\n        args.append(f"--exit-profile {live.exit_profile}")'),

    ("M33 the command omits the spread model", SRC,
     '        if live.spread_mode == "tick_floor":\n'
     '            args.append("--tick-spread")\n',
     ""),

    ("M34 the command omits the veto arm", SRC,
     '        if live.disabled_vetoes:\n'
     '            args.append("--disable-veto " + " ".join(live.disabled_vetoes))\n',
     ""),

    ("M35 the command omits the holding period", SRC,
     '        args.append(f"--holding-days {live.holding_max_days}")\n',
     ""),

    ("M36 the command omits the threshold", SRC,
     '        args.append(f"--baseline-threshold {live.baseline_threshold:g}")\n',
     ""),

    ("M37 the command drops --apply-entry-vetoes", SRC,
     '        args.append("--apply-entry-vetoes")\n',
     ""),

    ("M31 the sweep does not explain the n/a column", SWEEP,
     """    if any(x is None for _, _, x, _ in drops):""",
     """    if False:""",
     SWEEP_TESTS),
]


def failing_tests(tests=DEFAULT_TESTS) -> list[str]:
    out = subprocess.run([sys.executable, "-m", "pytest", *tests, "-q", "--no-header",
                          "-p", "no:cacheprovider"],
                         cwd=AUG, capture_output=True, text=True)
    return [ln.split("::")[-1].split()[0]
            for ln in out.stdout.splitlines() if ln.startswith("FAILED")]


def main() -> int:
    return run_mutations(AUG, MUTATIONS, failing_tests, DEFAULT_TESTS)


if __name__ == "__main__":
    raise SystemExit(main())
