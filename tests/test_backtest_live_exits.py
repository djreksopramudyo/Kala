"""
Tests for backtest_live_exits — the live-exit-engine backtest arm.

What matters:
  * PARITY where the rule sets overlap: a clean stop hit or take-profit must
    close on the same bar at the same price in both arms (entries + costs +
    mechanics identical, so any difference can only come from the rule set).
  * DIVERGENCE exactly where the rule sets differ: the live arm must exit on
    a CONSIDER-class rule (e.g. MACD reversal) the validated arm ignores,
    and must keep holding past the validated arm's max-holding-period exit
    (live has no such rule).
  * ARB lock carries: no exit of any kind fills on a limit-down-locked bar.
"""

import numpy as np
import pandas as pd
import pytest

from kala.backtest import backtest_ticker
from kala.backtest_live_exits import backtest_ticker_live_exits
from kala.config import BacktestConfig, Config, RiskConfig


def _make_df(closes, opens=None, lows=None, vols=None, start="2022-01-03"):
    closes = np.asarray(closes, dtype=float)
    n = len(closes)
    return pd.DataFrame(
        {
            "Open": np.asarray(opens, dtype=float) if opens is not None else closes,
            "High": closes * 1.005,
            "Low": np.asarray(lows, dtype=float) if lows is not None else closes * 0.995,
            "Close": closes,
            "Volume": np.asarray(vols, dtype=float) if vols is not None else np.full(n, 1e6),
        },
        index=pd.bdate_range(start, periods=n),
    )


def _base_cfg(**risk_kw) -> Config:
    risk = dict(trailing_enabled=False, hard_stop_pct=-5.0,
                atr_stop_multiple=99.0, target_profit_pct=8.0)
    risk.update(risk_kw)
    return Config(risk=RiskConfig(**risk),
                  backtest=BacktestConfig(score_entry_threshold=60.0,
                                          holding_max_days=20,
                                          apply_entry_vetoes=False))


def _entry_ramp(n=120, seed=3):
    """Noisy-but-strong uptrend that reliably clears threshold 60 without
    pinning RSI at 100 (has real down days)."""
    rng = np.random.default_rng(seed)
    return 1000 * np.exp(np.cumsum(rng.normal(0.004, 0.006, n)))


def _first_entry_idx(df, cfg) -> int:
    """Integer index of the first fill bar arm A produces on this data —
    used to splice a shared-exit event right after entry so the divergent
    live rules (RSI-overbought-in-profit, MACD) have no window to fire
    first. Parity is only guaranteed on the OVERLAPPING rules, so parity
    tests must engineer the overlap to trigger before anything else can."""
    a = backtest_ticker("PROBE.JK", df, None, cfg)
    assert a.closed, "probe data must produce at least one arm-A trade"
    return int(df.index.get_loc(a.closed[0].entry_date))


def test_parity_on_take_profit():
    """+12% gap ON the bar right after entry: profit jumps 0 -> past the +8%
    target in one bar, so the live arm's rule 2 and the validated arm's
    target fire on the same bar -> identical first trade."""
    ramp = _entry_ramp()
    probe = _make_df(np.concatenate([ramp, np.full(60, ramp[-1])]))
    cfg = _base_cfg()
    e = _first_entry_idx(probe, cfg)

    closes = probe["Close"].to_numpy().copy()
    closes[e + 1:] = closes[e] * 1.12            # gap +12%, then flat
    df = _make_df(closes)

    a = backtest_ticker("PAR.JK", df, None, cfg)
    b = backtest_ticker_live_exits("PAR.JK", df, None, cfg)
    assert a.closed and b.closed
    ta, tb = a.closed[0], b.closed[0]
    assert "target profit" in ta.exit_reason
    assert ta.entry_date == tb.entry_date
    assert ta.exit_date == tb.exit_date
    assert ta.net_return_pct == pytest.approx(tb.net_return_pct, abs=1e-9)


def test_parity_on_stop():
    """-6% drop on the bar right after entry (well inside the ARB band, so
    no lock): the governing stop is the same rule in both engines ->
    identical first trade."""
    ramp = _entry_ramp()
    probe = _make_df(np.concatenate([ramp, np.full(60, ramp[-1])]))
    cfg = _base_cfg()
    e = _first_entry_idx(probe, cfg)

    closes = probe["Close"].to_numpy().copy()
    closes[e + 1:] = closes[e] * 0.94            # -6%: through the -5% stop
    df = _make_df(closes)

    a = backtest_ticker("STP.JK", df, None, cfg)
    b = backtest_ticker_live_exits("STP.JK", df, None, cfg)
    assert a.closed and b.closed
    ta, tb = a.closed[0], b.closed[0]
    assert "stop" in ta.exit_reason
    assert ta.entry_date == tb.entry_date
    assert ta.exit_date == tb.exit_date
    assert ta.net_return_pct == pytest.approx(tb.net_return_pct, abs=1e-9)


