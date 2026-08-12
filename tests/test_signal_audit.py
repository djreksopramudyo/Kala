"""
Signal-auditor tests. All synthetic, no network.

The auditor's whole job is to be UNfoolable in the ways a signal service
fools its audience, so the tests target exactly those seams:
  * costs are really subtracted (net < gross),
  * a bar covering both TP and SL resolves as the STOP (pessimism),
  * unfilled / open / expired signals are counted, never dropped,
  * EV — not win rate — drives the verdict (the fat-loser book fails),
  * benchmark-excess is computed so beta can't masquerade as skill.
"""

import numpy as np
import pandas as pd
import pytest

from kala.config import Config, CostModel
from kala.signal_audit import Signal, audit_signals, resolve_signal


def _bars(rows, start="2024-01-02"):
    """rows: list of (open, high, low, close). Volume filled in."""
    rows = np.asarray(rows, dtype=float)
    idx = pd.bdate_range(start, periods=len(rows))
    return pd.DataFrame(
        {"Open": rows[:, 0], "High": rows[:, 1], "Low": rows[:, 2],
         "Close": rows[:, 3], "Volume": np.full(len(rows), 1e6)}, index=idx)


def _flat_df(level, n, start="2024-01-02"):
    return _bars([(level, level, level, level)] * n, start=start)


# --------------------------- resolution mechanics ---------------------------

def test_take_profit_resolves_net_of_costs():
    # publish day 0; from day1 price sits at entry, then a bar spikes to TP
    df = _bars([(100, 100, 100, 100),      # day0 publish
                (100, 100, 100, 100),      # day1 entry reachable (low<=100)
                (100, 120, 100, 115)])     # day2 high hits TP=110
    sig = Signal("X.JK", df.index[0], entry=100.0, take_profit=110.0, stop_loss=90.0)
    r = resolve_signal(sig, df, Config())
    assert r.status == "TP_HIT"
    # gross would be +10%; net must be visibly less after buy+sell costs+spread
    gross = (110.0 / 100.0 - 1.0) * 100.0
    assert r.net_return_pct < gross
    assert r.net_return_pct == pytest.approx(
        (110.0 * Config().costs.sell_multiplier(110.0)) /
        (100.0 * Config().costs.buy_multiplier(100.0)) * 100.0 - 100.0, rel=1e-9)


def test_stop_loss_resolves_negative():
    df = _bars([(100, 100, 100, 100),
                (100, 100, 100, 100),
                (100, 100, 85, 88)])       # low pierces SL=90
    sig = Signal("X.JK", df.index[0], entry=100.0, take_profit=110.0, stop_loss=90.0)
    r = resolve_signal(sig, df, Config())
    assert r.status == "SL_HIT"
    assert r.net_return_pct < 0


def test_same_bar_tp_and_sl_resolves_as_stop():
    """The anti-flattery rule: a bar whose range covers BOTH levels can't be
    known intraday, so it must count as the STOP, never the take-profit."""
    df = _bars([(100, 100, 100, 100),
                (100, 100, 100, 100),
                (100, 130, 80, 100)])      # range covers TP=110 AND SL=90
    sig = Signal("X.JK", df.index[0], entry=100.0, take_profit=110.0, stop_loss=90.0)
    r = resolve_signal(sig, df, Config())
    assert r.status == "SL_HIT"


def test_no_fill_when_entry_never_trades_down_to_limit():
    # price gaps away above entry and never comes back within the fill window
    df = _bars([(100, 100, 100, 100)] + [(120, 125, 118, 122)] * 5)
    sig = Signal("X.JK", df.index[0], entry=100.0, take_profit=110.0, stop_loss=90.0)
    r = resolve_signal(sig, df, Config(), fill_window_bars=3)
    assert r.status == "NO_FILL"
    assert r.net_return_pct is None


def test_expired_when_neither_level_hit_in_max_hold():
    df = _flat_df(100.0, n=30)             # nothing ever moves
    sig = Signal("X.JK", df.index[0], entry=100.0, take_profit=110.0, stop_loss=90.0)
    r = resolve_signal(sig, df, Config(), max_hold_bars=10)
    assert r.status == "EXPIRED"
    assert r.net_return_pct is not None    # marked to market, still counted


def test_open_when_data_runs_out_before_max_hold():
    df = _flat_df(100.0, n=5)              # fewer bars than max_hold
    sig = Signal("X.JK", df.index[0], entry=100.0, take_profit=110.0, stop_loss=90.0)
    r = resolve_signal(sig, df, Config(), max_hold_bars=20)
    assert r.status == "OPEN"
    assert r.net_return_pct is not None    # marked to market


def test_signal_acted_on_next_bar_not_publish_bar():
    """No look-ahead: a TP touched on the publish bar itself must not count —
    you couldn't have acted on an EOD signal that same day."""
    df = _bars([(100, 200, 100, 100),      # day0 publish: huge range, but unusable
                (100, 100, 100, 100),
                (100, 111, 100, 111)])      # day2 legitimately hits TP
    sig = Signal("X.JK", df.index[0], entry=100.0, take_profit=110.0, stop_loss=90.0)
    r = resolve_signal(sig, df, Config())
    assert r.status == "TP_HIT"
    assert pd.Timestamp(r.exit_date) == df.index[2]


