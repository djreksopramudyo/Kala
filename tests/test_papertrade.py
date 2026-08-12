"""Paper-trader + notifier tests: fills, sizing, lots, allocation, persistence."""

import numpy as np
import pandas as pd
import pytest

from kala.config import Config, RiskConfig
from kala.notify import format_daily_message
from kala.papertrade import LOT_SIZE, PaperTrader


def make_hist(closes, opens=None):
    closes = np.asarray(closes, dtype=float)
    n = len(closes)
    opens = np.asarray(opens, dtype=float) if opens is not None else closes
    return pd.DataFrame(
        {"Open": opens, "High": closes * 1.005, "Low": closes * 0.995,
         "Close": closes, "Volume": np.full(n, 1e6)},
        index=pd.bdate_range("2026-01-05", periods=n))


def flat_cfg():
    # generous stops/targets so exits don't fire during mechanics tests
    return Config(risk=RiskConfig(trailing_enabled=False, hard_stop_pct=-50.0,
                                  atr_stop_multiple=99.0, target_profit_pct=999.0))


def buy_fill(price, cfg=None):
    """What manual_buy BOOKS a raw broker price at, once commission and half
    the spread are added on -- the same conversion step() applies to
    automated fills. Manual trades charge costs since v3.9, so a test that
    hardcodes the raw price is asserting the old contract."""
    return price * (cfg or flat_cfg()).costs.buy_multiplier(price)


def sell_net(price, cfg=None):
    """Proceeds per share actually kept after commission, the final
    transaction tax and half the spread."""
    return price * (cfg or flat_cfg()).costs.sell_multiplier(price)


def buy_signal(ticker="AAAA.JK", price=1000.0, atr=15.0):
    return {"ticker": ticker, "signal": "BUY", "price": price, "atr": atr,
            "entry_vetoes": []}


def test_buy_queued_then_filled_at_next_open_with_costs(tmp_path):
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000, cfg=flat_cfg())
    h1 = make_hist(np.linspace(950, 1000, 70))
    r1 = pt.step({"AAAA.JK": h1}, [buy_signal()], allocation=10_000_000, today="2026-07-01")
    assert r1["buys_queued"] and not r1["fills"]          # queued, NOT filled same day
    assert any("BUY AAAA.JK" in t for t in r1["tickets"])

    # next day: open gaps to 1010 -> fill must use 1010 * (1+buy costs)
    h2 = make_hist(np.append(np.linspace(950, 1000, 70), 1012.0),
                   opens=np.append(np.linspace(950, 1000, 70), 1010.0))
    r2 = pt.step({"AAAA.JK": h2}, [], today="2026-07-02")
    assert len(r2["fills"]) == 1 and "BOUGHT" in r2["fills"][0]
    pos = pt.positions["AAAA.JK"]
    costs = pt.cfg.costs
    assert pos.entry_price == pytest.approx(1010.0 * (1 + costs.buy_commission + costs.half_spread))
    assert pos.shares % LOT_SIZE == 0 and pos.shares > 0
    assert pt.cash == pytest.approx(10_000_000 - pos.entry_price * pos.shares)


def test_sizing_respects_allocation_lots_and_risk(tmp_path):
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=100_000_000, cfg=flat_cfg())
    # allocation tiny: 1 lot at 1000 costs ~100k; give only 90k -> too small
    r = pt.step({"AAAA.JK": make_hist(np.linspace(950, 1000, 70))},
                [buy_signal(price=1000.0)], allocation=90_000, today="2026-07-01")
    assert not r["buys_queued"] and any("too small" in s for s in r["skipped"])

    # proper allocation: shares must be lot-rounded and per-slot capped
    pt2 = PaperTrader.load(tmp_path / "p2.json", start_capital=100_000_000, cfg=flat_cfg())
    pt2.step({"AAAA.JK": make_hist(np.linspace(950, 1000, 70))},
             [buy_signal(price=1000.0, atr=10.0)],
             allocation=10_000_000, today="2026-07-01",
             risk_pct=2.0, max_positions=5)
    o = pt2.pending[0]
    assert o.shares % LOT_SIZE == 0
    assert o.shares * 1000.0 <= 10_000_000 / 5 + 1e-6      # per-slot cap


def test_vetoed_and_duplicate_signals_skipped(tmp_path):
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000, cfg=flat_cfg())
    h = make_hist(np.linspace(950, 1000, 70))
    vetoed = {**buy_signal("BBBB.JK"), "entry_vetoes": ["overbought (RSI 80)"]}
    r = pt.step({"AAAA.JK": h, "BBBB.JK": h}, [buy_signal(), vetoed],
                allocation=10_000_000, today="2026-07-01")
    assert len(r["buys_queued"]) == 1 and "vetoed" in r["skipped"][0]
    # same signal again while pending -> no duplicate order
    r2 = pt.step({"AAAA.JK": h}, [buy_signal()], allocation=10_000_000, today="2026-07-01")
    assert not r2["buys_queued"]


def test_buys_ranked_by_score_not_alphabetical(tmp_path):
    """The scanner emits signals alphabetically. When slots are scarce, the
    paper trader must buy the HIGHEST-SCORED names (matching the dashboard's
    'Top opportunities'), not the alphabetically-first ones."""
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000, cfg=flat_cfg())
    h = make_hist(np.linspace(950, 1000, 70))
    # Alphabetical order AAAA<BBBB<CCCC, but scores are the REVERSE.
    sigs = [
        {**buy_signal("AAAA.JK"), "technical_score": 55},
        {**buy_signal("BBBB.JK"), "technical_score": 70},
        {**buy_signal("CCCC.JK"), "technical_score": 90},
    ]
    hist = {"AAAA.JK": h, "BBBB.JK": h, "CCCC.JK": h}
    # Only one slot available -> must pick CCCC (score 90), not AAAA.
    r = pt.step(hist, sigs, allocation=10_000_000, today="2026-07-01",
                max_positions=1)
    assert len(r["buys_queued"]) == 1
    assert r["buys_queued"][0].startswith("CCCC.JK")
    assert any("portfolio full" in s for s in r["skipped"])


def test_strong_buy_breaks_score_ties(tmp_path):
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000, cfg=flat_cfg())
    h = make_hist(np.linspace(950, 1000, 70))
    sigs = [
        {**buy_signal("AAAA.JK"), "signal": "BUY", "technical_score": 80},
        {**buy_signal("ZZZZ.JK"), "signal": "STRONG BUY", "technical_score": 80},
    ]
    r = pt.step({"AAAA.JK": h, "ZZZZ.JK": h}, sigs, allocation=10_000_000,
                today="2026-07-01", max_positions=1)
    assert r["buys_queued"][0].startswith("ZZZZ.JK")   # STRONG BUY wins the tie