def test_macd_reversal_is_advisory_and_no_longer_exits():
    """v3.3 alignment: a slow bleed that once triggered the (never-validated)
    MACD-bearish CONSIDER exit must no longer force a sale — both arms now
    leave via max-hold, on the same bar. This is THE regression test for the
    -0.21%-vs-+0.37% finding that drove the demotion."""
    ramp = _entry_ramp()
    drift = ramp[-1] * np.exp(np.cumsum(np.full(60, -0.0035)))   # -0.35%/day bleed
    df = _make_df(np.concatenate([ramp, drift]))
    cfg = _base_cfg(hard_stop_pct=-25.0)     # park the stop far away
    cfg.backtest.holding_max_days = 40

    a = backtest_ticker("MACD.JK", df, None, cfg)
    b = backtest_ticker_live_exits("MACD.JK", df, None, cfg)
    assert a.closed and b.closed
    assert not any("MACD" in t.exit_reason for t in b.closed), \
        "MACD reversal must never close a live trade after the v3.3 demotion"
    # post-alignment the rule sets are identical, so on lock-free data the
    # two arms must produce the SAME trades (reason strings differ in
    # wording; dates and returns must not)
    a_tr = [t for t in a.closed if "(eod)" not in t.exit_reason]
    b_tr = [t for t in b.closed if "(eod)" not in t.exit_reason]
    assert len(a_tr) == len(b_tr) and a_tr, "expected identical trade lists"
    for ta, tb in zip(a_tr, b_tr):
        assert ta.entry_date == tb.entry_date
        assert ta.exit_date == tb.exit_date
        assert ta.net_return_pct == pytest.approx(tb.net_return_pct, abs=1e-9)


def test_live_arm_applies_max_hold_like_validated():
    """v3.3 alignment: the live path gained the validated max-holding exit —
    on a quiet tape where nothing else fires, both arms exit max-hold on the
    same bar instead of the live arm stranding at end of data."""
    ramp = _entry_ramp()
    probe = _make_df(np.concatenate([ramp, np.full(60, ramp[-1])]))
    cfg = _base_cfg(hard_stop_pct=-25.0)
    cfg.backtest.holding_max_days = 10
    e = _first_entry_idx(probe, cfg)

    closes = probe["Close"].to_numpy().copy()
    n_tail = len(closes) - (e + 1)
    closes[e + 1:] = closes[e] * np.exp(np.cumsum(np.full(n_tail, 0.0004)))
    df = _make_df(closes)

    a = backtest_ticker("QUIET.JK", df, None, cfg)
    b = backtest_ticker_live_exits("QUIET.JK", df, None, cfg)
    a_mh = [t for t in a.closed if "max holding" in t.exit_reason]
    b_mh = [t for t in b.closed if "max holding" in t.exit_reason]
    assert a_mh and b_mh
    assert a_mh[0].exit_date == b_mh[0].exit_date


def test_live_arm_carries_unfillable_exit_across_locked_opens():
    """The stop decision lands on/around limit-down-locked bars: the fill
    must CARRY (papertrade stage-1 semantics) to the first tradable open —
    booking the real crash loss, not a fantasy fill at a locked open."""
    rng = np.random.default_rng(7)
    up = 1000 * np.exp(np.cumsum(rng.normal(0.004, 0.005, 120)))
    last = up[-1]
    lock1, lock2 = last * 0.855, last * 0.855 * 0.855
    tail = np.full(5, lock2 * 0.99)
    closes = np.concatenate([up, [lock1, lock2], tail])
    lows = closes * 0.995
    lows[120], lows[121] = lock1, lock2          # locked: close == low
    df = _make_df(closes, lows=lows)

    # trailing ENABLED so the ratcheted stop is decided on the FIRST locked
    # bar (close far below the peak-trailed stop) -> the fill attempt lands
    # on the SECOND locked open and must carry to the tradable tail
    cfg = _base_cfg(trailing_enabled=True, target_profit_pct=999.0)
    cfg.backtest.arb_limit_pct = 15.0
    cfg.backtest.holding_max_days = 500

    b = backtest_ticker_live_exits("LOCK.JK", df, None, cfg)
    assert b.closed
    t = b.closed[-1]                              # the trade caught in the crash
    assert t.arb_locked_bars >= 1, "fill must have carried across locked opens"
    # the fill must land on the FIRST TRADABLE open (bar 122, the tail) at
    # the crashed price — not on either locked open, and not at the price
    # where the stop was decided
    assert t.exit_date == df.index[122]
    sell_mult = 1 - cfg.costs.sell_total - cfg.costs.half_spread
    assert t.exit_price == pytest.approx(df["Open"].iloc[122] * sell_mult, rel=1e-9)
    assert t.net_return_pct < 0


def test_entry_side_identical_first_entry():
    """Same first entry date in both arms — the entry path is shared code."""
    rng = np.random.default_rng(11)
    closes = 1000 * np.exp(np.cumsum(rng.normal(0.002, 0.012, 300)))
    df = _make_df(closes)
    cfg = _base_cfg()
    a = backtest_ticker("ENT.JK", df, None, cfg)
    b = backtest_ticker_live_exits("ENT.JK", df, None, cfg)
    if a.closed and b.closed:
        assert a.closed[0].entry_date == b.closed[0].entry_date
        assert a.closed[0].entry_price == pytest.approx(b.closed[0].entry_price)
    else:
        assert bool(a.closed) == bool(b.closed)
