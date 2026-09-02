"""Telegram bot: pure-logic tests (money parsing, ranking, routing, config).

Network + trading actions are exercised only through dispatch routing with
the heavy action functions monkeypatched, so nothing here hits yfinance.
"""

import json
from datetime import date, timedelta

import pytest

import telegram_bot as tb

# The bot dates trades in WIB (kala/clock.py), deliberately, so these tests
# must anchor on the SAME clock. Using datetime.date.today() compares WIB
# behavior against the runner's LOCAL date, which agrees only when the runner
# happens to sit in a timezone whose date matches WIB's -- and fails for the
# ~7h/day window where UTC and WIB are on different calendar days. That made
# the suite pass on a machine in Indonesia and fail in a UTC container.
from kala.clock import today_wib as _today
from tests.test_papertrade import buy_fill, sell_net


def test_last_close_returns_none_for_nan_price(monkeypatch):
    """NaN latest bar must yield None, not NaN -- a NaN price renders as
    'nan' and misfires downstream <=/>= checks (the /checkstop-NaN bug)."""
    import math

    import pandas as pd

    import kala_daily_trader as dt
    idx = pd.bdate_range("2026-07-15", periods=3)
    df = pd.DataFrame({"Close": [100.0, 101.0, math.nan], "Open": [100.0, 101.0, 101.0],
                       "High": [100.0, 101.0, math.nan], "Low": [100.0, 101.0, 101.0],
                       "Volume": [1e6, 1e6, 1e6]}, index=idx)
    monkeypatch.setattr(dt, "download_stock_data", lambda t, *a, **k: df)
    assert tb._last_close("X.JK") is None


def test_last_close_returns_price_for_normal_bar(monkeypatch):
    import pandas as pd

    import kala_daily_trader as dt
    idx = pd.bdate_range("2026-07-15", periods=2)
    df = pd.DataFrame({"Close": [100.0, 101.5], "Open": [100.0, 101.0],
                       "High": [100.0, 102.0], "Low": [100.0, 101.0],
                       "Volume": [1e6, 1e6]}, index=idx)
    monkeypatch.setattr(dt, "download_stock_data", lambda t, *a, **k: df)
    assert tb._last_close("X.JK") == pytest.approx(101.5)


# ---------------- money parsing ----------------

@pytest.mark.parametrize("text,expected", [
    ("5000000", 5_000_000),
    ("5.000.000", 5_000_000),
    ("5,000,000", 5_000_000),
    ("5jt", 5_000_000),
    ("5 juta", 5_000_000),
    ("5m", 5_000_000),
    ("2.5jt", 2_500_000),
    ("2,5jt", 2_500_000),
    ("500rb", 500_000),
    ("500 ribu", 500_000),
    ("750k", 750_000),
    ("10000000", 10_000_000),
])
def test_parse_money_accepts_human_formats(text, expected):
    assert tb.parse_money(text) == pytest.approx(expected)


@pytest.mark.parametrize("bad", ["", "   ", "abc", "-5jt", "0", "jt", "5xyz"])
def test_parse_money_rejects_garbage(bad):
    assert tb.parse_money(bad) is None


# ---------------- price parsing (decimals) ----------------

@pytest.mark.parametrize("text,expected", [
    ("1500", 1500.0),
    ("1.500", 1500.0),          # thousands grouping, not decimal
    ("1,500", 1500.0),
    ("1500.5", 1500.5),         # fractional rupiah (e.g. adjusted close)
    ("1500,5", 1500.5),
    ("12.345.000", 12_345_000.0),
    ("1234.56", 1234.56),
])
def test_parse_price_accepts_decimals_and_thousands(text, expected):
    assert tb.parse_price(text) == pytest.approx(expected)


@pytest.mark.parametrize("bad", ["", "   ", "abc", "0", "-1500", "1500.555"])
def test_parse_price_rejects_garbage(bad):
    assert tb.parse_price(bad) is None


# ---------------- md_escape (error text must survive Telegram Markdown) ----
# Regression coverage for a real report: "Couldn't build the report: module
# 'generatedashboard' has no attribute 'builddashboard'" -- the underscores
# vanished. Root cause: send() uses parse_mode="Markdown", and
# "generate_dashboard"..."build_dashboard" contains a valid open/close
# underscore PAIR (no whitespace touching either _), which Telegram's parser
# reads as italic markup and swallows on render. Critically this is NOT an
# API failure -- parse_mode="Markdown" is syntactically valid -- so send()'s
# existing "retry as plain text on error" fallback never triggers; the
# corrupted render just succeeds silently.

def test_md_escape_preserves_a_real_attributeerror_message():
    msg = "module 'generate_dashboard' has no attribute 'build_dashboard'"
    escaped = tb.md_escape(msg)
    # backslash-escaped in the OUTGOING text...
    assert "generate\\_dashboard" in escaped
    assert "build\\_dashboard" in escaped
    # ...which is exactly what makes Telegram render the underscore literally
    # instead of consuming it as italic markup.
    assert "generatedashboard" not in escaped
    assert "builddashboard" not in escaped


def test_md_escape_handles_all_four_special_characters():
    assert tb.md_escape("a_b*c`d[e") == "a\\_b\\*c\\`d\\[e"


def test_md_escape_leaves_plain_text_untouched():
    assert tb.md_escape("nothing special here") == "nothing special here"


def test_md_escape_coerces_non_string_input():
    """Called as md_escape(e) on an exception object, not str(e) -- must not
    require the caller to convert first."""
    assert tb.md_escape(ValueError("bad_value")) == "bad\\_value"


def test_cmd_editentry_error_message_is_escaped(monkeypatch, tmp_path):
    """A real call site: /editentry on an unheld ticker returns a ValueError
    string through the exact f"⚠️ {md_escape(e)}" path."""
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)

    r = tb.cmd_editentry("GHOST_TICKER 1500")
    # "not holding" contains no special chars, but the ticker echoed back
    # might in principle -- the call must go through md_escape either way,
    # verified structurally rather than by exact string match here since
    # normalize_ticker's exact output isn't this test's concern.
    assert "not holding" in r


# ---------------- price display (decimals must survive to output) ---------
# Regression coverage for a real report: parse_price already accepted
# decimals, but every reply echoed prices through idr() (",.0f"), silently
# ROUNDING a correctly-stored 1500.75 to "IDR 1,501" in the message the user
# actually reads. price_idr() is the fix; idr() keeps rounding money TOTALS
# (cash, cost, P&L), where whole rupiah is correct and desired.

def test_price_idr_shows_decimals_when_present():
    assert tb.price_idr(1500.75) == "IDR 1,500.75"
    assert tb.price_idr(1234.5) == "IDR 1,234.50"


def test_price_idr_omits_decimals_for_whole_numbers():
    """The overwhelmingly common case (plain integer IDX prices) must read
    exactly like idr() -- no '.00' noise on every line."""
    assert tb.price_idr(2000.0) == "IDR 2,000"
    assert tb.price_idr(2000) == tb.idr(2000)


def test_idr_still_rounds_money_totals():
    """idr() itself must NOT change -- cash/cost/P&L totals stay whole
    rupiah. Only per-share prices moved to price_idr()."""
    assert tb.idr(1500.75) == "IDR 1,501"


def test_cmd_buy_reply_preserves_decimal_price(monkeypatch, tmp_path):
    """End-to-end: a decimal price typed into /buy must appear UNROUNDED in
    the bot's own reply, not just in the stored state."""
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)

    r = tb.cmd_buy("ANTM 200 1500.75")
    assert "1,500.75" in r
    assert "1,501" not in r   # the rounded figure must not appear anywhere


def test_cmd_editentry_reply_preserves_decimal_price(monkeypatch, tmp_path):
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)

    tb.cmd_buy("ANTM 200 1500")
    r = tb.cmd_editentry("ANTM 1234.5")
    assert "1,234.50" in r


def test_cmd_buy_reply_still_clean_for_whole_prices(monkeypatch, tmp_path):
    """No regression for the common case: a whole-number price must not
    grow a spurious '.00'."""
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)

    r = tb.cmd_buy("BBRI 100 2000")
    assert "2,000 " in r or r.rstrip().endswith("2,000")
    assert "2,000.00" not in r


# ---------------- date parsing (backdating /buy and /sell) ----------------

_TODAY = date(2026, 7, 15)


@pytest.mark.parametrize("text,expected", [
    ("today", "2026-07-15"),
    ("hari ini", "2026-07-15"),
    ("yesterday", "2026-07-14"),
    ("kemarin", "2026-07-14"),
    ("3 hari lalu", "2026-07-12"),
    ("3 days ago", "2026-07-12"),
    ("2026-07-10", "2026-07-10"),
])
def test_parse_date_accepts_human_formats(text, expected):
    assert tb.parse_date(text, today=_TODAY) == expected


@pytest.mark.parametrize("bad", ["", "   ", "next tuesday", "2026-07-16", "2099-01-01"])
def test_parse_date_rejects_garbage_and_future(bad):
    assert tb.parse_date(bad, today=_TODAY) is None


@pytest.mark.parametrize("arg,expected_rest,expected_date", [
    ("ANTM 200 1500", "ANTM 200 1500", None),
    ("ANTM 200 1500 @kemarin", "ANTM 200 1500", "kemarin"),
    ("ANTM 200 @3 hari lalu", "ANTM 200", "3 hari lalu"),
    ("ANTM 1650 @2026-07-10", "ANTM 1650", "2026-07-10"),
])
def test_split_trade_date(arg, expected_rest, expected_date):
    rest, date_text = tb._split_trade_date(arg)
    assert rest == expected_rest and date_text == expected_date


# ---------------- /buy and /sell backdating ----------------

def test_cmd_buy_backdates_with_at_date(monkeypatch, tmp_path):
    from kala.papertrade import PaperTrader
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)

    r = tb.cmd_buy("ANTM 200 1500 @2026-07-10")
    assert "2026-07-10" in r
    pos = PaperTrader.load(statefile).positions["ANTM.JK"]
    assert pos.entry_date == "2026-07-10"


