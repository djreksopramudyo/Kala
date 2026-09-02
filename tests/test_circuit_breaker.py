"""
Circuit-breaker tests.

Three properties matter more than the rest, because getting any of them wrong
turns a safety device into a hazard:
  * it must NEVER be able to sell (it only gates new buys);
  * it must be OFF unless explicitly enabled (it changes real-money behavior);
  * the peak must ratchet UP only (a peak that follows equity down can never
    trip, which is precisely the market where it is needed).
"""

import json

import pytest

from kala.circuit_breaker import (
    BreakerConfig,
    BreakerState,
    evaluate_breaker,
    format_breaker,
    load_breaker_state,
    save_breaker_state,
)

ON = BreakerConfig(enabled=True, halt_drawdown_pct=15.0, resume_drawdown_pct=10.0)


# ---------------- the three critical properties ----------------------------------

def test_module_exposes_no_way_to_sell():
    """A breaker that can liquidate would realize losses at the worst moment.
    The API surface must contain no sell/liquidate/close capability at all."""
    import kala.circuit_breaker as cb
    names = [n.lower() for n in dir(cb) if not n.startswith("_")]
    for forbidden in ("sell", "liquidate", "close_position", "exit_all", "flatten"):
        assert not any(forbidden in n for n in names)


def test_disabled_by_default_never_halts():
    """Default config must not change behavior, no matter how bad the drawdown."""
    s = evaluate_breaker(equity=10_000.0, stored_peak=100_000.0)   # -90%
    assert s.halted is False
    assert "disabled" in s.reason.lower()


def test_peak_ratchets_up_only():
    """A peak that drifts down with equity could never trigger a halt."""
    s = evaluate_breaker(equity=80_000.0, stored_peak=100_000.0, cfg=ON)
    assert s.peak == 100_000.0          # not lowered to 80k
    up = evaluate_breaker(equity=120_000.0, stored_peak=100_000.0, cfg=ON)
    assert up.peak == 120_000.0         # but does rise


# ---------------- halt / resume logic --------------------------------------------

def test_halts_at_the_threshold():
    s = evaluate_breaker(equity=85_000.0, stored_peak=100_000.0, cfg=ON)   # -15%
    assert s.halted is True
    assert s.drawdown_pct == pytest.approx(15.0)
    assert "HALTED" in s.reason


def test_does_not_halt_just_below_the_threshold():
    s = evaluate_breaker(equity=85_500.0, stored_peak=100_000.0, cfg=ON)   # -14.5%
    assert s.halted is False


def test_hysteresis_keeps_it_halted_between_the_two_levels():
    """At -12% (below the 15% halt line but above the 10% resume line) an
    already-halted breaker must STAY halted, or it chatters on and off."""
    s = evaluate_breaker(equity=88_000.0, stored_peak=100_000.0,
                         was_halted=True, cfg=ON)
    assert s.halted is True
    assert "Still halted" in s.reason


def test_resumes_once_recovered_past_the_resume_level():
    s = evaluate_breaker(equity=91_000.0, stored_peak=100_000.0,
                         was_halted=True, cfg=ON)   # -9%
    assert s.halted is False
    assert "RESUMED" in s.reason
    assert s.changed is True


def test_a_new_high_clears_the_halt():
    s = evaluate_breaker(equity=110_000.0, stored_peak=100_000.0,
                         was_halted=True, cfg=ON)
    assert s.halted is False
    assert s.drawdown_pct == 0.0
    assert s.peak == 110_000.0


# ---------------- deposit / withdrawal neutrality --------------------------------

def test_a_deposit_does_not_undo_a_drawdown():
    """Adding money raises equity but is not a recovery. Measuring raw equity
    would let a deposit silently clear a halt."""
    down = evaluate_breaker(equity=80_000.0, net_contributions=0.0,
                            stored_peak=100_000.0, cfg=ON)
    assert down.halted is True
    after_deposit = evaluate_breaker(equity=100_000.0, net_contributions=20_000.0,
                                     stored_peak=100_000.0, was_halted=True, cfg=ON)
    assert after_deposit.drawdown_pct == pytest.approx(down.drawdown_pct)
    assert after_deposit.halted is True


def test_a_withdrawal_does_not_fake_a_drawdown():
    """Taking cash out lowers equity without any trading loss; a naive
    breaker would halt for no reason."""
    s = evaluate_breaker(equity=70_000.0, net_contributions=-30_000.0,
                         stored_peak=100_000.0, cfg=ON)
    assert s.drawdown_pct == 0.0
    assert s.halted is False


# ---------------- degenerate input -----------------------------------------------

def test_first_run_with_no_stored_peak_does_not_halt():
    s = evaluate_breaker(equity=50_000.0, stored_peak=None, cfg=ON)
    assert s.halted is False
    assert s.peak == 50_000.0


