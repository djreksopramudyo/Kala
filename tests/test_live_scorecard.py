"""Live scorecard tests. The behaviours that matter: the benchmark is measured
over each trade's OWN window (not a single global window), a missing benchmark
becomes an explicit gap rather than silently scoring as 0% (which would fake
alpha), costs actually bite, and the small-sample warning is always printed —
this number is far too tempting to over-read."""

import numpy as np
import pandas as pd

from kala.live_scorecard import Scorecard, format_scorecard, score_live


def _bench(start="2026-07-01", periods=40, daily=0.001, level=1000.0):
    idx = pd.bdate_range(start, periods=periods)
    return pd.Series(level * np.cumprod(np.full(periods, 1.0 + daily)), index=idx)


def _state(positions=None, log=None):
    return {"positions": positions or {}, "log": log or []}


def _pos(ticker, entry, shares, date):
    return {ticker: {"ticker": ticker, "entry_price": entry,
                     "shares": shares, "entry_date": date}}


# ---------------- guardrails --------------------------------------------------

def test_empty_state_is_reported():
    sc = score_live(_state(), {}, _bench())
    assert sc.note and "No priced trades" in sc.note
    assert "No priced trades" in format_scorecard(sc)


def test_returns_dataclass():
    assert isinstance(score_live(_state(), {}, None), Scorecard)


def test_unpriced_position_is_skipped_not_zero_scored():
    """A held ticker with no current price must be omitted entirely -- scoring
    it at 0 would silently drag the portfolio total toward zero."""
    sc = score_live(_state(_pos("A.JK", 100.0, 10, "2026-07-01")), {}, _bench())
    assert len(sc.trades) == 0


# ---------------- the per-window benchmark (the whole point) ------------------

def test_benchmark_is_measured_over_each_trades_own_window():
    """Two trades entered on different dates must get DIFFERENT benchmark
    numbers -- a single global benchmark return would misattribute alpha."""
    bench = _bench(start="2026-07-01", periods=40, daily=0.01)   # strongly rising
    positions = {}
    positions.update(_pos("EARLY.JK", 100.0, 10, "2026-07-01"))
    positions.update(_pos("LATE.JK", 100.0, 10, "2026-08-14"))
    sc = score_live(_state(positions), {"EARLY.JK": 110.0, "LATE.JK": 110.0}, bench)
    by = {t.ticker: t for t in sc.trades}
    # EARLY was exposed to far more of the benchmark's rise than LATE
    assert by["EARLY.JK"].benchmark_return_pct > by["LATE.JK"].benchmark_return_pct


def test_excess_is_return_minus_that_windows_benchmark():
    bench = _bench(daily=0.0)          # flat benchmark -> excess == return
    sc = score_live(_state(_pos("A.JK", 100.0, 10, "2026-07-01")),
                    {"A.JK": 110.0}, bench, cost_rate=0.0)
    t = sc.trades[0]
    assert t.benchmark_return_pct == 0.0
    assert abs(t.return_pct - 10.0) < 1e-9
    assert abs(t.excess_pct - 10.0) < 1e-9


def test_beating_a_rising_benchmark_requires_more_than_a_positive_return():
    """The core discipline: +5% while the benchmark did +10% is UNDERperformance,
    even though the raw return looks fine."""
    bench = _bench(start="2026-07-01", periods=30, daily=0.005)
    sc = score_live(_state(_pos("A.JK", 100.0, 10, "2026-07-01")),
                    {"A.JK": 105.0}, bench, cost_rate=0.0)
    t = sc.trades[0]
    assert t.return_pct > 0            # looks good in isolation
    assert t.excess_pct < 0            # but lost to the benchmark


def test_missing_benchmark_is_flagged_not_scored_as_zero():
    """No benchmark data must produce an explicit note, so a reader can't
    mistake 'benchmark unavailable' for 'benchmark went nowhere'."""
    sc = score_live(_state(_pos("A.JK", 100.0, 10, "2026-07-01")),
                    {"A.JK": 110.0}, None)
    assert sc.trades[0].note == "no benchmark data"