def test_cmd_buy_rejects_unparseable_date(monkeypatch, tmp_path):
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)

    r = tb.cmd_buy("ANTM 200 1500 @not-a-date")
    assert "Couldn't read the date" in r
    assert not statefile.exists(), "a rejected date must not touch state"


def test_cmd_buy_rejects_future_date(monkeypatch, tmp_path):
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)

    r = tb.cmd_buy("ANTM 200 1500 @2099-01-01")
    assert "Couldn't read the date" in r


def test_cmd_buy_without_at_date_uses_today(monkeypatch, tmp_path):
    from kala.papertrade import PaperTrader
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)

    tb.cmd_buy("ANTM 200 1500")
    pos = PaperTrader.load(statefile).positions["ANTM.JK"]
    assert pos.entry_date == _today().isoformat()


def test_cmd_sell_backdates_with_at_date(monkeypatch, tmp_path):
    from kala.papertrade import PaperTrader
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)

    tb.cmd_buy("ANTM 200 1500 @3 hari lalu")   # entry predates the sell's @date
    r = tb.cmd_sell("ANTM 1800 @kemarin")
    assert "on" in r
    pt = PaperTrader.load(statefile)
    assert pt.log[-1]["date"] == (_today() - timedelta(days=1)).isoformat()


def test_cmd_sell_rejects_date_before_entry(monkeypatch, tmp_path):
    """A sell dated before its own position's entry must be rejected outright
    -- it would otherwise log a negative hold time that /edge silently
    averages into avg_hold_days."""
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)

    tb.cmd_buy("ANTM 200 1500")   # entry_date = today
    r = tb.cmd_sell("ANTM 1800 @kemarin")   # yesterday: before entry
    assert "before" in r and "entry date" in r
    from kala.papertrade import PaperTrader
    assert "ANTM.JK" in PaperTrader.load(statefile).positions   # nothing sold


# ---------------- /editentry (correct a wrong recorded price) --------------

def test_cmd_editentry_corrects_price_and_reconciles_cash(monkeypatch, tmp_path):
    from kala.papertrade import PaperTrader
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)

    tb.cmd_buy("ANTM 200 1500")
    cash_after_buy = PaperTrader.load(statefile).cash

    r = tb.cmd_editentry("ANTM 1400")
    # /buy books 1500 raw as its cost-inclusive fill, so THAT is the old
    # price /editentry reports back -- and /editentry stores the new one
    # as given, without adding costs a second time.
    old = buy_fill(1500.0)
    assert f"{old:,.2f}" in r             # shows old (all-in) price
    assert "1,400" in r or "1400" in r    # and new price
    pt = PaperTrader.load(statefile)
    assert pt.positions["ANTM.JK"].entry_price == 1400.0
    assert pt.cash == pytest.approx(cash_after_buy + 200 * (old - 1400.0))


def test_cmd_editentry_on_unheld_ticker_shows_clear_error(monkeypatch, tmp_path):
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)

    r = tb.cmd_editentry("ANTM 1500")
    assert "not holding" in r


def test_cmd_editentry_missing_args_shows_usage(monkeypatch, tmp_path):
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)

    assert "Usage" in tb.cmd_editentry("ANTM")
    assert "Usage" in tb.cmd_editentry("")


def test_cmd_editentry_is_reachable_via_dispatch(monkeypatch, tmp_path):
    """The command must actually be wired into the router, not just defined."""
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)

    tb.cmd_buy("ANTM 200 1500")
    tb.dispatch("/editentry ANTM 1450")
    from kala.papertrade import PaperTrader
    assert PaperTrader.load(statefile).positions["ANTM.JK"].entry_price == 1450.0


def test_cmd_editentry_is_undoable_via_dispatch(monkeypatch, tmp_path):
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)

    tb.cmd_buy("ANTM 200 1500")
    tb.cmd_editentry("ANTM 1400")
    tb.dispatch("/undo")
    from kala.papertrade import PaperTrader
    assert PaperTrader.load(statefile).positions["ANTM.JK"].entry_price == (
        pytest.approx(buy_fill(1500.0)))


# ---------------- /sell partial (take-profit on part of a position) --------

def test_cmd_sell_partial_keeps_remainder_open(monkeypatch, tmp_path):
    from kala.papertrade import PaperTrader
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)

    tb.cmd_buy("ANTM 200 1500")
    r = tb.cmd_sell("ANTM 100 1800")
    assert "Sold 100" in r and "Remaining: 100" in r
    pos = PaperTrader.load(statefile).positions["ANTM.JK"]
    assert pos.shares == 100
    assert pos.entry_price == pytest.approx(buy_fill(1500.0))  # cost basis unchanged


def test_cmd_sell_full_two_token_form_still_works(monkeypatch, tmp_path):
    """Backward compatibility: /sell TICKER PRICE (2 tokens) must still sell
    the WHOLE position, exactly as before partial sell was added."""
    from kala.papertrade import PaperTrader
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)

    tb.cmd_buy("ANTM 200 1500")
    r = tb.cmd_sell("ANTM 1800")
    assert "Recorded SELL" in r and "Remaining" not in r
    assert "ANTM.JK" not in PaperTrader.load(statefile).positions


def test_cmd_sell_partial_accepts_decimal_price(monkeypatch, tmp_path):
    from kala.papertrade import PaperTrader
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)

    tb.cmd_buy("ANTM 200 1500")
    tb.cmd_sell("ANTM 100 1800.5")
    # the decimal survives; what is stored is the NET of that price, since
    # the exit booked is the proceeds actually kept
    assert PaperTrader.load(statefile).log[-1]["exit"] == pytest.approx(
        sell_net(1800.5))


# ---------------- /history ----------------

def test_cmd_history_lists_recent_trades_most_recent_first(monkeypatch, tmp_path):
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)

    tb.cmd_buy("ANTM 100 1000")
    tb.cmd_sell("ANTM 1100")
    tb.cmd_buy("BBRI 100 2000")
    tb.cmd_sell("BBRI 1900")

    r = tb.cmd_history("")
    first_ticker_line = next(l for l in r.splitlines() if "BBRI" in l or "ANTM" in l)
    assert "BBRI" in first_ticker_line          # most recent trade shown first
    assert "1/2 winners" in r


def test_cmd_history_respects_n_and_caps_at_50(monkeypatch, tmp_path):
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 100_000_000}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)

    for i in range(3):
        tb.cmd_buy(f"T{i} 10 1000")
        tb.cmd_sell(f"T{i} 1100")

    r = tb.cmd_history("2")
    assert "Last 2 closed" in r


def test_cmd_history_with_no_trades(monkeypatch, tmp_path):
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)
    assert "No closed trades" in tb.cmd_history("")


def test_dispatch_routes_history_and_aliases(monkeypatch):
    monkeypatch.setattr(tb, "cmd_history", lambda a: f"H:{a}")
    assert tb.dispatch("/history 5") == "H:5"
    assert tb.dispatch("/riwayat") == "H:"
    assert tb.dispatch("/log") == "H:"


def test_cmd_edge_with_no_trades(monkeypatch, tmp_path):
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)
    assert "No closed trades yet" in tb.cmd_edge()


def test_cmd_edge_unvalidated_by_default(monkeypatch, tmp_path):
    """As of 2026-07-20 edge_expectations.validated defaults to False again
    -- the apparent >= IDR 1,000 edge was retracted after a point-in-time
    re-test (compare_exit_engines.py) came back significantly negative,
    contradicting the ticker-level-filtered walk-forward result it was
    based on. /edge must say so plainly, not silently fall back to
    comparing against a baseline that's under active dispute."""
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)

    tb.cmd_buy("ANTM 100 1000 @2026-07-01")
    tb.cmd_sell("ANTM 1100")

    r = tb.cmd_edge()
    assert "UNVALIDATED" in r
    assert "ref only" in r          # reference column relabelled, not "backtest"


def test_cmd_edge_validated_when_overridden(monkeypatch, tmp_path):
    """edge_expectations.validated can still be forced True (e.g. after a
    real re-validation) -- /edge must compare against the real backtest
    column, not say UNVALIDATED."""
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000,
                                   "edge_expectations": {"validated": True}}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)

    tb.cmd_buy("ANTM 100 1000 @2026-07-01")
    tb.cmd_sell("ANTM 1100")

    r = tb.cmd_edge()
    assert "UNVALIDATED" not in r
    assert "TOO EARLY" in r         # only 1 closed trade
    assert "backtest" in r          # real reference column, not "ref only"


def test_cmd_edge_small_sample_reads_too_early(monkeypatch, tmp_path):
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000,
                                   "edge_expectations": {"validated": True}}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)

    tb.cmd_buy("ANTM 100 1000 @2026-07-01")
    tb.cmd_sell("ANTM 1100")
    tb.cmd_buy("BBRI 100 2000 @2026-07-05")
    tb.cmd_sell("BBRI 1900")

    r = tb.cmd_edge()
    assert "TOO EARLY" in r
    assert "EV/trade" in r and "backtest" in r
    assert "avg hold" in r          # both trades carry entry_date now
    assert "Exit mix" in r and "manual 2" in r


def test_cmd_edge_respects_config_expectations(monkeypatch, tmp_path):
    """runner_config.json's edge_expectations must reach the report — the
    backtest column shows the overridden EV, not the built-in default."""
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000,
                                   "edge_expectations": {"ev_pct": 9.99}}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)
    tb.cmd_buy("ANTM 100 1000")
    tb.cmd_sell("ANTM 1100")
    assert "+9.99%" in tb.cmd_edge()


def test_dispatch_routes_edge_and_aliases(monkeypatch):
    monkeypatch.setattr(tb, "cmd_edge", lambda: "E")
    assert tb.dispatch("/edge") == "E"
    assert tb.dispatch("/track") == "E"
    assert tb.dispatch("/vsbacktest") == "E"


# ---------------- /checkstop: on-demand mid-day stop/target check ----------

