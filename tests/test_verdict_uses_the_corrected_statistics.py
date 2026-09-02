"""The headline verdict must obey the corrections printed above it.

This went live. Against an equal-weighted benchmark the report printed:

    clustered t (by entry date) = 1.60  vs plain t = 1.74
    deflated Sharpe = 0.670 ...
    Below ~0.95, the winning threshold is not distinguishable from the best
    of that many coin flips.
    ALPHA VERDICT: ALPHA CHECK: EDGE CONFIRMED OOS

Both corrections said no. The verdict said yes, computed off a plain t of 2.05
that the surrounding prose had just finished explaining was too generous.

That is this project's signature failure in its purest form: the careful
numbers were all present and correct, and the one line a reader actually acts
on ignored them. Nothing was missing; the summary just disagreed with its own
evidence.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kala.walkforward import (  # noqa: E402
    DSR_CONFIDENT,
    T_CONFIDENT,
    Fold,
    FoldResult,
    WalkForwardReport,
    _edge_verdict,
    trade_stats,
)

STRONG = {"n": 5241, "ev_pct": 5.52, "t_stat": 6.36}
WEAK = {"n": 5241, "ev_pct": 1.73, "t_stat": 2.05}      # the real EQUAL_WEIGHT run


def test_a_clustered_t_below_two_overrides_a_plain_t_above_it():
    """The exact case that shipped: plain t 2.05, clustered t 1.60."""
    v = _edge_verdict(WEAK, clustered_t=1.60, dsr=1.0, n_trials=6)
    assert "EDGE CONFIRMED" not in v
    assert "WEAK" in v
    assert "1.60" in v, "the verdict must quote the number it judged on"


def test_a_deflated_sharpe_below_the_bar_blocks_confirmation():
    """Surviving the t is not enough when the threshold was the best of N."""
    v = _edge_verdict(STRONG, clustered_t=5.04, dsr=0.42, n_trials=6)
    assert "EDGE CONFIRMED" not in v
    assert "DEFLATED SHARPE" in v
    assert "0.420" in v and "6" in v


def test_a_genuinely_strong_result_still_confirms():
    """Non-vacuity. Without this, always returning WEAK would pass the above."""
    v = _edge_verdict(STRONG, clustered_t=5.04, dsr=1.000, n_trials=6)
    assert "EDGE CONFIRMED OOS" in v


def test_the_bars_are_the_ones_the_report_prints():
    """The thresholds must match the prose, or the report argues with itself."""
    assert T_CONFIDENT == 2.0
    assert DSR_CONFIDENT == 0.95
    # Just under each bar fails; just over passes.
    assert "WEAK" in _edge_verdict(WEAK, clustered_t=1.999, dsr=1.0, n_trials=6)
    assert "EDGE CONFIRMED" in _edge_verdict(WEAK, clustered_t=2.0, dsr=1.0, n_trials=6)
    assert "DEFLATED" in _edge_verdict(WEAK, clustered_t=3.0, dsr=0.949, n_trials=6)
    assert "EDGE CONFIRMED" in _edge_verdict(WEAK, clustered_t=3.0, dsr=0.95, n_trials=6)


def test_a_negative_ev_is_still_no_edge_regardless_of_the_corrections():
    v = _edge_verdict({"n": 500, "ev_pct": -1.0, "t_stat": -3.0},
                      clustered_t=-3.0, dsr=1.0, n_trials=6)
    assert "NO OOS EDGE" in v


def test_too_few_trades_still_wins_over_everything():
    v = _edge_verdict({"n": 5, "ev_pct": 9.0, "t_stat": 9.0},
                      clustered_t=9.0, dsr=1.0, n_trials=6)
    assert "INCONCLUSIVE" in v


def test_without_a_clustered_t_it_falls_back_to_the_plain_one():
    """The raw-return verdict has no clustered t; it must not silently pass."""
    assert "EDGE CONFIRMED" in _edge_verdict(STRONG)
    assert "WEAK" in _edge_verdict({"n": 500, "ev_pct": 1.0, "t_stat": 1.2})


def test_dsr_is_ignored_when_no_thresholds_were_tried():
    """Deflation corrects for selection. With n_trials 0 there was none."""
    assert "EDGE CONFIRMED" in _edge_verdict(STRONG, clustered_t=5.0, dsr=0.1,
                                             n_trials=0)


# ---- and the same, through the rendered report ---------------------------

def _report(exc_baseline_returns, clustered_b, dsr_b, n_trials=6):
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
        oos_excess_chosen=trade_stats([1.0, 2.0]),
        oos_excess_baseline=trade_stats([1.0, 2.0]),
    )
    rep = WalkForwardReport(folds=[fr], baseline_threshold=80.0)
    rep.pooled_chosen = trade_stats([1.0, -2.0, 3.0] * 20)
    rep.pooled_baseline = trade_stats([1.0, -2.0] * 30)
    rep.pooled_excess_chosen = trade_stats(exc_baseline_returns)
    rep.pooled_excess_baseline = trade_stats(exc_baseline_returns)
    rep.pooled_excess_clustered_t = 3.0
    rep.pooled_excess_dsr = 1.0
    rep.dsr_n_trials = n_trials
    rep.pooled_excess_baseline_clustered_t = clustered_b
    rep.pooled_excess_baseline_dsr = dsr_b
    return rep


def test_the_rendered_alpha_verdict_obeys_the_baseline_arms_clustered_t():
    # A series with a healthy plain t but a weak clustered t.
    returns = [1.5] * 40 + [-1.0] * 20
    rep = _report(returns, clustered_b=1.55, dsr_b=1.0)
    text = rep.summary_text()

    alpha = [ln for ln in text.splitlines() if ln.startswith("ALPHA VERDICT")]
    assert alpha, "no ALPHA VERDICT line rendered"
    assert "EDGE CONFIRMED" not in alpha[0], (
        f"the verdict ignored a clustered t of 1.55: {alpha[0]!r}")
    # And the number it judged on must be visible on the page.
    assert "the ALPHA VERDICT is judged on THIS" in text


def test_the_rendered_alpha_verdict_reports_the_baseline_arms_dsr():
    returns = [1.5] * 40 + [-1.0] * 20
    rep = _report(returns, clustered_b=4.0, dsr_b=0.31)
    text = rep.summary_text()
    alpha = [ln for ln in text.splitlines() if ln.startswith("ALPHA VERDICT")]
    assert "DEFLATED SHARPE" in alpha[0]
    assert "0.310" in text


def test_the_raw_verdict_is_not_affected_by_the_alpha_corrections():
    """The raw arm has no benchmark and no clustered t; leave it alone."""
    returns = [1.5] * 40 + [-1.0] * 20
    rep = _report(returns, clustered_b=1.0, dsr_b=0.1)
    raw = [ln for ln in rep.summary_text().splitlines()
           if ln.startswith("VERDICT (raw")]
    assert raw, "no raw verdict line"
    # pooled_baseline is [1.0, -2.0]*30 -> negative EV -> NO OOS EDGE
    assert "NO OOS EDGE" in raw[0]


@pytest.mark.parametrize("clustered,dsr,expect_confirmed", [
    (5.0, 1.00, True),
    (1.9, 1.00, False),
    (5.0, 0.90, False),
    (1.9, 0.90, False),
])
def test_both_gates_must_pass_for_a_confirmation(clustered, dsr, expect_confirmed):
    v = _edge_verdict(STRONG, clustered_t=clustered, dsr=dsr, n_trials=6)
    assert ("EDGE CONFIRMED OOS" in v) is expect_confirmed
