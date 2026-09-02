"""The verdict's control arm must sit on the tested signal's own scale.

`_edge_verdict` is computed from `pooled_excess_baseline` — the FIXED baseline
arm, deliberately, because judging on the per-fold chosen threshold would be
the multiple-testing trap this harness exists to avoid.

But `walk_forward_strategy`'s docstring says an explicit `cfg` overrides the
strategy's own `default_threshold` — "used exactly as given, no magic" — and
`--exit-profile forward_test` carries `score_entry_threshold=80`, a number
from the COMPOSITE SCORE's work. Applied to another signal it is a number
from a different scale:

    strategy              own default   own grid    forced to
    mean_reversion             60        40-80         80   (top of grid)
    support_resistance         50        20-60         80   (OUTSIDE)
    dividend_yield             50        30-70         80   (OUTSIDE)

For the two marked OUTSIDE the baseline arm sits above the strategy's entire
grid: it trades almost nothing, and the verdict printed from it is noise.
That was live, and a run of mean_reversion printed "NO OOS EDGE" from a
baseline arm at 80 while its walk-forward arm showed excess +2.09% at
clustered t +3.58.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kala.config import CostModel  # noqa: E402
from kala.strategies import get_strategy, list_strategies  # noqa: E402
from kala.walkforward import excess_ev, trade_stats  # noqa: E402
from run_walkforward import (  # noqa: E402
    baseline_provenance_lines,
    build_run_config,
    thin_baseline_arm_warning,
)

for _m in ("strategy_mean_reversion", "strategy_support_resistance",
           "strategy_dividend_yield", "strategy_low_volatility",
           "strategy_multihorizon_trend"):
    try:
        importlib.import_module(f"kala.{_m}")
    except Exception:  # noqa: BLE001 - a missing optional strategy is not this test's business
        pass


def _cfg(profile="forward_test", baseline=None):
    return build_run_config(profile, CostModel(), False, False,
                            baseline_threshold=baseline)


def test_the_profile_threshold_is_still_used_when_nothing_overrides_it():
    """Momentum keeps the historical behaviour — this is not a silent change."""
    assert _cfg().backtest.score_entry_threshold == 80.0


def test_an_explicit_baseline_wins():
    assert _cfg(baseline=55.0).backtest.score_entry_threshold == 55.0
    assert _cfg("legacy", baseline=30.0).backtest.score_entry_threshold == 30.0


def test_the_baseline_does_not_disturb_the_exit_geometry():
    """It is an ENTRY threshold; the profile still decides the exits."""
    c = _cfg(baseline=42.0)
    assert c.risk.trailing_enabled is False        # forward_test geometry intact
    assert c.risk.hard_stop_pct == -99.0
    assert c.backtest.holding_max_days == 60


@pytest.mark.parametrize("name", sorted(list_strategies()))
def test_every_strategys_own_default_sits_inside_its_own_grid(name):
    """The invariant that makes 'use the strategy's default' safe."""
    s = get_strategy(name)
    grid = getattr(s, "default_thresholds_grid", None)
    if not grid:
        pytest.skip(f"{name} declares no grid")
    assert min(grid) <= s.default_threshold <= max(grid), (
        f"{name}: default {s.default_threshold} outside grid "
        f"{min(grid)}-{max(grid)}")


@pytest.mark.parametrize("name", sorted(list_strategies()))
def test_the_forward_test_threshold_is_wrong_for_non_momentum_strategies(name):
    """Non-vacuity for the fix: show the number it replaces is really unusable.

    If this ever stops holding — because every strategy is rescaled to 0-100
    with the same meaning — the fix becomes unnecessary and this test says so
    by failing.
    """
    if name == "momentum":
        pytest.skip("momentum is the scale 80 came from")
    s = get_strategy(name)
    grid = getattr(s, "default_thresholds_grid", None)
    if not grid:
        pytest.skip(f"{name} declares no grid")
    forced = _cfg().backtest.score_entry_threshold          # 80, the profile's
    assert s.default_threshold != forced, (
        f"{name}: default already equals the profile's {forced}")


def test_run_walkforward_uses_the_strategy_default_for_non_momentum():
    src = (ROOT / "run_walkforward.py").read_text(encoding="utf-8")
    assert 'if baseline is None and strategy.name != "momentum":' in src
    assert "baseline = strategy.default_threshold" in src
    assert "baseline_threshold=baseline" in src


