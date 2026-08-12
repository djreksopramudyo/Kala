r"""
Kala interactive Telegram bot.
=========================================================================

The scheduler (daily_run.py) PUSHES one message a day. This bot lets you PULL
on demand and talk back to the system from your phone:

  /capital 5jt         set today's buy budget ceiling (does NOT touch real cash)
  /deposit 5jt         add real money mid-cycle — raises cash + start_capital
                       so the deposit itself never reads as a "gain"
  /scan                run the daily-trader scan -> ranked BUY recommendations,
                       each sized to your current capital   (read-only)
  /priority            merges /review + /scan into ONE ranked to-do list:
                       SELL NOW > TAKE PROFIT > ADD TO WINNERS > NEW BUY
                       IDEAS, numbered, best-scoring first within each tier
  /buy / /sell         record a real trade you made — the ONLY way a position
                       is created (nothing auto-buys unless auto_paper_trade
                       is turned on in runner_config.json). Buying more of a
                       ticker you already hold ADDS to it (blended avg price).
                       Forgot to log it same-day? Append @date (@kemarin,
                       @3 hari lalu, @2026-07-10) to backdate it — the
                       holding period is then measured from when you
                       actually traded, not from when you reported it.
                       /sell TICKER SHARES PRICE sells only PART of a
                       position (take-profit); the remainder keeps its
                       original cost basis unchanged.
  /undo / /redo        fat-fingered a number on /buy, /sell, or /deposit?
                       /undo reverts it (last 5 kept); /redo brings it back
  /review              review the stocks you already hold: HOLD / SELL / ADD,
                       using the same exit ladder + score the engine uses
  /status              paper-account summary (equity, cash, alpha vs IHSG)
  /history [N]         your last N closed trades, most recent first
  /edge                live track record vs the validated backtest numbers —
                       the edge-decay check, with a small-sample-honest verdict
  /checkstop           on-demand mid-day check: has any HELD position hit its
                       stop/target/limit-down RIGHT NOW? Also lists every
                       position's CURRENT stop-loss price, not just breaches.
                       Same logic the 15-min scheduled push watcher
                       (intraday_watch.py) uses, just triggered by you
                       instead of a timer. Quotes are DELAYED ~15min
                       (Yahoo's free tier), NOT real time — a decision aid,
                       not a live feed.
  /news <TICKER>       headlines + sentiment (advisory only, never a signal)
  /run                 execute the full daily cycle: scan, manage exits on
                       what you hold, list BUY ideas — same as the 17:00
                       scheduler; does not auto-buy
  /reset               wipe cash/positions/history to a clean slate
                       (2-step confirm — see /help)
  /help                this menu

DESIGN
------
* Only the raw Telegram HTTP API via `requests` — no extra dependencies, no
  async framework to fight with on Windows.
* Long-polling (getUpdates). Single-user: while a /scan runs (a few minutes,
  ~600 tickers) the loop blocks — that's fine, we send a "working…" ack first.
* SECURITY: the bot replies ONLY to the chat_id in runner_config.json. Anyone
  else who finds the bot gets ignored. (Set telegram_chat_id before running.)
* The heavy lifting is delegated to the SAME functions the scheduler uses
  (kala_daily_trader, PaperTrader, evaluate_position) so the bot can
  never drift from what the daily run would do.

RUN IT
------
Windows (laptop must be on):
    .\.venv\Scripts\Activate.ps1
    python telegram_bot.py

Leave it running in a terminal (or wrap it with NSSM / Task Scheduler to run
at logon). Ctrl-C to stop.

Linux/VPS (always-on, no laptop needed -- see DEPLOY_VPS.md for the full
walkthrough):
    systemctl enable --now kala-bot.service
"""

from __future__ import annotations

import json
import re
import time
import traceback
from datetime import date, timedelta
from pathlib import Path

import requests

from kala.clock import today_wib  # WIB, not server-local (see kala/clock.py)

ROOT = Path(__file__).parent
CONFIG_PATH = ROOT / "runner_config.json"
STATE_PATH = ROOT / "paper_state.json"

API = "https://api.telegram.org/bot{token}/{method}"
POLL_TIMEOUT = 30          # long-poll seconds
MAX_MSG = 3900             # Telegram hard-caps at 4096; chunk below that


# =========================================================================
# Pure helpers (unit-tested, no network)
# =========================================================================

def parse_money(text: str) -> float | None:
    """Parse an IDR amount written the way a human would.

    Accepts: '5000000', '5.000.000', '5,000,000', '5jt', '5 juta', '5m',
    '500rb', '500 ribu', '2.5jt', '2,5jt'. Returns rupiah as float, or None
    if it can't be understood.
    """
    if not text:
        return None
    s = text.strip().lower().replace(" ", "")

    m = re.fullmatch(r"([\d.,]+)(jt|juta|m|rb|ribu|k)?", s)
    if not m:
        return None
    num_raw, suffix = m.group(1), m.group(2)

    # Decide decimal vs thousands separator. If both '.' and ',' appear, the
    # LAST one is the decimal point (Indonesian uses '.' for thousands, ','
    # for decimals; but people mix). Simplify: if a suffix multiplier exists,
    # treat separators loosely and allow one decimal.
    if suffix in ("jt", "juta", "m", "rb", "ribu", "k"):
        # suffix present -> separators may be decimals (2,5jt / 2.5jt = 2.5M)
        num_raw = num_raw.replace(",", ".")
        if num_raw.count(".") > 1:                 # keep only the last as decimal
            head, _, tail = num_raw.rpartition(".")
            num_raw = head.replace(".", "") + "." + tail
    else:
        # plain number: strip thousands separators entirely
        num_raw = num_raw.replace(".", "").replace(",", "")
    try:
        val = float(num_raw)
    except ValueError:
        return None

    mult = {"jt": 1e6, "juta": 1e6, "m": 1e6,
            "rb": 1e3, "ribu": 1e3, "k": 1e3}.get(suffix, 1.0)
    val *= mult
    if val <= 0:
        return None
    return val


def parse_price(text: str) -> float | None:
    """Parse a stock PRICE (unlike parse_money, which is for capital/deposit
    amounts and always treats '.'/',' as thousands separators). Prices
    genuinely carry fractional rupiah — e.g. yfinance adjusted closes — so a
    lone separator followed by 1-2 digits is a decimal point; a separator
    followed by exactly 3 digits (repeatable) is a thousands grouping.

    Accepts: '1500', '1.500' (=1500), '1,500' (=1500), '1500.5', '1500,5'
    (=1500.5), '12.345.000' (=12345000). Returns None if ambiguous/invalid.
    """
    if not text:
        return None
    s = text.strip().replace(" ", "")
    if re.fullmatch(r"\d+", s):
        val = float(s)
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", s):
        val = float(s.replace(".", ""))
    elif re.fullmatch(r"\d{1,3}(,\d{3})+", s):
        val = float(s.replace(",", ""))
    elif re.fullmatch(r"\d+\.\d{1,2}", s):
        val = float(s)
    elif re.fullmatch(r"\d+,\d{1,2}", s):
        val = float(s.replace(",", "."))
    else:
        return None
    return val if val > 0 else None


def parse_shares(text: str) -> int | None:
    """Parse a SHARE COUNT. Returns None for anything ambiguous.

    Shares are whole units, so unlike parse_price this accepts thousands
    grouping and nothing else. It exists because the previous inline parse
    stripped '.' and ',' unconditionally, which silently mangles the format
    an Indonesian broker screen actually prints: '1.000,00' — one thousand
    shares — became 100000, a hundredfold error, recorded without a murmur
    whenever the account had enough cash to cover it. '20.0' likewise became
    200.

    Anything carrying a decimal part is REJECTED rather than guessed at. A
    fractional share count means the input came from somewhere this parser
    should not be interpreting, and asking is cheaper than recording a trade
    that never happened.

    Accepts: '200', '1.000' (=1000), '1,000' (=1000), '12.345.000'.
    Rejects: '1.000,00', '20.0', '1,5', '10.5', '' and junk.
    """
    if not text:
        return None
    s = text.strip().replace(" ", "")
    if re.fullmatch(r"\d+", s):
        val = int(s)
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", s):
        val = int(s.replace(".", ""))
    elif re.fullmatch(r"\d{1,3}(,\d{3})+", s):
        val = int(s.replace(",", ""))
    else:
        return None
    return val if val > 0 else None


def parse_date(text: str, today: date | None = None) -> str | None:
    """Parse a purchase/sale date reported after the fact — e.g. you forgot
    to /buy on the day it actually happened. Accepts 'YYYY-MM-DD',
    'today'/'hari ini', 'yesterday'/'kemarin', and 'N hari lalu' / 'N days
    ago'. Returns an ISO date string, or None if unparseable or in the
    future (a trade can't have happened yet)."""
    if not text:
        return None
    s = text.strip().lower()
    base = today or today_wib()
    if s in ("today", "hari ini", "hariini"):
        d = base
    elif s in ("yesterday", "kemarin"):
        d = base - timedelta(days=1)
    else:
        m = re.fullmatch(r"(\d+)\s*(?:hari|days?)\s*(?:yang\s*)?(?:lalu|ago)", s)
        if m:
            d = base - timedelta(days=int(m.group(1)))
        else:
            try:
                d = date.fromisoformat(s)
            except ValueError:
                return None
    if d > base:
        return None
    return d.isoformat()


def _split_trade_date(arg: str) -> tuple[str, str | None]:
    """Pull a trailing '@<date>' token out of a /buy or /sell argument
    string. '@' marks the date unambiguously (a bare token like '3' could
    otherwise be mistaken for either a price or the start of '3 hari lalu').
    Returns (trade_args_without_date, date_text_or_None) — date_text still
    needs parse_date(); this function only splits, it doesn't validate."""
    parts = arg.split()
    at_idx = next((i for i, p in enumerate(parts) if p.startswith("@")), None)
    if at_idx is None:
        return arg, None
    date_text = " ".join(parts[at_idx:])[1:].strip()
    return " ".join(parts[:at_idx]), (date_text or None)


def rank_buys(signals: list[dict]) -> list[dict]:
    """BUY/STRONG BUY candidates, highest technical_score first (STRONG BUY
    wins ties) — the same ordering the paper trader uses to pick names."""
    rank = {"STRONG BUY": 1, "BUY": 0}
    buys = [s for s in (signals or [])
            if str(s.get("signal", "")).upper() in ("BUY", "STRONG BUY")]
    buys.sort(key=lambda s: (float(s.get("technical_score", 0) or 0),
                             rank.get(str(s.get("signal", "")).upper(), 0)),
              reverse=True)
    return buys


def idr(x: float) -> str:
    return f"IDR {x:,.0f}"


def price_idr(x: float) -> str:
    """Format a PER-SHARE price. Unlike idr() (always whole rupiah — correct
    for money TOTALS like cash, cost, or P&L), a price genuinely carries
    fractional rupiah -- yfinance adjusted closes, or a /editentry correction
    typed as e.g. 1500.75 -- and idr()'s ,.0f would silently round it in
    every message that echoes it back, even though the stored value is exact
    (see parse_price's docstring: this project already accepts decimal
    price input; only the DISPLAY was rounding it).

    Shows up to 2 decimals ONLY when the price actually has a fraction, so
    the overwhelmingly common case (plain integer IDX prices) still reads
    exactly like idr() -- no '.00' noise on every line."""
    return f"IDR {x:,.0f}" if x == int(x) else f"IDR {x:,.2f}"


def md_escape(text) -> str:
    """Escape Telegram legacy Markdown's four special characters (_ * ` [)
    so arbitrary/dynamic text -- almost always an exception's message --
    renders LITERALLY instead of being silently reinterpreted as formatting.

    This is what was actually happening to error messages: an AttributeError
    reading "module 'generate_dashboard' has no attribute 'build_dashboard'"
    contains a valid OPEN/CLOSE underscore pair (no whitespace touching
    either _), which Telegram's Markdown parser treats as italic markup and
    swallows on render -- the message arrives as "...'generatedashboard'...
    'builddashboard'...", underscores gone, with no indication anything was
    altered. Critically this is NOT an API failure (parse_mode="Markdown" is
    syntactically valid), so send()'s existing "retry as plain text on
    error" fallback never triggers -- the corrupted render succeeds. Any
    exception text is equally exposed: a stray *, `, or [ has the same
    effect. Apply this to the DYNAMIC portion of a message before
    interpolating it into Markdown-formatted text; leave literal/authored
    text (e.g. intentional *bold* headers) unescaped.
    """
    return re.sub(r"([_*`\[])", r"\\\1", str(text))