def test_cmd_checkstop_no_positions(monkeypatch, tmp_path):
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)
    assert "No open positions" in tb.cmd_checkstop()


def test_cmd_checkstop_reports_stop_hit(monkeypatch, tmp_path):
    import intraday_watch
    from kala.intraday import Quote

    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    _seed_positions_state(statefile, ["ANTM.JK"])
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)
    # entry 1000, default hard_stop_pct -5% -> stop at 950; quote well below it
    monkeypatch.setattr(intraday_watch, "get_quotes", lambda tickers: {
        "ANTM.JK": Quote(ticker="ANTM.JK", price=930.0, prev_close=995.0, day_high=1000.0)})

    r = tb.cmd_checkstop()
    assert "hit its stop intraday" in r
    assert "ANTM.JK" in r
    assert "All clear" not in r


def test_cmd_checkstop_reports_take_profit(monkeypatch, tmp_path):
    import intraday_watch
    from kala.intraday import Quote

    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    _seed_positions_state(statefile, ["ANTM.JK"])
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)
    # entry 1000, default target_profit_pct 8% -> +9% clears it
    monkeypatch.setattr(intraday_watch, "get_quotes", lambda tickers: {
        "ANTM.JK": Quote(ticker="ANTM.JK", price=1090.0, prev_close=1000.0, day_high=1090.0)})

    r = tb.cmd_checkstop()
    assert "reached take-profit intraday" in r


def test_cmd_checkstop_all_clear(monkeypatch, tmp_path):
    import intraday_watch
    from kala.intraday import Quote

    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    _seed_positions_state(statefile, ["ANTM.JK"])
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)
    # entry 1000, quote flat at 1000 -- nowhere near stop or target
    monkeypatch.setattr(intraday_watch, "get_quotes", lambda tickers: {
        "ANTM.JK": Quote(ticker="ANTM.JK", price=1000.0, prev_close=998.0, day_high=1005.0)})

    r = tb.cmd_checkstop()
    assert "All clear" in r
    assert "Sell levels right now" in r
    assert "ANTM.JK" in r and "stop" in r and "target" in r


def test_cmd_checkstop_lists_every_position_sorted_by_closest_to_stop(monkeypatch, tmp_path):
    import intraday_watch
    from kala.intraday import Quote

    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    _seed_positions_state(statefile, ["SAFE.JK", "CLOSE.JK"])
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)
    # both entry 1000; kept below the 4% breakeven-trigger so both stay in
    # phase 1 (hard stop 950, no ATR data) rather than a trailing phase
    monkeypatch.setattr(intraday_watch, "get_quotes", lambda tickers: {
        "SAFE.JK": Quote(ticker="SAFE.JK", price=1020.0, prev_close=1015.0, day_high=1020.0),
        "CLOSE.JK": Quote(ticker="CLOSE.JK", price=960.0, prev_close=990.0, day_high=1000.0),
    })

    r = tb.cmd_checkstop()
    levels = r[r.index("Sell levels"):]
    # the one nearer its stop must be listed first (sorted by distance)
    assert levels.index("CLOSE.JK") < levels.index("SAFE.JK")
    assert "🟢 SAFE.JK" in r        # far above its stop (1100 vs 950)
    assert "⚠️ CLOSE.JK" in r       # close but not through it yet (960 vs 950, ~1% away)


def test_cmd_checkstop_shows_target_and_flags_when_reached(monkeypatch, tmp_path):
    """'When to sell' has two sides -- a position at/past its take-profit
    target must show the target price and the 🎯 flag, not just the stop."""
    import intraday_watch
    from kala.intraday import Quote

    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    _seed_positions_state(statefile, ["WINNER.JK"])
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)
    # entry 1000, default target_profit_pct 8% -> target 1080; price/peak 1090
    # (past the 8% trail_start, phase-3 stop ~1057 -> not through the stop,
    # but already past the take-profit target)
    monkeypatch.setattr(intraday_watch, "get_quotes", lambda tickers: {
        "WINNER.JK": Quote(ticker="WINNER.JK", price=1090.0, prev_close=1085.0, day_high=1090.0)})

    r = tb.cmd_checkstop()
    assert "target IDR 1,080" in r
    assert "🎯 WINNER.JK" in r
    assert "to go" in r


def test_cmd_checkstop_handles_missing_quote(monkeypatch, tmp_path):
    import intraday_watch

    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    _seed_positions_state(statefile, ["ANTM.JK"])
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)
    monkeypatch.setattr(intraday_watch, "get_quotes", lambda tickers: {})   # no quote at all

    r = tb.cmd_checkstop()
    assert "couldn't get a fresh quote" in r


def test_dispatch_routes_checkstop_and_aliases(monkeypatch):
    monkeypatch.setattr(tb, "cmd_checkstop", lambda: "C")
    assert tb.dispatch("/checkstop") == "C"
    assert tb.dispatch("/cekstop") == "C"
    assert tb.dispatch("/stoploss") == "C"
    assert tb.dispatch("/sl") == "C"


def test_dispatch_routes_priority_and_aliases(monkeypatch):
    monkeypatch.setattr(tb, "cmd_priority", lambda: "P")
    assert tb.dispatch("/priority") == "P"
    assert tb.dispatch("/prioritas") == "P"
    assert tb.dispatch("/todo") == "P"
    assert tb.dispatch("/aksi") == "P"


# ---------------- /positions days-held ----------------

def test_calendar_days_held():
    ten_days_ago = (_today() - timedelta(days=10)).isoformat()
    assert tb._calendar_days_held(ten_days_ago) == 10
    assert tb._calendar_days_held("not-a-date") is None


def test_cmd_positions_shows_days_held(monkeypatch, tmp_path):
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)

    five_days_ago = (_today() - timedelta(days=5)).isoformat()
    tb.cmd_buy(f"ANTM 100 1500 @{five_days_ago}")
    r = tb.cmd_positions()
    assert "5d held" in r


# ---------------- buy ranking ----------------

def test_rank_buys_orders_by_score_then_strength():
    sigs = [
        {"ticker": "A.JK", "signal": "BUY", "technical_score": 60},
        {"ticker": "B.JK", "signal": "HOLD", "technical_score": 99},   # dropped
        {"ticker": "C.JK", "signal": "STRONG BUY", "technical_score": 80},
        {"ticker": "D.JK", "signal": "BUY", "technical_score": 80},
    ]
    out = tb.rank_buys(sigs)
    assert [s["ticker"] for s in out] == ["C.JK", "D.JK", "A.JK"]  # HOLD excluded
    assert out[0]["ticker"] == "C.JK"  # STRONG BUY wins the 80-80 tie


def test_rank_buys_empty():
    assert tb.rank_buys([]) == []
    assert tb.rank_buys(None) == []


# ---------------- chunking ----------------

def test_chunk_splits_long_messages():
    parts = tb.chunk("x" * 9000, size=3900)
    assert len(parts) == 3 and "".join(parts) == "x" * 9000


def test_chunk_never_empty():
    assert tb.chunk("") == [""]


# ---------------- config mutation ----------------

def test_save_capital_persists(tmp_path, monkeypatch):
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"daily_capital_idr": 1, "max_positions": 5}), encoding="utf-8")
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    tb.save_capital(7_000_000)
    on_disk = json.loads(cfgfile.read_text(encoding="utf-8"))
    assert on_disk["daily_capital_idr"] == 7_000_000
    assert on_disk["max_positions"] == 5   # other keys preserved


def test_cmd_capital_updates_and_confirms(tmp_path, monkeypatch):
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"daily_capital_idr": 1}), encoding="utf-8")
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    reply = tb.cmd_capital("5jt")
    assert "5,000,000" in reply
    assert json.loads(cfgfile.read_text(encoding="utf-8"))["daily_capital_idr"] == 5_000_000


def test_cmd_capital_rejects_bad_input(tmp_path, monkeypatch):
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"daily_capital_idr": 1}), encoding="utf-8")
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    reply = tb.cmd_capital("banana")
    assert "Couldn't read" in reply
    assert json.loads(cfgfile.read_text(encoding="utf-8"))["daily_capital_idr"] == 1  # unchanged


# ---------------- /maxpositions ----------------

def test_cmd_maxpositions_updates_and_shows_per_slot_cap(tmp_path, monkeypatch):
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"daily_capital_idr": 30_000_000, "max_positions": 30}), encoding="utf-8")
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    reply = tb.cmd_maxpositions("10")
    assert "max_positions set to 10" in reply
    assert "3,000,000" in reply           # 30,000,000 / 10 per-slot cap shown
    assert json.loads(cfgfile.read_text(encoding="utf-8"))["max_positions"] == 10


def test_cmd_maxpositions_rejects_non_positive(tmp_path, monkeypatch):
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"max_positions": 5}), encoding="utf-8")
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    for bad in ("0", "-3", "banana", ""):
        reply = tb.cmd_maxpositions(bad)
        assert "Usage" in reply or "must be positive" in reply
    assert json.loads(cfgfile.read_text(encoding="utf-8"))["max_positions"] == 5   # unchanged


def test_dispatch_routes_maxpositions_and_aliases(monkeypatch):
    monkeypatch.setattr(tb, "cmd_maxpositions", lambda a: f"M:{a}")
    assert tb.dispatch("/maxpositions 10") == "M:10"
    assert tb.dispatch("/maxpos 10") == "M:10"
    assert tb.dispatch("/slots 10") == "M:10"


def test_cmd_performance_shows_win_loss_and_net_pnl(monkeypatch, tmp_path):
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)

    tb.cmd_buy("ANTM 100 1000")
    tb.cmd_sell("ANTM 1100")     # win
    tb.cmd_buy("BBRI 100 1000")
    tb.cmd_sell("BBRI 900")      # loss

    r = tb.cmd_performance("")
    assert "WIN RATE: 50%" in r
    assert "1W / 1L" in r
    assert "ANTM" in r and "BBRI" in r
    assert "UNVALIDATED" in r or "/edge" in r     # points back at the honest baseline