def test_portfolio_cap_counts_existing_holdings(tmp_path):
    """max_positions caps TOTAL names: if we already hold enough, no new buys."""
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000, cfg=flat_cfg())
    h = make_hist(np.linspace(950, 1000, 70))
    # Take one position first (max_positions=2 -> one slot used).
    pt.step({"AAAA.JK": h}, [{**buy_signal("AAAA.JK"), "technical_score": 60}],
            allocation=10_000_000, today="2026-07-01", max_positions=2)
    # fill it
    h2 = make_hist(np.append(np.linspace(950, 1000, 70), 1000.0))
    pt.step({"AAAA.JK": h2}, [], today="2026-07-02", max_positions=2)
    assert "AAAA.JK" in pt.positions
    # Now two strong new BUYs but only ONE slot left.
    sigs = [{**buy_signal("BBBB.JK"), "technical_score": 95},
            {**buy_signal("CCCC.JK"), "technical_score": 90}]
    r = pt.step({"BBBB.JK": h, "CCCC.JK": h}, sigs, allocation=10_000_000,
                today="2026-07-03", max_positions=2)
    assert len(r["buys_queued"]) == 1 and r["buys_queued"][0].startswith("BBBB.JK")


def test_stop_breach_queues_sell_then_fills(tmp_path):
    cfg = Config(risk=RiskConfig(trailing_enabled=False, hard_stop_pct=-5.0,
                                 atr_stop_multiple=99.0, target_profit_pct=999.0))
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000, cfg=cfg)
    base = np.linspace(950, 1000, 70)
    pt.step({"AAAA.JK": make_hist(base)}, [buy_signal()], today="2026-07-01")
    pt.step({"AAAA.JK": make_hist(np.append(base, 1000.0))}, [], today="2026-07-02")  # fill

    # crash -8% -> exit engine must queue an URGENT sell
    crash = np.append(np.append(base, 1000.0), 920.0)
    r3 = pt.step({"AAAA.JK": make_hist(crash)}, [], today="2026-07-03")
    assert r3["exits_queued"] and any("SELL AAAA.JK" in t for t in r3["tickets"])

    # next open: sell fills with sell-side costs, trade logged
    nxt = np.append(crash, 915.0)
    r4 = pt.step({"AAAA.JK": make_hist(nxt, opens=np.append(crash, 918.0))}, [],
                 today="2026-07-04")
    assert any("SOLD AAAA.JK" in f for f in r4["fills"])
    assert "AAAA.JK" not in pt.positions and len(pt.log) == 1
    assert pt.log[0]["pnl_pct"] < 0


def test_state_roundtrip(tmp_path):
    p = tmp_path / "p.json"
    pt = PaperTrader.load(p, start_capital=10_000_000, cfg=flat_cfg())
    pt.step({"AAAA.JK": make_hist(np.linspace(950, 1000, 70))}, [buy_signal()],
            today="2026-07-01")
    pt2 = PaperTrader.load(p, cfg=flat_cfg())
    assert pt2.cash == pt.cash and len(pt2.pending) == 1
    assert pt2.pending[0].ticker == "AAAA.JK"
    s = pt2.summary({"AAAA.JK": 1000.0})
    assert s["equity"] == pytest.approx(pt2.cash)          # nothing filled yet


def test_message_contains_tickets_and_caveat():
    report = {"date": "2026-07-06", "fills": ["BOUGHT X.JK 500 @ 1,010"],
              "tickets": ["BUY Y.JK — 700 shares ≈ IDR 2,000,000 (last 2,850, initial stop 2,745)"],
              "skipped": [], "exits_queued": [], "buys_queued": []}
    msg = format_daily_message(report, summary={"equity": 10_100_000, "cash": 5_000_000,
                                                "return_pct": 1.0, "open_positions": 2,
                                                "closed_trades": 3, "win_rate_pct": 66.7},
                               market_status="NEUTRAL",
                               extra_alerts=[{"ticker": "BBCA.JK", "discount_pct": 18.0,
                                              "price": 9000.0, "fair_value": 11000.0}])
    for needle in ["BUY Y.JK", "700 shares", "stop 2,745", "BBCA.JK", "18% below",
                   "equity IDR 10,100,000", "not advice"]:
        assert needle in msg, needle


# ---- v2.3: liquidity cap, ARB sell carry, alpha vs IHSG ----------------------

def make_hist_vol(closes, volume, opens=None, lows=None):
    closes = np.asarray(closes, dtype=float)
    n = len(closes)
    opens = np.asarray(opens, dtype=float) if opens is not None else closes
    lows = np.asarray(lows, dtype=float) if lows is not None else closes * 0.995
    return pd.DataFrame(
        {"Open": opens, "High": closes * 1.005, "Low": lows,
         "Close": closes, "Volume": np.full(n, float(volume))},
        index=pd.bdate_range("2026-01-05", periods=n))


def test_liquidity_cap_shrinks_illiquid_order(tmp_path):
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=100_000_000, cfg=flat_cfg())
    # ADV ~= 975 * 4000 = IDR 3.9M/day; 5% cap ~= IDR 195k -> exactly 1 lot,
    # far below the ~2000 shares risk-based sizing would otherwise give.
    thin = make_hist_vol(np.linspace(950, 1000, 70), volume=4000)
    r = pt.step({"THIN.JK": thin}, [buy_signal("THIN.JK", price=1000.0)],
                allocation=50_000_000, today="2026-07-01", max_pct_of_adv=5.0)
    assert len(pt.pending) == 1 and pt.pending[0].shares == LOT_SIZE
    assert any("liquidity cap" in s for s in r["skipped"])


def test_liquidity_cap_skips_untradeable(tmp_path):
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=100_000_000, cfg=flat_cfg())
    # ADV = 1000 * 100 = IDR 100,000; 5% = IDR 5,000 < 1 lot -> skip entirely.
    dust = make_hist_vol(np.linspace(950, 1000, 70), volume=100)
    r = pt.step({"DUST.JK": dust}, [buy_signal("DUST.JK", price=1000.0)],
                allocation=50_000_000, today="2026-07-01")
    assert not pt.pending and any("too illiquid" in s for s in r["skipped"])


def test_sell_carried_on_limit_down(tmp_path):
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000, cfg=flat_cfg())
    from kala.papertrade import PaperPosition, PendingOrder
    pt.positions["CRSH.JK"] = PaperPosition(
        ticker="CRSH.JK", entry_price=1000.0, shares=1000,
        entry_date="2026-06-01", peak_price=1000.0)
    pt.pending = [PendingOrder(ticker="CRSH.JK", side="SELL", shares=1000,
                               reason="stop", queued="2026-06-30")]
    # yesterday closed 1000; today pinned limit-down -25%, close == low
    closes = np.append(np.linspace(990, 1000, 69), 750.0)
    h = make_hist_vol(closes, volume=1e6,
                      opens=np.append(np.linspace(990, 1000, 69), 760.0),
                      lows=np.append(np.linspace(990, 1000, 69) * 0.995, 750.0))
    r = pt.step({"CRSH.JK": h}, [], today="2026-07-01")
    assert "CRSH.JK" in pt.positions            # NOT fantasy-filled
    assert len(pt.pending) == 1                 # order carried
    assert any("limit down" in s for s in r["skipped"])
    # next day trades normally at 800 -> now it fills, at the REAL price
    closes2 = np.append(closes, 800.0)
    h2 = make_hist_vol(closes2, volume=1e6,
                       opens=np.append(closes, 800.0),
                       lows=np.append(closes * 0.995, 790.0))
    r2 = pt.step({"CRSH.JK": h2}, [], today="2026-07-02")
    assert "CRSH.JK" not in pt.positions and r2["fills"]


