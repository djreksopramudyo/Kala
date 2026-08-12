"""
INTRADAY WATCH — the small, fast sibling of daily_run.py.
==========================================================

Task Scheduler calls this every 15 minutes during market hours (see
setup_intraday_scheduler.ps1). It is READ-ONLY and event-driven:

  * exits silently when IDX is closed (weekends, lunch break, evenings);
  * fetches delayed quotes ONLY for held paper positions + watchlist names
    (a handful of tickers, ~2-5 s — not the 600+ universe scan);
  * sends a Telegram message ONLY when something changed state today:
    stop breached, limit-down pin, take-profit reached, watchlist dip;
  * each (ticker, event) alerts at most once per day — no spam, no repeats;
  * optional heartbeat: set "intraday_pulse_minutes" in runner_config.json
    (e.g. 60) to also get a compact portfolio snapshot at most that often.
    Leave it 0/absent for events-only (recommended — you WILL mute a bot
    that pings every 15 minutes with nothing to say).

It never touches paper_state.json — daily_run.py owns all trading decisions.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent
CONFIG_PATH = ROOT / "runner_config.json"
STATE_PATH = ROOT / "paper_state.json"
DEDUP_PATH = ROOT / "results" / "intraday_alerts.json"
PULSE_PATH = ROOT / "results" / "intraday_pulse.txt"


def get_quotes(tickers: set[str]) -> dict:
    """Delayed snapshot per ticker via yfinance 2-day daily bars: today's
    partial bar carries the live-ish Close/High, yesterday's Close is prev.

    A ticker is OMITTED (not included with a broken value) if today's bar
    hasn't posted a real number yet -- yfinance can return NaN for the
    newest row before it's filled in (e.g. just after a session rolls over
    to a new calendar day, or an illiquid name with no prints yet). Passing
    a NaN price downstream used to get silently turned into a fake "0%
    distance to stop" by position_stop_status, which read as a false
    stop-hit alarm on every affected position. Skipping it here instead
    means the caller's existing "N position(s) couldn't get a fresh quote"
    fallback handles it honestly."""
    import math

    import yfinance as yf

    from kala.intraday import Quote

    quotes = {}
    for t in tickers:
        try:
            h = yf.Ticker(t).history(period="5d")
            if h is None or len(h) < 2:
                continue
            price = float(h["Close"].iloc[-1])
            prev_close = float(h["Close"].iloc[-2])
            day_high = float(h["High"].iloc[-1])
            if not (math.isfinite(price) and math.isfinite(prev_close)
                    and math.isfinite(day_high) and price > 0):
                continue
            quotes[t] = Quote(ticker=t, price=price, prev_close=prev_close,
                              day_high=day_high)
        except Exception as e:
            from kala.logging_util import log_swallowed
            log_swallowed(f"get_quotes({t})", e)
    return quotes


def maybe_pulse(cfg, positions, quotes, now) -> str | None:
    """Return a snapshot message if the pulse interval elapsed, else None."""
    every = int(cfg.get("intraday_pulse_minutes", 0) or 0)
    if every <= 0 or not positions:
        return None
    try:
        last = datetime.fromisoformat(PULSE_PATH.read_text().strip())
        if (now - last).total_seconds() < every * 60:
            return None
    except Exception:
        pass  # no pulse yet today -> send one
    PULSE_PATH.parent.mkdir(exist_ok=True)
    PULSE_PATH.write_text(now.isoformat())

    lines = [f"⏱ Kala intraday {now.strftime('%H:%M')} WIB (quotes delayed ~15m)"]
    for t, p in positions.items():
        q = quotes.get(t)
        if not q:
            continue
        pnl = (q.price / p.entry_price - 1) * 100
        lines.append(f"  {t}: {q.price:,.0f} ({pnl:+.1f}%)")
    return "\n".join(lines)


def main():
    from kala.clock import now_wib
    now = now_wib()   # WIB, not server-local — is_idx_open must judge the IDX clock

    from kala.intraday import AlertDedup, is_idx_open, position_alerts, watchlist_alerts

    force = "--force" in sys.argv  # for testing outside market hours
    if not is_idx_open(now) and not force:
        return  # closed -> exit silently, costs nothing

    cfg = json.loads(CONFIG_PATH.read_text()) if CONFIG_PATH.exists() else {}

    from kala.notify import resolve_telegram_credentials, send_telegram
    from kala.papertrade import PaperTrader
    from kala.watchlist import WatchlistStore

    pt = PaperTrader.load(STATE_PATH, cfg.get("start_capital_idr", 10_000_000))
    wl = WatchlistStore.load(ROOT / "watchlist.json")

    tickers = set(pt.positions.keys()) | {i.ticker for i in wl}
    if not tickers:
        return  # nothing held, nothing watched -> nothing to do

    quotes = get_quotes(tickers)

    alerts = []
    for t, pos in pt.positions.items():
        q = quotes.get(t)
        if q:
            alerts += position_alerts(pos, q)
    alerts += watchlist_alerts(wl, quotes,
                               cfg.get("watchlist_min_discount_pct", 15.0))

    dedup = AlertDedup(DEDUP_PATH)
    fresh = dedup.filter_new(alerts, now.date().isoformat())
    dedup.save()

    parts = []
    if fresh:
        parts.append("\n".join(a["text"] for a in fresh))
    pulse = maybe_pulse(cfg, pt.positions, quotes, now)
    if pulse:
        parts.append(pulse)

    if parts:
        tg_token, tg_chat_id = resolve_telegram_credentials(cfg)
        send_telegram(tg_token, tg_chat_id, "\n\n".join(parts))


if __name__ == "__main__":
    main()