def test_entry_before_benchmark_history_is_flagged():
    bench = _bench(start="2026-07-01", periods=20)
    sc = score_live(_state(_pos("A.JK", 100.0, 10, "2020-01-01")),
                    {"A.JK": 110.0}, bench)
    # entry precedes history -> first available bar is used, no gap note needed,
    # but an entry AFTER all history must be flagged
    late = score_live(_state(_pos("B.JK", 100.0, 10, "2030-01-01")),
                      {"B.JK": 110.0}, bench)
    assert late.trades[0].note == "entry date after benchmark history"
    assert sc.trades[0].note == ""


# ---------------- closed trades -----------------------------------------------

def test_closed_trades_use_entry_and_exit_dates():
    bench = _bench(start="2026-07-01", periods=40, daily=0.01)
    log = [{"date": "2026-07-15", "entry_date": "2026-07-01", "ticker": "C.JK",
            "entry": 100.0, "exit": 120.0, "shares": 10, "reason": "manual sell"}]
    sc = score_live(_state(log=log), {}, bench, cost_rate=0.0)
    t = sc.trades[0]
    assert not t.is_open
    assert abs(t.return_pct - 20.0) < 1e-9
    assert t.benchmark_return_pct > 0      # priced over Jul 1 -> Jul 15 only


def test_open_only_excludes_the_closed_log():
    log = [{"date": "2026-07-15", "entry_date": "2026-07-01", "ticker": "C.JK",
            "entry": 100.0, "exit": 120.0, "shares": 10}]
    sc = score_live(_state(_pos("A.JK", 100.0, 10, "2026-07-01"), log),
                    {"A.JK": 110.0}, _bench(), include_closed=False)
    assert sc.n_closed == 0 and sc.n_open == 1


# ---------------- costs -------------------------------------------------------

def test_cost_rate_reduces_every_trades_return():
    bench = _bench(daily=0.0)
    free = score_live(_state(_pos("A.JK", 100.0, 10, "2026-07-01")),
                      {"A.JK": 110.0}, bench, cost_rate=0.0)
    costly = score_live(_state(_pos("A.JK", 100.0, 10, "2026-07-01")),
                        {"A.JK": 110.0}, bench, cost_rate=0.006)
    assert costly.trades[0].return_pct < free.trades[0].return_pct
    assert costly.total_pnl_idr < free.total_pnl_idr


# ---------------- aggregation + reporting -------------------------------------

def test_totals_are_cost_weighted_not_naive_averages():
    """A big position must move the total more than a small one."""
    bench = _bench(daily=0.0)
    positions = {}
    positions.update(_pos("BIG.JK", 100.0, 1000, "2026-07-01"))   # 100k basis
    positions.update(_pos("SMALL.JK", 100.0, 1, "2026-07-01"))    # 100 basis
    sc = score_live(_state(positions), {"BIG.JK": 90.0, "SMALL.JK": 200.0},
                    bench, cost_rate=0.0)
    # BIG lost 10%, SMALL doubled; naive mean would be strongly positive,
    # cost-weighted must be close to BIG's -10%.
    assert sc.total_return_pct < 0


def test_format_always_states_the_small_sample_warning():
    bench = _bench(daily=0.0)
    sc = score_live(_state(_pos("A.JK", 100.0, 10, "2026-07-01")),
                    {"A.JK": 110.0}, bench)
    text = format_scorecard(sc)
    assert "NOT evidence" in text
    assert "sequence luck" in text.lower()
    assert "READ:" in text


# ---------------- significance --------------------------------------------------

def _many(returns, entry=100.0, shares=10, date="2026-07-01"):
    """Build N positions whose returns are exactly the given list."""
    positions, prices = {}, {}
    for i, r in enumerate(returns):
        t = f"T{i}.JK"
        positions[t] = {"ticker": t, "entry_price": entry, "shares": shares,
                        "entry_date": date}
        prices[t] = entry * (1 + r / 100.0)
    return positions, prices


def test_noisy_zero_edge_is_not_significant():
    """Returns scattered symmetrically around zero must NOT be called an edge."""
    bench = _bench(daily=0.0)
    rets = [-6, -5, -4, -3, -2, -1, 1, 2, 3, 4, 5, 6]
    pos, px = _many(rets)
    sc = score_live(_state(pos), px, bench, cost_rate=0.0)
    assert not sc.is_significant
    assert sc.ci_low < 0 < sc.ci_high        # CI straddles zero
    assert abs(sc.t_stat) < 2.0