def test_the_run_prints_which_arm_the_verdict_comes_from():
    """The contradiction was readable only if you knew where to look.

    Naming the arm is half of it. The other half is the baseline's PROVENANCE:
    a reader who sees "80" alone cannot tell whether that is this strategy's
    own number or one carried in from the composite score's scale. So the line
    prints the strategy's default and grid beside it.

    An earlier version of this test pinned the string "OUTSIDE this strategy's
    grid", from a warning that declared such runs' verdicts meaningless. That
    warning was itself wrong — momentum's headline run has a baseline of 80
    against a 50-75 grid and traded 5,241 times — so the test was pinning a
    false claim in place. What replaced it is the provenance, which is true
    regardless of where the baseline lands.
    """
    out = " ".join(baseline_provenance_lines(80.0, 60.0, [40, 50, 60, 70, 80]))
    assert "fixed-baseline threshold: 80" in out
    assert "the VERDICT below is computed from this arm" in out
    assert "strategy default 60" in out          # provenance: whose number is it
    assert "grid 40-80" in out                   # provenance: what was searched
    assert "meaningless" not in out              # the old overclaim, not back


def test_the_provenance_line_survives_a_strategy_with_no_grid():
    """A strategy declaring no grid must still get a readable line, not a crash."""
    lines = baseline_provenance_lines(80.0, 60.0, None)
    out = " ".join(lines)
    assert "fixed-baseline threshold: 80" in out
    assert "strategy default 60" in out
    assert "grid" not in lines[0]                # no range invented on the head line
    assert "declares no grid" in out             # and the absence is stated, not hidden
    assert "NOTE:" not in out                    # no grid means no grid verdict


# ---- per-fold excess must be printed -------------------------------------

def test_the_fold_table_prints_per_fold_excess():
    """Comparing two strategies on the RAW fold column measures the market.

    Two long-only baskets drawn from the same universe rise together when the
    index rises, so their raw per-fold EV correlates strongly whether or not
    either has an edge. That is exactly the wrong quantity to compare, and it
    was the only one the report printed — which produced a false alarm about a
    hidden common factor before anyone noticed the column was raw.

    Asserted by RENDERING a fold with a known excess and reading the row back,
    not by grepping walkforward.py for the expression that computes it. The
    grep version of this test kept passing while the rendered column was wrong.
    """
    from kala.walkforward import Fold, FoldResult, WalkForwardReport

    fr = FoldResult(
        fold=Fold(fold_id=0,
                  train_start=pd.Timestamp("2024-01-01"),
                  train_end=pd.Timestamp("2024-06-30"),
                  test_start=pd.Timestamp("2024-07-01"),
                  test_end=pd.Timestamp("2024-09-30")),
        chosen_threshold=75.0,
        train_stats=trade_stats([1.0, 2.0]),
        oos_chosen=trade_stats([1.0, -2.0, 3.0]),
        oos_baseline=trade_stats([1.0, -2.0]),
        benchmark_return_pct=4.0,
        oos_excess_chosen=trade_stats([5.0, 5.0, 5.0]),   # a known +5.00
        oos_excess_baseline=trade_stats([5.0, 5.0]),
    )
    rep = WalkForwardReport(folds=[fr], baseline_threshold=80.0)
    rep.pooled_chosen = trade_stats([1.0, -2.0, 3.0])
    rep.pooled_baseline = trade_stats([1.0, -2.0])
    text = rep.summary_text()

    assert "excess%" in text, "the fold table has no excess column"
    row = [ln for ln in text.splitlines() if ln.startswith("0    ")]
    assert row, "the fold row was not rendered"
    assert "+5.00" in row[0], f"the excess column did not render: {row[0]!r}"


def test_a_fold_without_a_benchmark_prints_n_a_not_zero():
    """No benchmark means no excess. Printing 0.00 reads as 'measured, no alpha'.

    This test used to assert on the SOURCE TEXT of walkforward.py — it checked
    that the file contained the string
    `ex_s = f"{ex:+.2f}" if ex is not None else "  n/a"`. That string was
    present and the behaviour was still wrong, so the test passed for months
    while a real run printed `+0.00` fourteen times.

    The reason: `trade_stats([])` returns a fully populated dict whose ev_pct
    is 0.0, and a populated dict is TRUTHY, so `if fr.oos_excess_chosen` let
    the empty result through and `.get("ev_pct")` handed back 0.0 — never None,
    so the `else "n/a"` branch was unreachable. A source-text assertion cannot
    see that; only calling the code can.
    """
    assert excess_ev(trade_stats([])) is None, "an empty result must not be 0.0"
    assert excess_ev({}) is None
    assert excess_ev(None) is None
    # And a real measurement must still come through as a number, including a
    # genuine zero — which is a different fact from 'not measured'.
    assert excess_ev(trade_stats([2.0, -2.0])) == pytest.approx(0.0)
    assert excess_ev(trade_stats([1.0, 2.0, 3.0])) == pytest.approx(2.0)