def test_alpha_vs_benchmark(tmp_path):
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000, cfg=flat_cfg())
    pt.note_benchmark(7000.0)                    # IHSG on day 1
    s = pt.summary({}, benchmark_price=7350.0)   # index +5%, account flat
    assert s["benchmark_return_pct"] == pytest.approx(5.0)
    assert s["alpha_pct"] == pytest.approx(-5.0)
    # baseline locks: a later note_benchmark must not overwrite it
    pt.note_benchmark(9999.0)
    assert pt.benchmark_start == 7000.0
    # persists across restart
    pt2 = PaperTrader.load(tmp_path / "p.json", cfg=flat_cfg())
    assert pt2.benchmark_start == 7000.0
    # and the notifier renders it
    msg = format_daily_message({"date": "2026-07-06", "tickets": []},
                               summary=pt2.summary({}, benchmark_price=7350.0))
    assert "alpha" in msg and "IHSG" in msg


# ---------------- manual buy/sell (real trades recorded from the bot) ----

def test_manual_buy_records_position_and_deducts_cash(tmp_path):
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000, cfg=flat_cfg())
    pt.manual_buy("ANTM.JK", shares=200, price=1500)
    assert "ANTM.JK" in pt.positions
    pos = pt.positions["ANTM.JK"]
    fill = buy_fill(1500)
    assert pos.shares == 200 and pos.entry_price == pytest.approx(fill)
    # peak tracks the MARKET price, not the cost-inclusive one -- seeding it
    # above any price the market printed would arm the trailing stop early
    assert pos.peak_price == 1500
    assert pt.cash == pytest.approx(10_000_000 - 200 * fill)
    # persisted to disk
    reloaded = PaperTrader.load(tmp_path / "p.json")
    assert "ANTM.JK" in reloaded.positions


def test_manual_buy_rejects_insufficient_cash(tmp_path):
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=100_000, cfg=flat_cfg())
    with pytest.raises(ValueError, match="not enough cash"):
        pt.manual_buy("ANTM.JK", shares=200, price=1500)


# ---------------------------------------------------------------------------
# manual_buy on an already-held ticker -- ADDS to the position (weighted-
# average cost basis) instead of rejecting. /review's "could add" note is
# only meaningful if this actually works.
# ---------------------------------------------------------------------------

def test_manual_buy_on_held_ticker_blends_weighted_average_price(tmp_path):
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000, cfg=flat_cfg())
    pt.manual_buy("BBRI.JK", shares=100, price=1000.0)
    pt.manual_buy("BBRI.JK", shares=100, price=1200.0)   # added at a higher price

    pos = pt.positions["BBRI.JK"]
    f1, f2 = buy_fill(1000.0), buy_fill(1200.0)
    assert pos.shares == 200
    assert pos.entry_price == pytest.approx((100 * f1 + 100 * f2) / 200)
    assert pt.cash == pytest.approx(10_000_000 - 100 * f1 - 100 * f2)


def test_manual_buy_add_preserves_peak_and_original_entry_date(tmp_path):
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000, cfg=flat_cfg())
    pt.manual_buy("BBRI.JK", shares=100, price=1000.0, date="2026-07-01")
    pt.positions["BBRI.JK"].peak_price = 1300.0   # simulate a rally since entry

    # adding at a LOWER price than the peak must not reset the peak --
    # the trailing stop still has to respect the true historical high
    pt.manual_buy("BBRI.JK", shares=50, price=1100.0, date="2026-07-10")
    pos = pt.positions["BBRI.JK"]
    assert pos.peak_price == 1300.0
    assert pos.entry_date == "2026-07-01"          # still the FIRST purchase date

    # adding at a NEW high must bump the peak
    pt.manual_buy("BBRI.JK", shares=50, price=1400.0, date="2026-07-12")
    assert pt.positions["BBRI.JK"].peak_price == 1400.0


def test_manual_buy_add_refreshes_atr_only_when_given(tmp_path):
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000, cfg=flat_cfg())
    pt.manual_buy("BBRI.JK", shares=100, price=1000.0, atr=20.0)
    pt.manual_buy("BBRI.JK", shares=100, price=1000.0)              # no atr given
    assert pt.positions["BBRI.JK"].entry_atr == 20.0                # unchanged
    pt.manual_buy("BBRI.JK", shares=100, price=1000.0, atr=25.0)
    assert pt.positions["BBRI.JK"].entry_atr == 25.0                # refreshed


def test_manual_buy_add_persists_across_reload(tmp_path):
    from kala.papertrade import PaperTrader as PT
    pt = PT.load(tmp_path / "p.json", start_capital=10_000_000, cfg=flat_cfg())
    pt.manual_buy("BBRI.JK", shares=100, price=1000.0)
    pt.manual_buy("BBRI.JK", shares=100, price=1200.0)
    reloaded = PT.load(tmp_path / "p.json")
    assert reloaded.positions["BBRI.JK"].shares == 200
    assert reloaded.positions["BBRI.JK"].entry_price == pytest.approx(
        (buy_fill(1000.0) + buy_fill(1200.0)) / 2)


# ---------------------------------------------------------------------------
# add_capital -- deposit fresh money mid-cycle. Must move cash AND
# start_capital together so return_pct isn't inflated by the deposit itself.
# ---------------------------------------------------------------------------

def test_add_capital_increases_cash_and_start_capital_together(tmp_path):
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000, cfg=flat_cfg())
    pt.add_capital(5_000_000, date="2026-07-14")
    assert pt.cash == pytest.approx(15_000_000)
    assert pt.start_capital == pytest.approx(15_000_000)
    assert pt.capital_additions == [{"date": "2026-07-14", "amount": 5_000_000.0}]


def test_add_capital_does_not_change_return_pct(tmp_path):
    """The whole point: a deposit must not look like a trading gain."""
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000, cfg=flat_cfg())
    before = pt.summary({})["return_pct"]
    pt.add_capital(5_000_000)
    after = pt.summary({})["return_pct"]
    assert before == pytest.approx(after) == pytest.approx(0.0)


def test_add_capital_rejects_non_positive(tmp_path):
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000, cfg=flat_cfg())
    with pytest.raises(ValueError, match="positive"):
        pt.add_capital(0)
    with pytest.raises(ValueError, match="positive"):
        pt.add_capital(-100)
    assert pt.cash == pytest.approx(10_000_000)   # rejected -- nothing moved