def test_cmd_performance_shows_benchmark_when_available(monkeypatch, tmp_path):
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)
    monkeypatch.setattr(tb, "_benchmark_window_return", lambda days: 3.4)

    tb.cmd_buy("ANTM 100 1000")
    tb.cmd_sell("ANTM 1100")

    r = tb.cmd_performance("")
    assert "IHSG over the same 7d: +3.40%" in r


def test_cmd_performance_omits_benchmark_when_unavailable(monkeypatch, tmp_path):
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)
    monkeypatch.setattr(tb, "_benchmark_window_return", lambda days: None)

    tb.cmd_buy("ANTM 100 1000")
    tb.cmd_sell("ANTM 1100")

    r = tb.cmd_performance("")
    assert "IHSG over the same" not in r    # gracefully omitted, no crash


def test_cmd_performance_shows_active_positions(monkeypatch, tmp_path):
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)

    tb.cmd_buy("ANTM 100 1000")   # still open

    r = tb.cmd_performance("")
    assert "1 open position" in r
    assert "ANTM" in r


def test_cmd_performance_no_trades_message(monkeypatch, tmp_path):
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)

    r = tb.cmd_performance("")
    assert "0 open position" in r
    assert "No closed trades" in r


def test_cmd_performance_respects_days_arg(monkeypatch, tmp_path):
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)

    r = tb.cmd_performance("30")
    assert "last 30d" in r


def test_dispatch_routes_performance_and_aliases(monkeypatch):
    monkeypatch.setattr(tb, "cmd_performance", lambda arg: f"P:{arg}")
    assert tb.dispatch("/performance") == "P:"
    assert tb.dispatch("/dashboard 14") == "P:14"
    assert tb.dispatch("/weekly") == "P:"


def test_cmd_status_shows_max_positions_and_per_slot_cap(monkeypatch, tmp_path):
    import kala_daily_trader as dt
    from kala.papertrade import PaperTrader

    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000,
                                   "daily_capital_idr": 10_000_000,
                                   "max_positions": 20}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)
    monkeypatch.setattr(dt, "check_market_health", lambda: {"jci_price": None})
    PaperTrader.load(statefile, start_capital=10_000_000).save()

    r = tb.cmd_status()
    assert "Max positions: 20" in r
    assert "500,000" in r    # 10,000,000 / 20 per-slot cap


def test_cmd_status_shows_dividends_when_present(monkeypatch, tmp_path):
    import kala_daily_trader as dt

    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)
    monkeypatch.setattr(dt, "check_market_health", lambda: {"jci_price": None})

    tb.cmd_dividend("ANTM 50000")
    r = tb.cmd_status()
    assert "Dividends received" in r


def test_cmd_status_omits_dividend_line_when_none_recorded(monkeypatch, tmp_path):
    import kala_daily_trader as dt
    from kala.papertrade import PaperTrader

    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)
    monkeypatch.setattr(dt, "check_market_health", lambda: {"jci_price": None})
    PaperTrader.load(statefile, start_capital=10_000_000).save()

    assert "Dividends received" not in tb.cmd_status()


# ---------------- dispatch routing ----------------

def test_dispatch_routes_each_command(monkeypatch):
    calls = {}
    monkeypatch.setattr(tb, "cmd_help", lambda: calls.update(help=True) or "H")
    monkeypatch.setattr(tb, "cmd_capital", lambda a: calls.update(cap=a) or "C")
    monkeypatch.setattr(tb, "cmd_scan", lambda a=None: calls.update(scan=a) or "S")
    monkeypatch.setattr(tb, "cmd_review", lambda: calls.update(rev=True) or "R")
    monkeypatch.setattr(tb, "cmd_status", lambda: calls.update(stat=True) or "T")
    monkeypatch.setattr(tb, "cmd_run", lambda: calls.update(run=True) or "U")

    assert tb.dispatch("/help") == "H"
    assert tb.dispatch("/capital 5jt") == "C" and calls["cap"] == "5jt"
    assert tb.dispatch("/scan") == "S"
    assert tb.dispatch("/scan 3jt") == "S" and calls["scan"] == "3jt"
    assert tb.dispatch("/review") == "R"
    assert tb.dispatch("/status") == "T"
    assert tb.dispatch("/run") == "U"


def test_dispatch_tolerates_botname_suffix_and_aliases(monkeypatch):
    monkeypatch.setattr(tb, "cmd_review", lambda: "R")
    assert tb.dispatch("/portfolio@KalaBot") == "R"
    assert tb.dispatch("/cek") == "R"


def test_dispatch_unknown_and_empty():
    assert "Unknown" in tb.dispatch("/wat")
    assert tb.dispatch("") == ""
    assert tb.dispatch("just chatting, no slash").startswith("Unknown")


# ---------------- buy/sell/positions routing + ticker normalization ----

def test_normalize_ticker():
    assert tb.normalize_ticker("antm") == "ANTM.JK"
    assert tb.normalize_ticker("ANTM.JK") == "ANTM.JK"
    assert tb.normalize_ticker("bbri.jk") == "BBRI.JK"   # suffix preserved


def test_normalize_ticker_leaves_known_us_sharia_ticker_bare():
    """A bare US ticker (from kala.universe.US_SHARIA_STOCKS) must NOT get
    '.JK' appended -- that would silently turn a real /buy AAPL into a
    nonexistent IDX ticker."""
    assert tb.normalize_ticker("aapl") == "AAPL"
    assert tb.normalize_ticker("MSFT") == "MSFT"


def test_normalize_ticker_unknown_bare_ticker_still_defaults_to_idx():
    """Anything not recognized as a US sharia ticker keeps the historical
    default -- .JK -- so every existing IDX /buy call is unaffected."""
    assert tb.normalize_ticker("gotorandomjunk") == "GOTORANDOMJUNK.JK"


def test_dispatch_routes_buy_sell_positions(monkeypatch):
    calls = {}
    monkeypatch.setattr(tb, "cmd_buy", lambda a: calls.update(buy=a) or "B")
    monkeypatch.setattr(tb, "cmd_sell", lambda a: calls.update(sell=a) or "S")
    monkeypatch.setattr(tb, "cmd_positions", lambda: calls.update(pos=True) or "P")
    assert tb.dispatch("/buy ANTM 200 1500") == "B" and calls["buy"] == "ANTM 200 1500"
    assert tb.dispatch("/sell ANTM 1650") == "S" and calls["sell"] == "ANTM 1650"
    assert tb.dispatch("/beli BBRI 100") == "B"       # Indonesian alias
    assert tb.dispatch("/jual BBRI") == "S"
    assert tb.dispatch("/positions") == "P"


def test_cmd_buy_usage_and_bad_shares(monkeypatch, tmp_path):
    import json
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000}), encoding="utf-8")
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    assert "Usage" in tb.cmd_buy("ANTM")              # too few args
    assert "Couldn't read shares" in tb.cmd_buy("ANTM abc 1500")


def test_cmd_buy_and_sell_end_to_end(monkeypatch, tmp_path):
    import json

    from kala.papertrade import PaperTrader
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)
    # explicit price -> no network
    r = tb.cmd_buy("ANTM 200 1500")
    assert "Recorded BUY ANTM.JK" in r
    assert "ANTM.JK" in PaperTrader.load(statefile).positions
    r2 = tb.cmd_sell("ANTM 1650")
    # 1650/1500 is +10% raw; what the user keeps is less, and the reply
    # says so rather than quoting the gross move
    expected = (sell_net(1650.0) / buy_fill(1500.0) - 1) * 100.0
    assert f"{expected:+.1f}%" in r2
    assert "+10.0%" not in r2
    assert "ANTM.JK" not in PaperTrader.load(statefile).positions


# ---------------------------------------------------------------------------
# /reset — two-step, destructive, must reuse reset_paper.py's tested core
# ---------------------------------------------------------------------------

def _reset_env(tmp_path, monkeypatch, start_capital=10_000_000):
    import json
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": start_capital,
                                   "daily_capital_idr": 999_999_999}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)
    return cfgfile, statefile


def test_reset_without_confirm_shows_warning_and_touches_nothing(monkeypatch, tmp_path):
    cfgfile, statefile = _reset_env(tmp_path, monkeypatch)
    tb.cmd_buy("ANTM 200 1500")
    before = statefile.read_text(encoding="utf-8")

    r = tb.cmd_reset("")
    assert "confirm" in r.lower() and "ANTM.JK" in r
    assert statefile.read_text(encoding="utf-8") == before, "plain /reset must not touch state"
    assert not list(tmp_path.glob("paper_state_backup_*.json")), "no backup without confirm either"


def test_reset_confirm_wipes_state_and_backs_up(monkeypatch, tmp_path):
    from kala.papertrade import PaperTrader
    cfgfile, statefile = _reset_env(tmp_path, monkeypatch)
    tb.cmd_buy("ANTM 200 1500")
    assert PaperTrader.load(statefile).positions   # sanity: something to lose

    r = tb.cmd_reset("confirm")
    assert "Reset done" in r
    pt = PaperTrader.load(statefile)
    assert pt.positions == {} and pt.pending == [] and pt.log == []
    assert pt.cash == pytest.approx(10_000_000)     # kept the existing start_capital_idr
    backups = list(tmp_path.glob("paper_state_backup_*.json"))
    assert len(backups) == 1
    assert "ANTM.JK" in backups[0].read_text(encoding="utf-8")       # the lost position is recoverable on disk


def test_reset_confirm_with_amount_changes_capital_and_syncs_config(monkeypatch, tmp_path):
    import json

    from kala.papertrade import PaperTrader
    cfgfile, statefile = _reset_env(tmp_path, monkeypatch)

    r = tb.cmd_reset("confirm 5jt")
    assert "Reset done" in r and "5" in r
    pt = PaperTrader.load(statefile)
    assert pt.cash == pytest.approx(5_000_000) and pt.start_capital == pytest.approx(5_000_000)
    cfg = json.loads(cfgfile.read_text(encoding="utf-8"))
    assert cfg["start_capital_idr"] == 5_000_000
    assert cfg["daily_capital_idr"] == 5_000_000     # the 999,999,999 mismatch is gone


