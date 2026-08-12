"""The pooled t-statistic assumes trades are independent. They are not.

Every "no edge" verdict in PROJECT_STATUS.md rests on a t computed by
trade_stats: mean / (std/sqrt(n)). That divisor is only right if the n trades
are independent draws. Trades opened on the SAME DAY across different tickers
share whatever the market did that day; subtracting the benchmark removes the
index component, but sector and style moves survive it.

Measured by simulation on trades whose TRUE edge is exactly zero, |t| >= 2
fires at:

    0% shared variance ->  4.4%   (correct)
   10%                -> 13.1%
   20%                -> 20.8%
   40%                -> 31.5%

Which cuts both ways, and the direction matters:
  * a NULL found by a test biased toward finding edges is stronger, not weaker
  * a POSITIVE t needs discounting before it is believed

clustered_t_stat applies the standard cluster-robust correction.
"""

import numpy as np
import pytest

from kala.walkforward import clustered_t_stat, trade_stats


def test_reduces_to_the_plain_t_when_every_trade_is_its_own_cluster():
    """One trade per day means no clustering to correct for; the two must
    agree, or the correction is doing something other than it claims."""
    rng = np.random.default_rng(0)
    rets = list(rng.normal(0.5, 3.0, 200))
    keys = list(range(200))                    # all distinct

    plain = trade_stats(rets)["t_stat"]
    assert clustered_t_stat(rets, keys) == pytest.approx(plain, rel=0.02)


def test_clustering_shrinks_t_when_same_day_trades_move_together():
    """The whole point: correlated trades within a day carry less independent
    information than their count suggests."""
    rng = np.random.default_rng(1)
    n_days, per_day = 40, 10
    common = rng.normal(0.5, 3.0, n_days)      # the day's shared move
    rets, keys = [], []
    for d in range(n_days):
        for _ in range(per_day):
            rets.append(common[d] + rng.normal(0, 0.5))
            keys.append(d)

    plain = trade_stats(rets)["t_stat"]
    clustered = clustered_t_stat(rets, keys)
    assert abs(clustered) < abs(plain)
    assert abs(clustered) < abs(plain) * 0.6, "correction is too timid to matter"


def test_a_genuine_edge_survives_the_correction():
    """Guard against 'fixing' significance by destroying it. A large, real,
    uncorrelated effect must still read as significant."""
    rng = np.random.default_rng(2)
    rets, keys = [], []
    for d in range(300):
        rets.append(3.0 + rng.normal(0, 1.0))
        keys.append(d)
    assert clustered_t_stat(rets, keys) > 5.0


def test_false_positive_rate_is_controlled_when_the_plain_t_is_not():
    """The measurement that motivates the whole thing: with zero true edge
    and strongly clustered trades, the plain t cries significance far more
    often than 5%. The clustered t must do substantially better."""
    rng = np.random.default_rng(3)
    n_sims, n_days, per_day = 300, 40, 8
    plain_hits = clustered_hits = 0

    for _ in range(n_sims):
        common = rng.normal(0, 2.0, n_days)
        rets, keys = [], []
        for d in range(n_days):
            for _ in range(per_day):
                rets.append(common[d] + rng.normal(0, 2.0))
                keys.append(d)
        if abs(trade_stats(rets)["t_stat"]) >= 2.0:
            plain_hits += 1
        if abs(clustered_t_stat(rets, keys)) >= 2.0:
            clustered_hits += 1

    plain_rate = plain_hits / n_sims
    clustered_rate = clustered_hits / n_sims
    assert plain_rate > 0.15, f"fixture too weak to show the problem ({plain_rate:.0%})"
    assert clustered_rate < plain_rate / 2


# ------------------------------------------------------------ degenerate ---

@pytest.mark.parametrize("rets,keys", [
    ([], []),
    ([1.0], [0]),
    ([1.0, 2.0], [0]),          # mismatched lengths
    ([1.0, 1.0], [0, 0]),       # single cluster
])
def test_degenerate_inputs_return_zero_not_a_crash(rets, keys):
    assert clustered_t_stat(rets, keys) == 0.0


def test_report_field_defaults_to_zero_without_a_benchmark():
    from kala.walkforward import WalkForwardReport
    r = WalkForwardReport(folds=[], baseline_threshold=60.0)
    assert r.pooled_excess_clustered_t == 0.0


# ------------------------------------------------- deflated Sharpe wiring ---
# kala/overfitting.py had ZERO production callers while CASE_STUDY.md told a
# reader the multiple-testing check was in place. These lock in that the
# walk-forward now actually runs it.

def test_walkforward_report_carries_a_deflated_sharpe():
    from kala.walkforward import _dsr_fields

    rng = np.random.default_rng(11)
    rets = list(rng.normal(0.4, 3.0, 400))
    out = _dsr_fields(rets, n_trials=6)

    assert out["dsr_n_trials"] == 6
    assert 0.0 <= out["pooled_excess_dsr"] <= 1.0


def test_more_trials_deflate_harder():
    """The entire point of the correction: the same observed number is less
    convincing when it was the best of many attempts."""
    from kala.walkforward import _dsr_fields

    rng = np.random.default_rng(12)
    rets = list(rng.normal(0.4, 3.0, 400))

    few = _dsr_fields(rets, n_trials=1)["pooled_excess_dsr"]
    many = _dsr_fields(rets, n_trials=50)["pooled_excess_dsr"]
    assert many < few


def test_dsr_never_takes_down_the_study_it_diagnoses():
    from kala.walkforward import _dsr_fields

    assert _dsr_fields([], 6)["pooled_excess_dsr"] == 0.0
    assert _dsr_fields([1.0, 1.0, 1.0], 6)["pooled_excess_dsr"] == 0.0   # std 0
    assert _dsr_fields([1.0, 2.0, 3.0], 0)["dsr_n_trials"] == 0


def test_summary_text_prints_both_diagnostics():
    from kala.walkforward import WalkForwardReport

    stats = {"n": 10, "ev_pct": 0.5, "median_pct": 0.1, "win_rate_pct": 50.0,
             "profit_factor": 1.1, "std_pct": 3.0, "t_stat": 1.0,
             "total_compounded_pct": 5.0}
    r = WalkForwardReport(
        folds=[], baseline_threshold=60.0,
        pooled_chosen=dict(stats),
        pooled_baseline={"n": 10, "ev_pct": 0.5, "median_pct": 0.1,
                         "win_rate_pct": 50.0, "profit_factor": 1.1,
                         "std_pct": 3.0, "t_stat": 1.0,
                         "total_compounded_pct": 5.0},
        pooled_excess_chosen={"n": 10, "ev_pct": 0.2, "median_pct": 0.1,
                              "win_rate_pct": 50.0, "profit_factor": 1.0,
                              "std_pct": 3.0, "t_stat": 2.5,
                              "total_compounded_pct": 2.0},
        pooled_excess_baseline={"n": 10, "ev_pct": 0.2, "median_pct": 0.1,
                                "win_rate_pct": 50.0, "profit_factor": 1.0,
                                "std_pct": 3.0, "t_stat": 2.5,
                                "total_compounded_pct": 2.0},
        pooled_excess_clustered_t=1.4,
        pooled_excess_dsr=0.61,
        dsr_n_trials=6,
    )
    text = r.summary_text()
    assert "clustered t" in text
    assert "deflated Sharpe" in text
    assert "0.61" in text


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