def test_add_capital_persists_across_reload(tmp_path):
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000, cfg=flat_cfg())
    pt.add_capital(2_000_000)
    reloaded = PaperTrader.load(tmp_path / "p.json")
    assert reloaded.cash == pytest.approx(12_000_000)
    assert reloaded.start_capital == pytest.approx(12_000_000)
    assert len(reloaded.capital_additions) == 1


# ---------------------------------------------------------------------------
# record_dividend — the deliberate OPPOSITE of add_capital: real return
# (raises cash only), not external principal (which would also raise
# start_capital and get excluded from return_pct).
# ---------------------------------------------------------------------------

def test_record_dividend_increases_cash_not_start_capital(tmp_path):
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000, cfg=flat_cfg())
    pt.record_dividend("ANTM.JK", 50_000, date="2026-07-14")
    assert pt.cash == pytest.approx(10_050_000)
    assert pt.start_capital == pytest.approx(10_000_000)   # UNCHANGED, unlike add_capital
    assert pt.dividends == [{"date": "2026-07-14", "ticker": "ANTM.JK", "amount": 50_000.0}]


def test_record_dividend_counts_as_real_return_unlike_deposit():
    """The whole point, mirrored against test_add_capital_does_not_change_return_pct:
    a dividend MUST move return_pct, since it's real investment income."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        pt = PaperTrader.load(f"{d}/p.json", start_capital=10_000_000, cfg=flat_cfg())
        before = pt.summary({})["return_pct"]
        pt.record_dividend("ANTM.JK", 500_000)
        after = pt.summary({})["return_pct"]
        assert before == pytest.approx(0.0)
        assert after > before
        assert after == pytest.approx(5.0)   # 500k / 10,000,000 = 5%


def test_record_dividend_rejects_non_positive(tmp_path):
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000, cfg=flat_cfg())
    with pytest.raises(ValueError, match="positive"):
        pt.record_dividend("ANTM.JK", 0)
    with pytest.raises(ValueError, match="positive"):
        pt.record_dividend("ANTM.JK", -100)
    assert pt.cash == pytest.approx(10_000_000)   # rejected -- nothing moved


def test_record_dividend_persists_across_reload(tmp_path):
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000, cfg=flat_cfg())
    pt.record_dividend("BBCA.JK", 75_000)
    reloaded = PaperTrader.load(tmp_path / "p.json")
    assert reloaded.cash == pytest.approx(10_075_000)
    assert reloaded.start_capital == pytest.approx(10_000_000)
    assert len(reloaded.dividends) == 1
    assert reloaded.dividends[0]["ticker"] == "BBCA.JK"


def test_record_dividend_does_not_require_still_holding_ticker(tmp_path):
    """A dividend can be paid after you've already sold -- must not require
    an open position to record it."""
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000, cfg=flat_cfg())
    pt.record_dividend("NEVERBOUGHT.JK", 10_000)
    assert pt.cash == pytest.approx(10_010_000)


def test_record_dividend_undo_redo_round_trips(tmp_path):
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000, cfg=flat_cfg())
    pt.record_dividend("ANTM.JK", 50_000)
    assert pt.cash == pytest.approx(10_050_000)

    info = pt.undo()
    assert info["kind"] == "dividend"
    assert pt.cash == pytest.approx(10_000_000)
    assert pt.dividends == []

    pt.redo()
    assert pt.cash == pytest.approx(10_050_000)
    assert len(pt.dividends) == 1


def test_old_undo_snapshot_without_dividends_field_restores_cleanly(tmp_path):
    """A snapshot taken before this field existed (mid-upgrade) has no
    'dividends' key -- restoring it must degrade to [], not KeyError."""
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000, cfg=flat_cfg())
    old_style_snapshot = pt._snapshot()
    del old_style_snapshot["dividends"]
    pt.dividends = [{"date": "2026-01-01", "ticker": "X.JK", "amount": 1.0}]  # pre-restore state
    pt._restore(old_style_snapshot)
    assert pt.dividends == []


# ---------------------------------------------------------------------------
# max holding period — validated exit rule, applied by the live path since
# v3.3 (it was previously backtest-only, one half of the -0.21%-vs-+0.37%
# exit-engine divergence).
# ---------------------------------------------------------------------------

def test_step_queues_sell_at_max_holding_period(tmp_path):
    from kala.papertrade import PaperPosition
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000, cfg=flat_cfg())
    pt.cfg.backtest.holding_max_days = 15

    h = make_hist(np.full(70, 1000.0))          # flat: no other rule can fire
    entry_date = h.index[-20].date().isoformat()   # held 19 bars > 15
    pt.positions["OLDY.JK"] = PaperPosition(
        ticker="OLDY.JK", entry_price=1000.0, shares=100,
        entry_date=entry_date, peak_price=1000.0)

    r = pt.step({"OLDY.JK": h}, [], today=h.index[-1].date().isoformat())
    assert any(o.side == "SELL" and o.ticker == "OLDY.JK" for o in pt.pending)
    assert any("max holding" in s for s in r["exits_queued"])


def test_step_no_max_hold_sell_before_the_limit(tmp_path):
    from kala.papertrade import PaperPosition
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000, cfg=flat_cfg())
    pt.cfg.backtest.holding_max_days = 15

    h = make_hist(np.full(70, 1000.0))
    entry_date = h.index[-5].date().isoformat()    # held only 4 bars
    pt.positions["YUNG.JK"] = PaperPosition(
        ticker="YUNG.JK", entry_price=1000.0, shares=100,
        entry_date=entry_date, peak_price=1000.0)

    pt.step({"YUNG.JK": h}, [], today=h.index[-1].date().isoformat())
    assert not any(o.side == "SELL" for o in pt.pending)


def test_manual_sell_returns_pnl_and_logs(tmp_path):
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000, cfg=flat_cfg())
    pt.manual_buy("ANTM.JK", shares=200, price=1500)
    pnl = pt.manual_sell("ANTM.JK", price=1650)
    fill, net = buy_fill(1500), sell_net(1650)
    # ~10% raw, less the round trip's friction on both legs
    expected = (net / fill - 1) * 100.0
    assert expected < 10.0
    assert pnl == pytest.approx(expected)
    assert "ANTM.JK" not in pt.positions
    assert pt.log[-1]["ticker"] == "ANTM.JK"
    assert pt.log[-1]["pnl_pct"] == pytest.approx(expected)
    assert pt.cash == pytest.approx(10_000_000 - 200 * fill + 200 * net)


def test_manual_sell_unheld_raises(tmp_path):
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000, cfg=flat_cfg())
    with pytest.raises(ValueError, match="not holding"):
        pt.manual_sell("XXXX.JK", price=100)


# ---------------------------------------------------------------------------
# manual_sell with shares= -- partial sell (take-profit on part of a
# position). The un-sold shares must keep their ORIGINAL cost basis: they
# didn't change price just because some siblings were sold.
# ---------------------------------------------------------------------------

def test_manual_sell_partial_keeps_position_open_at_same_cost_basis(tmp_path):
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000, cfg=flat_cfg())
    pt.manual_buy("ANTM.JK", shares=200, price=1500.0, date="2026-07-01")
    pt.positions["ANTM.JK"].peak_price = 1700.0

    pnl = pt.manual_sell("ANTM.JK", price=1650.0, shares=100)
    fill, net = buy_fill(1500.0), sell_net(1650.0)
    assert pnl == pytest.approx((net / fill - 1) * 100.0)   # pnl on the SOLD shares
    pos = pt.positions["ANTM.JK"]
    assert pos.shares == 100                                # half remains open
    assert pos.entry_price == pytest.approx(fill)            # cost basis UNCHANGED
    assert pos.peak_price == pytest.approx(1700.0)
    assert pos.entry_date == "2026-07-01"
    assert pt.cash == pytest.approx(10_000_000 - 200 * fill + 100 * net)
    assert pt.log[-1]["shares"] == 100


def test_manual_sell_full_shares_closes_position_same_as_default(tmp_path):
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000, cfg=flat_cfg())
    pt.manual_buy("ANTM.JK", shares=200, price=1500.0)
    pt.manual_sell("ANTM.JK", price=1650.0, shares=200)      # explicit full amount
    assert "ANTM.JK" not in pt.positions


def test_manual_sell_more_than_held_raises(tmp_path):
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000, cfg=flat_cfg())
    pt.manual_buy("ANTM.JK", shares=100, price=1500.0)
    with pytest.raises(ValueError, match="only hold 100"):
        pt.manual_sell("ANTM.JK", price=1650.0, shares=200)


# ---------------------------------------------------------------------------
# edit_entry_price -- correcting a wrong entry price already on the books,
# without touching /undo's single-step-back scope. Cash must reconcile
# (entry_price is cost-inclusive) and peak_price must never fall below the
# corrected entry, or the trailing-stop logic computes a stop below cost basis.
# ---------------------------------------------------------------------------

def test_edit_entry_price_updates_price_and_reconciles_cash_downward(tmp_path):
    """Correcting to a LOWER price means less was actually spent -- cash
    must increase by the difference."""
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000, cfg=flat_cfg())
    pt.manual_buy("ANTM.JK", shares=200, price=1500.0)
    cash_after_buy = pt.cash

    # edit_entry_price sets the STORED cost basis directly -- it does not
    # add costs on top, so the old value read back is the costed buy fill.
    old = pt.edit_entry_price("ANTM.JK", 1400.0)
    assert old == pytest.approx(buy_fill(1500.0))
    assert pt.positions["ANTM.JK"].entry_price == 1400.0
    assert pt.cash == pytest.approx(cash_after_buy + 200 * (buy_fill(1500.0) - 1400.0))


def test_edit_entry_price_upward_debits_cash_further(tmp_path):
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000, cfg=flat_cfg())
    pt.manual_buy("ANTM.JK", shares=200, price=1500.0)
    cash_after_buy = pt.cash

    pt.edit_entry_price("ANTM.JK", 1550.0)
    assert pt.cash == pytest.approx(cash_after_buy - 200 * (1550.0 - buy_fill(1500.0)))


def test_edit_entry_price_leaves_shares_and_date_untouched(tmp_path):
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000, cfg=flat_cfg())
    pt.manual_buy("ANTM.JK", shares=200, price=1500.0, date="2026-07-01")
    pt.edit_entry_price("ANTM.JK", 1450.0)
    pos = pt.positions["ANTM.JK"]
    assert pos.shares == 200
    assert pos.entry_date == "2026-07-01"


def test_edit_entry_price_raises_peak_when_correction_exceeds_it(tmp_path):
    """peak_price must never sit below entry_price -- a trailing stop
    computed off a peak below cost basis defeats the point of a stop-loss."""
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000, cfg=flat_cfg())
    pt.manual_buy("ANTM.JK", shares=200, price=1500.0)
    pt.edit_entry_price("ANTM.JK", 1700.0)   # above the seeded peak of 1500
    assert pt.positions["ANTM.JK"].peak_price == 1700.0


def test_edit_entry_price_does_not_lower_an_already_higher_peak(tmp_path):
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000, cfg=flat_cfg())
    pt.manual_buy("ANTM.JK", shares=200, price=1500.0)
    pt.positions["ANTM.JK"].peak_price = 1900.0   # simulate a run-up since entry
    pt.edit_entry_price("ANTM.JK", 1550.0)
    assert pt.positions["ANTM.JK"].peak_price == 1900.0   # untouched, not clobbered


def test_edit_entry_price_unheld_raises(tmp_path):
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000, cfg=flat_cfg())
    with pytest.raises(ValueError, match="not holding"):
        pt.edit_entry_price("ANTM.JK", 1500.0)


def test_edit_entry_price_rejects_non_positive(tmp_path):
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000, cfg=flat_cfg())
    pt.manual_buy("ANTM.JK", shares=200, price=1500.0)
    with pytest.raises(ValueError, match="positive"):
        pt.edit_entry_price("ANTM.JK", 0.0)
    with pytest.raises(ValueError, match="positive"):
        pt.edit_entry_price("ANTM.JK", -100.0)


def test_edit_entry_price_rejects_identical_price(tmp_path):
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000, cfg=flat_cfg())
    pt.manual_buy("ANTM.JK", shares=200, price=1500.0)
    with pytest.raises(ValueError, match="nothing to change"):
        pt.edit_entry_price("ANTM.JK", buy_fill(1500.0))


def test_edit_entry_price_rejects_when_cash_cannot_cover_the_correction(tmp_path):
    """An upward correction implies MORE was spent than recorded -- if that
    exceeds available cash, the correction can't be real."""
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=301_000, cfg=flat_cfg())
    pt.manual_buy("ANTM.JK", shares=200, price=1500.0)   # spends nearly all of it
    with pytest.raises(ValueError, match="only have"):
        pt.edit_entry_price("ANTM.JK", 2000.0)
    # rejected correction must not have mutated anything
    assert pt.positions["ANTM.JK"].entry_price == pytest.approx(buy_fill(1500.0))