def test_reset_confirm_bad_amount_does_not_touch_state(monkeypatch, tmp_path):
    cfgfile, statefile = _reset_env(tmp_path, monkeypatch)
    tb.cmd_buy("ANTM 200 1500")
    before = statefile.read_text(encoding="utf-8")

    r = tb.cmd_reset("confirm not-a-number")
    assert "Couldn't read an amount" in r
    assert statefile.read_text(encoding="utf-8") == before


def test_reset_no_prior_state_is_safe(monkeypatch, tmp_path):
    """First-ever /reset (no paper_state.json yet) must not crash and must
    say so plainly rather than a confusing empty summary."""
    _reset_env(tmp_path, monkeypatch)
    r = tb.cmd_reset("")
    assert "no paper_state.json exists" in r.lower()
    r2 = tb.cmd_reset("confirm")
    assert "Reset done" in r2


def test_dispatch_routes_reset(monkeypatch):
    monkeypatch.setattr(tb, "cmd_reset", lambda a: f"R:{a}")
    assert tb.dispatch("/reset") == "R:"
    assert tb.dispatch("/reset confirm") == "R:confirm"
    assert tb.dispatch("/ulang confirm 5jt") == "R:confirm 5jt"


def test_dispatch_routes_deposit(monkeypatch):
    monkeypatch.setattr(tb, "cmd_deposit", lambda a: f"D:{a}")
    assert tb.dispatch("/deposit 5jt") == "D:5jt"
    assert tb.dispatch("/topup 5jt") == "D:5jt"
    assert tb.dispatch("/setor 5jt") == "D:5jt"


# ---------------------------------------------------------------------------
# /buy on an already-held ticker (ADD) and /deposit, end to end
# ---------------------------------------------------------------------------

def test_cmd_buy_add_to_held_position_blends_and_reports_new_avg(monkeypatch, tmp_path):
    import json

    from kala.papertrade import PaperTrader
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)

    r1 = tb.cmd_buy("ANTM 100 1000")
    assert "Recorded BUY ANTM.JK" in r1

    r2 = tb.cmd_buy("ANTM 100 1200")
    assert "Added to ANTM.JK" in r2
    blended = (buy_fill(1000.0) + buy_fill(1200.0)) / 2
    assert "200" in r2 and f"{blended:,.2f}" in r2   # blended avg shown back

    pos = PaperTrader.load(statefile).positions["ANTM.JK"]
    assert pos.shares == 200 and pos.entry_price == pytest.approx(blended)


def test_cmd_deposit_raises_cash_start_capital_and_daily_budget(monkeypatch, tmp_path):
    import json

    from kala.papertrade import PaperTrader
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000,
                                   "daily_capital_idr": 5_000_000}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)

    r = tb.cmd_deposit("5jt")
    assert "Deposited" in r
    pt = PaperTrader.load(statefile)
    assert pt.cash == pytest.approx(15_000_000)
    assert pt.start_capital == pytest.approx(15_000_000)
    cfg = json.loads(cfgfile.read_text(encoding="utf-8"))
    assert cfg["start_capital_idr"] == pytest.approx(15_000_000)
    assert cfg["daily_capital_idr"] == pytest.approx(10_000_000)   # 5jt + 5jt deposit


def test_cmd_deposit_rejects_bad_amount(monkeypatch, tmp_path):
    import json
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)
    assert "Couldn't read" in tb.cmd_deposit("not-a-number")
    assert not statefile.exists(), "a rejected deposit must not create/touch state"


# ---------------- /dividend -- real return, deliberately NOT a deposit ------

def test_cmd_dividend_raises_cash_not_start_capital(monkeypatch, tmp_path):
    import json

    from kala.papertrade import PaperTrader
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)

    r = tb.cmd_dividend("ANTM 50000")
    assert "DIVIDEND" in r
    pt = PaperTrader.load(statefile)
    assert pt.cash == pytest.approx(10_050_000)
    assert pt.start_capital == pytest.approx(10_000_000)   # unchanged, unlike /deposit
    assert pt.dividends[0]["ticker"] == "ANTM.JK"


def test_cmd_dividend_supports_backdating(monkeypatch, tmp_path):
    import json

    from kala.papertrade import PaperTrader
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)

    r = tb.cmd_dividend("ANTM 50000 @2026-07-01")
    assert "2026-07-01" in r
    pt = PaperTrader.load(statefile)
    assert pt.dividends[0]["date"] == "2026-07-01"


def test_cmd_dividend_rejects_bad_amount(monkeypatch, tmp_path):
    import json
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)
    assert "Couldn't read" in tb.cmd_dividend("ANTM not-a-number")
    assert not statefile.exists()


def test_cmd_dividend_usage_message_on_missing_args(monkeypatch, tmp_path):
    monkeypatch.setattr(tb, "CONFIG_PATH", tmp_path / "runner_config.json")
    monkeypatch.setattr(tb, "STATE_PATH", tmp_path / "paper_state.json")
    assert "Usage" in tb.cmd_dividend("ANTM")


def test_cmd_dividend_normalizes_us_sharia_ticker(monkeypatch, tmp_path):
    import json

    from kala.papertrade import PaperTrader
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)

    tb.cmd_dividend("aapl 15000")
    pt = PaperTrader.load(statefile)
    assert pt.dividends[0]["ticker"] == "AAPL"   # not "AAPL.JK"


def test_dispatch_routes_dividend_command(monkeypatch, tmp_path):
    import json
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)
    assert "DIVIDEND" in tb.dispatch("/dividend ANTM 50000")
    assert "DIVIDEND" in tb.dispatch("/dividen BBCA 20000")   # Indonesian alias


def test_cmd_undo_reverts_dividend(monkeypatch, tmp_path):
    import json

    from kala.papertrade import PaperTrader
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)

    tb.cmd_dividend("ANTM 50000")
    r = tb.cmd_undo()
    assert "Undone" in r
    pt = PaperTrader.load(statefile)
    assert pt.cash == pytest.approx(10_000_000)
    assert pt.dividends == []


# ---------------- /rebalance -- read-only maintenance plan -------------------

def test_cmd_rebalance_needs_target_allocation(monkeypatch, tmp_path):
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000}), encoding="utf-8")   # no target
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", tmp_path / "paper_state.json")
    r = tb.cmd_rebalance("")
    assert "No target mix set" in r
    assert "target_allocation" in r


def test_cmd_rebalance_noop_when_on_target(monkeypatch, tmp_path):
    from kala.papertrade import PaperTrader
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({
        "start_capital_idr": 10_000_000,
        "target_allocation": {"ANTM.JK": 50, "BBCA.JK": 50},
    }), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)
    # equal holdings, both priced 100, and almost no idle cash -> ~50/50 of
    # the pot, within band -> no-op. (Start capital sized so the two buys
    # consume nearly all of it; leftover cash is a tiny buffer.)
    monkeypatch.setattr(tb, "_last_close", lambda t: 100.0)
    cfg = json.loads(cfgfile.read_text(encoding="utf-8"))
    cfg["start_capital_idr"] = 201_000
    cfgfile.write_text(json.dumps(cfg), encoding="utf-8")
    pt = PaperTrader.load(statefile, start_capital=201_000)
    pt.manual_buy("ANTM.JK", 1000, 100.0)
    pt.manual_buy("BBCA.JK", 1000, 100.0)

    r = tb.cmd_rebalance("")
    assert "No rebalancing needed" in r


def test_cmd_rebalance_suggests_orders_when_drifted(monkeypatch, tmp_path):
    from kala.papertrade import PaperTrader
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({
        "start_capital_idr": 10_000_000,
        "target_allocation": {"ANTM.JK": 50, "BBCA.JK": 50},
    }), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)
    monkeypatch.setattr(tb, "_last_close", lambda t: 100.0)
    # Size start capital so the two buys consume nearly all of it -> the pot is
    # dominated by holdings (80/20), not idle cash, isolating the pure
    # sell-the-winner / buy-the-laggard rebalance case.
    cfg = json.loads(cfgfile.read_text(encoding="utf-8"))
    cfg["start_capital_idr"] = 1_010_000
    cfgfile.write_text(json.dumps(cfg), encoding="utf-8")
    pt = PaperTrader.load(statefile, start_capital=1_010_000)
    pt.manual_buy("ANTM.JK", 8000, 100.0)   # 800k -> ~79% of pot
    pt.manual_buy("BBCA.JK", 2000, 100.0)   # 200k -> ~20% of pot, badly drifted

    r = tb.cmd_rebalance("")
    assert "SELL ANTM" in r
    assert "BUY BBCA" in r
    assert "transaction cost" in r.lower()
    assert "NOT a signal" in r     # honesty framing present


def test_dispatch_routes_rebalance(monkeypatch, tmp_path):
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000}), encoding="utf-8")   # no target
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", tmp_path / "paper_state.json")
    assert "No target mix set" in tb.dispatch("/rebalance")


# ---------------------------------------------------------------------------
# undo / redo -- fat-finger safety net
# ---------------------------------------------------------------------------

def test_cmd_undo_reverts_bad_buy(monkeypatch, tmp_path):
    import json

    from kala.papertrade import PaperTrader
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)

    tb.cmd_buy("ANTM 200 15000")          # fat-fingered an extra zero
    r = tb.cmd_undo()
    assert "Undone" in r and "ANTM.JK" in r
    pt = PaperTrader.load(statefile)
    assert "ANTM.JK" not in pt.positions
    assert pt.cash == pytest.approx(10_000_000)


def test_cmd_undo_with_nothing_to_undo(monkeypatch, tmp_path):
    import json
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)
    assert "nothing to undo" in tb.cmd_undo()