def chunk(text: str, size: int = MAX_MSG) -> list[str]:
    return [text[i:i + size] for i in range(0, len(text), size)] or [""]


# =========================================================================
# Config
# =========================================================================

def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text())


def save_capital(amount: float) -> None:
    cfg = load_config()
    cfg["daily_capital_idr"] = float(amount)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))


def save_max_positions(n: int) -> None:
    cfg = load_config()
    cfg["max_positions"] = int(n)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))


# =========================================================================
# Command actions (network-heavy; import trading modules lazily)
# =========================================================================

def cmd_help() -> str:
    return (
        "🤖 *Kala bot* — your daily loop:\n\n"
        "*1. Set budget*\n"
        "/capital <amount> — today's buy budget ceiling, e.g. /capital 5jt\n"
        "/maxpositions <N> — how many concurrent names to plan around. "
        "Each position is capped at budget÷N, so a HIGHER N means SMALLER "
        "positions — lower it if cash is sitting idle despite a full budget\n"
        "/deposit <amount> — add REAL money mid-cycle (raises cash, not "
        "just the budget), e.g. /deposit 5jt\n"
        "/dividend <TICKER> <amount> [@date] — record dividend income, "
        "e.g. /dividend ANTM 50000. NOT the same as /deposit: a dividend "
        "counts as real return; a deposit doesn't — mixing them up under- "
        "or over-states your actual performance\n\n"
        "*2. Get ideas*\n"
        "/scan — today's ranked BUY recommendations, sized to your budget\n"
        "/priority — one ranked to-do list merging /review + /scan: SELL "
        "NOW, TAKE PROFIT, ADD TO WINNERS, NEW BUY IDEAS, in that order — "
        "start here if two separate reports are hard to prioritize\n\n"
        "*3. Record what you actually bought*\n"
        "/buy <TICKER> <shares> [price] [@date] — e.g. /buy ANTM 200 1500\n"
        "   (leave price out to use today's close; buying more of something\n"
        "   you already hold ADDS to it at a blended average price)\n"
        "   Forgot to log it? Add @date: /buy ANTM 200 1500 @kemarin,\n"
        "   @3 hari lalu, or @2026-07-10 — backdates it to when you\n"
        "   ACTUALLY bought instead of today\n\n"
        "*4. Let it manage them*\n"
        "/review — HOLD / SELL / ADD for each stock you hold,\n"
        "   with the trailing stop that rises as profit grows\n"
        "/sell <TICKER> [price] [@date] — sell the WHOLE position\n"
        "/sell <TICKER> <shares> <price> [@date] — sell PART of it "
        "(take partial profit; rest keeps its cost basis)\n"
        "/undo — typed the wrong number on /buy, /sell, or /deposit? "
        "undo the last one (keeps last 5)\n"
        "/editentry <TICKER> <price> — fix a WRONG entry price on a "
        "position you're still holding, even from several trades ago "
        "(/undo only reaches the most recent action). Cash reconciles "
        "automatically to match what you actually paid\n"
        "/redo — bring back what you just /undo'd\n\n"
        "*Anytime*\n"
        "/positions — quick list of what you hold\n"
        "/status — account summary (equity, cash, alpha vs IHSG)\n"
        "/history [N] — your last N closed trades, most recent first "
        "(default 10)\n"
        "/edge — live results vs the validated backtest numbers (EV, win "
        "rate, hold time) with an honest small-sample verdict\n"
        "/performance [days] — live performance dashboard, last 7 days by "
        "default (win rate, W/L, net P&L) — counts every closed trade, "
        "wins and losses, not a cherry-picked screenshot\n"
        "/checkstop — RIGHT NOW: has any position hit its stop/target/"
        "limit-down, PLUS every position's current stop-loss price at a "
        "glance (delayed ~15min quotes, not real time)\n"
        "/news <TICKER> — headlines + sentiment (advisory only, never changes the signal)\n"
        "/ask <question> — free-text questions over your trade log, e.g. "
        "'/ask how did BBCA do', '/ask worst trade' (keyword matching, "
        "not real AI — see /ask with no text for the recognized phrases)\n"
        "/chart — equity curve image (cumulative REALIZED P&L from closed "
        "trades only, not full mark-to-market)\n"
        "/report — full HTML dashboard as a file: time-weighted return "
        "since inception, allocation drift vs your target_allocation "
        "(runner_config.json), correlation panel — everything /performance's "
        "quick card leaves out\n"
        "/rebalance [band] — read-only plan to trade back to your "
        "target_allocation mix: specific lot-level BUY/SELL orders + the "
        "transaction cost, so you can keep the portfolio on-target without "
        "over-trading (maintenance, not a signal)\n"
        "/friction — what trading has actually COST you in rupiah, and how "
        "much of your reported profit is an accounting illusion (/buy and "
        "/sell record raw prices and never deduct commission, tax or spread)\n"
        "/taxreport [year] — raw transaction list from your closed trades "
        "(NOT tax advice — a record-keeping skeleton only, see the reply "
        "for the full disclaimer)\n"
        "/run — run the full daily cycle: scan, manage exits on what you hold,\n"
        "   and list BUY ideas — does NOT auto-buy, /buy still records it\n"
        "/reset — wipe cash/positions/history back to a clean slate\n"
        "   (2-step: /reset shows what's at stake, /reset confirm does it)\n"
        "/help — this menu"
    )


def normalize_ticker(t: str) -> str:
    """ANTM -> ANTM.JK ; leaves an existing suffix alone; leaves a bare US
    sharia ticker (AAPL, MSFT, ...) UN-suffixed instead of mangling it into
    "AAPL.JK" — a real bug once kala.universe.US_SHARIA_STOCKS existed as a
    valid /buy target, not just IDX names. Anything else with no dot still
    defaults to IDX (.JK), the historical assumption every existing /buy
    command relies on."""
    from kala.universe import US_SHARIA_STOCKS

    t = t.strip().upper()
    if "." in t:
        return t
    if t in US_SHARIA_STOCKS:
        return t
    return f"{t}.JK"


def _benchmark_window_return(days: int) -> float | None:
    """IHSG (^JKSE) percent return over the last ``days`` CALENDAR days, or
    None if unavailable. Context for /performance: 'my closed trades netted
    +X% this week' means little without 'the whole market did +Y%'. NaN-safe
    (same class of guard as _last_close)."""
    import math
    from datetime import timedelta as _td

    import kala_daily_trader as dt
    try:
        d = dt.download_stock_data("^JKSE", dt.START_DATE, dt.END_DATE)
        if d is None or len(d) < 2:
            return None
        cutoff = (today_wib() - _td(days=days)).isoformat()
        window = d.loc[d.index >= cutoff]
        if len(window) < 2:
            window = d.tail(2)                # fall back to the last two bars
        first = float(window["Close"].iloc[0])
        last = float(window["Close"].iloc[-1])
        if not (math.isfinite(first) and math.isfinite(last) and first > 0):
            return None
        return (last / first - 1.0) * 100.0
    except Exception as e:
        from kala.logging_util import log_swallowed
        log_swallowed("_benchmark_window_return", e)
        return None


def _last_close(ticker: str) -> float | None:
    """Today's close for a ticker, or None if unavailable.

    Returns None (not NaN) when the newest bar's Close isn't a real number
    — yfinance can hand back NaN for an unposted/illiquid latest bar, and a
    NaN leaking into price math renders as 'nan' and misfires <=/>= checks
    (the /checkstop-NaN class of bug). None routes through every caller's
    existing 'no price' path instead."""
    import math

    import kala_daily_trader as dt
    try:
        d = dt.download_stock_data(ticker, dt.START_DATE, dt.END_DATE)
        if d is not None and len(d):
            px = float(d["Close"].iloc[-1])
            if math.isfinite(px) and px > 0:
                return px
    except Exception as e:
        from kala.logging_util import log_swallowed
        log_swallowed(f"_last_close({ticker})", e)
    return None


def _charge_manual_costs(cfg: dict) -> bool:
    """Whether /buy and /sell apply the cost model to the price you type.

    On by default, so a hand-kept book means the same thing as an automated
    one. Set "charge_manual_costs": false in runner_config.json to record raw
    broker prices instead -- the pre-v3.9 behavior, for reconciling against a
    statement line by line. Trades already on the books are unaffected either
    way; this only governs NEW fills.
    """
    return bool(cfg.get("charge_manual_costs", True))


def cmd_buy(arg: str) -> str:
    """/buy TICKER SHARES [PRICE] [@DATE] — record a real buy so /review
    manages it. PRICE is the raw price your broker filled you at; commission
    and half the spread are added on top, so the position's cost basis is
    what the shares really cost. If you already hold TICKER, this ADDS to the position
    (weighted-average cost basis) instead of rejecting — the move /review's
    "could add" note points at. @DATE backdates a purchase you forgot to
    log — e.g. '@kemarin', '@3 hari lalu', '@2026-07-10' — so the holding
    period and stop/target are measured from when you ACTUALLY bought, not
    from today."""
    from kala.papertrade import PaperTrader
    arg, date_text = _split_trade_date(arg)
    trade_date = None
    if date_text is not None:
        trade_date = parse_date(date_text)
        if trade_date is None:
            return (f"Couldn't read the date '@{date_text}'. Try @kemarin, "
                     f"@3 hari lalu, or @2026-07-10.")
    parts = arg.split()
    if len(parts) < 2:
        return "Usage: /buy <TICKER> <shares> [price] [@date]\nExample: /buy ANTM 200 1500 @kemarin"
    ticker = normalize_ticker(parts[0])
    shares = parse_shares(parts[1])
    if shares is None:
        return (f"Couldn't read shares '{parts[1]}'. Shares must be a whole "
                f"number — '1.000' and '1,000' both mean 1000, but something "
                f"like '1.000,00' or '20.5' is ambiguous, so type the plain "
                f"count. Example: /buy ANTM 200 1500")
    price = parse_price(parts[2]) if len(parts) > 2 else _last_close(ticker)
    if not price:
        return (f"Couldn't get a price for {ticker}. Give one explicitly: "
                f"/buy {parts[0]} {shares} 1500")

    cfg = load_config()
    pt = PaperTrader.load(STATE_PATH, cfg.get("start_capital_idr", 10_000_000),
                          charge_manual_costs=_charge_manual_costs(cfg))
    was_held = ticker in pt.positions
    try:
        fill = pt.manual_buy(ticker, shares, price, date=trade_date)
    except ValueError as e:
        return f"⚠️ {md_escape(e)}"

    when = f" on {trade_date}" if trade_date else ""
    # Show what the costs did. Quoting only the raw price would hide why cash
    # dropped by more than price x shares.
    costs_line = ""
    if fill != price:
        costs_line = (f"Booked at {price_idr(fill)}/sh incl. fee + spread "
                      f"(+{idr(fill * shares - price * shares)} in costs).\n")
    if was_held:
        pos = pt.positions[ticker]
        return (f"✅ Added to {ticker}: +{shares:,} sh @ {price_idr(price)}{when}.\n"
                f"{costs_line}"
                f"New position: {pos.shares:,} sh @ avg {price_idr(pos.entry_price)} "
                f"(blended cost basis — the stop/target now measure from this, "
                f"not your original entry).\n"
                f"Cash left: {idr(pt.cash)}. Wrong number? /undo")
    return (f"✅ Recorded BUY {ticker}: {shares:,} sh @ {price_idr(price)}{when} "
            f"(≈ {idr(fill * shares)}).\n{costs_line}Cash left: {idr(pt.cash)}.\n"
            f"Send /review anytime and I'll manage the stop for you. Wrong number? /undo")