def test_edit_entry_price_without_cash_reconciliation(tmp_path):
    """reconcile_cash=False: price changes, cash does not."""
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000, cfg=flat_cfg())
    pt.manual_buy("ANTM.JK", shares=200, price=1500.0)
    cash_after_buy = pt.cash
    pt.edit_entry_price("ANTM.JK", 2000.0, reconcile_cash=False)
    assert pt.cash == cash_after_buy
    assert pt.positions["ANTM.JK"].entry_price == 2000.0


def test_edit_entry_price_is_undoable(tmp_path):
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000, cfg=flat_cfg())
    pt.manual_buy("ANTM.JK", shares=200, price=1500.0)
    cash_after_buy = pt.cash
    pt.edit_entry_price("ANTM.JK", 1400.0)
    pt.undo()
    assert pt.positions["ANTM.JK"].entry_price == pytest.approx(buy_fill(1500.0))
    assert pt.cash == pytest.approx(cash_after_buy)


def test_edit_entry_price_persists_across_reload(tmp_path):
    path = tmp_path / "p.json"
    pt = PaperTrader.load(path, start_capital=10_000_000, cfg=flat_cfg())
    pt.manual_buy("ANTM.JK", shares=200, price=1500.0)
    pt.edit_entry_price("ANTM.JK", 1420.0)
    reloaded = PaperTrader.load(path)
    assert reloaded.positions["ANTM.JK"].entry_price == 1420.0