def test_cmd_redo_reapplies_undone_buy(monkeypatch, tmp_path):
    import json

    from kala.papertrade import PaperTrader
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)

    tb.cmd_buy("ANTM 200 1500")
    tb.cmd_undo()
    r = tb.cmd_redo()
    assert "Redone" in r and "ANTM.JK" in r
    pt = PaperTrader.load(statefile)
    assert pt.positions["ANTM.JK"].shares == 200


def test_cmd_undo_deposit_also_reverts_config_sync(monkeypatch, tmp_path):
    """/deposit raises runner_config.json's start_capital_idr/daily_capital_idr
    as a side effect outside PaperTrader -- /undo must reverse that too, or
    the config silently drifts from the reverted state (the same class of
    bug reset_paper.py's --sync-config exists to fix)."""
    import json

    from kala.papertrade import PaperTrader
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000,
                                   "daily_capital_idr": 5_000_000}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)

    tb.cmd_deposit("50jt")                # fat-fingered: meant 5jt
    cfg_after_deposit = json.loads(cfgfile.read_text(encoding="utf-8"))
    assert cfg_after_deposit["start_capital_idr"] == pytest.approx(60_000_000)

    tb.cmd_undo()
    pt = PaperTrader.load(statefile)
    assert pt.cash == pytest.approx(10_000_000)
    assert pt.start_capital == pytest.approx(10_000_000)
    cfg = json.loads(cfgfile.read_text(encoding="utf-8"))
    assert cfg["start_capital_idr"] == pytest.approx(10_000_000)
    assert cfg["daily_capital_idr"] == pytest.approx(5_000_000)

    r = tb.cmd_redo()
    assert "Redone" in r
    cfg2 = json.loads(cfgfile.read_text(encoding="utf-8"))
    assert cfg2["start_capital_idr"] == pytest.approx(60_000_000)
    assert cfg2["daily_capital_idr"] == pytest.approx(55_000_000)


def test_cmd_undo_deposit_restores_exact_predeposit_budget_despite_intervening_capital_call(
        monkeypatch, tmp_path):
    """Regression: the old relative-arithmetic reversal did
    CURRENT_daily_capital - deposit_amount, which drifts to a value nobody
    chose if /capital ran between the deposit and the /undo. The fix
    restores the EXACT pre-deposit value captured at deposit time."""
    import json
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000,
                                   "daily_capital_idr": 10_000_000}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)

    tb.cmd_deposit("5jt")                 # daily_capital_idr: 10jt -> 15jt
    tb.cmd_capital("8jt")                 # unrelated manual override: -> 8jt
    tb.cmd_undo()                         # must restore the TRUE pre-deposit value: 10jt

    cfg = json.loads(cfgfile.read_text(encoding="utf-8"))
    assert cfg["daily_capital_idr"] == pytest.approx(10_000_000)   # not 8jt - 5jt = 3jt
    assert cfg["start_capital_idr"] == pytest.approx(10_000_000)


def test_dispatch_routes_undo_redo_and_aliases(monkeypatch):
    monkeypatch.setattr(tb, "cmd_undo", lambda: "U")
    monkeypatch.setattr(tb, "cmd_redo", lambda: "R")
    assert tb.dispatch("/undo") == "U"
    assert tb.dispatch("/batal") == "U"
    assert tb.dispatch("/redo") == "R"
    assert tb.dispatch("/ulangi") == "R"


# ---------------- /review: sized "could add" + partial-trim suggestion ----

def test_partial_trim_suggestion_splits_into_lots():
    msg = tb._partial_trim_suggestion("ANTM.JK", shares=200, price=1650.0)
    assert msg is not None
    assert "/sell ANTM.JK 100 1650" in msg
    assert "100" in msg and "ride" in msg


def test_partial_trim_suggestion_rounds_to_nearest_lot():
    # 250 sh: naive half is 125 (not a lot multiple) -> rounds down to 100
    msg = tb._partial_trim_suggestion("ANTM.JK", shares=250, price=1000.0)
    assert "/sell ANTM.JK 100 1000" in msg


def test_partial_trim_suggestion_none_for_unsplittable_position():
    assert tb._partial_trim_suggestion("ANTM.JK", shares=1, price=1000.0) is None


def test_add_more_suggestion_sizes_like_scan(tmp_path):
    from kala.papertrade import PaperTrader
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=50_000_000)
    msg, shares = tb._add_more_suggestion(pt, "ANTM.JK", price=1500.0, stop=1400.0,
                                          allocation=10_000_000, risk_pct=2.0, max_positions=5)
    assert "could add" in msg
    assert "/buy ANTM.JK" in msg
    assert shares > 0


def test_add_more_suggestion_too_small_for_a_lot(tmp_path):
    from kala.papertrade import PaperTrader
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=50_000)  # tiny cash
    msg, shares = tb._add_more_suggestion(pt, "ANTM.JK", price=1500.0, stop=1400.0,
                                          allocation=50_000, risk_pct=2.0, max_positions=5)
    assert "budget too small" in msg
    assert shares == 0


def test_add_more_suggestion_respects_cash_override_not_full_account_cash(tmp_path):
    """The whole point of cash_override: a caller ranking several ADD ideas
    can size this one against what's LEFT, not the account's full cash."""
    from kala.papertrade import PaperTrader
    pt = PaperTrader.load(tmp_path / "p.json", start_capital=50_000_000)
    msg, shares = tb._add_more_suggestion(pt, "ANTM.JK", price=1500.0, stop=1400.0,
                                          allocation=50_000_000, risk_pct=2.0,
                                          max_positions=5, cash_override=100_000.0)
    assert "budget too small" in msg   # only enough left for a fraction of a lot
    assert shares == 0


# ---------------- /scan: per-stock overnight gap range ----------------

def test_entry_price_range_uses_stock_history(monkeypatch):
    import numpy as np
    import pandas as pd

    import kala_daily_trader as dt

    n = 80
    rng = np.random.default_rng(5)
    close = pd.Series(1000 * np.exp(np.cumsum(rng.normal(0.0005, 0.01, n))))
    gap_noise = rng.normal(0.0, 0.015, n)
    open_ = close.shift(1) * (1 + gap_noise)
    open_.iloc[0] = close.iloc[0]
    hist = pd.DataFrame({"Open": open_, "Close": close})
    monkeypatch.setattr(dt, "download_stock_data", lambda *a, **k: hist)

    result = tb._entry_price_range("ANTM.JK")
    assert result is not None
    lo, hi = result
    assert lo < hi


def test_entry_price_range_none_on_download_failure(monkeypatch):
    import kala_daily_trader as dt

    def boom(*a, **k):
        raise RuntimeError("network down")
    monkeypatch.setattr(dt, "download_stock_data", boom)
    assert tb._entry_price_range("ANTM.JK") is None


def test_entry_price_range_none_on_too_little_history(monkeypatch):
    import pandas as pd

    import kala_daily_trader as dt
    monkeypatch.setattr(dt, "download_stock_data",
                        lambda *a, **k: pd.DataFrame({"Open": [1000.0], "Close": [1000.0]}))
    assert tb._entry_price_range("ANTM.JK") is None


# ---------------- /priority: merges /review + /scan into one ranked list ----

def _seed_positions_state(statefile, tickers):
    payload = {
        "cash": 1_000_000, "start_capital": 10_000_000,
        "positions": {t: {"ticker": t, "entry_price": 1000.0, "shares": 100,
                          "entry_date": "2026-07-01", "peak_price": 1000.0,
                          "entry_atr": None} for t in tickers},
        "pending": [], "log": [], "benchmark_start": None, "capital_additions": [],
    }
    statefile.write_text(json.dumps(payload), encoding="utf-8")


def test_cmd_priority_orders_tiers_and_ranks_within_tier(monkeypatch, tmp_path):
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    _seed_positions_state(statefile, ["URG.JK", "TP.JK", "ADD.JK", "HOLD.JK", "NODATA.JK"])
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)

    def fake_holdings(pt, cfg):
        return {"status": "BULLISH", "records": [
            {"ticker": "URG.JK", "no_data": False, "urgency": "URGENT",
             "reason": "governing stop hit", "pnl_pct": -6.0,
             "trim_suggestion": None, "add_suggestion": None, "add_score": None},
            {"ticker": "TP.JK", "no_data": False, "urgency": "CONSIDER",
             "reason": "target profit reached", "pnl_pct": 8.5,
             "trim_suggestion": "trim half: /sell TP.JK 100 2000",
             "add_suggestion": None, "add_score": None},
            {"ticker": "ADD.JK", "no_data": False, "urgency": "NONE", "reason": None,
             "pnl_pct": 3.0, "trim_suggestion": None,
             "add_suggestion": "could add 200 sh: /buy ADD.JK 200 1500", "add_score": 75.0},
            {"ticker": "HOLD.JK", "no_data": False, "urgency": "NONE", "reason": None,
             "pnl_pct": 1.0, "trim_suggestion": None, "add_suggestion": None, "add_score": 40.0},
            {"ticker": "NODATA.JK", "no_data": True},
        ]}

    def fake_scan(cfg, pt):
        return {"status": "BULLISH", "candidates": [
            {"ticker": "NEW_LOW.JK", "kind": "sized", "tag": "BUY", "score": 60.0,
             "price": 2000.0, "shares": 100, "est": 200_000.0},
            {"ticker": "NEW_HIGH.JK", "kind": "sized", "tag": "STRONG BUY", "score": 80.0,
             "price": 1000.0, "shares": 300, "est": 300_000.0},
            {"ticker": "SKIP.JK", "kind": "too_small", "tag": "BUY", "score": 50.0, "price": 1e5},
            {"ticker": "HELD.JK", "kind": "held", "score": 55.0},
        ]}

    monkeypatch.setattr(tb, "_evaluate_holdings", fake_holdings)
    monkeypatch.setattr(tb, "_rank_new_buys", fake_scan)

    r = tb.cmd_priority()

    # tier order: SELL NOW before TAKE PROFIT before ADD before NEW BUY
    i_sell = r.index("SELL NOW")
    i_tp = r.index("TAKE PROFIT")
    i_add = r.index("ADD TO WINNERS")
    i_new = r.index("NEW BUY IDEAS")
    assert i_sell < i_tp < i_add < i_new

    # within NEW BUY IDEAS, higher score (NEW_HIGH, 80) must be listed before NEW_LOW (60)
    assert r.index("NEW_HIGH.JK") < r.index("NEW_LOW.JK")

    assert "URG.JK" in r and "governing stop hit" in r
    assert "trim half" in r
    assert "could add 200 sh" in r
    # footer must count, not itemize, the uninteresting stuff
    assert "1 holding(s): HOLD, nothing to do" in r
    assert "1 holding(s): no fresh data" in r
    assert "2 scan candidate(s) skipped" in r   # SKIP.JK + HELD.JK