def cmd_editentry(arg: str) -> str:
    """/editentry TICKER PRICE — fix a WRONG entry price already on the
    books (you mistyped it in /buy, or your broker confirmation shows a
    different fill than what you logged). Only the entry price changes —
    shares and entry date stay the same.

    NOTE the difference from /buy: this sets the STORED cost basis directly,
    which already includes fee and spread. Nothing is added on top — pass the
    all-in per-share figure you want on the books, not the raw broker price.
    (Adding costs here would silently inject them into positions opened
    before /buy started charging them.)

    Unlike /undo (which only reaches the MOST RECENT action), this targets
    any currently-held position directly, even if you've traded since.
    Cash is automatically reconciled to what you actually paid, and
    peak_price is raised if the correction pushes entry above it, so the
    trailing stop never sits below cost basis. Doesn't touch the closed-
    trade log — only open positions."""
    from kala.papertrade import PaperTrader
    parts = arg.split()
    if len(parts) < 2:
        return "Usage: /editentry <TICKER> <new_price>\nExample: /editentry ANTM 1550"
    ticker = normalize_ticker(parts[0])
    price = parse_price(parts[1])
    if not price:
        return f"Couldn't read price '{parts[1]}'. Example: /editentry {parts[0]} 1550"

    cfg = load_config()
    pt = PaperTrader.load(STATE_PATH, cfg.get("start_capital_idr", 10_000_000))
    try:
        old_price = pt.edit_entry_price(ticker, price)
    except ValueError as e:
        return f"⚠️ {md_escape(e)}"

    pos = pt.positions[ticker]
    return (f"✅ {ticker} entry price corrected: {price_idr(old_price)} → {price_idr(price)}\n"
            f"Stored as-is (all-in cost basis; no fee/spread added on top).\n"
            f"Shares unchanged: {pos.shares:,}. Cash adjusted to {idr(pt.cash)} to "
            f"match what you actually paid.\nWrong on purpose? /undo")


def cmd_sell(arg: str) -> str:
    """/sell TICKER [PRICE] [@DATE] — sell the WHOLE position (backward
    compatible with every earlier /sell). PRICE is the raw price your broker
    filled you at; commission, the final tax and half the spread come off it,
    so the P/L shown is what you actually keep.
    /sell TICKER SHARES PRICE [@DATE]
    — sell only SHARES (partial/take-profit); the rest stays open at the
    SAME cost basis, since the shares you didn't sell didn't change price.
    @DATE backdates a sale you forgot to log."""
    from kala.papertrade import PaperTrader
    arg, date_text = _split_trade_date(arg)
    trade_date = None
    if date_text is not None:
        trade_date = parse_date(date_text)
        if trade_date is None:
            return (f"Couldn't read the date '@{date_text}'. Try @kemarin, "
                     f"@3 hari lalu, or @2026-07-10.")
    parts = arg.split()
    if not parts:
        return ("Usage: /sell <TICKER> [price] [@date]  (whole position)\n"
                 "       /sell <TICKER> <shares> <price> [@date]  (partial)\n"
                 "Example: /sell ANTM 1650  or  /sell ANTM 100 1650")
    ticker = normalize_ticker(parts[0])
    shares = None
    if len(parts) >= 3:
        shares = parse_shares(parts[1])
        if shares is None:
            return (f"Couldn't read shares '{parts[1]}'. Shares must be a "
                    f"whole number — '1.000' and '1,000' both mean 1000, but "
                    f"something like '1.000,00' or '20.5' is ambiguous, so "
                    f"type the plain count. Example: /sell ANTM 100 1650")
        price = parse_price(parts[2])
    elif len(parts) == 2:
        price = parse_price(parts[1])
    else:
        price = _last_close(ticker)
    if not price:
        return f"Couldn't get a price for {ticker}. Give one: /sell {parts[0]} 1650"

    cfg = load_config()
    pt = PaperTrader.load(STATE_PATH, cfg.get("start_capital_idr", 10_000_000),
                          charge_manual_costs=_charge_manual_costs(cfg))
    try:
        pnl = pt.manual_sell(ticker, price, shares=shares, date=trade_date)
    except ValueError as e:
        return f"⚠️ {md_escape(e)}"
    when = f" on {trade_date}" if trade_date else ""
    emoji = "🟢" if pnl >= 0 else "🔴"
    net = pt.manual_fill_price(price, "SELL")
    costs_line = ""
    if net != price:
        costs_line = (f"Net {price_idr(net)}/sh after fee, tax + spread; "
                      f"the {pnl:+.1f}% is after those.\n")
    remaining = pt.positions.get(ticker)
    if remaining is not None:
        return (f"{emoji} Sold {shares:,} sh of {ticker} @ {price_idr(price)}{when} "
                f"→ {pnl:+.1f}%.\n{costs_line}Remaining: {remaining.shares:,} sh @ avg "
                f"{price_idr(remaining.entry_price)} (cost basis unchanged).\n"
                f"Cash now: {idr(pt.cash)}. Wrong number? /undo")
    return (f"{emoji} Recorded SELL {ticker} @ {price_idr(price)}{when} → {pnl:+.1f}%.\n"
            f"{costs_line}Cash now: {idr(pt.cash)}. Wrong number? /undo")


def _calendar_days_held(entry_date: str) -> int | None:
    """Calendar days since entry_date, or None if it can't be parsed. This is
    a quick display figure — the exit engine's actual max-holding-period
    rule counts TRADING bars, not calendar days (see papertrade._bars_held);
    this is deliberately not that, just a fast no-network approximation."""
    try:
        return (today_wib() - date.fromisoformat(entry_date)).days
    except ValueError:
        return None


def cmd_positions() -> str:
    """Quick list of open holdings (no analysis — that's /review)."""
    from kala.papertrade import PaperTrader
    cfg = load_config()
    pt = PaperTrader.load(STATE_PATH, cfg.get("start_capital_idr", 10_000_000))
    if not pt.positions:
        return "No open positions. /scan for ideas, then /buy to record one."
    lines = ["📋 *Your positions:*"]
    for t, p in pt.positions.items():
        held = _calendar_days_held(p.entry_date)
        held_txt = f", {held}d held" if held is not None else ""
        lines.append(f"• {t} — {p.shares:,} sh @ {price_idr(p.entry_price)} "
                     f"(since {p.entry_date}{held_txt})")
    lines.append(f"\nCash: {idr(pt.cash)}. Use /review for HOLD/SELL/ADD calls.")
    return "\n".join(lines)


def cmd_reset(arg: str) -> str:
    """/reset — wipe paper-trading state (cash, positions, trade history)
    back to a clean slate. Two-step on purpose: plain /reset only shows what
    would be lost and how to confirm; nothing is touched until you send
    /reset confirm. Reuses reset_paper.py's tested backup+reset core, so the
    phone command and the PC script behave identically — including the
    backup file, which /reset cannot restore for you (it's on disk, not
    something this chat can hand back)."""
    import reset_paper
    root = STATE_PATH.parent
    parts = arg.split()

    if not parts or parts[0].lower() != "confirm":
        raw = reset_paper.read_current_state(root)
        cfg = load_config()
        current_capital = float(cfg.get("start_capital_idr", 10_000_000))
        if raw is None:
            summary = "nothing yet — no paper_state.json exists."
        else:
            n_pos = len(raw.get("positions", {}))
            tickers = ", ".join(raw.get("positions", {}).keys()) or "none"
            n_log = len(raw.get("log", []))
            summary = (f"cash {idr(raw.get('cash', 0))}, {n_pos} open position(s) "
                      f"({tickers}), {n_log} closed trade(s) in history")
        return (
            "⚠️ *Reset paper-trading state?*\n\n"
            f"This wipes: {summary}\n\n"
            "This INCLUDES real trades you recorded with /buy, not just "
            "system ideas. It's destructive — a backup file is kept on disk "
            "next to paper_state.json, but I can't restore it for you from "
            "here; that's a manual step on your PC.\n\n"
            "To actually do it, send:\n"
            f"/reset confirm — keep the current starting capital ({idr(current_capital)})\n"
            "/reset confirm <amount> — reset AND change it, e.g. /reset confirm 5jt\n\n"
            "Plain /reset (what you just sent) never changes anything by itself."
        )

    cfg = load_config()
    if len(parts) > 1:
        amt = parse_money(" ".join(parts[1:]))
        if not amt or amt <= 0:
            return (f"Couldn't read an amount from '{' '.join(parts[1:])}'. "
                    "Example: /reset confirm 5jt")
        capital = amt
    else:
        capital = float(cfg.get("start_capital_idr", 10_000_000))

    result = reset_paper.perform_reset(capital, sync_config=True, root=root)
    lines = [f"✅ Reset done. paper_state.json is now a clean {idr(capital)} slate."]
    if result["backed_up_to"]:
        lines.append(f"Old state backed up to {result['backed_up_to']} (on disk, "
                     "next to paper_state.json).")
    if result["config_synced"]:
        lines.append("runner_config.json's start_capital_idr / daily_capital_idr synced to match.")
    lines.append("\n/positions and /status reflect this immediately. /scan for fresh ideas.")
    return "\n".join(lines)


def cmd_capital(arg: str) -> str:
    amount = parse_money(arg)
    if amount is None:
        return ("Couldn't read that amount. Try: `/capital 5000000`, "
                "`/capital 5jt`, or `/capital 500rb`.")
    save_capital(amount)
    return (f"✅ Daily buy budget set to {idr(amount)}.\n"
            f"Send /scan to see today's recommendations sized to it.")


def cmd_maxpositions(arg: str) -> str:
    """/maxpositions <N> — how many concurrent positions the sizing math
    plans around. IMPORTANT: this is not a diversification-only knob — every
    new BUY is capped at (budget / max_positions), so a HIGHER number makes
    EACH position SMALLER, not more of your cash deployed. A high
    max_positions with too few qualifying BUY signals is the classic way
    capital sits idle despite a full budget (size_position()'s by_slot
    cap): raising this fixes diversification headroom, LOWERING it is what
    actually gets more capital into each position."""
    arg = arg.strip()
    try:
        n = int(arg)
    except ValueError:
        return "Usage: /maxpositions <N> — e.g. /maxpositions 10"
    if n <= 0:
        return "max_positions must be positive."
    cfg = load_config()
    allocation = float(cfg.get("daily_capital_idr", 0))
    save_max_positions(n)
    per_slot = idr(allocation / n) if allocation > 0 else "?"
    return (f"✅ max_positions set to {n}.\n"
            f"Per-slot cap is now ≈ {per_slot} (budget {idr(allocation)} ÷ {n}) — "
            f"that's the ceiling on EACH new position, regardless of leftover cash.\n"
            f"Lower this number to put more money into fewer names; raise it to "
            f"spread thinner across more.")


def cmd_deposit(arg: str) -> str:
    """/deposit AMOUNT — top up the account with fresh money mid-cycle (you
    added funds in your real broker today). This is NOT the same as
    /capital: /capital only sets today's buy budget ceiling and never
    touches actual cash; /deposit increases real cash (and start_capital,
    so the deposit itself never shows up as a "gain" in /status). It also
    raises daily_capital_idr by the same amount so today's budget reflects
    the new money — the same config-drift bug we've hit before (a stale
    budget number that doesn't match real cash) would otherwise recur here
    on every deposit."""
    from kala.papertrade import PaperTrader
    amount = parse_money(arg)
    if amount is None or amount <= 0:
        return ("Couldn't read that amount. Try: `/deposit 5000000`, "
                "`/deposit 5jt`, or `/deposit 500rb`.")

    cfg = load_config()
    pt = PaperTrader.load(STATE_PATH, cfg.get("start_capital_idr", 10_000_000))
    pre_daily_capital = float(cfg.get("daily_capital_idr", 0))
    pt.add_capital(amount, meta={"pre_daily_capital_idr": pre_daily_capital})

    cfg = load_config()
    cfg["start_capital_idr"] = pt.start_capital
    cfg["daily_capital_idr"] = pre_daily_capital + amount
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))

    return (f"✅ Deposited {idr(amount)}.\n"
            f"Cash now: {idr(pt.cash)}. Starting capital adjusted to "
            f"{idr(pt.start_capital)} too, so /status's return% still measures "
            f"trading performance, not this deposit.\n"
            f"Today's buy budget raised to {idr(cfg['daily_capital_idr'])} to match "
            f"— change it with /capital if you don't want the new money available "
            f"to trade today.\nWrong number? /undo")