def test_save_is_atomic_no_tmp_left_and_roundtrips(tmp_path):
    """save() writes via temp-file + os.replace so a crash mid-write can
    never corrupt paper_state.json. After a normal save: no .tmp remains,
    and the file parses + round-trips."""
    path = tmp_path / "p.json"
    pt = PaperTrader.load(path, start_capital=10_000_000, cfg=flat_cfg())
    pt.manual_buy("ANTM.JK", shares=100, price=1500.0)
    assert not list(tmp_path.glob("*.tmp")), "temp file must not linger"
    reloaded = PaperTrader.load(path)
    assert reloaded.positions["ANTM.JK"].shares == 100


def test_rotate_state_backup_creates_and_prunes(tmp_path):
    import json as _json

    from kala.papertrade import rotate_state_backup

    state = tmp_path / "paper_state.json"
    state.write_text(_json.dumps({"cash": 1}))
    bdir = tmp_path / "backups"

    # seed 9 fake older backups; a rotate with keep=7 must leave the 7 newest
    for i in range(1, 10):
        (bdir / f"paper_state_202601{i:02d}.json").parent.mkdir(exist_ok=True)
        (bdir / f"paper_state_202601{i:02d}.json").write_text("{}")
    dest = rotate_state_backup(state, bdir, keep=7)
    assert dest is not None and dest.exists()
    remaining = sorted(bdir.glob("paper_state_*.json"))
    assert len(remaining) == 7
    assert dest in remaining                       # today's copy survives
    assert (bdir / "paper_state_20260101.json") not in remaining  # oldest pruned

    # same-day second call: overwrites, doesn't duplicate
    rotate_state_backup(state, bdir, keep=7)
    assert len(sorted(bdir.glob("paper_state_*.json"))) == 7


def test_rotate_state_backup_none_when_no_state_file(tmp_path):
    from kala.papertrade import rotate_state_backup
    assert rotate_state_backup(tmp_path / "missing.json", tmp_path / "b") is None
    assert not (tmp_path / "b").exists() or not list((tmp_path / "b").iterdir())


def test_backup_restores_to_an_identical_trader_after_corruption(tmp_path):
    """A backup you've never restored isn't a backup. Prove the round-trip:
    build a real trader with positions + a closed-trade log, back it up,
    corrupt the live state file, restore the backup over it, and confirm the
    reloaded trader is byte-for-byte the same account."""
    import shutil

    from kala.papertrade import rotate_state_backup

    state = tmp_path / "paper_state.json"
    pt = PaperTrader.load(state, start_capital=10_000_000, cfg=flat_cfg())
    pt.manual_buy("ANTM.JK", shares=200, price=1500.0, date="2026-07-10")
    pt.manual_buy("BBRI.JK", shares=100, price=4000.0, date="2026-07-11")
    pt.manual_sell("ANTM.JK", price=1650.0, date="2026-07-14")   # a closed trade in the log
    original_json = state.read_text()

    bdir = tmp_path / "backups"
    backup = rotate_state_backup(state, bdir)
    assert backup is not None and backup.exists()

    # simulate corruption: overwrite the live state with garbage
    state.write_text("{ this is not valid json at all")

    # restore from the backup, exactly as an operator would
    shutil.copy2(backup, state)
    assert state.read_text() == original_json                     # bytes identical

    # and the reloaded trader is the same account
    restored = PaperTrader.load(state, start_capital=10_000_000, cfg=flat_cfg())
    assert set(restored.positions) == {"BBRI.JK"}                 # ANTM was sold
    assert restored.positions["BBRI.JK"].shares == 100
    assert restored.positions["BBRI.JK"].entry_price == pytest.approx(buy_fill(4000.0))
    assert restored.cash == pytest.approx(pt.cash)
    assert len(restored.log) == 1 and restored.log[0]["ticker"] == "ANTM.JK"


def test_recent_performance_counts_wins_and_losses_in_window(tmp_path):
    from datetime import date as _date
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000, cfg=flat_cfg())
    pt.manual_buy("WIN.JK", shares=100, price=1000.0, date="2026-07-10")
    pt.manual_sell("WIN.JK", price=1100.0, date="2026-07-12")     # +10%, win
    pt.manual_buy("LOSE.JK", shares=100, price=1000.0, date="2026-07-11")
    pt.manual_sell("LOSE.JK", price=900.0, date="2026-07-13")     # -10%, loss

    r = pt.recent_performance(days=7, today=_date(2026, 7, 14))
    assert r["n"] == 2
    assert r["wins"] == 1 and r["losses"] == 1
    assert r["win_rate_pct"] == pytest.approx(50.0)
    # Raw prices are symmetric (+100 / -100 per share), so the gross would
    # net to zero. It does NOT: both round trips paid friction, and with no
    # edge that is exactly what a symmetric pair of trades leaves behind.
    expected = (100 * (sell_net(1100.0) - buy_fill(1000.0))
                + 100 * (sell_net(900.0) - buy_fill(1000.0)))
    assert expected < 0
    assert r["net_profit_idr"] == pytest.approx(expected)
    tickers = {t["ticker"] for t in r["trades"]}
    assert tickers == {"WIN.JK", "LOSE.JK"}


def test_recent_performance_excludes_trades_outside_window(tmp_path):
    from datetime import date as _date
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000, cfg=flat_cfg())
    pt.manual_buy("OLD.JK", shares=100, price=1000.0, date="2026-06-01")
    pt.manual_sell("OLD.JK", price=1200.0, date="2026-06-03")     # long before window

    r = pt.recent_performance(days=7, today=_date(2026, 7, 14))
    assert r["n"] == 0
    assert r["win_rate_pct"] == 0.0
    assert r["net_profit_idr"] == 0.0


def test_recent_performance_net_profit_is_rupiah_not_percent(tmp_path):
    from datetime import date as _date
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000, cfg=flat_cfg())
    pt.manual_buy("BIG.JK", shares=1000, price=2000.0, date="2026-07-10")
    pt.manual_sell("BIG.JK", price=2100.0, date="2026-07-11")     # +5%, but 1000 shares

    r = pt.recent_performance(days=7, today=_date(2026, 7, 12))
    expected = 1000 * (sell_net(2100.0) - buy_fill(2000.0))
    assert r["net_profit_idr"] == pytest.approx(expected)
    assert r["trades"][0]["profit_idr"] == pytest.approx(expected)
    # still rupiah, not percent -- the point of this test
    assert r["trades"][0]["profit_idr"] > 10_000