# --------------------------- benchmark / excess -----------------------------

def test_excess_return_measured_against_benchmark_window():
    df = _bars([(100, 100, 100, 100),
                (100, 100, 100, 100),
                (100, 120, 100, 115)])     # TP=110 hit day2
    # benchmark rose 4% between entry (day1) and exit (day2)
    bench = pd.DataFrame({"Close": [100, 100, 104]}, index=df.index)
    sig = Signal("X.JK", df.index[0], entry=100.0, take_profit=110.0, stop_loss=90.0)
    r = resolve_signal(sig, df, Config(), benchmark=bench)
    assert r.benchmark_return_pct == pytest.approx(4.0, rel=1e-9)
    assert r.excess_return_pct == pytest.approx(r.net_return_pct - 4.0, rel=1e-9)


# --------------------------- aggregate scorecard ----------------------------

def _tp_df(start):
    return _bars([(100, 100, 100, 100), (100, 100, 100, 100), (100, 120, 100, 115)],
                 start=start)


def _sl_df(start):
    return _bars([(100, 100, 100, 100), (100, 100, 100, 100), (100, 100, 80, 85)],
                 start=start)


def test_audit_counts_every_signal_including_unfilled():
    dfs = {"WIN.JK": _tp_df("2024-01-02"),
           "LOSE.JK": _sl_df("2024-01-02"),
           "GONE.JK": _bars([(100, 100, 100, 100)] + [(200, 205, 199, 202)] * 4)}
    sigs = [Signal("WIN.JK", dfs["WIN.JK"].index[0], 100, 110, 90),
            Signal("LOSE.JK", dfs["LOSE.JK"].index[0], 100, 110, 90),
            Signal("GONE.JK", dfs["GONE.JK"].index[0], 100, 110, 90),   # never fills
            Signal("MISSING.JK", "2024-01-02", 100, 110, 90)]           # no data
    rep = audit_signals(sigs, dfs)
    assert rep.n_signals == 4
    assert rep.status_counts.get("TP_HIT") == 1
    assert rep.status_counts.get("SL_HIT") == 1
    assert rep.status_counts.get("NO_FILL") == 1
    assert rep.status_counts.get("NO_DATA") == 1
    assert rep.filled["n"] == 2            # only the two that became positions


def test_ev_not_winrate_drives_the_verdict():
    """A fat-loser book: many small take-profits, a few catastrophic stops.
    Win rate looks great; EV is negative; the verdict must follow EV."""
    dfs, sigs = {}, []
    # 34 small winners: TP just above entry
    for i in range(34):
        t = f"W{i}.JK"
        dfs[t] = _bars([(100, 100, 100, 100), (100, 100, 100, 100),
                        (100, 102, 100, 101)])   # TP=101
        sigs.append(Signal(t, dfs[t].index[0], entry=100.0, take_profit=101.0, stop_loss=70.0))
    # 6 disasters: SL far below entry
    for i in range(6):
        t = f"L{i}.JK"
        dfs[t] = _bars([(100, 100, 100, 100), (100, 100, 100, 100),
                        (100, 100, 65, 68)])     # SL=70 pierced
        sigs.append(Signal(t, dfs[t].index[0], entry=100.0, take_profit=101.0, stop_loss=70.0))
    rep = audit_signals(sigs, dfs)
    assert rep.filled["win_rate_pct"] > 80          # looks like the ad
    assert rep.filled["ev_pct"] < 0                 # but loses money
    assert "NEGATIVE" in rep.summary_text()


def test_summary_text_leads_with_ev_and_counts():
    dfs = {"A.JK": _tp_df("2024-01-02"), "B.JK": _sl_df("2024-01-02")}
    sigs = [Signal("A.JK", dfs["A.JK"].index[0], 100, 110, 90),
            Signal("B.JK", dfs["B.JK"].index[0], 100, 110, 90)]
    txt = audit_signals(sigs, dfs).summary_text(service="Zeta AI IDX")
    assert "Zeta AI IDX" in txt
    assert "EV/trade (net)" in txt
    assert "signals logged: 2" in txt


def test_tick_floor_costs_bite_harder_on_cheap_signals():
    """A cheap-stock TP under tick-floored spread must net less than the same
    percentage move under the flat cost model — the spread floor is real."""
    df = _bars([(120, 120, 120, 120), (120, 120, 120, 120), (120, 140, 120, 135)])
    sig = Signal("CHEAP.JK", df.index[0], entry=120.0, take_profit=132.0, stop_loss=108.0)
    flat = resolve_signal(sig, df, Config(costs=CostModel(spread_mode="flat")))
    tick = resolve_signal(sig, df, Config(costs=CostModel(spread_mode="tick_floor")))
    assert tick.net_return_pct < flat.net_return_pct
