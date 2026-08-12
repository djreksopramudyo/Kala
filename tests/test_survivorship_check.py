"""Survivorship-check tests. The point of this module is to DETECT a
hindsight-selection artifact, so the tests construct both worlds explicitly:
one where the core is genuinely weak (random baskets beat it too -> finding
survives) and one where only a hand-picked winner beats it (random baskets
don't -> finding is an artifact). If the verdict can't tell those apart, it's
useless."""

import numpy as np
import pandas as pd

from kala.survivorship_check import (
    SurvivorshipResult,
    check_survivorship,
    format_survivorship,
)


def _price(rets, start="2016-01-01"):
    idx = pd.bdate_range(start, periods=len(rets) + 1)
    return pd.Series(1000 * np.cumprod(np.concatenate([[1.0], 1.0 + np.asarray(rets)])),
                     index=idx)


def _world(n=1500, core_drift=0.0, universe_drift=0.0, n_names=30, seed=0,
           winners=(), winner_drift=0.0015, vol=0.012, core_vol=0.002):
    """Build a core plus a universe of ``n_names``. Names listed in ``winners``
    get an extra drift — used to simulate 'only a few names did well, and they
    happen to be the ones a human picked in hindsight'.

    ``core_vol`` is deliberately LOW by default so the core's realized return
    lands close to its intended drift. An earlier version gave the core the
    same volatility as the stocks, and a single unlucky draw made a
    'deliberately strong core' come out at -3.2% CAGR — which silently
    inverted the scenario a test was trying to construct. Keeping the
    reference arm near-deterministic is what makes these scenario tests
    actually test the scenario."""
    rng = np.random.default_rng(seed)
    core = _price(rng.normal(core_drift, core_vol, n))
    uni = {}
    for i in range(n_names):
        name = f"N{i}.JK"
        d = winner_drift if name in winners else universe_drift
        uni[name] = _price(np.random.default_rng(seed + 1 + i).normal(d, vol, n))
    return core, uni


# ---------------- guardrails --------------------------------------------------

def test_universe_smaller_than_k_is_reported():
    core, uni = _world(n_names=5)
    r = check_survivorship(core, uni, k=8, n_random=10)
    assert r.note and "larger than k" in r.note


def test_too_little_history_is_reported():
    core, uni = _world(n=100, n_names=20)
    r = check_survivorship(core, uni, k=8, n_random=10)
    assert r.note and "at least a year" in r.note


def test_returns_dataclass():
    assert isinstance(check_survivorship(_price([0.0, 0.0]), {}, k=8), SurvivorshipResult)


# ---------------- world 1: the core is genuinely weak -------------------------

def test_weak_core_means_most_random_baskets_win_and_finding_survives():
    """If the core just underperforms the whole universe, random baskets beat
    it too — so the edge is NOT about picking well, and the finding stands."""
    core, uni = _world(core_drift=-0.0004, universe_drift=0.0004, n_names=30, seed=1)
    r = check_survivorship(core, uni, k=8, n_random=120, seed=3)
    assert r.pct_random_beating_core_cagr > 70.0
    text = format_survivorship(r)
    assert "FINDING SURVIVES" in text


# ---------------- world 2: only the hand-picked names did well ----------------

def test_handpicked_winners_with_weak_universe_is_flagged_as_suspect():
    """The artifact case: the universe as a whole does NOT beat the core, but
    the specific names a human 'picked' happen to be the few that soared. The
    verdict must call this out rather than endorsing the sleeve."""
    winners = tuple(f"N{i}.JK" for i in range(8))
    # core clearly strong (~+20%/yr), typical universe name clearly weak
    # (~-15%/yr), the 'picked' winners far better than either.
    core, uni = _world(core_drift=0.0008, universe_drift=-0.0006,
                       n_names=40, seed=2, winners=winners, winner_drift=0.0025)
    r = check_survivorship(core, uni, handpicked=list(winners), k=8,
                           n_random=150, seed=5)
    assert r.pct_random_beating_core_cagr < 40.0
    assert r.handpicked_percentile_cagr > 70.0
    text = format_survivorship(r)
    assert "FINDING IS SUSPECT" in text
    assert "hindsight" in text.lower() or "WHICH names" in text


def test_handpicked_percentile_is_reported_when_names_are_in_the_pool():
    winners = ("N0.JK", "N1.JK", "N2.JK", "N3.JK")
    core, uni = _world(n_names=25, seed=6, winners=winners, winner_drift=0.002)
    r = check_survivorship(core, uni, handpicked=list(winners), k=4,
                           n_random=80, seed=7)
    assert not np.isnan(r.handpicked_percentile_cagr)
    assert 0.0 <= r.handpicked_percentile_cagr <= 100.0


def test_handpicked_absent_from_pool_is_nan_not_a_crash():
    core, uni = _world(n_names=20, seed=8)
    r = check_survivorship(core, uni, handpicked=["NOT_IN_POOL.JK"], k=8,
                           n_random=30, seed=9)
    assert np.isnan(r.handpicked_percentile_cagr)
    assert "hand-picked" not in format_survivorship(r).split("READ:")[0]


# ---------------- the caveat must always be stated ----------------------------

def test_verdict_always_repeats_the_universe_level_bias_it_cannot_fix():
    """Whatever the outcome, the output must state that the random pool is
    itself survivor-filtered (today's ISSI list) — otherwise a 'SURVIVES'
    verdict reads as 'no bias', which would be false."""
    for seed, cd, ud in ((1, -0.0004, 0.0004), (2, 0.0005, -0.0002), (3, 0.0, 0.0)):
        core, uni = _world(core_drift=cd, universe_drift=ud, n_names=25, seed=seed)
        r = check_survivorship(core, uni, k=8, n_random=60, seed=seed)
        text = format_survivorship(r)
        assert "TODAY's sharia list" in text or "today's ISSI" in text.lower()
        assert "cannot fix" in text.lower()


def test_format_handles_failed_run():
    core, uni = _world(n_names=3)
    assert "could not run" in format_survivorship(check_survivorship(core, uni, k=8))