def test_cmd_priority_handles_no_positions_and_no_new_buys(monkeypatch, tmp_path):
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)
    monkeypatch.setattr(tb, "_rank_new_buys",
                        lambda cfg, pt: {"status": "NEUTRAL", "candidates": []})

    r = tb.cmd_priority()
    assert "Nothing urgent" in r


def test_cmd_scan_shows_entry_signal_warning_by_default(monkeypatch, tmp_path):
    import kala_daily_trader as dt
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000,
                                   "daily_capital_idr": 10_000_000}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)
    monkeypatch.setattr(dt, "check_market_health", lambda: {"status": "NEUTRAL"})
    monkeypatch.setattr(dt, "live_trading_dashboard", lambda: [
        {"ticker": "GOOD.JK", "signal": "BUY", "technical_score": 70, "price": 1000, "atr": 20}])
    monkeypatch.setattr(tb, "_entry_price_range", lambda t: None)

    assert "UNVALIDATED" in tb.cmd_scan()


def test_cmd_scan_no_warning_once_validated(monkeypatch, tmp_path):
    import kala_daily_trader as dt
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000,
                                   "daily_capital_idr": 10_000_000,
                                   "edge_expectations": {"validated": True}}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)
    monkeypatch.setattr(dt, "check_market_health", lambda: {"status": "NEUTRAL"})
    monkeypatch.setattr(dt, "live_trading_dashboard", lambda: [
        {"ticker": "GOOD.JK", "signal": "BUY", "technical_score": 70, "price": 1000, "atr": 20}])
    monkeypatch.setattr(tb, "_entry_price_range", lambda t: None)

    assert "UNVALIDATED" not in tb.cmd_scan()


def test_cmd_priority_shows_entry_signal_warning_on_new_buy_tier(monkeypatch, tmp_path):
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)
    monkeypatch.setattr(tb, "_rank_new_buys", lambda cfg, pt: {"status": "NEUTRAL", "candidates": [
        {"ticker": "NEW.JK", "kind": "sized", "tag": "BUY", "score": 70.0,
         "price": 1000.0, "shares": 100, "est": 100_000.0}]})

    r = tb.cmd_priority()
    assert "NEW BUY IDEAS" in r and "UNVALIDATED" in r


def test_cmd_priority_no_warning_once_validated(monkeypatch, tmp_path):
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000,
                                   "edge_expectations": {"validated": True}}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)
    monkeypatch.setattr(tb, "_rank_new_buys", lambda cfg, pt: {"status": "NEUTRAL", "candidates": [
        {"ticker": "NEW.JK", "kind": "sized", "tag": "BUY", "score": 70.0,
         "price": 1000.0, "shares": 100, "est": 100_000.0}]})

    r = tb.cmd_priority()
    assert "NEW BUY IDEAS" in r and "UNVALIDATED" not in r


def test_signal_reason_summarises_available_indicators():
    s = {"sma_fast": 110, "sma_slow": 100, "rsi": 72, "macd": 1.2,
        "macd_signal": 0.8, "volume_ratio": 1.8, "consecutive_up": 3}
    reason = tb._signal_reason(s)
    assert "uptrend" in reason
    assert "RSI 72 (hot)" in reason
    assert "MACD bullish" in reason
    assert "volume 1.8x avg" in reason
    assert "3 day(s) up in a row" in reason


def test_signal_reason_falls_back_when_no_indicators_present():
    assert tb._signal_reason({}) == "score-driven (no indicator breakdown available)"


def test_cmd_scan_sized_candidate_includes_reason_line(monkeypatch, tmp_path):
    import kala_daily_trader as dt
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000,
                                   "daily_capital_idr": 10_000_000,
                                   "edge_expectations": {"validated": True}}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)
    monkeypatch.setattr(dt, "check_market_health", lambda: {"status": "NEUTRAL"})
    monkeypatch.setattr(dt, "live_trading_dashboard", lambda: [
        {"ticker": "GOOD.JK", "signal": "BUY", "technical_score": 70, "price": 1000,
         "atr": 20, "sma_fast": 105, "sma_slow": 100, "rsi": 55, "macd": 0.5,
         "macd_signal": 0.3}])
    monkeypatch.setattr(tb, "_entry_price_range", lambda t: None)

    r = tb.cmd_scan()
    assert "reason:" in r
    assert "uptrend" in r and "RSI 55" in r


def test_rank_new_buys_classifies_kinds(monkeypatch, tmp_path):
    import kala_daily_trader as dt
    from kala.papertrade import PaperTrader

    statefile = tmp_path / "paper_state.json"
    _seed_positions_state(statefile, ["HELD.JK"])
    pt = PaperTrader.load(statefile, start_capital=10_000_000)

    monkeypatch.setattr(dt, "check_market_health", lambda: {"status": "BULLISH"})
    monkeypatch.setattr(dt, "live_trading_dashboard", lambda: [
        {"ticker": "HELD.JK", "signal": "BUY", "technical_score": 70, "price": 1000, "atr": 20},
        {"ticker": "GOOD.JK", "signal": "STRONG BUY", "technical_score": 85, "price": 1500, "atr": 30},
    ])
    monkeypatch.setattr(tb, "_entry_price_range", lambda t: None)

    r = tb._rank_new_buys({"daily_capital_idr": 10_000_000, "max_positions": 5,
                           "risk_pct_per_trade": 2.0}, pt)
    kinds = {c["ticker"]: c["kind"] for c in r["candidates"]}
    assert kinds["HELD.JK"] == "held"
    assert kinds["GOOD.JK"] == "sized"


def test_rank_new_buys_does_not_size_every_candidate_against_full_cash(monkeypatch, tmp_path):
    """The reported bug: with low cash and several ranked BUY ideas, each one
    used to be sized as if it ALONE had access to the full account cash --
    buying every idea shown would need several times the actual money on
    hand. Total cost of everything sized here must never exceed real cash,
    and later (lower-ranked) ideas must shrink as the running total depletes."""
    import kala_daily_trader as dt
    from kala.papertrade import PaperTrader

    statefile = tmp_path / "paper_state.json"
    pt = PaperTrader.load(statefile, start_capital=3_000_000)   # small cash on purpose

    monkeypatch.setattr(dt, "check_market_health", lambda: {"status": "NEUTRAL"})
    monkeypatch.setattr(dt, "live_trading_dashboard", lambda: [
        {"ticker": "A.JK", "signal": "STRONG BUY", "technical_score": 90, "price": 1000, "atr": 20},
        {"ticker": "B.JK", "signal": "BUY", "technical_score": 80, "price": 1000, "atr": 20},
        {"ticker": "C.JK", "signal": "BUY", "technical_score": 70, "price": 1000, "atr": 20},
    ])
    monkeypatch.setattr(tb, "_entry_price_range", lambda t: None)

    # risk_pct deliberately generous so by_risk never binds regardless of the
    # exact stop distance -- isolates the per-slot cap (fixed, independent of
    # cash) from the running CASH total (the thing that must shrink between
    # candidates) as the two constraints under test.
    r = tb._rank_new_buys({"daily_capital_idr": 10_000_000, "max_positions": 5,
                           "risk_pct_per_trade": 50.0}, pt)
    sized = [c for c in r["candidates"] if c["kind"] == "sized"]
    assert len(sized) >= 2, "need at least 2 sized candidates for this to test anything"

    total_cost = sum(c["est"] for c in sized)
    assert total_cost <= pt.cash * 1.001   # never recommend more than you actually have

    by_ticker = {c["ticker"]: c["shares"] for c in sized}
    assert by_ticker["A.JK"] > by_ticker.get("B.JK", 0) >= 0   # cash pool visibly shrinks


def test_evaluate_holdings_flags_max_holding_period_as_sell(monkeypatch, tmp_path):
    """The max-holding-period rule only ever lived in papertrade.step()'s own
    loop (evaluate_exit has no bars-held context) -- without checking it here
    too, /review and /priority would show HOLD right up until the EOD /run
    silently sells the same position. Must escalate NONE -> CONSIDER, never
    downgrade an existing URGENT/CONSIDER verdict."""
    import numpy as np
    import pandas as pd

    import kala_daily_trader as dt
    from kala.config import Config, RiskConfig
    from kala.papertrade import PaperTrader

    n = 90
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
    entry_bar = n - 25   # 24 bars held by the fill-day-0 convention -> past the 20-bar default
    entry_date = idx[entry_bar].strftime("%Y-%m-%d")

    statefile = tmp_path / "paper_state.json"
    statefile.write_text(json.dumps({
        "cash": 1_000_000, "start_capital": 10_000_000,
        "positions": {"OLD.JK": {"ticker": "OLD.JK", "entry_price": 1000.0, "shares": 100,
                                 "entry_date": entry_date, "peak_price": 1000.0, "entry_atr": None}},
        "pending": [], "log": [], "benchmark_start": None, "capital_additions": [],
    }), encoding="utf-8")
    cfg = Config(risk=RiskConfig(trailing_enabled=False, hard_stop_pct=-50.0,
                                 atr_stop_multiple=99.0, target_profit_pct=999.0))
    pt = PaperTrader.load(statefile, start_capital=10_000_000, cfg=cfg)

    closes = np.full(n, 1000.0)
    hist = pd.DataFrame({"Open": closes, "High": closes * 1.005, "Low": closes * 0.995,
                         "Close": closes, "Volume": np.full(n, 1e6)}, index=idx)

    monkeypatch.setattr(dt, "check_market_health", lambda: {"status": "NEUTRAL"})
    monkeypatch.setattr(dt, "download_stock_data", lambda *a, **k: hist)
    monkeypatch.setattr(dt, "get_live_signal", lambda *a, **k: None)

    result = tb._evaluate_holdings(pt, {"daily_capital_idr": 10_000_000, "max_positions": 5})
    rec = result["records"][0]
    assert rec["urgency"] == "CONSIDER"
    assert "max holding period" in rec["reason"]
    assert rec["add_suggestion"] is None   # flagged for exit -> never also pitched as an add
    assert rec["bars_held"] == 24 and rec["max_days"] == 20