def test_the_rendered_fold_table_says_n_a_when_there_was_no_benchmark():
    """End to end through summary_text(), which is what a user actually reads."""
    from kala.walkforward import Fold, FoldResult, WalkForwardReport

    fr = FoldResult(
        fold=Fold(fold_id=0,
                  train_start=pd.Timestamp("2024-01-01"),
                  train_end=pd.Timestamp("2024-06-30"),
                  test_start=pd.Timestamp("2024-07-01"),
                  test_end=pd.Timestamp("2024-09-30")),
        chosen_threshold=75.0,
        train_stats=trade_stats([1.0, 2.0]),
        oos_chosen=trade_stats([1.0, -2.0, 3.0]),
        oos_baseline=trade_stats([1.0, -2.0]),
        benchmark_return_pct=None,
        oos_excess_chosen=trade_stats([]),        # the no-benchmark case
        oos_excess_baseline=trade_stats([]),
    )
    rep = WalkForwardReport(folds=[fr], baseline_threshold=80.0)
    rep.pooled_chosen = trade_stats([1.0, -2.0, 3.0])
    rep.pooled_baseline = trade_stats([1.0, -2.0])

    row = [ln for ln in rep.summary_text().splitlines() if ln.startswith("0    ")]
    assert row, "the fold row was not rendered"
    assert "n/a" in row[0], f"expected n/a in the excess column, got: {row[0]!r}"
    assert "+0.00" not in row[0], f"a missing excess rendered as zero: {row[0]!r}"


def test_the_saved_fold_json_writes_null_not_zero_for_a_missing_excess():
    """--save-folds outlives the terminal; a fabricated 0.0 there is worse.

    Fourteen identical zeros also have zero variance, so correlating against
    them returns NaN — which reads as the comparison tool correctly declining
    to answer, when in fact it was handed invented data.
    """
    src = (ROOT / "run_walkforward.py").read_text(encoding="utf-8")
    assert '"excess_pct": excess_ev(' in src, "the save path bypasses excess_ev"
    # And the behaviour the save path depends on:
    assert excess_ev(trade_stats([])) is None
    assert json.dumps({"excess_pct": excess_ev(trade_stats([]))}) == '{"excess_pct": null}'


def test_an_out_of_grid_baseline_is_a_NOTE_not_a_verdict_killer():
    """80 is outside momentum's 50-75 search grid and still traded 5,241 times.

    Outside the SEARCH grid is not the same as invalid: these scores are 0-100,
    so a baseline above the grid is simply tighter than anything the per-fold
    selection considers. The first version of this warning called such a run's
    verdict meaningless, which was wrong on the project's own headline result.
    """
    # momentum's real shape: grid 50-75, baseline 80.
    out = " ".join(baseline_provenance_lines(80.0, 60.0, [50, 55, 60, 65, 70, 75]))
    assert "NOTE: baseline 80 sits outside the search grid (50-75)" in out
    assert "That is allowed" in out
    for overclaim in ("cannot be trusted", "meaningless", "is noise", "invalid"):
        assert overclaim not in out, f"the NOTE says {overclaim!r}"


def test_a_baseline_inside_the_grid_produces_no_NOTE_at_all():
    """Non-vacuity: the NOTE has to be absent when it does not apply.

    Without this, deleting the NOTE's condition entirely — printing it always,
    or never — would still satisfy the test above.
    """
    inside = " ".join(baseline_provenance_lines(60.0, 60.0, [50, 60, 70]))
    assert "NOTE:" not in inside
    assert "outside the search grid" not in inside
    # Boundaries are inside, not outside.
    assert "NOTE:" not in " ".join(baseline_provenance_lines(50.0, 60.0, [50, 60, 70]))
    assert "NOTE:" not in " ".join(baseline_provenance_lines(70.0, 60.0, [50, 60, 70]))
    # And one step past the top edge is outside.
    assert "NOTE:" in " ".join(baseline_provenance_lines(71.0, 60.0, [50, 60, 70]))


def test_a_thin_baseline_arm_is_flagged_from_the_MEASURED_trade_count():
    """The real check happens after the run, where the count exists.

    A grid comparison made before the run cannot say whether the baseline arm
    traded: 80 against a 50-75 grid sounds fatal and traded 5,241 times, while
    80 against support_resistance's 20-60 trades almost nothing. Only the
    count separates them.
    """
    # Thin: the fatal case, a verdict resting on almost no trades.
    warn = thin_baseline_arm_warning(40, 5000)
    assert warn is not None
    assert "40" in warn and "5000" in warn
    assert "treat it as unreliable" in warn

    # Healthy: momentum's actual run. No warning, or the flag means nothing.
    assert thin_baseline_arm_warning(5241, 5600) is None

    # The boundary is the fifth, and it is not exclusive of the healthy side.
    assert thin_baseline_arm_warning(1000, 5000) is None      # exactly 20%
    assert thin_baseline_arm_warning(999, 5000) is not None   # just under

    # No trades anywhere is not a thin-arm story; it is a no-run story, and
    # blaming the baseline for it would point the reader at the wrong thing.
    assert thin_baseline_arm_warning(0, 0) is None