def test_recent_performance_trades_sorted_most_recent_first(tmp_path):
    from datetime import date as _date
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000, cfg=flat_cfg())
    pt.manual_buy("A.JK", shares=100, price=1000.0, date="2026-07-08")
    pt.manual_sell("A.JK", price=1010.0, date="2026-07-09")
    pt.manual_buy("B.JK", shares=100, price=1000.0, date="2026-07-11")
    pt.manual_sell("B.JK", price=1010.0, date="2026-07-13")

    r = pt.recent_performance(days=7, today=_date(2026, 7, 14))
    assert [t["ticker"] for t in r["trades"]] == ["B.JK", "A.JK"]


def test_recent_performance_default_days_is_seven(tmp_path):
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000, cfg=flat_cfg())
    r = pt.recent_performance()
    assert r["window_days"] == 7


def test_manual_sell_rejects_date_before_entry_date(tmp_path):
    """A sell dated before its own entry produces a negative hold time that
    the /edge tracker's live_stats() averages in uncaught -- reject it
    outright instead."""
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000, cfg=flat_cfg())
    pt.manual_buy("ANTM.JK", shares=100, price=1500.0, date="2026-07-10")
    with pytest.raises(ValueError, match="before ANTM.JK's entry date"):
        pt.manual_sell("ANTM.JK", price=1650.0, date="2026-07-05")
    assert "ANTM.JK" in pt.positions   # rejected -- nothing sold, no log entry
    assert pt.log == []


def test_manual_sell_allows_date_equal_to_entry_date(tmp_path):
    """Same-day buy and sell (day-trade recorded after the fact) must NOT be
    rejected -- only a sell STRICTLY before entry is invalid."""
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000, cfg=flat_cfg())
    pt.manual_buy("ANTM.JK", shares=100, price=1500.0, date="2026-07-10")
    pt.manual_sell("ANTM.JK", price=1600.0, date="2026-07-10")
    assert "ANTM.JK" not in pt.positions


def test_manual_sell_zero_or_negative_shares_raises(tmp_path):
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000, cfg=flat_cfg())
    pt.manual_buy("ANTM.JK", shares=100, price=1500.0)
    with pytest.raises(ValueError, match="positive"):
        pt.manual_sell("ANTM.JK", price=1650.0, shares=0)


def test_undo_reverts_partial_sell_to_full_position(tmp_path):
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000, cfg=flat_cfg())
    pt.manual_buy("ANTM.JK", shares=200, price=1500.0)
    pt.manual_sell("ANTM.JK", price=1650.0, shares=100)
    info = pt.undo()
    assert info["kind"] == "sell"
    assert pt.positions["ANTM.JK"].shares == 200
    assert pt.log == []


# ---------------------------------------------------------------------------
# auto_buy=False — recommendation-only mode (the /positions-shows-stocks-
# -I-never-bought fix: a scanner BUY must never become a real position or
# move cash unless the user calls manual_buy).
# ---------------------------------------------------------------------------

def test_auto_buy_false_recommends_without_touching_state(tmp_path):
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000, cfg=flat_cfg())
    h = make_hist(np.linspace(950, 1000, 70))
    cash_before = pt.cash

    r = pt.step({"AAAA.JK": h}, [buy_signal()], allocation=10_000_000,
               today="2026-07-01", auto_buy=False)

    assert pt.positions == {}, "auto_buy=False must never open a position"
    assert pt.pending == [], "auto_buy=False must never queue an order"
    assert pt.cash == cash_before, "no cash may move without a real fill"
    assert r["buys_queued"] == []
    assert any("IDEA AAAA.JK" in t for t in r["tickets"])
    assert any("/buy AAAA" in t for t in r["tickets"]), "must tell the user how to confirm it"

    # a second step() the "next day" must NOT auto-fill anything either --
    # there's nothing pending to fill, unlike the auto_buy=True case
    r2 = pt.step({"AAAA.JK": make_hist(np.append(np.linspace(950, 1000, 70), 1010.0))},
                [], today="2026-07-02", auto_buy=False)
    assert pt.positions == {} and not r2["fills"]


def test_auto_buy_true_default_matches_historical_behavior(tmp_path):
    """Sanity: omitting auto_buy (or passing True) must behave exactly like
    every pre-existing test above — the default did not change."""
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000, cfg=flat_cfg())
    h = make_hist(np.linspace(950, 1000, 70))
    r = pt.step({"AAAA.JK": h}, [buy_signal()], allocation=10_000_000, today="2026-07-01")
    assert r["buys_queued"] and "AAAA.JK" in {o.ticker for o in pt.pending}


def test_tickets_show_stop_and_target_in_both_modes(tmp_path):
    cfg = flat_cfg()
    cfg.risk.target_profit_pct = 8.0
    h = make_hist(np.linspace(950, 1000, 70))

    pt_auto = PaperTrader.load(tmp_path / "auto.json", start_capital=10_000_000, cfg=cfg)
    r_auto = pt_auto.step({"AAAA.JK": h}, [buy_signal()], allocation=10_000_000,
                          today="2026-07-01", auto_buy=True)
    auto_ticket = next(t for t in r_auto["tickets"] if "AAAA.JK" in t)
    assert "stop-loss" in auto_ticket and "take-profit" in auto_ticket and "+8%" in auto_ticket

    pt_reco = PaperTrader.load(tmp_path / "reco.json", start_capital=10_000_000, cfg=cfg)
    r_reco = pt_reco.step({"AAAA.JK": h}, [buy_signal()], allocation=10_000_000,
                          today="2026-07-01", auto_buy=False)
    reco_ticket = next(t for t in r_reco["tickets"] if "AAAA.JK" in t)
    assert "stop-loss" in reco_ticket and "take-profit" in reco_ticket and "+8%" in reco_ticket


def test_auto_buy_false_still_manages_exits_on_manually_bought_positions(tmp_path):
    """The fix must not weaken exit management -- a position opened via
    manual_buy still gets its stop evaluated and a SELL queued when hit,
    regardless of auto_buy."""
    cfg = Config(risk=RiskConfig(trailing_enabled=False, hard_stop_pct=-5.0,
                                 atr_stop_multiple=99.0, target_profit_pct=999.0))
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000, cfg=cfg)
    pt.manual_buy("AAAA.JK", shares=100, price=1000.0)

    crash = np.append(np.linspace(950, 1000, 70), [940.0])   # -6%: through the -5% stop
    h = make_hist(crash)
    r = pt.step({"AAAA.JK": h}, [], today="2026-07-01", auto_buy=False)
    assert any(o.side == "SELL" and o.ticker == "AAAA.JK" for o in pt.pending)
    assert r["exits_queued"]