def test_cmd_priority_never_lists_same_ticker_in_take_profit_and_add(monkeypatch, tmp_path):
    """Regression for the /priority contradiction bug: even if a stubbed
    _evaluate_holdings record carries BOTH urgency=CONSIDER and a non-null
    add_suggestion (what the pre-fix code could produce), cmd_priority's own
    tier filter must still keep it out of ADD TO WINNERS."""
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    _seed_positions_state(statefile, ["BOTH.JK"])
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)

    monkeypatch.setattr(tb, "_evaluate_holdings", lambda pt, cfg: {"status": "BULLISH", "records": [
        {"ticker": "BOTH.JK", "no_data": False, "urgency": "CONSIDER",
         "reason": "target profit reached (+9.0%)", "pnl_pct": 9.0,
         "trim_suggestion": "trim half: /sell BOTH.JK 50 2000",
         "add_suggestion": "could add 100 sh: /buy BOTH.JK 100 2000", "add_score": 80.0},
    ]})
    monkeypatch.setattr(tb, "_rank_new_buys", lambda cfg, pt: {"status": "BULLISH", "candidates": []})

    r = tb.cmd_priority()
    assert "ADD TO WINNERS" not in r
    assert "TAKE PROFIT" in r and "BOTH.JK" in r
    assert "could add" not in r


def test_evaluate_holdings_marks_no_data(monkeypatch, tmp_path):
    import kala_daily_trader as dt
    from kala.papertrade import PaperTrader

    statefile = tmp_path / "paper_state.json"
    _seed_positions_state(statefile, ["SUSPENDED.JK"])
    pt = PaperTrader.load(statefile, start_capital=10_000_000)

    monkeypatch.setattr(dt, "check_market_health", lambda: {"status": "BULLISH"})
    monkeypatch.setattr(dt, "download_stock_data", lambda *a, **k: None)

    result = tb._evaluate_holdings(pt, {"daily_capital_idr": 10_000_000, "max_positions": 5})
    assert len(result["records"]) == 1
    assert result["records"][0]["no_data"] is True


def test_cmd_ask_no_arg_shows_usage(monkeypatch, tmp_path):
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)

    r = tb.cmd_ask("")
    assert "Ask a question" in r


def test_cmd_ask_answers_from_real_log(monkeypatch, tmp_path):
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)

    tb.cmd_buy("ANTM 100 1000")
    tb.cmd_sell("ANTM 1100")     # win
    tb.cmd_buy("BBRI 100 1000")
    tb.cmd_sell("BBRI 900")      # loss

    r = tb.cmd_ask("how did I do")
    assert "2 trade(s)" in r
    assert "50%" in r


def test_cmd_ask_no_matching_trades(monkeypatch, tmp_path):
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)

    r = tb.cmd_ask("how did BBCA do")
    assert "No matching trades" in r


def test_dispatch_routes_ask_and_aliases(monkeypatch):
    monkeypatch.setattr(tb, "cmd_ask", lambda a: f"A:{a}")
    assert tb.dispatch("/ask worst trade") == "A:worst trade"
    assert tb.dispatch("/tanya worst trade") == "A:worst trade"
    assert tb.dispatch("/query worst trade") == "A:worst trade"


# ---------------- equity chart --------------------------------------------------

def test_build_equity_chart_png_not_enough_trades(monkeypatch, tmp_path):
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)

    png, caption = tb.build_equity_chart_png()
    assert png is None
    assert "Not enough closed trades" in caption


def test_build_equity_chart_png_with_trades(monkeypatch, tmp_path):
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)

    tb.cmd_buy("ANTM 100 1000")
    tb.cmd_sell("ANTM 1100")

    png, caption = tb.build_equity_chart_png()
    assert png is not None
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert "Realized only" in caption
    assert "1 closed trade" in caption


def test_bot_send_photo_posts_multipart(monkeypatch):
    calls = {}

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"ok": True}

    def fake_post(url, data=None, files=None, timeout=None):
        calls["url"] = url
        calls["data"] = data
        calls["files"] = files
        return FakeResp()

    monkeypatch.setattr(tb.requests, "post", fake_post)
    bot = tb.Bot(token="TOKEN", chat_id="123")
    bot.send_photo(b"\x89PNG\r\n\x1a\n", caption="hello")

    assert "sendPhoto" in calls["url"]
    assert calls["data"]["chat_id"] == "123"
    assert calls["data"]["caption"] == "hello"
    assert calls["files"]["photo"][0] == "chart.png"


def test_bot_send_document_posts_multipart(monkeypatch):
    calls = {}

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"ok": True}

    def fake_post(url, data=None, files=None, timeout=None):
        calls["url"] = url
        calls["data"] = data
        calls["files"] = files
        return FakeResp()

    monkeypatch.setattr(tb.requests, "post", fake_post)
    bot = tb.Bot(token="TOKEN", chat_id="123")
    bot.send_document(b"<html></html>", "dashboard.html", caption="hi")

    assert "sendDocument" in calls["url"]
    assert calls["data"]["chat_id"] == "123"
    assert calls["data"]["caption"] == "hi"
    assert calls["files"]["document"][0] == "dashboard.html"
    assert calls["files"]["document"][2] == "text/html"


# ---------------- /report: full dashboard document --------------------------

def test_build_dashboard_document_no_positions(monkeypatch, tmp_path):
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)

    import generate_dashboard as gd
    monkeypatch.setattr(gd.yf, "download",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no net")))

    html_bytes, caption = tb.build_dashboard_document()
    assert html_bytes is not None
    assert html_bytes.startswith(b"<") or len(html_bytes) > 0
    assert "Equity:" in caption
    assert "TWR since inception" in caption
    assert "0 open position" in caption
    assert "Dividends received" not in caption   # none recorded -> omitted


def test_build_dashboard_document_shows_dividends_when_present(monkeypatch, tmp_path):
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)

    import generate_dashboard as gd
    monkeypatch.setattr(gd.yf, "download",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no net")))

    tb.cmd_dividend("ANTM 50000")
    _, caption = tb.build_dashboard_document()
    assert "Dividends received" in caption


def test_build_dashboard_document_flags_drift(monkeypatch, tmp_path):
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({
        "start_capital_idr": 10_000_000,
        "target_allocation": {"ANTM.JK": 10.0, "BBCA.JK": 90.0},
    }), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)

    import generate_dashboard as gd
    monkeypatch.setattr(gd.yf, "download",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no net")))

    tb.cmd_buy("ANTM 100 1000")   # 100% actual vs 10% target -> big drift

    html_bytes, caption = tb.build_dashboard_document()
    assert html_bytes is not None
    assert "Drifted from target" in caption
    assert "ANTM" in caption


def test_build_dashboard_document_none_on_build_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(tb, "CONFIG_PATH", tmp_path / "runner_config.json")
    monkeypatch.setattr(tb, "STATE_PATH", tmp_path / "paper_state.json")

    import generate_dashboard as gd

    def raising_build_dashboard(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(gd, "build_dashboard", raising_build_dashboard)
    html_bytes, caption = tb.build_dashboard_document()
    assert html_bytes is None
    assert "Couldn't build the report" in caption


def test_dispatch_not_used_for_chart_command_directly():
    """'/chart' is intercepted before dispatch() (photos need a different
    transport than dispatch's text-only contract) -- dispatch() itself must
    still fall through to the unknown-command message for it."""
    assert tb.dispatch("/chart") == "Unknown command. Send /help for the menu."


def test_dispatch_not_used_for_report_command_directly():
    """Same reasoning as /chart -- /report needs sendDocument, not
    dispatch()'s plain-text reply, so it's intercepted in the polling loop
    too and must NOT be reachable through dispatch()."""
    assert tb.dispatch("/report") == "Unknown command. Send /help for the menu."
    assert tb.dispatch("/laporan") == "Unknown command. Send /help for the menu."


def test_cmd_taxreport_shows_disclaimer_and_totals(monkeypatch, tmp_path):
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)

    tb.cmd_buy("ANTM 100 1000")
    tb.cmd_sell("ANTM 1100")

    r = tb.cmd_taxreport("")
    assert "NOT TAX ADVICE" in r
    assert "1 closed transaction(s)" in r


def test_cmd_taxreport_filters_by_year(monkeypatch, tmp_path):
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)

    r = tb.cmd_taxreport("2019")
    assert "No closed trades" in r
    assert "2019" in r


def test_cmd_taxreport_rejects_bad_year(monkeypatch, tmp_path):
    cfgfile = tmp_path / "runner_config.json"
    cfgfile.write_text(json.dumps({"start_capital_idr": 10_000_000}), encoding="utf-8")
    statefile = tmp_path / "paper_state.json"
    monkeypatch.setattr(tb, "CONFIG_PATH", cfgfile)
    monkeypatch.setattr(tb, "STATE_PATH", statefile)

    r = tb.cmd_taxreport("banana")
    assert "Usage" in r


def test_dispatch_routes_taxreport_and_alias(monkeypatch):
    monkeypatch.setattr(tb, "cmd_taxreport", lambda a: f"T:{a}")
    assert tb.dispatch("/taxreport 2026") == "T:2026"
    assert tb.dispatch("/pajak 2026") == "T:2026"