def cmd_dividend(arg: str) -> str:
    """/dividend TICKER AMOUNT [@DATE] — record dividend income received.
    NOT the same as /deposit: a dividend is real investment RETURN (it
    increases cash but NOT start_capital), while a deposit is external
    principal (increases both, deliberately excluded from return%). Log a
    dividend as a /deposit by mistake and your real return gets
    UNDERSTATED — the cash sits there looking like unexplained principal
    instead of counting toward performance. @DATE backdates it (e.g. the
    stock actually paid out a few days ago) — same syntax as /buy."""
    from kala.papertrade import PaperTrader
    arg, date_text = _split_trade_date(arg)
    trade_date = None
    if date_text is not None:
        trade_date = parse_date(date_text)
        if trade_date is None:
            return (f"Couldn't read the date '@{date_text}'. Try @kemarin, "
                     f"@3 hari lalu, or @2026-07-10.")
    parts = arg.split()
    if len(parts) < 2:
        return ("Usage: /dividend <TICKER> <amount> [@date]\n"
                "Example: /dividend ANTM 50000 @kemarin")
    ticker = normalize_ticker(parts[0])
    amount = parse_money(parts[1])
    if amount is None or amount <= 0:
        return f"Couldn't read amount '{parts[1]}'. Try: /dividend {parts[0]} 50000"

    cfg = load_config()
    pt = PaperTrader.load(STATE_PATH, cfg.get("start_capital_idr", 10_000_000))
    try:
        pt.record_dividend(ticker, amount, date=trade_date)
    except ValueError as e:
        return f"⚠️ {md_escape(e)}"

    when = f" on {trade_date}" if trade_date else ""
    total = sum(d["amount"] for d in pt.dividends)
    return (f"✅ Recorded DIVIDEND {ticker}: {idr(amount)}{when}.\n"
            f"Cash now: {idr(pt.cash)}. Total dividends received to date: {idr(total)}.\n"
            f"This counts toward your real return (unlike /deposit). Wrong number? /undo")


def cmd_friction(arg: str = "") -> str:
    """/friction — how much has trading itself cost you, in rupiah.

    Reads your own state file; no network needed. The number matters more
    here than in most systems: /edge explains that no signal in this project
    survived an honest out-of-sample test, and when expected return per
    trade is ~zero BEFORE costs, every round trip is an expected loss of
    roughly its friction.

    Note this also surfaces an accounting gap: /buy and /sell record the RAW
    price you type (so paper P/L matches your broker screen) and never deduct
    the commission, final tax and spread you actually paid. Your reported
    return is overstated by exactly the amount shown here."""
    from kala.clock import now_wib
    from kala.config import CostModel
    from kala.friction import format_friction, friction_report

    raw = json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {}
    if not raw.get("positions") and not raw.get("log"):
        return "No trades recorded yet — nothing to cost."

    # tick_floor is the honest IDX default here: cheap stocks cannot trade
    # tighter than their tick, and this book holds sub-1000-rupiah names.
    report = friction_report(raw, costs=CostModel(spread_mode="tick_floor"),
                             already_charged=False,
                             today=now_wib().strftime("%Y-%m-%d"))
    return format_friction(report)


def cmd_rebalance(arg: str = "") -> str:
    """/rebalance [band_pp] — READ-ONLY plan to move your holdings back toward
    the target mix you set in runner_config.json's ``target_allocation``.
    Suggests specific lot-level BUY/SELL orders and the estimated
    transaction cost, then leaves it to YOU: nothing is executed, record any
    trade you decide to make with the normal /buy or /sell.

    ``band_pp`` (default 5) is the anti-churn threshold — names within that
    many percentage points of target are left alone. Raise it to trade less
    often. This is portfolio MAINTENANCE (risk control + discipline), not a
    buy/sell signal — see /edge for why this project has no validated
    timing edge."""
    from kala.config import CostModel, us_equity_costs
    from kala.papertrade import PaperTrader
    from kala.rebalance import plan_rebalance

    cfg = load_config()
    target = cfg.get("target_allocation")
    if not target:
        return ("No target mix set. Add a `target_allocation` to "
                "runner_config.json first, e.g.\n"
                '  "target_allocation": {"ANTM.JK": 40, "BBCA.JK": 60}\n'
                "then /rebalance shows what to trade to hold that mix.")
    target = {normalize_ticker(t): float(w) for t, w in target.items()}

    band = 5.0
    if arg.strip():
        try:
            band = max(0.0, float(arg.strip()))
        except ValueError:
            pass

    pt = PaperTrader.load(STATE_PATH, cfg.get("start_capital_idr", 10_000_000))
    tickers = set(pt.positions) | set(target)
    prices = {t: _last_close(t) for t in tickers}
    holdings_value = {t: pos.shares * prices[t]
                      for t, pos in pt.positions.items() if prices.get(t)}
    # Positions we hold but couldn't price. These must be declared, not just
    # dropped: they belong in the pot every weight is measured against, and
    # omitting one silently inflates every other holding's weight.
    unpriced_held = [t for t in pt.positions if not prices.get(t)]

    # US names (bare tickers) use the cheaper cost model for the estimate; a
    # mixed book is rare here, so pick IDX unless EVERY traded name is US.
    all_us = tickers and all(not t.endswith(".JK") for t in tickers)
    costs = us_equity_costs() if all_us else CostModel()

    plan = plan_rebalance(holdings_value, target, prices, pt.cash,
                          band_pp=band, cost_model=costs,
                          unpriced_holdings=unpriced_held)

    lines = [f"⚖️ *Rebalance plan* — band {band:.0f}pp — {today_wib().isoformat()}",
             "Maintenance, NOT a signal. Read-only — record trades with /buy or /sell.\n"]
    if plan.skipped and not unpriced_held:
        # Only names you DON'T hold were unpriceable — the pot is still whole,
        # so the rest of the plan stands. (When a HELD name is unpriced the
        # plan is refused outright and plan.note explains it in full, so this
        # line would only contradict it.)
        lines.append(f"⚠️ No price for: {', '.join(s.split('.')[0] for s in plan.skipped)} "
                     f"— skipped.\n")
    if plan.is_noop:
        lines.append(plan.note)
        return "\n".join(lines)

    for o in plan.orders:
        icon = "🔴" if o.action == "SELL" else "🟢"
        lots_note = f"{o.lots} lot" if o.ticker.endswith(".JK") else f"{o.shares} sh"
        lines.append(f"{icon} {o.action} {o.ticker.split('.')[0]}: {lots_note} "
                     f"@ {price_idr(o.price)} ≈ {idr(o.value)}  ({o.reason})")
    lines.append("")
    lines.append(f"Sell {idr(plan.total_sell_value)} / buy {idr(plan.total_buy_value)}; "
                 f"cash {idr(plan.cash_before)} → {idr(plan.cash_after)}")
    lines.append(f"Est. transaction cost: {idr(plan.est_cost)} "
                 f"({plan.est_cost / plan.pot * 100:.2f}% of portfolio) — "
                 f"is fixing this drift worth that? Your call.")
    return "\n".join(lines)


def _sync_config_for_deposit_undo(pt, info: dict, redo: bool) -> None:
    """/deposit also raises runner_config.json's start_capital_idr/
    daily_capital_idr as a side effect outside PaperTrader — undo/redo must
    mirror that adjustment or the config drifts from the reverted state.

    Restores the EXACT pre-deposit budget captured in `meta` at deposit
    time (see cmd_deposit), rather than doing relative arithmetic on
    whatever daily_capital_idr CURRENTLY holds — the old relative approach
    drifted to a value nobody chose if a /capital call happened between the
    deposit and the /undo. If a manual /capital override did happen in
    between, /undo intentionally discards it and restores the known
    pre-deposit number — a defensible, predictable value beats an
    arithmetic guess. Older undo entries recorded before `meta` existed
    (pre-upgrade) have no pre_daily_capital_idr and are left alone."""
    if info.get("kind") != "deposit" or not info.get("amount"):
        return
    pre = (info.get("meta") or {}).get("pre_daily_capital_idr")
    if pre is None:
        return
    cfg = load_config()
    cfg["start_capital_idr"] = pt.start_capital
    cfg["daily_capital_idr"] = pre + info["amount"] if redo else pre
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))


def cmd_undo() -> str:
    """/undo — revert your last /buy, /sell, or /deposit if you typed the
    wrong number. Keeps the last 5 manual actions; chain /undo to go back
    further. Does NOT touch positions opened/closed automatically by /run —
    that's a batch decision, not a typo, and isn't in scope here."""
    from kala.papertrade import PaperTrader
    cfg = load_config()
    pt = PaperTrader.load(STATE_PATH, cfg.get("start_capital_idr", 10_000_000))
    try:
        info = pt.undo()
    except ValueError as e:
        return f"⚠️ {md_escape(e)}"
    _sync_config_for_deposit_undo(pt, info, redo=False)
    return f"↩️ Undone: {info['label']}\nCash: {idr(pt.cash)}. Send /redo to bring it back."


def cmd_redo() -> str:
    """/redo — re-apply the action you just /undo'd."""
    from kala.papertrade import PaperTrader
    cfg = load_config()
    pt = PaperTrader.load(STATE_PATH, cfg.get("start_capital_idr", 10_000_000))
    try:
        info = pt.redo()
    except ValueError as e:
        return f"⚠️ {md_escape(e)}"
    _sync_config_for_deposit_undo(pt, info, redo=True)
    return f"↪️ Redone: {info['label']}\nCash: {idr(pt.cash)}."


def cmd_status() -> str:
    import kala_daily_trader as dt
    from kala.papertrade import PaperTrader

    cfg = load_config()
    pt = PaperTrader.load(STATE_PATH, cfg.get("start_capital_idr", 10_000_000))
    # last prices for open positions (cheap: only held tickers)
    last = {}
    jci = None
    try:
        mkt = dt.check_market_health()
        jci = mkt.get("jci_price")
    except Exception:
        pass
    for t in pt.positions:
        px = _last_close(t)      # None (not NaN) when the latest bar is unposted
        if px is not None:
            last[t] = px
    s = pt.summary(last, benchmark_price=jci)

    max_pos = int(cfg.get("max_positions", 5))
    allocation = float(cfg.get("daily_capital_idr", 0))
    per_slot = allocation / max_pos if max_pos > 0 else 0
    lines = [f"💼 *Paper account* — {today_wib().isoformat()}",
             f"Equity: {idr(s['equity'])} ({s['return_pct']:+.2f}%)",
             f"Cash: {idr(s['cash'])}",
             f"Open: {s['open_positions']} | Closed: {s['closed_trades']} | "
             f"Win rate: {s['win_rate_pct']:.0f}%",
             f"Daily buy budget: {idr(allocation)}",
             f"Max positions: {max_pos} (≈ {idr(per_slot)}/slot cap — "
             f"the ceiling on each NEW position, not total cash; "
             f"/maxpositions to change)"]
    if pt.dividends:
        total_div = sum(d["amount"] for d in pt.dividends)
        lines.append(f"Dividends received: {idr(total_div)} ({len(pt.dividends)} "
                     f"payment(s)) — counted in the return above, not shown separately")
    if s["closed_trades"]:
        lines.append(f"Edge check: /edge ({s['closed_trades']} closed trade(s) "
                     f"vs the validated backtest numbers)")
    if "alpha_pct" in s:
        beat = "beating" if s["alpha_pct"] >= 0 else "TRAILING"
        lines.append(f"vs IHSG buy&hold: {s['benchmark_return_pct']:+.2f}% "
                     f"→ alpha {s['alpha_pct']:+.2f}% ({beat} the index)")
    return "\n".join(lines)


def cmd_ask(arg: str) -> str:
    """Free-text questions over your closed-trade log, e.g. '/ask how did
    BBCA do', '/ask show my losses this month', '/ask worst trade'.

    This is keyword/pattern matching (see kala/log_query.py's module
    docstring), not real natural-language understanding — no LLM call, a
    fixed recognizable vocabulary. Unrecognized wording falls back to 'show
    everything' rather than silently misreading the question."""
    from kala.log_query import answer
    from kala.papertrade import PaperTrader

    if not arg.strip():
        return ("Ask a question about your trade history, e.g.:\n"
               "/ask how did BBCA do\n"
               "/ask show my losses this month\n"
               "/ask worst trade\n"
               "/ask best 3 trades last 30 days")

    cfg = load_config()
    pt = PaperTrader.load(STATE_PATH, cfg.get("start_capital_idr", 10_000_000))
    return answer(arg, pt.log, today=today_wib())