def test_non_positive_peak_fails_open_and_says_so():
    """Freezing the system on a transient data problem is worse than one
    extra buy — but the condition must be reported, not swallowed."""
    s = evaluate_breaker(equity=0.0, stored_peak=0.0, cfg=ON)
    assert s.halted is False
    assert "fails open" in s.reason


def test_returns_dataclass():
    assert isinstance(evaluate_breaker(equity=1.0), BreakerState)


# ---------------- persistence ----------------------------------------------------

def test_round_trip_through_disk(tmp_path):
    p = tmp_path / "breaker.json"
    s = evaluate_breaker(equity=85_000.0, stored_peak=100_000.0, cfg=ON)
    save_breaker_state(p, s)
    peak, halted = load_breaker_state(p)
    assert peak == 100_000.0
    assert halted is True


def test_missing_file_re_anchors_instead_of_crashing(tmp_path):
    peak, halted = load_breaker_state(tmp_path / "nope.json")
    assert peak is None and halted is False


def test_corrupt_file_re_anchors_instead_of_crashing(tmp_path):
    p = tmp_path / "breaker.json"
    p.write_text("{not json at all", encoding="utf-8")
    peak, halted = load_breaker_state(p)
    assert peak is None and halted is False
    # and a re-anchored evaluation must not halt
    assert evaluate_breaker(equity=50_000.0, stored_peak=peak,
                            was_halted=halted, cfg=ON).halted is False


def test_save_is_atomic_leaving_no_tmp_file(tmp_path):
    p = tmp_path / "breaker.json"
    save_breaker_state(p, evaluate_breaker(equity=100.0, cfg=ON))
    assert p.exists()
    assert not list(tmp_path.glob("*.tmp"))
    assert json.loads(p.read_text(encoding="utf-8"))["peak"] == 100.0


# ---------------- reporting ------------------------------------------------------

def test_format_states_that_nothing_is_force_sold_when_halted():
    s = evaluate_breaker(equity=80_000.0, stored_peak=100_000.0, cfg=ON)
    text = format_breaker(s, ON)
    assert "force-sold" in s.reason
    assert "drawdown" in text.lower()


def test_format_shows_off_when_disabled():
    assert "OFF" in format_breaker(evaluate_breaker(equity=1.0), BreakerConfig())


# ---------------- integration: what halting actually does to the trader ----------

def _hist(n=80, lo=1000.0, hi=1100.0):
    import numpy as np
    import pandas as pd
    close = np.linspace(lo, hi, n)
    idx = pd.bdate_range("2026-04-01", periods=n)
    return pd.DataFrame({"Open": close, "High": close * 1.01, "Low": close * 0.99,
                         "Close": close, "Volume": np.full(n, 5e9)}, index=idx)


def _trader(tmp_path, capital=30_000_000):
    from kala.papertrade import PaperTrader
    return PaperTrader.load(tmp_path / "s.json", start_capital=capital)


def test_zero_allocation_blocks_every_new_buy(tmp_path):
    """This is HOW the breaker halts: daily_run passes allocation=0 rather
    than touching papertrade. If size_position ever stopped returning 0 for a
    non-positive allocation, the breaker would silently do nothing."""
    h = _hist()
    signals = [{"ticker": "AAA.JK", "signal": "STRONG BUY", "price": 1100.0,
                "atr": 20.0, "technical_score": 90},
               {"ticker": "BBB.JK", "signal": "BUY", "price": 1100.0,
                "atr": 20.0, "technical_score": 80}]
    hist = {"AAA.JK": h, "BBB.JK": h}

    normal = _trader(tmp_path / "a")
    (tmp_path / "a").mkdir()
    rep_normal = normal.step(hist, signals, allocation=5_000_000.0,
                             today="2026-08-03", auto_buy=True)
    assert len(rep_normal["buys_queued"]) > 0      # control: it does buy normally

    (tmp_path / "b").mkdir()
    halted = _trader(tmp_path / "b")
    rep_halted = halted.step(hist, signals, allocation=0.0,
                             today="2026-08-03", auto_buy=True)
    assert rep_halted["buys_queued"] == []
    assert halted.pending == []


def test_halting_does_not_freeze_exits(tmp_path):
    """The whole safety argument rests on this: a halted breaker must not
    trap a losing position. Stops and exits keep running."""
    (tmp_path / "c").mkdir()
    pt = _trader(tmp_path / "c")
    pt.manual_buy("AAA.JK", 1000, 2000.0, date="2026-04-01")   # deep underwater
    rep = pt.step({"AAA.JK": _hist()}, [], allocation=0.0,
                  today="2026-08-03", auto_buy=True)
    assert len(rep["exits_queued"]) == 1
    assert any(o.side == "SELL" for o in pt.pending)