# ---------------------------------------------------------------------------
# undo / redo -- fat-finger safety net for manual_buy / manual_sell /
# add_capital. Scoped to those three; step()'s automated fills are untouched.
# ---------------------------------------------------------------------------

def test_undo_reverts_manual_buy(tmp_path):
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000, cfg=flat_cfg())
    pt.manual_buy("ANTM.JK", shares=200, price=1500)
    cash_after_buy = pt.cash
    info = pt.undo()
    assert "ANTM.JK" not in pt.positions
    assert pt.cash == 10_000_000
    assert pt.cash != cash_after_buy
    assert info["kind"] == "buy" and "ANTM.JK" in info["label"]
    # persisted
    reloaded = PaperTrader.load(tmp_path / "p.json")
    assert "ANTM.JK" not in reloaded.positions
    assert reloaded.cash == 10_000_000


def test_undo_reverts_manual_sell(tmp_path):
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000, cfg=flat_cfg())
    pt.manual_buy("ANTM.JK", shares=200, price=1500)
    pt.manual_sell("ANTM.JK", price=1800)
    assert "ANTM.JK" not in pt.positions
    info = pt.undo()
    assert info["kind"] == "sell"
    assert pt.positions["ANTM.JK"].shares == 200
    assert pt.positions["ANTM.JK"].entry_price == pytest.approx(buy_fill(1500))
    assert pt.log == []                     # the sell's log entry is gone too


def test_undo_reverts_add_capital(tmp_path):
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000, cfg=flat_cfg())
    pt.add_capital(5_000_000, date="2026-07-14")
    info = pt.undo()
    assert pt.cash == 10_000_000 and pt.start_capital == 10_000_000
    assert pt.capital_additions == []
    assert info["kind"] == "deposit" and info["amount"] == pytest.approx(5_000_000)


def test_add_capital_meta_roundtrips_through_undo_and_redo(tmp_path):
    """meta is an opaque bag the caller (the bot) uses to carry the exact
    pre-deposit budget for a precise config-sync reversal -- undo()/redo()
    must hand it back unchanged."""
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000, cfg=flat_cfg())
    pt.add_capital(5_000_000, meta={"pre_daily_capital_idr": 7_000_000})
    info = pt.undo()
    assert info["meta"] == {"pre_daily_capital_idr": 7_000_000}
    info2 = pt.redo()
    assert info2["meta"] == {"pre_daily_capital_idr": 7_000_000}


def test_redo_reapplies_undone_action(tmp_path):
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000, cfg=flat_cfg())
    pt.manual_buy("ANTM.JK", shares=200, price=1500)
    pt.undo()
    info = pt.redo()
    assert info["kind"] == "buy"
    assert pt.positions["ANTM.JK"].shares == 200
    assert pt.cash == pytest.approx(10_000_000 - 200 * buy_fill(1500))


def test_undo_with_nothing_to_undo_raises(tmp_path):
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000, cfg=flat_cfg())
    with pytest.raises(ValueError, match="nothing to undo"):
        pt.undo()


def test_redo_with_nothing_to_redo_raises(tmp_path):
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000, cfg=flat_cfg())
    pt.manual_buy("ANTM.JK", shares=200, price=1500)
    with pytest.raises(ValueError, match="nothing to redo"):
        pt.redo()                           # no undo happened yet


def test_new_manual_action_clears_redo_stack(tmp_path):
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000, cfg=flat_cfg())
    pt.manual_buy("ANTM.JK", shares=200, price=1500)
    pt.undo()
    pt.manual_buy("BBRI.JK", shares=100, price=1000)   # a fresh action, not a redo
    with pytest.raises(ValueError, match="nothing to redo"):
        pt.redo()


def test_undo_stack_depth_is_capped(tmp_path):
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=50_000_000, cfg=flat_cfg())
    for i in range(8):
        pt.manual_buy(f"T{i}.JK", shares=10, price=100)
    assert len(pt.undo_stack) == 5           # MAX_UNDO_DEPTH
    for _ in range(5):
        pt.undo()
    assert len(pt.undo_stack) == 0
    # the 3 oldest buys (T0-T2) are permanently out of undo range
    assert "T0.JK" in pt.positions and "T2.JK" in pt.positions
    assert "T3.JK" not in pt.positions       # the 5 most recent got undone


def test_closed_trade_log_records_entry_date_manual_path(tmp_path):
    """The /edge tracker computes hold time from the log alone, so every
    close must record WHEN the position was opened, not just at what price."""
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000, cfg=flat_cfg())
    pt.manual_buy("ANTM.JK", shares=100, price=1000.0, date="2026-07-01")
    pt.manual_sell("ANTM.JK", price=1100.0, date="2026-07-10")
    assert pt.log[-1]["entry_date"] == "2026-07-01"
    assert pt.log[-1]["date"] == "2026-07-10"


def test_closed_trade_log_records_entry_date_automated_path(tmp_path):
    """Same guarantee for sells filled by step() (the automated exit path)."""
    cfg = Config(risk=RiskConfig(trailing_enabled=False, hard_stop_pct=-5.0,
                                 atr_stop_multiple=99.0, target_profit_pct=999.0))
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000, cfg=cfg)
    base = np.linspace(950, 1000, 70)
    pt.step({"AAAA.JK": make_hist(base)}, [buy_signal()], today="2026-07-01")
    pt.step({"AAAA.JK": make_hist(np.append(base, 1000.0))}, [], today="2026-07-02")
    crash = np.append(np.append(base, 1000.0), 920.0)
    pt.step({"AAAA.JK": make_hist(crash)}, [], today="2026-07-03")
    pt.step({"AAAA.JK": make_hist(np.append(crash, 915.0))}, [], today="2026-07-04")
    assert len(pt.log) == 1
    assert pt.log[0]["entry_date"] == "2026-07-02"   # the fill day, not the queue day
    assert pt.log[0]["date"] == "2026-07-04"


def test_undo_reverts_manual_buy_on_held_ticker_to_pre_blend_state(tmp_path):
    """Undoing an ADD (buying more of a held ticker) must restore the exact
    pre-blend shares/entry_price/peak, not just subtract shares."""
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=10_000_000, cfg=flat_cfg())
    pt.manual_buy("BBRI.JK", shares=100, price=1000.0, date="2026-07-01")
    pt.positions["BBRI.JK"].peak_price = 1300.0
    pt.manual_buy("BBRI.JK", shares=50, price=1100.0, date="2026-07-10")
    assert pt.positions["BBRI.JK"].shares == 150

    pt.undo()
    pos = pt.positions["BBRI.JK"]
    assert pos.shares == 100
    assert pos.entry_price == pytest.approx(buy_fill(1000.0))
    assert pos.peak_price == 1300.0
    assert pos.entry_date == "2026-07-01"