def cmd_taxreport(arg: str) -> str:
    """/taxreport [year] — NOT tax advice, see kala/tax_report.py's
    module docstring. A raw transaction list from your PAPER-trading
    records, optionally filtered to one exit year, with the disclaimer
    attached every time."""
    from kala.papertrade import PaperTrader
    from kala.tax_report import build_transaction_report, summary_text

    year = None
    if arg.strip():
        try:
            year = int(arg.strip())
        except ValueError:
            return "Usage: /taxreport [year], e.g. /taxreport 2026"

    cfg = load_config()
    pt = PaperTrader.load(STATE_PATH, cfg.get("start_capital_idr", 10_000_000))
    rows = build_transaction_report(pt.log, year=year)
    return summary_text(rows, year=year)


def build_equity_chart_png() -> tuple[bytes | None, str]:
    """(png_bytes_or_None, caption). The chart is CUMULATIVE REALIZED P&L
    from closed trades only (see kala/chart.py's module docstring for
    why) — the caption says so explicitly rather than letting an image
    look more authoritative than it is. None if there aren't enough closed
    trades yet to draw a line."""
    from kala.chart import equity_curve_points, render_equity_curve_png
    from kala.papertrade import PaperTrader

    cfg = load_config()
    pt = PaperTrader.load(STATE_PATH, cfg.get("start_capital_idr", 10_000_000))
    points = equity_curve_points(pt.log, pt.start_capital, pt.capital_additions)
    png = render_equity_curve_png(points)
    if png is None:
        return None, "Not enough closed trades yet to chart (need at least 1)."

    final = points[-1][1]
    change_pct = (final / pt.start_capital - 1) * 100 if pt.start_capital else 0.0
    caption = (f"Cumulative realized P&L from {len(points) - 1} closed trade(s): "
              f"{change_pct:+.2f}% (start {idr(pt.start_capital)} -> {idr(final)}). "
              f"Realized only — excludes unrealized P&L on open positions.")
    return png, caption


def build_dashboard_document() -> tuple[bytes | None, str]:
    """(html_bytes_or_None, caption) for /report -- the FULL real dashboard
    (TWR since inception, allocation drift vs your configured target,
    correlation panel, position-vs-benchmark) as a document, not just
    /performance's quick win-rate card. Reuses generate_dashboard.py's
    build_dashboard() directly so this is the exact same report the CLI
    (`python generate_dashboard.py`) would write to disk -- one
    implementation, no second copy to drift out of sync. None only if
    building the report itself raises (e.g. a corrupt state file);
    fetch failures for individual tickers/benchmark degrade gracefully
    inside build_dashboard() already and never reach here as None."""
    import generate_dashboard as gd

    try:
        result = gd.build_dashboard(str(STATE_PATH), str(CONFIG_PATH), days=7)
    except Exception as e:
        return None, f"Couldn't build the report: {md_escape(e)}"

    twr = result["twr_result"]
    lines = [
        f"Equity: {idr(result['summary']['equity'])} | "
        f"{result['n_positions']} open position(s)",
        f"TWR since inception: {twr.twr_pct:+.2f}%"
        + (f" (CAGR {twr.cagr_pct:+.2f}%)" if twr.cagr_pct is not None else ""),
        # Never print this bare: on the realized-only fallback it counts only
        # losses locked in by selling, and reads reassuringly close to zero
        # while a position is deep underwater.
        f"Max drawdown: {twr.max_drawdown_pct:.2f}%"
        + ("" if twr.drawdown_is_complete
           else " (realized only — excludes open positions, so the real "
                "figure is worse)" if not twr.drawdown_is_real
           else " (some holdings had no price history and were held flat at "
                "cost, so the real figure is worse)"),
    ]
    if result["total_dividends"] > 0:
        lines.append(f"Dividends received: {idr(result['total_dividends'])} "
                     f"(included in TWR above)")
    # Before the drift line on purpose: if a holding is priced at cost, the
    # drift figures below are partly made of that placeholder, and reading
    # them as a reason to trade would be acting on a number that isn't one.
    fallbacks = result.get("price_fallbacks") or []
    if fallbacks:
        names = ", ".join(t.split(".")[0] for t in fallbacks)
        lines.append(f"⚠️ No price for {names} — valued at COST. Equity and "
                     f"the drift figures below include that placeholder.")

    drifted = [r for r in result["drift_rows"] if r["flag"] != "ON TARGET"]
    if drifted:
        worst = ", ".join(f"{r['ticker'].split('.')[0]} {r['flag']}" for r in drifted[:3])
        lines.append(f"⚠️ Drifted from target: {worst}"
                     + (f" (+{len(drifted) - 3} more)" if len(drifted) > 3 else ""))
    lines.append("Full report attached — open the HTML file for charts + detail.")
    return result["html"].encode("utf-8"), "\n".join(lines)


def cmd_performance(arg: str = "") -> str:
    """Live performance dashboard, styled like the 'X sinyal, Y% win rate'
    cards signal-service ads lead with — except every number here is
    computed from YOUR real paper-trading log, honestly: every closed trade
    in the window counts (wins AND losses), nothing held back as
    'watchlist', no cherry-picked screenshot. ``arg`` is an optional day
    count (default 7)."""
    from kala.papertrade import PaperTrader

    cfg = load_config()
    pt = PaperTrader.load(STATE_PATH, cfg.get("start_capital_idr", 10_000_000))
    days = 7
    if arg.strip():
        try:
            days = max(1, int(arg.strip()))
        except ValueError:
            pass
    r = pt.recent_performance(days=days)

    lines = [f"📊 *Live Performance* — last {days}d — {today_wib().isoformat()}",
             "=" * 32]

    held = sorted(pt.positions)
    lines.append(f"🟢 ACTIVE: {len(held)} open position(s)"
                + (f" — {', '.join(t.split('.')[0] for t in held)}" if held else ""))

    if r["n"] == 0:
        lines.append(f"\nNo closed trades in the last {days} day(s).")
    else:
        lines.append(f"\n📈 WIN RATE: {r['win_rate_pct']:.0f}%  "
                     f"({r['wins']}W / {r['losses']}L, {r['n']} resolved)")
        sign = "+" if r["net_profit_idr"] >= 0 else ""
        lines.append(f"💰 NET P&L: {sign}{idr(r['net_profit_idr'])}")
        bench = _benchmark_window_return(days)
        if bench is not None:
            lines.append(f"📉 IHSG over the same {days}d: {bench:+.2f}% "
                         f"(context — did your week beat just holding the index?)")
        lines.append("")
        for t in r["trades"]:
            icon = "🟢" if t["pnl_pct"] > 0 else "🔴"
            lines.append(f"{icon} {t['ticker']} {t['pnl_pct']:+.2f}% "
                         f"({idr(t['profit_idr'])}) — {t['reason']}")

    lines.append("\n" + "-" * 32)
    lines.append("Every closed trade counts here — wins and losses. "
                 "Compare against the (currently UNVALIDATED — see /edge) "
                 "backtest baseline before reading anything into a good week.")
    return "\n".join(lines)


def cmd_history(arg: str) -> str:
    """/history [N] — your last N closed trades (default 10, max 50), most
    recent first. Reads pt.log directly — no network call, so it's fast."""
    from kala.papertrade import PaperTrader
    cfg = load_config()
    pt = PaperTrader.load(STATE_PATH, cfg.get("start_capital_idr", 10_000_000))
    if not pt.log:
        return "No closed trades yet. /review manages what you hold; closed trades land here."
    try:
        n = int(arg.strip()) if arg.strip() else 10
    except ValueError:
        n = 10
    n = max(1, min(n, 50))
    recent = list(reversed(pt.log))[:n]

    lines = [f"📜 *Last {len(recent)} closed trade(s):*"]
    for t in recent:
        emoji = "🟢" if t["pnl_pct"] >= 0 else "🔴"
        lines.append(f"{emoji} {t['date']}  {t['ticker']}  {t['shares']:,} sh  "
                     f"{price_idr(t['entry'])} → {price_idr(t['exit'])}  {t['pnl_pct']:+.1f}%  "
                     f"({t['reason']})")
    wins = sum(1 for t in recent if t["pnl_pct"] >= 0)
    lines.append(f"\n{wins}/{len(recent)} winners in this window.")
    return "\n".join(lines)


def cmd_checkstop() -> str:
    """/checkstop — on demand, right now: for every position you hold, has
    the CURRENT price hit its stop-loss, take-profit, or an IDX limit-down
    (ARB) band? Also lists each position's CURRENT stop-loss AND take-profit
    target (not just breaches) — "when to sell" has two sides, cut the loss
    or lock in the gain, and this shows both at a glance instead of only
    finding out after one is already hit.

    Prices are DELAYED ~15 minutes (Yahoo Finance's free tier), NOT real
    time — this is a decision aid for manual action, not a live execution
    feed. Reuses kala.intraday.position_alerts / position_stop_status —
    the exact same detection logic the scheduled push-watcher
    (intraday_watch.py) runs every 15 minutes during market hours, just
    triggered by you instead of a timer. The trailing peak used here is
    read-only (never written back to paper_state.json — only the EOD run
    advances the real trailing stop, so checking this can't silently drift
    your official numbers). Nothing here records a trade; if a stop IS hit,
    decide for yourself whether to mirror a manual /sell now or let the EOD
    run queue it as usual."""
    import intraday_watch
    from kala.intraday import is_idx_open, position_alerts, position_stop_status
    from kala.papertrade import PaperTrader

    cfg = load_config()
    pt = PaperTrader.load(STATE_PATH, cfg.get("start_capital_idr", 10_000_000))
    if not pt.positions:
        return "No open positions to check. /scan for ideas, then /buy to record one."

    from kala.clock import now_wib
    now = now_wib()   # WIB, not server-local — is_idx_open must judge the IDX clock
    quotes = intraday_watch.get_quotes(set(pt.positions))

    alerts = []
    statuses = []
    checked = 0
    for t, pos in pt.positions.items():
        q = quotes.get(t)
        if q is None:
            continue
        checked += 1
        alerts += position_alerts(pos, q, pt.cfg.risk)
        statuses.append(position_stop_status(pos, q, pt.cfg.risk))

    lines = [f"🩺 *Stop check* — {now.strftime('%Y-%m-%d %H:%M')} WIB (quotes delayed ~15m, NOT real time)"]
    if not is_idx_open(now):
        lines.append("⚠️ IDX is closed right now — this reflects the last available "
                     "quote, not a live price.")
    if alerts:
        lines.append("")
        lines.extend(a["text"] for a in alerts)
    else:
        lines.append(f"\n✅ All clear — none of your {checked} position(s) with a "
                     f"quote have hit a stop, target, or limit-down band.")

    if statuses:
        # Any already-triggered position (stop hit OR target hit) floats to
        # the top regardless of which; the rest sort by how close the stop
        # is, since downside is generally the more time-sensitive watch.
        def _urgency(s):
            triggered = s["distance_pct"] <= 0 or s["target_distance_pct"] <= 0
            return (0 if triggered else 1, s["distance_pct"])

        lines.append("\n📍 *Sell levels right now* (cut-loss AND take-profit):")
        for s in sorted(statuses, key=_urgency):
            if s["distance_pct"] <= 0:
                flag = "🛑"       # through the stop -- cut loss
            elif s["target_distance_pct"] <= 0:
                flag = "🎯"       # at/past the target -- lock in the gain
            elif s["distance_pct"] < 3:
                flag = "⚠️"       # getting close to the stop
            else:
                flag = "🟢"
            lines.append(f"{flag} {s['ticker']}: {price_idr(s['price'])} | "
                         f"stop {price_idr(s['stop'])} ({s['distance_pct']:+.1f}%) | "
                         f"target {price_idr(s['target'])} ({s['target_distance_pct']:+.1f}% to go) | "
                         f"P&L {s['pnl_pct']:+.1f}%")

    missing = len(pt.positions) - checked
    if missing:
        lines.append(f"\n({missing} position(s) couldn't get a fresh quote — try again shortly.)")
    lines.append("\nThis is a guide, not an order — nothing is recorded automatically. "
                 "/sell to record a cut if you act on it.")
    return "\n".join(lines)