def test_large_consistent_edge_is_significant():
    """A big, consistent, repeated edge must clear the bar -- otherwise the
    test is vacuous and would call everything noise."""
    bench = _bench(daily=0.0)
    pos, px = _many([9, 10, 11, 9, 10, 11, 9, 10, 11, 10, 10, 10])
    sc = score_live(_state(pos), px, bench, cost_rate=0.0)
    assert sc.is_significant
    assert sc.ci_low > 0                     # CI entirely above zero
    assert sc.trades_needed < len(sc.trades)


def test_small_n_uses_small_sample_critical_value():
    """At n=21 the bar is t>2.09, not 1.96 -- using the normal value would
    overstate confidence, the exact error this module exists to prevent."""
    from kala.live_scorecard import _t_crit
    assert _t_crit(21) > 1.96
    assert _t_crit(5) > _t_crit(30) > _t_crit(1000)
    assert _t_crit(1000) == 1.96


def test_trades_needed_grows_as_the_edge_shrinks():
    bench = _bench(daily=0.0)
    big, bpx = _many([5, 6, 4, 5, 6, 4, 5, 6, 4, 5])
    small, spx = _many([0.4, 0.6, 0.2, 0.5, 0.7, 0.1, 0.5, 0.6, 0.3, 0.5])
    n_big = score_live(_state(big), bpx, bench, cost_rate=0.0).trades_needed
    n_small = score_live(_state(small), spx, bench, cost_rate=0.0).trades_needed
    assert n_small > n_big


def test_sign_disagreement_between_weighted_and_equal_is_surfaced():
    """One huge winner + many small losers -> cost-weighted positive but the
    typical trade negative. The reader must be told the headline comes from
    sizing, not picking."""
    bench = _bench(daily=0.0)
    positions, prices = {}, {}
    positions["BIG.JK"] = {"ticker": "BIG.JK", "entry_price": 100.0,
                           "shares": 10000, "entry_date": "2026-07-01"}
    prices["BIG.JK"] = 120.0                      # +20% on a huge position
    for i in range(25):                           # enough small losers that the
                                                  # equal-weighted mean goes negative
        t = f"S{i}.JK"
        positions[t] = {"ticker": t, "entry_price": 100.0, "shares": 10,
                        "entry_date": "2026-07-01"}
        prices[t] = 99.0                          # -1% on tiny positions
    sc = score_live(_state(positions), prices, bench, cost_rate=0.0)
    assert sc.excess_pct > 0                      # headline positive
    assert sc.mean_excess_per_trade < 0           # typical trade negative
    text = format_scorecard(sc).lower()
    assert "happened to be large" in text and "not by picking" in text


def test_format_reports_significance_block():
    bench = _bench(daily=0.0)
    pos, px = _many([-3, -1, 1, 3, -2, 2])
    text = format_scorecard(score_live(_state(pos), px, bench, cost_rate=0.0))
    assert "SIGNIFICANCE" in text
    assert "NOT significant" in text
    assert "t-stat" in text
    assert "trades needed" in text


def test_format_reports_friction_share_of_gross_edge():
    bench = _bench(daily=0.0)
    pos, px = _many([2.0] * 6)
    text = format_scorecard(score_live(_state(pos), px, bench, cost_rate=0.0064))
    assert "Friction took" in text


def test_single_trade_does_not_crash_significance():
    bench = _bench(daily=0.0)
    sc = score_live(_state(_pos("A.JK", 100.0, 10, "2026-07-01")),
                    {"A.JK": 110.0}, bench, cost_rate=0.0)
    assert not sc.is_significant
    format_scorecard(sc)


def test_format_shows_benchmark_and_excess_columns():
    bench = _bench(daily=0.0)
    sc = score_live(_state(_pos("A.JK", 100.0, 10, "2026-07-01")),
                    {"A.JK": 110.0}, bench, benchmark_name="XIJI.JK")
    text = format_scorecard(sc)
    assert "XIJI.JK" in text
    assert "excess" in text.lower()
