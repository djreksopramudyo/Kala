"""A position that cannot be AGED must not read as a position that is young.

``_bars_held`` returned a bare None for every failure and both callers wrote
``if bars_held is not None and bars_held >= max_days``. So a None produced the
identical output to a fresh position: no exit queued, no report line, nothing
anywhere on screen.

Under the ``forward_test`` profile that is not a missed nudge. Every price
exit is inert there by design and ``holding_max_days`` is the ONLY rule that
closes a position, so such a position has no exit rule at all — while
``/review`` goes on printing HOLD. The audit opened with "it kept on telling me
to hold"; this is a mechanism that does exactly that.

Every test here calls the live code and reads what the user would see.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kala.config import Config, RiskConfig  # noqa: E402
from kala.papertrade import (  # noqa: E402
    PaperPosition,
    PaperTrader,
    bars_held_or_reason,
)

BARS = 200


def hist(n: int = BARS) -> pd.DataFrame:
    c = np.full(n, 1000.0)
    return pd.DataFrame(
        {"Open": c, "High": c * 1.005, "Low": c * 0.995, "Close": c,
         "Volume": np.full(n, 1e6)},
        index=pd.bdate_range("2026-01-05", periods=n))


def flat_cfg(max_days: int = 15) -> Config:
    """Every price-based exit inert — the forward_test shape, where the max
    holding period is the only rule that can close anything."""
    cfg = Config(risk=RiskConfig(trailing_enabled=False, hard_stop_pct=-99.0,
                                 atr_stop_multiple=99.0,
                                 target_profit_pct=999.0,
                                 breakeven_trigger_pct=999.0))
    cfg.backtest.holding_max_days = max_days
    return cfg


def trader(tmp_path, max_days: int = 15) -> PaperTrader:
    return PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000,
                            cfg=flat_cfg(max_days))


def hold(pt, ticker: str, entry_date: str) -> None:
    pt.positions[ticker] = PaperPosition(
        ticker=ticker, entry_price=1000.0, shares=100,
        entry_date=entry_date, peak_price=1000.0)


def run(pt, h) -> dict:
    return pt.step({t: h for t in pt.positions}, [],
                   today=h.index[-1].date().isoformat())


# ---------------------------------------------------------------------------
# an off-bar entry date is a real position, not a dead end
# ---------------------------------------------------------------------------

def test_a_weekend_entry_date_still_ages():
    """The old match was exact date equality, so a Saturday never matched.

    ``manual_buy`` takes any date string with no trading-day validation, and
    ``daily_run`` has no trading-day guard, so a scheduler firing on an IDX
    holiday stamps fills with a date that is not a bar. Neither is exotic.
    """
    h = hist()
    saturday = (h.index[10] + pd.Timedelta(days=5)).date().isoformat()
    assert pd.Timestamp(saturday).weekday() == 5, "fixture is not a Saturday"
    bars, why = bars_held_or_reason(saturday, h)
    assert why is None
    # The position started at the next open, which is index[15].
    assert bars == BARS - 1 - 15


def test_an_on_bar_entry_date_is_unchanged():
    """Non-vacuity: the snap must not shift dates that were already exact."""
    h = hist()
    for i in (0, 10, 137, BARS - 1):
        bars, why = bars_held_or_reason(h.index[i].date().isoformat(), h)
        assert why is None
        assert bars == BARS - 1 - i


def test_an_idx_holiday_entry_ages_to_the_next_session():
    """2026-08-17 is Independence Day. This project has no exchange calendar."""
    idx = pd.bdate_range("2026-08-10", periods=15)
    idx = idx[idx.date != pd.Timestamp("2026-08-17").date()]     # closed
    c = np.full(len(idx), 1000.0)
    h = pd.DataFrame({"Open": c, "High": c, "Low": c, "Close": c,
                      "Volume": np.full(len(idx), 1e6)}, index=idx)
    bars, why = bars_held_or_reason("2026-08-17", h)
    assert why is None
    assert bars == len(idx) - 1 - list(idx.date).index(
        pd.Timestamp("2026-08-18").date())


def test_the_holiday_position_is_actually_sold(tmp_path):
    """The point of ageing it: the exit rule fires."""
    h = hist()
    pt = trader(tmp_path)
    hold(pt, "GHOST.JK", (h.index[10] + pd.Timedelta(days=5)).date().isoformat())
    r = run(pt, h)
    assert [o.ticker for o in pt.pending] == ["GHOST.JK"]
    assert any("max holding" in s for s in r["exits_queued"])


# ---------------------------------------------------------------------------
# what is still refused must be SAID, never merely skipped
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("entry,fragment", [
    ("2019-01-01", "predates this history window"),
    ("2099-01-01", "after the last bar"),
    ("not-a-date", "is not a date"),
    ("", "is not a date"),
])
def test_an_unageable_position_is_reported_not_skipped(tmp_path, entry, fragment):
    h = hist()
    pt = trader(tmp_path)
    hold(pt, "X.JK", entry)
    r = run(pt, h)
    assert not pt.pending, "it must not be sold on a guess either"
    joined = " | ".join(r["unevaluated"])
    assert "max-holding rule NOT checked" in joined, (
        "the position vanished from every report — the original defect")
    assert fragment in joined, "the reason must say WHICH failure this was"


def test_an_ageable_position_produces_no_unevaluated_note(tmp_path):
    """Non-vacuity: the warning must not attach itself to healthy positions."""
    h = hist()
    pt = trader(tmp_path)
    hold(pt, "GOOD.JK", h.index[10].date().isoformat())
    r = run(pt, h)
    assert r["unevaluated"] == []


def test_a_pre_window_entry_is_not_snapped_forward():
    """Snapping it would measure from the window's start, not the entry.

    That trades a silent non-exit for a silent EARLY exit, which is worse: the
    position gets sold on an age nobody computed from the real entry.
    """
    h = hist()
    bars, why = bars_held_or_reason("2019-01-01", h)
    assert bars is None
    assert "predates" in why


def test_a_young_position_is_still_not_sold(tmp_path):
    """The original contract, unchanged."""
    h = hist()
    pt = trader(tmp_path, max_days=15)
    hold(pt, "YUNG.JK", h.index[-5].date().isoformat())
    r = run(pt, h)
    assert not pt.pending
    assert r["unevaluated"] == []


@pytest.mark.parametrize("bars,sold", [(14, False), (15, True), (16, True)])
def test_the_limit_is_inclusive_at_exactly_max_days(tmp_path, bars, sold):
    """`held >= max_days`, matching backtest.py — not `>`.

    Found by mutation: swapping the comparison to `>` survived the whole
    suite, because nothing held a position for EXACTLY the limit. An
    off-by-one there is not a rounding detail — under forward_test this is
    the only exit rule, so every position would run one bar longer than the
    rule that was validated, on every trade, forever.
    """
    h = hist()
    pt = trader(tmp_path, max_days=15)
    hold(pt, "EDGE.JK", h.index[-1 - bars].date().isoformat())
    r = run(pt, h)
    assert bool(pt.pending) is sold, f"{bars} bars held, max 15"
    if sold:
        assert f"({bars} bars >= 15)" in r["exits_queued"][0]


# ---------------------------------------------------------------------------
# the silent-skip, reproduced end to end
# ---------------------------------------------------------------------------

def test_two_identical_positions_are_treated_identically(tmp_path):
    """The reproduction that made this a finding.

    Two positions, same ticker shape, same history, both far past the limit,
    differing only in whether the entry date happens to land on a bar. Before
    the fix one was queued for sale and the other appeared in NO list at all —
    not exits_queued, not unevaluated, not skipped, not tickets.
    """
    h = hist()
    pt = trader(tmp_path)
    hold(pt, "GOOD.JK", h.index[10].date().isoformat())
    hold(pt, "GHOST.JK", (h.index[10] + pd.Timedelta(days=5)).date().isoformat())
    r = run(pt, h)
    assert sorted(o.ticker for o in pt.pending) == ["GHOST.JK", "GOOD.JK"]
    assert len(r["exits_queued"]) == 2


def test_an_unageable_position_appears_somewhere_in_the_report(tmp_path):
    """Whatever else happens, it must not be invisible."""
    h = hist()
    pt = trader(tmp_path)
    hold(pt, "X.JK", "2019-01-01")
    r = run(pt, h)
    everywhere = " | ".join(
        r["unevaluated"] + r["exits_queued"] + r["skipped"] + r["tickets"])
    assert "X.JK" in everywhere


# ---------------------------------------------------------------------------
# /review must not print a bare HOLD for a position with no working exit
# ---------------------------------------------------------------------------

def _review(tmp_path, monkeypatch, entry_date: str) -> dict:
    """One record out of the real /review path, for a position entered then."""
    import json

    import kala_daily_trader as dt
    tb = pytest.importorskip("telegram_bot")

    n = 90
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
    c = np.full(n, 1000.0)
    h = pd.DataFrame({"Open": c, "High": c * 1.005, "Low": c * 0.995,
                      "Close": c, "Volume": np.full(n, 1e6)}, index=idx)

    statefile = tmp_path / "paper_state.json"
    statefile.write_text(json.dumps({
        "cash": 1_000_000, "start_capital": 10_000_000,
        "positions": {"X.JK": {"ticker": "X.JK", "entry_price": 1000.0,
                               "shares": 100, "entry_date": entry_date,
                               "peak_price": 1000.0, "entry_atr": None}},
        "pending": [], "log": [], "benchmark_start": None,
        "capital_additions": [],
    }), encoding="utf-8")
    pt = PaperTrader.load(statefile, start_capital=10_000_000, cfg=flat_cfg(20))

    monkeypatch.setattr(dt, "check_market_health", lambda: {"status": "NEUTRAL"})
    monkeypatch.setattr(dt, "download_stock_data", lambda *a, **k: h)
    monkeypatch.setattr(dt, "get_live_signal", lambda *a, **k: None)
    result = tb._evaluate_holdings(
        pt, {"daily_capital_idr": 10_000_000, "max_positions": 5})
    return result["records"][0]


def test_review_says_the_rule_did_not_run(tmp_path, monkeypatch):
    """telegram_bot carried a second copy of the same `is not None` guard.

    A position it could not age showed as a bare HOLD in /review and /priority
    forever — the complaint this audit opened with, rendered literally.
    """
    rec = _review(tmp_path, monkeypatch, "2019-01-01")
    assert rec["bars_held"] is None
    assert rec["reason"], "a bare HOLD with no reason is the original defect"
    assert "NOT checked" in rec["reason"]
    assert "predates" in rec["reason"]


def test_review_still_shows_nothing_for_a_healthy_young_position(tmp_path, monkeypatch):
    """Non-vacuity: the note must not appear on every holding."""
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=90)
    rec = _review(tmp_path, monkeypatch, idx[-5].strftime("%Y-%m-%d"))
    assert rec["urgency"] == "NONE"
    assert not rec["reason"]


def test_review_ages_an_off_bar_entry_instead_of_holding_forever(tmp_path, monkeypatch):
    """The weekend entry now reaches CONSIDER like any other old position."""
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=90)
    saturday = (idx[90 - 40] + pd.Timedelta(days=5)).strftime("%Y-%m-%d")
    rec = _review(tmp_path, monkeypatch, saturday)
    assert rec["urgency"] == "CONSIDER"
    assert "max holding period" in rec["reason"]