def cmd_edge() -> str:
    """/edge — is the LIVE track record still consistent with the numbers
    validated in backtests? Compares closed-trade EV / win rate / hold time
    against the expectations in kala/edge.py (overridable via
    runner_config.json's "edge_expectations"), with an honest small-sample
    verdict: a handful of trades reads TOO EARLY, never a false alarm.
    Reads only the local trade log — instant, no network."""
    from kala.edge import MIN_TRADES_FOR_VERDICT, edge_report
    from kala.papertrade import PaperTrader
    cfg = load_config()
    pt = PaperTrader.load(STATE_PATH, cfg.get("start_capital_idr", 10_000_000))
    if not pt.log:
        return ("No closed trades yet — nothing to compare against the backtest. "
                "The tracker starts meaning something after "
                f"~{MIN_TRADES_FOR_VERDICT} closed trades.")

    r = edge_report(pt.log, cfg)
    live, exp = r["live"], r["expected"]
    icon = {"TOO EARLY": "⏳", "ON TRACK": "🟢", "WATCH": "🟡", "DIVERGING": "🔴",
            "UNVALIDATED": "🚧"}[r["verdict"]]

    def _fmt_exp(key, fmt):
        v = exp.get(key)
        return fmt.format(v) if v is not None else "—"

    ref_col = "ref only" if r["verdict"] == "UNVALIDATED" else "backtest"
    lines = [f"📐 *Live vs backtest* — {today_wib().isoformat()}",
             f"{icon} *{r['verdict']}* — {r['verdict_reason']}",
             "",
             f"{'':14}{'live':>10}{ref_col:>10}",
             f"{'trades':14}{live['n']:>10d}{'':>10}",
             f"{'EV/trade':14}{live['ev_pct']:>+9.2f}%{_fmt_exp('ev_pct', '{:+.2f}%'):>10}",
             f"{'median':14}{live['median_pct']:>+9.2f}%{'':>10}",
             f"{'win rate':14}{live['win_rate_pct']:>9.0f}%{_fmt_exp('win_rate_pct', '{:.0f}%'):>10}"]
    if live["avg_hold_days"] is not None:
        lines.append(f"{'avg hold (d)':14}{live['avg_hold_days']:>10.1f}"
                     f"{_fmt_exp('avg_hold_days', '{:.1f}'):>10}")
        if live["n_with_hold"] < live["n"]:
            lines.append(f"  (hold time from the {live['n_with_hold']} trade(s) "
                         f"logged with an entry date)")
    if live["reasons"]:
        mix = ", ".join(f"{k} {v}" for k, v in live["reasons"].most_common())
        lines.append(f"\nExit mix (live): {mix}")
    if r["verdict"] == "UNVALIDATED":
        lines.append("\nRun run_walkforward.py / compare_exit_engines.py with "
                     "--tick-spread on an UNFILTERED universe; if it clears "
                     "|t|>=2 positive, refresh \"edge_expectations\" in "
                     "runner_config.json and set validated=true.")
    else:
        lines.append("\nBacktest column source: see kala/edge.py's module "
                     "docstring for provenance; re-run after any rule change and "
                     "refresh \"edge_expectations\" in runner_config.json.")
    return "\n".join(lines)


def _entry_price_range(ticker: str) -> tuple[float, float] | None:
    """This stock's historical open-vs-prior-close gap range, as an ADDITIVE
    band around last close — NOT a promise, since the actual open is set by
    IDX's pre-opening auction tomorrow morning, which this can't see. It's a
    measured 'here's how much this ticker usually moves overnight', so a
    single point price doesn't read as more precise than it is."""
    import kala_daily_trader as dt
    from kala.indicators import overnight_gap_range_pct
    try:
        h = dt.download_stock_data(ticker, dt.START_DATE, dt.END_DATE)
    except Exception as e:
        from kala.logging_util import log_swallowed
        log_swallowed(f"_entry_price_range({ticker})", e)
        return None
    if h is None or len(h) < 20:
        return None
    return overnight_gap_range_pct(h)


def _rank_new_buys(cfg: dict, pt) -> dict:
    """Core of /scan, minus formatting: scan the universe, rank BUY
    candidates, size the ones that fit the budget. Returns a dict with
    everything both cmd_scan (full detail) and cmd_priority (ranked
    one-liners) need, so the two commands can never drift apart — there is
    exactly one scan/size computation, just two ways of printing it.

    Returns {"status": str, "buys": list[dict] (raw ranked signals, may be
    empty), "held": set[str], "slots": int, "candidates": list[dict]}.
    Each candidate dict: {"ticker", "kind" ("sized"/"held"/"over_cap"/
    "too_small"/"invalid"), "tag", "score", "price", "shares", "stop",
    "target", "est", "gap"} — fields beyond ticker/kind/score are only
    populated when relevant to that kind."""
    import kala_daily_trader as dt
    from kala.exits import governing_stop

    allocation = float(cfg.get("daily_capital_idr", 5_000_000))
    max_pos = int(cfg.get("max_positions", 5))
    risk_pct = float(cfg.get("risk_pct_per_trade", 2.0))

    mkt = dt.check_market_health()
    status = mkt.get("status", "UNKNOWN")
    signals = dt.live_trading_dashboard() or []
    buys = rank_buys(signals)

    held = set(pt.positions)
    slots = max(0, max_pos - len(held))
    candidates: list[dict] = []
    shown = 0
    # Running total: each candidate is sized against what's LEFT after
    # hypothetically buying every higher-ranked candidate before it, not
    # against the full account cash every time — otherwise 5 ranked ideas
    # would each be sized as if they alone had access to all of it, and
    # buying all 5 as shown would need up to 5x the actual cash on hand.
    remaining_cash = pt.cash
    for s in buys:
        t = s["ticker"]
        price = float(s.get("price") or s.get("close") or 0)
        score = float(s.get("technical_score", 0) or 0)
        tag = "STRONG BUY" if str(s.get("signal", "")).upper() == "STRONG BUY" else "BUY"
        if price <= 0:
            candidates.append({"ticker": t, "kind": "invalid", "score": score})
            continue
        if t in held:
            candidates.append({"ticker": t, "kind": "held", "score": score})
            continue
        if shown >= slots and slots > 0:
            candidates.append({"ticker": t, "kind": "over_cap", "score": score})
            continue
        atr_val = s.get("atr")
        stop, _, _ = governing_stop(price, price, atr_val, pt.cfg.risk)
        shares = pt.size_position(price, stop, allocation, risk_pct=risk_pct,
                                  max_positions=max_pos, cash_override=remaining_cash)
        if shares < 100:
            candidates.append({"ticker": t, "kind": "too_small", "tag": tag,
                              "score": score, "price": price})
            continue
        target = price * (1 + pt.cfg.risk.target_profit_pct / 100.0)
        est = price * shares
        remaining_cash -= est
        candidates.append({"ticker": t, "kind": "sized", "tag": tag, "score": score,
                          "price": price, "shares": shares, "stop": stop,
                          "target": target, "est": est,
                          "gap": _entry_price_range(t), "reason": _signal_reason(s)})
        shown += 1

    return {"status": status, "allocation": allocation, "max_pos": max_pos,
            "buys": buys, "held": held, "slots": slots, "candidates": candidates,
            "cash": pt.cash}


def _signal_reason(s: dict) -> str:
    """Short, factual 'why' line for a BUY candidate — the same technical
    fields the composite score already reads (kala_daily_trader.py's
    signal dict), just summarised in plain language instead of buried in a
    score. Describes what the indicators show; does not imply any of this
    combination has a proven edge (see /edge — it doesn't, currently)."""
    bits = []
    fast, slow = s.get("sma_fast"), s.get("sma_slow")
    if fast is not None and slow is not None:
        bits.append("uptrend (SMA fast>slow)" if fast > slow else "downtrend (SMA fast<slow)")
    rsi = s.get("rsi")
    if rsi is not None:
        label = "hot" if rsi >= 70 else ("cool" if rsi <= 35 else "neutral")
        bits.append(f"RSI {rsi:.0f} ({label})")
    macd, macd_sig = s.get("macd"), s.get("macd_signal")
    if macd is not None and macd_sig is not None:
        bits.append("MACD bullish" if macd > macd_sig else "MACD bearish")
    vol_ratio = s.get("volume_ratio")
    if vol_ratio:
        bits.append(f"volume {vol_ratio:.1f}x avg")
    consecutive = s.get("consecutive_up")
    if consecutive:
        bits.append(f"{consecutive} day(s) up in a row")
    return ", ".join(bits) if bits else "score-driven (no indicator breakdown available)"


def _format_scan_candidate(c: dict, risk_cfg) -> str:
    """Render one _rank_new_buys() candidate as /scan's full-detail line."""
    t, score = c["ticker"], c["score"]
    if c["kind"] == "held":
        return f"• {t} — already held (see /review) | score {score:.0f}"
    if c["kind"] == "over_cap":
        return f"• {t} — score {score:.0f} (over the cap, not sized)"
    if c["kind"] == "too_small":
        return (f"• {t} {'🟢🟢 STRONG BUY' if c['tag'] == 'STRONG BUY' else '🟢 BUY'} "
                f"| score {score:.0f} @ {price_idr(c['price'])} — budget too small for 1 lot")
    tag_emoji = "🟢🟢 STRONG BUY" if c["tag"] == "STRONG BUY" else "🟢 BUY"
    gap = c.get("gap")
    price = c["price"]
    if gap:
        lo_pct, hi_pct = gap
        open_lo, open_hi = price * (1 + lo_pct / 100.0), price * (1 + hi_pct / 100.0)
        price_line = (f"    @ {price_idr(price)} last close — likely opens "
                     f"{price_idr(open_lo)}–{price_idr(open_hi)} ({lo_pct:+.1f}% to {hi_pct:+.1f}%, "
                     f"this stock's own historical gap range)")
    else:
        price_line = f"    @ {price_idr(price)} last close (not enough history for a gap range)"
    return (f"• {t} {tag_emoji} | score {score:.0f}\n"
            f"    {c['shares']:,} sh ≈ {idr(c['est'])}\n{price_line}\n"
            f"    🛑 stop-loss {price_idr(c['stop'])}  |  🎯 take-profit {price_idr(c['target'])} "
            f"(+{risk_cfg.target_profit_pct:.0f}%)\n"
            f"    (stop rises automatically as profit grows — see /review)\n"
            f"    reason: {c.get('reason', 'n/a')}")


def cmd_scan(inline_capital: str | None = None) -> str:
    """Read-only: rank today's BUYs and size the top names to the budget.
    Does NOT change paper state (that's /run)."""
    from kala.papertrade import PaperTrader

    cfg = load_config()
    if inline_capital:
        amt = parse_money(inline_capital)
        if amt:
            save_capital(amt)
            cfg = load_config()

    pt = PaperTrader.load(STATE_PATH, cfg.get("start_capital_idr", 10_000_000))
    r = _rank_new_buys(cfg, pt)

    header = [f"🔎 *Scan* — {today_wib().isoformat()}",
              f"Market: {r['status']}",
              f"Budget: {idr(r['allocation'])} across up to {r['max_pos']} names "
              f"(cash on hand: {idr(r['cash'])} — each idea below is sized against "
              f"what's LEFT after the ones ranked above it)"]
    from kala.edge import entry_signal_warning
    warning = entry_signal_warning(cfg)
    if warning:
        header.append(warning)
    if r["status"] in ("BEARISH",):
        header.append("⚠️ IHSG bearish — scores penalised 30%, few/no BUYs is *correct*, not a bug.")
    if not r["buys"]:
        header.append("\nNo BUY signals today. Sitting in cash is a position too.")
        return "\n".join(header)

    lines = [*header, f"\n🎯 Top BUY candidates "
             f"({min(r['slots'], len(r['buys'])) or len(r['buys'])} shown):"]
    for c in r["candidates"]:
        if c["kind"] == "invalid":
            continue
        lines.append(_format_scan_candidate(c, pt.cfg.risk))

    lines.append("\nNothing here is recorded automatically — if you actually buy one, "
                "send /buy <TICKER> <shares> <price> so /review can manage the stop.")
    lines.append("⚠️ Signals, not advice. Check news before acting.")
    return "\n".join(lines)


