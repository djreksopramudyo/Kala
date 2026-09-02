"""`--apply-entry-vetoes` is five filters; the cost has to be attributable.

Measured on the full universe against EQUAL_WEIGHT, fixed-baseline arm:

    no vetoes                  +1.71%/trade   clustered t +1.92
    --apply-entry-vetoes       -2.52%/trade   clustered t -3.10
    + --veto-ranging-stock     -2.31%/trade   clustered t -2.69

So the group costs about 4.2 points and the ranging veto is not the cause. But
the group is RSI, parabolic, OBV-distribution, thin-volume and bear-regime
switched on together, and until now the CLI had no way to separate them — the
EntryConfig flags existed, nothing exposed them.

Leave-one-out over `--disable-veto` is what attributes it.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kala.config import CostModel, EntryConfig  # noqa: E402
from run_walkforward import (  # noqa: E402
    VETO_FLAGS,
    build_run_config,
    run_provenance,
    saved_table,
)


def _entries(disabled=(), apply_vetoes=True):
    return build_run_config("forward_test", CostModel(), apply_vetoes, False,
                            disabled_vetoes=tuple(disabled)).entries


def test_every_registry_name_maps_to_a_real_EntryConfig_field():
    """A typo here would silently disable nothing at all.

    `EntryConfig(**{"veto_ovrebought": False})` raises, so a wrong mapping
    fails loudly — but only if something constructs it. This asserts the
    fields exist independently of that.
    """
    default = EntryConfig()
    for name, field in VETO_FLAGS.items():
        assert hasattr(default, field), f"{name} -> {field} is not an EntryConfig field"
        assert getattr(default, field) is True, (
            f"{field} defaults to False, so disabling it measures nothing")


def test_disabling_nothing_leaves_every_veto_on():
    e = _entries()
    for field in VETO_FLAGS.values():
        assert getattr(e, field) is True


@pytest.mark.parametrize("name", sorted(VETO_FLAGS))
def test_disabling_one_veto_turns_off_exactly_that_one(name):
    """Leave-one-out is only interpretable if exactly one thing changed."""
    e = _entries([name])
    assert getattr(e, VETO_FLAGS[name]) is False, f"{name} was not disabled"
    for other, field in VETO_FLAGS.items():
        if other != name:
            assert getattr(e, field) is True, (
                f"disabling {name} also disabled {other}")


def test_disabling_several_turns_off_exactly_those():
    e = _entries(["rsi", "parabolic"])
    assert e.veto_overbought is False
    assert e.veto_parabolic is False
    assert e.veto_distribution is True
    assert e.veto_thin_volume is True
    assert e.block_buys_in_bear is True


def test_disabling_all_five_is_not_the_same_object_as_no_vetoes():
    """It reproduces the no-veto ENTRY behaviour, which is worth stating.

    A run with every veto disabled is the plain arm with extra steps; the run
    banner says so rather than letting it be filed as a veto experiment.
    """
    e = _entries(sorted(VETO_FLAGS))
    for field in VETO_FLAGS.values():
        assert getattr(e, field) is False


def test_the_ranging_veto_is_independent_of_the_five():
    """It has its own flag and must not be touched by --disable-veto."""
    e = build_run_config("forward_test", CostModel(), True, True,
                         disabled_vetoes=("rsi", "bear")).entries
    assert e.veto_ranging_stock is True
    assert "veto_ranging_stock" not in VETO_FLAGS.values()


# ---- the CLI refuses the silent no-op -------------------------------------

def _cli(*extra):
    return subprocess.run(
        [sys.executable, str(ROOT / "run_walkforward.py"),
         "--tickers", "AAAA.JK", "--period", "1y", *extra],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(ROOT), timeout=300)


def test_disable_veto_without_apply_entry_vetoes_is_refused():
    """Without --apply-entry-vetoes no veto runs, so disabling one is a no-op.

    Left permitted, it would produce a run identical to the plain no-veto arm
    and save it under a filename claiming to measure a specific veto — a
    result that reads as evidence and contains none.
    """
    out = _cli("--disable-veto", "rsi")
    assert out.returncode == 1
    assert "has no effect without" in out.stderr
    assert "--apply-entry-vetoes" in out.stderr


def test_an_unknown_veto_name_is_rejected_by_the_parser():
    """A typo must not silently disable nothing."""
    out = _cli("--apply-entry-vetoes", "--disable-veto", "rsii")
    assert out.returncode != 0
    assert "invalid choice" in (out.stderr + out.stdout)


def test_the_flag_is_documented_in_help():
    out = subprocess.run([sys.executable, str(ROOT / "run_walkforward.py"), "--help"],
                         capture_output=True, text=True, encoding="utf-8",
                         errors="replace", cwd=str(ROOT))
    assert out.returncode == 0
    assert "--disable-veto" in out.stdout
    for name in VETO_FLAGS:
        assert name in out.stdout, f"{name} is not listed in --help"


# ---- the saved table must say which arm produced it -----------------------

class _Strategy:
    name = "momentum"


def _args(apply_vetoes=False, disabled=()):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply-entry-vetoes", action="store_true")
    ap.add_argument("--disable-veto", nargs="*", default=[], choices=sorted(VETO_FLAGS))
    ap.add_argument("--exit-profile", default="forward_test")
    ap.add_argument("--benchmark", default="EQUAL_WEIGHT")
    argv = (["--apply-entry-vetoes"] if apply_vetoes else [])
    if disabled:
        argv += ["--disable-veto", *disabled]
    return ap.parse_args(argv)


def _prov(apply_vetoes=False, disabled=(), measured_at="2026-08-23"):
    cfg = build_run_config("forward_test", CostModel(), apply_vetoes, False,
                           disabled_vetoes=tuple(disabled))
    return run_provenance(_args(apply_vetoes, disabled), _Strategy(), cfg, 569,
                          measured_at=measured_at)


def test_the_saved_fold_json_records_the_veto_arm():
    """v68 CLAIMED to write these fields and did not.

    The patch that added them used a replacement anchor with the wrong
    indentation and NO assertion, so it matched nothing and silently did
    nothing — while CHANGES.md stated the fields were being written. Fifteen
    real runs later, every saved table was missing `apply_entry_vetoes` and
    `disabled_vetoes`, and the only thing distinguishing a no-veto table from
    an all-veto one was its filename.

    Asserted by CALLING run_provenance, which is why it is a function.
    """
    prov = _prov(apply_vetoes=True, disabled=["rsi", "bear"])
    assert prov["apply_entry_vetoes"] is True
    assert prov["disabled_vetoes"] == ["bear", "rsi"], "must be sorted, for diffing"


def test_a_no_veto_run_is_distinguishable_from_an_all_veto_run():
    """The whole point: two tables must not be identical but for the filename."""
    assert _prov(apply_vetoes=False) != _prov(apply_vetoes=True)
    assert _prov(apply_vetoes=False)["apply_entry_vetoes"] is False
    assert _prov(apply_vetoes=True)["apply_entry_vetoes"] is True


def test_two_different_leave_one_out_arms_are_distinguishable():
    """f_veto_no_rsi and f_veto_no_obv must not read as the same run."""
    a = _prov(apply_vetoes=True, disabled=["rsi"])
    b = _prov(apply_vetoes=True, disabled=["obv"])
    assert a != b
    assert a["disabled_vetoes"] == ["rsi"] and b["disabled_vetoes"] == ["obv"]


def test_the_provenance_is_json_serialisable():
    """It is written with json.dumps; a stray numpy float would break the save."""
    import json as _json
    round_tripped = _json.loads(_json.dumps(_prov(apply_vetoes=True, disabled=["obv"])))
    assert round_tripped["disabled_vetoes"] == ["obv"]
    assert round_tripped["strategy"] == "momentum"
    assert round_tripped["n_tickers"] == 569


def test_the_saved_table_still_carries_what_it_carried_before():
    """Extracting the dict must not have dropped any pre-existing field."""
    prov = _prov()
    for key in ("strategy", "exit_profile", "baseline_threshold",
                "holding_max_days", "benchmark", "n_tickers"):
        assert key in prov, f"{key} was lost in the extraction"


def _fake_report():
    """A stand-in for WalkForwardReport — enough shape for saved_table."""
    from datetime import datetime
    from types import SimpleNamespace as NS

    def fold(i, n, ev, exc):
        return NS(fold=NS(fold_id=i,
                          test_start=datetime(2024, 1, 1 + i),
                          test_end=datetime(2024, 4, 1 + i)),
                  chosen_threshold=60.0,
                  oos_chosen={"n": n, "ev_pct": ev, "win_rate_pct": 50.0},
                  benchmark_return_pct=1.0,
                  oos_excess_chosen={"n": n, "ev_pct": exc},
                  # Baseline arm: different n AND different excess, so a test
                  # cannot pass by reading the chosen arm's column.
                  oos_excess_baseline={"n": n // 2, "ev_pct": exc + 10.0})

    return NS(folds=[fold(0, 40, 2.0, 1.5), fold(1, 10, -1.0, -3.0)],
              pooled_excess_baseline={"n": 50, "ev_pct": 0.6},
              pooled_excess_chosen={"n": 80, "ev_pct": 0.9},
              pooled_excess_clustered_t=1.1,
              pooled_excess_dsr=0.4,
              pooled_excess_baseline_clustered_t=1.2,
              pooled_excess_baseline_dsr=0.5)


def test_the_written_table_actually_contains_the_provenance():
    """Ties run_provenance to the bytes on disk — by CALLING the writer.

    This assertion used to be ``assert "**run_provenance(args, strategy, cfg,
    len(dfs))," in src`` — a grep of this module's own source. That is not a
    test of anything: it passes whenever the line exists, including when the
    line is unreachable, and it would have passed unchanged through the v68
    defect it was written to prevent (a patch anchored at the wrong
    indentation matched nothing, the old line stayed, the grep stayed green,
    and fifteen tables were written without the fields).

    Extracting ``saved_table`` makes the real question answerable: given this
    provenance and this report, what dict gets serialised?
    """
    prov = _prov(apply_vetoes=True, disabled=["rsi"])
    table = saved_table(prov, _fake_report())
    for key, value in prov.items():
        assert table[key] == value, f"{key} did not reach the saved table"
    assert table["apply_entry_vetoes"] is True
    assert table["disabled_vetoes"] == ["rsi"]


def test_the_written_table_keeps_the_fold_rows_and_pooled_statistics():
    """The provenance must not have displaced the numbers it describes."""
    table = saved_table(_prov(), _fake_report())
    assert [f["fold"] for f in table["folds"]] == [0, 1]
    assert table["folds"][0]["excess_pct"] == 1.5
    assert table["folds"][0]["start"] == "2024-01-01"
    # Both arms, distinguishable. Until this release only the chosen arm's
    # per-fold excess was saved, so nothing could decompose the baseline
    # headline the verdict is actually rendered from.
    assert table["folds"][0]["excess_baseline_pct"] == 11.5
    assert table["folds"][0]["n_baseline"] == 20
    assert table["pooled_excess_chosen"] == {"n": 80, "ev_pct": 0.9}
    assert table["pooled_excess_baseline"] == {"n": 50, "ev_pct": 0.6}
    assert table["pooled_excess_baseline_clustered_t"] == 1.2
    assert table["pooled_excess_baseline_dsr"] == 0.5


def test_the_table_records_when_it_was_measured():
    """Without it the daily run can only ever say 'age unknown'."""
    assert _prov(measured_at="2026-01-31")["measured_at"] == "2026-01-31"


def test_the_table_records_how_many_thresholds_the_dsr_deflated_for():
    """A DSR of 0.77 means different things over a 6-grid and a 60-grid."""
    class Gridded:
        name = "momentum"
        default_thresholds_grid = (50, 55, 60, 65, 70, 75)

    cfg = build_run_config("forward_test", CostModel(), False, False)
    prov = run_provenance(_args(), Gridded(), cfg, 10, measured_at="2026-01-01")
    assert prov["threshold_grid_size"] == 6
    # A strategy declaring no grid records 0, not a guess.
    assert _prov()["threshold_grid_size"] == 0