def _partial_trim_suggestion(ticker: str, shares: int, price: float) -> str | None:
    """Suggest trimming HALF a position (rounded to the nearest lot when the
    position is big enough to split) on a take-profit hit, instead of only
    offering a full exit. None if the position is too small to meaningfully
    halve (a 1-share position can't be split). Advisory text only — this
    does not change what papertrade.step() auto-queues."""
    from kala.papertrade import LOT_SIZE
    half = (shares // 2 // LOT_SIZE) * LOT_SIZE or shares // 2
    if half <= 0 or half >= shares:
        return None
    return (f"💡 or trim half: /sell {ticker} {half:,} {price:.0f} — locks in "
            f"{half:,} sh, lets {shares - half:,} ride (not a backtested rule, your call)")


def _add_more_suggestion(pt, ticker: str, price: float, stop: float, allocation: float,
                         risk_pct: float, max_positions: int,
                         cash_override: float | None = None) -> tuple[str, int]:
    """A sized 'could add' recommendation — same size_position() math /scan
    uses for fresh entries, so an add suggestion is risk-budgeted the same
    way a new position would be, not a bare yes/no flag. Returns (message,
    shares) — the caller decrements a running cash total by shares*price
    between positions, same reason /scan's new-buy ranking does: without
    it, an ADD suggestion on every held winner would each assume the FULL
    account cash independently, over-suggesting in total."""
    from kala.papertrade import LOT_SIZE
    add_shares = pt.size_position(price, stop, allocation, risk_pct=risk_pct,
                                  max_positions=max_positions, cash_override=cash_override)
    if add_shares >= LOT_SIZE:
        return (f"could add {add_shares:,} sh (~{idr(add_shares * price)}): "
                f"/buy {ticker} {add_shares} {price:.0f}", add_shares)
    return ("could add (budget too small for 1 lot)", 0)


def _evaluate_holdings(pt, cfg: dict) -> dict:
    """Core of /review, minus formatting: evaluate every open position
    through the real exit engine, plus a re-score for an ADD opinion.
    Returns a dict both cmd_review (full detail) and cmd_priority (ranked
    one-liners) build their output from — one evaluation, two renderings.

    Returns {"status": str|None, "records": list[dict]}. Each record:
    {"ticker", "no_data" (bool), "pnl_pct", "cur_price", "shares",
    "entry_price", "urgency" ("URGENT"/"CONSIDER"/"NONE"), "reason",
    "trim_suggestion", "add_suggestion", "add_score", "trail_stop",
    "bars_held", "max_days"} — fields beyond ticker/no_data are only
    populated when relevant."""
    import kala_daily_trader as dt
    from kala.live import evaluate_position
    from kala.papertrade import _bars_held

    allocation = float(cfg.get("daily_capital_idr", 5_000_000))
    max_pos = int(cfg.get("max_positions", 5))
    risk_pct = float(cfg.get("risk_pct_per_trade", 2.0))

    try:
        mkt = dt.check_market_health()
        status = mkt.get("status", "UNKNOWN")
    except Exception:
        mkt, status = None, None

    records: list[dict] = []
    # Same running-cash logic as _rank_new_buys: each ADD suggestion is
    # sized against what's left after the higher-ranked ones before it,
    # not the full account cash every time.
    remaining_cash = pt.cash
    for t, pos in pt.positions.items():
        try:
            h = dt.download_stock_data(t, dt.START_DATE, dt.END_DATE)
        except Exception as e:
            from kala.logging_util import log_swallowed
            log_swallowed(f"_evaluate_holdings({t})", e)
            h = None
        if h is None or len(h) < 60:
            records.append({"ticker": t, "no_data": True})
            continue

        r = evaluate_position(ticker=t, entry_price=pos.entry_price, history=h,
                              peak_price=pos.peak_price, market_status=status,
                              cfg=pt.cfg.risk)
        try:
            sig = dt.get_live_signal(t, dt.DEFAULT_FAST_SMA, dt.DEFAULT_SLOW_SMA,
                                     preloaded_data=h, market_health=mkt)
        except Exception:
            sig = None

        cur = r["current_price"]
        trail = r.get("trailing_stop_price")
        urgency = r["urgency"] if (r["exit_signal"] and r["urgency"] in ("URGENT", "CONSIDER")) else "NONE"
        reason = r["reasons"][0] if urgency != "NONE" else None

        # Max-holding-period: evaluate_exit() has no bars-held context (its
        # signature carries no entry_date/history-length), so this rule only
        # ever lived in papertrade.step()'s own loop. Without checking it
        # here too, /review and /priority would silently disagree with what
        # that evening's /run actually queues — a position could sit shown
        # as HOLD right up until the EOD run sells it. Never DOWNGRADES an
        # existing URGENT/CONSIDER verdict, same "urgency never downgrades"
        # rule the exit engine itself uses.
        bars_held = _bars_held(pos.entry_date, h)
        max_days = pt.cfg.backtest.holding_max_days
        if urgency == "NONE" and bars_held is not None and bars_held >= max_days:
            urgency = "CONSIDER"
            reason = f"max holding period ({bars_held} bars >= {max_days})"

        trim_suggestion = None
        if urgency == "CONSIDER" and reason and "target profit" in reason:
            trim_suggestion = _partial_trim_suggestion(t, pos.shares, cur)

        add_suggestion = add_score = None
        if sig:
            ssig = str(sig.get("signal", "")).upper()
            add_score = float(sig.get("technical_score", 0) or 0)
            # NONE only: a position already flagged SELL/TAKE-PROFIT this
            # run should never also be pitched as an add in the same
            # breath — /priority ranks these into separate, mutually
            # exclusive tiers, and showing both here would let the same
            # ticker land in two contradictory tiers at once.
            if ssig in ("BUY", "STRONG BUY") and urgency == "NONE":
                stop_for_sizing = trail if trail else cur * 0.95
                add_suggestion, add_shares = _add_more_suggestion(
                    pt, t, cur, stop_for_sizing, allocation, risk_pct, max_pos,
                    cash_override=remaining_cash)
                remaining_cash -= add_shares * cur

        records.append({
            "ticker": t, "no_data": False, "pnl_pct": r["profit_pct"], "cur_price": cur,
            "shares": pos.shares, "entry_price": pos.entry_price, "urgency": urgency,
            "reason": reason, "trim_suggestion": trim_suggestion,
            "add_suggestion": add_suggestion, "add_score": add_score,
            "trail_stop": trail, "bars_held": bars_held, "max_days": max_days,
        })
    return {"status": status, "records": records}


def cmd_review() -> str:
    """Review every open holding: HOLD vs SELL (exit ladder) and whether it
    still scores as a BUY (candidate to add). Two recommendations here are
    SIZED (specific shares + price, not just a yes/no flag):
      * "could add" reuses size_position() — the exact sizing math /scan
        uses for fresh entries — so an add suggestion is risk-budgeted the
        same way a new position would be, not a guess.
      * a take-profit (CONSIDER) hit also suggests trimming HALF the
        position instead of only offering a full exit. This is advisory,
        NOT a validated rule: the auto-queued order in papertrade.step()
        still sells 100% on this trigger, unchanged, because a partial-exit
        RULE changes the return profile and hasn't been backtested (same
        reasoning that kept rules 4-8 advisory-only in exits.py v3.3). This
        just gives you the option with real numbers instead of nothing.

    For a merged, ranked to-do list across this AND /scan together, see
    /priority."""
    from kala.papertrade import PaperTrader

    cfg = load_config()
    pt = PaperTrader.load(STATE_PATH, cfg.get("start_capital_idr", 10_000_000))
    if not pt.positions:
        return "You hold no paper positions right now. Send /scan for ideas."

    result = _evaluate_holdings(pt, cfg)
    lines = [f"🩺 *Holdings review* — {today_wib().isoformat()}",
             f"Market: {result['status'] or 'unknown'}\n"]

    for rec in result["records"]:
        t = rec["ticker"]
        if rec["no_data"]:
            lines.append(f"• {t}: ⏸ no fresh data (suspended?) — can't review")
            continue

        if rec["urgency"] != "NONE":
            verdict = f"🔴 *SELL* ({rec['urgency']}) — {rec['reason']}"
            if rec["trim_suggestion"]:
                verdict += f"\n    {rec['trim_suggestion']}"
        else:
            verdict = "🟢 *HOLD*"

        if rec["add_suggestion"]:
            add_note = f" | ➕ still scores BUY ({rec['add_score']:.0f}) — {rec['add_suggestion']}"
        elif rec["add_score"] is not None:
            add_note = f" | score {rec['add_score']:.0f}"
        else:
            add_note = ""

        trail_txt = f" | trail stop {price_idr(rec['trail_stop'])}" if rec["trail_stop"] else ""
        bars = rec["bars_held"]
        held_txt = f" | held {bars}/{rec['max_days']} bars" if bars is not None else ""
        lines.append(
            f"• *{t}* {rec['pnl_pct']:+.1f}%  ({price_idr(rec['entry_price'])}→{price_idr(rec['cur_price'])}, "
            f"{rec['shares']:,} sh)\n    {verdict}{add_note}{trail_txt}{held_txt}")

    lines.append("\n⚠️ Signals, not advice. Re-check the thesis before acting.")
    return "\n".join(lines)


def cmd_priority() -> str:
    """/priority — one ranked to-do list merging /review (your holdings) and
    /scan (new candidates), instead of reading two separate reports and
    figuring out the order yourself. Runs both underlying evaluations (same
    computations, same numbers — this doesn't re-derive anything) and sorts
    into five tiers by urgency:

      1. SELL NOW      — governing stop / death cross hit (capital at risk)
      2. TAKE PROFIT    — target-profit CONSIDER hit (lock in gains)
      3. ADD TO WINNERS — held positions that still score BUY, best score first
      4. NEW BUY IDEAS  — /scan candidates you don't hold, best score first
      5. everything else — HOLDs and skipped scan candidates, counted not listed

    Numbers are for THIS EOD read; re-run after market close, don't act on
    a mid-day rerun (see the /review-timing discussion — same principle)."""
    from kala.papertrade import PaperTrader

    cfg = load_config()
    pt = PaperTrader.load(STATE_PATH, cfg.get("start_capital_idr", 10_000_000))

    hold_result = _evaluate_holdings(pt, cfg) if pt.positions else {"status": None, "records": []}
    scan_result = _rank_new_buys(cfg, pt)

    status = hold_result["status"] or scan_result["status"]
    lines = [f"📌 *Priority actions* — {today_wib().isoformat()}",
             f"Market: {status or 'unknown'}"]

    sell_now = [r for r in hold_result["records"] if not r["no_data"] and r["urgency"] == "URGENT"]
    take_profit = [r for r in hold_result["records"] if not r["no_data"] and r["urgency"] == "CONSIDER"]
    # urgency == "NONE" only: a ticker already flagged SELL NOW/TAKE PROFIT
    # above must never ALSO show up here telling you to buy more of it —
    # _evaluate_holdings already enforces this (add_suggestion is only set
    # when urgency=="NONE"), this is a second, explicit guard at the tier
    # boundary so this list can never silently overlap the other two even
    # if that upstream invariant changes.
    add_more = sorted(
        [r for r in hold_result["records"]
         if not r["no_data"] and r["urgency"] == "NONE" and r["add_suggestion"]],
        key=lambda r: r["add_score"], reverse=True)
    new_buys = sorted([c for c in scan_result["candidates"] if c["kind"] == "sized"],
                      key=lambda c: c["score"], reverse=True)

    n = 0
    if sell_now:
        lines.append(f"\n🔴 *SELL NOW* ({len(sell_now)}) — capital at risk, don't wait for EOD on these")
        for r in sell_now:
            n += 1
            lines.append(f"{n}. {r['ticker']} {r['pnl_pct']:+.1f}% — {r['reason']}")

    if take_profit:
        lines.append(f"\n🟠 *TAKE PROFIT* ({len(take_profit)}) — target hit, lock in gains")
        for r in take_profit:
            n += 1
            line = f"{n}. {r['ticker']} {r['pnl_pct']:+.1f}% — {r['reason']}"
            if r["trim_suggestion"]:
                line += f"\n    {r['trim_suggestion']}"
            lines.append(line)

    if add_more:
        lines.append(f"\n➕ *ADD TO WINNERS* ({len(add_more)}, best score first)")
        for r in add_more:
            n += 1
            lines.append(f"{n}. {r['ticker']} — {r['add_suggestion']}")

    if new_buys:
        lines.append(f"\n🆕 *NEW BUY IDEAS* ({len(new_buys)}, best score first)")
        from kala.edge import entry_signal_warning
        warning = entry_signal_warning(cfg)
        if warning:
            lines.append(warning)
        for c in new_buys:
            n += 1
            lines.append(f"{n}. {c['ticker']} {c['tag']} (score {c['score']:.0f}) — "
                         f"{c['shares']:,} sh ≈ {idr(c['est'])} @ {price_idr(c['price'])}")

    if n == 0:
        lines.append("\nNothing urgent — no SELL/TAKE PROFIT/ADD signals on your holdings, "
                     "and no new BUY candidates cleared the budget/cap today.")

    holds = sum(1 for r in hold_result["records"] if not r["no_data"] and r["urgency"] == "NONE"
               and not r["add_suggestion"])
    no_data = sum(1 for r in hold_result["records"] if r["no_data"])
    skipped = sum(1 for c in scan_result["candidates"]
                  if c["kind"] in ("over_cap", "too_small", "held"))
    footer = []
    if holds:
        footer.append(f"{holds} holding(s): HOLD, nothing to do")
    if no_data:
        footer.append(f"{no_data} holding(s): no fresh data, couldn't evaluate")
    if skipped:
        footer.append(f"{skipped} scan candidate(s) skipped (already held / over cap / too small)")
    if footer:
        lines.append("\n⚪ " + " | ".join(footer))

    lines.append("\n⚠️ Signals, not advice. /review and /scan for full detail on any of these.")
    return "\n".join(lines)


def cmd_run() -> str:
    """Trigger the full daily cycle. daily_run sends its own detailed message;
    we just kick it and confirm. Since runner_config.json's auto_paper_trade
    defaults to False, this only MANAGES positions you already /buy'd
    (exits) and RECOMMENDS new ones — it does not open positions on its
    own. Set auto_paper_trade=True to restore the old fully-autonomous
    paper-trading benchmark instead."""
    import daily_run
    daily_run.main()
    return "▶️ Daily cycle finished — see the detailed message just above."


def cmd_news(arg: str) -> str:
    """Headlines + sentiment for one ticker — the same engine kala_engine.py's
    dashboard and the daily runner use. ADVISORY ONLY: sentiment has no
    historical archive, so it can never be walk-forward validated and must
    never feed the signal. It informs you, not the engine."""
    if not arg.strip():
        return "Usage: /news <TICKER> — e.g. /news ANTM"
    ticker = normalize_ticker(arg.split()[0])
    from kala.news import get_news_sentiment, scrape_idx_announcements, scrape_indonesian_news
    score, n, desc = get_news_sentiment(ticker)
    lines = [f"📰 *{ticker}* — news check (advisory only)", desc]
    headlines = ([f"• {a} ({s})" for a, s, _ in scrape_idx_announcements(ticker)[:3]]
                 + [f"• {h} ({s})" for h, s in scrape_indonesian_news(ticker)[:3]])
    if headlines:
        lines.append("")
        lines.extend(headlines[:6])
    if n:
        lines.append(f"\nSentiment score: {score:.0f}/100 across {n} items "
                     "(does NOT affect BUY/SELL — trade the /scan signal)")
    return "\n".join(lines)


# =========================================================================
# Dispatch
# =========================================================================

def dispatch(text: str) -> str:
    """Map an incoming message to a reply. Pure routing + arg parsing; the
    action functions do the work."""
    text = (text or "").strip()
    if not text:
        return ""
    parts = text.split(maxsplit=1)
    cmd = parts[0].lower().lstrip("/").split("@")[0]   # tolerate /cmd@BotName
    arg = parts[1] if len(parts) > 1 else ""

    if cmd in ("start", "help", "menu"):
        return cmd_help()
    if cmd in ("capital", "budget", "modal"):
        return cmd_capital(arg)
    if cmd in ("maxpositions", "maxpos", "slots"):
        return cmd_maxpositions(arg)
    if cmd in ("deposit", "topup", "setor"):
        return cmd_deposit(arg)
    if cmd in ("dividend", "dividen"):
        return cmd_dividend(arg)
    if cmd in ("rebalance", "rebalancing", "seimbang"):
        return cmd_rebalance(arg)
    if cmd in ("friction", "cost", "costs", "biaya", "fee"):
        return cmd_friction(arg)
    if cmd in ("buy", "beli"):
        return cmd_buy(arg)
    if cmd in ("sell", "jual"):
        return cmd_sell(arg)
    if cmd in ("editentry", "edit", "editharga", "fixentry", "koreksi"):
        return cmd_editentry(arg)
    if cmd in ("undo", "batal"):
        return cmd_undo()
    if cmd in ("redo", "ulangi"):
        return cmd_redo()
    if cmd in ("positions", "mystocks", "list", "punya"):
        return cmd_positions()
    if cmd in ("scan", "recommend", "rekom", "rekomendasi"):
        return cmd_scan(arg or None)
    if cmd in ("review", "portfolio", "holdings", "cek", "hold"):
        return cmd_review()
    if cmd in ("priority", "prioritas", "todo", "aksi"):
        return cmd_priority()
    if cmd in ("status", "summary", "akun"):
        return cmd_status()
    if cmd in ("history", "riwayat", "log"):
        return cmd_history(arg)
    if cmd in ("performance", "dashboard", "kinerja", "weekly"):
        return cmd_performance(arg)
    if cmd in ("ask", "tanya", "query"):
        return cmd_ask(arg)
    if cmd in ("taxreport", "pajak"):
        return cmd_taxreport(arg)
    if cmd in ("edge", "track", "vsbacktest"):
        return cmd_edge()
    if cmd in ("checkstop", "cekstop", "stoploss", "sl"):
        return cmd_checkstop()
    if cmd in ("run", "daily", "jalankan"):
        return cmd_run()
    if cmd in ("news", "berita", "sentiment"):
        return cmd_news(arg)
    if cmd in ("reset", "ulang"):
        return cmd_reset(arg)
    return "Unknown command. Send /help for the menu."


# =========================================================================
# Telegram transport + polling loop
# =========================================================================

class Bot:
    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = str(chat_id)
        self.offset = None

    def _api(self, method: str, **params):
        r = requests.post(API.format(token=self.token, method=method),
                          json=params, timeout=POLL_TIMEOUT + 10)
        r.raise_for_status()
        return r.json()

    def send(self, text: str, chat_id: str | None = None):
        for part in chunk(text):
            try:
                self._api("sendMessage", chat_id=chat_id or self.chat_id,
                          text=part, parse_mode="Markdown")
            except Exception:
                # Markdown can choke on stray characters; retry as plain text
                self._api("sendMessage", chat_id=chat_id or self.chat_id, text=part)

    def send_photo(self, photo_bytes: bytes, caption: str = "", chat_id: str | None = None):
        """sendPhoto needs multipart/form-data (a file upload), not the
        JSON POST _api() uses for text methods — Telegram's Bot API has no
        JSON-only way to attach binary image data."""
        r = requests.post(
            API.format(token=self.token, method="sendPhoto"),
            data={"chat_id": chat_id or self.chat_id, "caption": caption},
            files={"photo": ("chart.png", photo_bytes, "image/png")},
            timeout=POLL_TIMEOUT + 10,
        )
        r.raise_for_status()
        return r.json()

    def send_document(self, doc_bytes: bytes, filename: str, caption: str = "",
                      chat_id: str | None = None):
        """sendDocument — same multipart requirement as sendPhoto, used for
        the /report HTML dashboard (Telegram doesn't render/preview HTML
        inline, but a document upload lets the user download and open it
        in a real browser)."""
        r = requests.post(
            API.format(token=self.token, method="sendDocument"),
            data={"chat_id": chat_id or self.chat_id, "caption": caption},
            files={"document": (filename, doc_bytes, "text/html")},
            timeout=POLL_TIMEOUT + 10,
        )
        r.raise_for_status()
        return r.json()

    def poll(self):
        resp = self._api("getUpdates", offset=self.offset, timeout=POLL_TIMEOUT)
        return resp.get("result", [])

    def run(self):
        from kala.heartbeat import write_heartbeat

        print(f"Bot online. Authorised chat: {self.chat_id}. Ctrl-C to stop.")
        # Drain any backlog so we don't replay old commands on restart.
        try:
            for u in self.poll():
                self.offset = u["update_id"] + 1
        except Exception as e:
            print(f"Initial poll failed: {e}")

        self.send("🤖 Kala bot online. Send /help for commands.")
        write_heartbeat()
        while True:
            try:
                write_heartbeat()   # touched once per poll cycle -- see
                                    # kala/heartbeat.py + healthcheck.py
                for u in self.poll():
                    self.offset = u["update_id"] + 1
                    msg = u.get("message") or u.get("edited_message")
                    if not msg:
                        continue
                    incoming_chat = str(msg.get("chat", {}).get("id", ""))
                    text = msg.get("text", "")
                    if incoming_chat != self.chat_id:
                        print(f"Ignored message from unauthorised chat {incoming_chat}")
                        continue
                    if not text.strip():
                        # A photo, sticker or location has no "text". Without
                        # this, the split below raises IndexError, the loop's
                        # catch-all sleeps 5s and prints a traceback — every
                        # time you send the bot an image by accident.
                        continue
                    print(f"< {text}")
                    cmd_word = text.split(maxsplit=1)[0].lower().lstrip("/").split("@")[0]
                    if cmd_word in ("scan", "recommend", "rekom", "rekomendasi", "run", "daily", "jalankan",
                                    "priority", "prioritas", "todo", "aksi"):
                        self.send("⏳ Working… scanning ~600 stocks, this takes a few minutes.")
                    if cmd_word in ("chart", "equity", "curve", "grafik"):
                        try:
                            png, caption = build_equity_chart_png()
                            if png is not None:
                                self.send_photo(png, caption=caption)
                            else:
                                self.send(caption)
                            print("> replied (chart)")
                        except Exception as e:
                            self.send(f"⚠️ Error: {md_escape(e)}")
                            print(traceback.format_exc(limit=3))
                        continue
                    if cmd_word in ("report", "laporan", "fulldashboard"):
                        self.send("⏳ Building the full report (fetching live prices)…")
                        try:
                            html_bytes, caption = build_dashboard_document()
                            if html_bytes is not None:
                                self.send_document(html_bytes, "dashboard.html", caption=caption)
                            else:
                                self.send(caption)
                            print("> replied (report)")
                        except Exception as e:
                            self.send(f"⚠️ Error: {md_escape(e)}")
                            print(traceback.format_exc(limit=3))
                        continue
                    try:
                        reply = dispatch(text)
                    except Exception as e:
                        reply = f"⚠️ Error: {md_escape(e)}"
                        print(traceback.format_exc(limit=3))
                    if reply:
                        self.send(reply)
                        print(f"> replied ({len(reply)} chars)")
            except KeyboardInterrupt:
                print("\nStopping.")
                self.send("🤖 Bot going offline.")
                return
            except Exception as e:
                print(f"Loop error: {e} — retrying in 5s")
                time.sleep(5)


def main():
    from kala.notify import CHAT_ID_ENV, TOKEN_ENV, resolve_telegram_credentials
    cfg = load_config()
    token, chat_id = resolve_telegram_credentials(cfg)
    if not token or not chat_id:
        print(f"Telegram credentials missing. Provide them via the {TOKEN_ENV} / "
              f"{CHAT_ID_ENV} environment variables (preferred on a server) or "
              "telegram_token / telegram_chat_id in runner_config.json. "
              "Run test_ping.py first to confirm them.")
        return
    Bot(token, chat_id).run()


if __name__ == "__main__":
    main()
