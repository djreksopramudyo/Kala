"""
Intraday guard — the *useful* version of "ping me every 5 minutes".

Your whole system is end-of-day: signal at close, fill at next open, exits
evaluated once per evening. That leaves exactly one blind spot: a position can
blow through its stop at 10:30 and you would not hear about it until 17:00.
This module closes that gap WITHOUT turning your phone into a slot machine:

  * It watches ONLY things you already own or already researched
    (paper positions + watchlist). It never generates new BUY ideas intraday —
    that would be a different, faster strategy than the one you backtested.
  * It alerts on STATE CHANGES, once per ticker per event per day:
        STOP  — price at/below the governing (trailing) stop right now
        ARB   — price pinned near IDX auto-rejection lower bound (limit down)
        DIP   — watchlist name crossed your margin-of-safety discount
        TP    — price reached the take-profit target intraday
  * Optional low-frequency "pulse" snapshot so you know it is alive.

Everything here is pure (tested); the network + scheduling glue lives in
``intraday_watch.py`` at the repo root.

Honesty note: Yahoo's IDX quotes are delayed ~10–20 minutes. Polling every
5 minutes therefore buys you nothing over every 15 — the data itself is older
than that. The scheduler script uses 15 minutes.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path

from .config import RiskConfig
from .exits import governing_stop

# IDX regular trading sessions, WIB (post-April-2023 schedule).
# Mon-Thu: 09:00-12:00 and 13:30-15:50 | Fri: 09:00-11:30 and 14:00-15:50
_SESSIONS_MON_THU = ((time(9, 0), time(12, 0)), (time(13, 30), time(15, 50)))
_SESSIONS_FRI = ((time(9, 0), time(11, 30)), (time(14, 0), time(15, 50)))


def is_idx_open(now: datetime) -> bool:
    """True during IDX regular sessions (local clock assumed to be WIB)."""
    wd = now.weekday()
    if wd >= 5:  # Sat/Sun
        return False
    sessions = _SESSIONS_FRI if wd == 4 else _SESSIONS_MON_THU
    t = now.time()
    return any(a <= t <= b for a, b in sessions)


def arb_lower_limit_pct(prev_close: float) -> float:
    """IDX auto-rejection lower bound (symmetric ARB, restored 2023) by tier.

    IDR 50-200: 35% | IDR >200-5,000: 25% | IDR >5,000: 20%
    """
    if prev_close <= 200:
        return 35.0
    if prev_close <= 5000:
        return 25.0
    return 20.0


@dataclass
class Quote:
    """A delayed intraday snapshot for one ticker."""
    ticker: str
    price: float          # latest (delayed) price
    prev_close: float     # yesterday's close
    day_high: float       # today's high so far (for the trailing peak)


def position_stop_status(pos, quote: Quote, cfg: RiskConfig | None = None) -> dict:
    """Current price vs. this position's stop-loss AND take-profit target
    RIGHT NOW — for every held position, not just ones that have breached a
    threshold. "When to sell" has two sides: cut the loss (stop) or lock in
    the gain (target), and showing only one is half the answer. Same
    read-only peak/governing_stop computation position_alerts uses
    internally (this IS what it uses — single source of truth, so a status
    line and an alert can never quietly disagree about where the stop is).

    target_distance_pct: positive = still short of the target (needs to
    rise that much more); <= 0 = at/past it — the SAME condition
    position_alerts' TP rule fires on, just always visible here instead of
    only when it fires.

    Read-only, same guarantee as position_alerts: never mutates pos.peak_price.
    """
    cfg = cfg or RiskConfig()
    peak = max(pos.peak_price, quote.day_high or quote.price)
    stop, phase, label = governing_stop(pos.entry_price, peak, pos.entry_atr, cfg)
    pnl_pct = (quote.price / pos.entry_price - 1.0) * 100.0
    # NaN-safe: `quote.price > 0` is False for NaN too (Python), so a caller
    # that (against the contract) hands in a bad quote used to fall through
    # to a fabricated 0.0 -- which reads as "exactly at the stop" and fires
    # a false alarm. math.nan here instead: honestly "unknown", and every
    # comparison against NaN is False, so it can't misfire any flag/icon.
    price_ok = math.isfinite(quote.price) and quote.price > 0
    distance_pct = ((quote.price - stop) / quote.price * 100.0) if price_ok else math.nan
    target = pos.entry_price * (1.0 + cfg.target_profit_pct / 100.0)
    target_distance_pct = ((target - quote.price) / quote.price * 100.0) if price_ok else math.nan
    return {"ticker": pos.ticker, "price": quote.price, "stop": stop, "phase": phase,
            "label": label, "pnl_pct": pnl_pct, "distance_pct": distance_pct,
            "target": target, "target_distance_pct": target_distance_pct}


def position_alerts(pos, quote: Quote, cfg: RiskConfig | None = None) -> list[dict]:
    """Alerts for one held position given a fresh quote.

    ``pos`` needs .ticker, .entry_price, .peak_price, .entry_atr — i.e. a
    ``papertrade.PaperPosition``. Read-only: the daily run owns the state file;
    the watcher must never mutate peaks, or the EOD close-based trailing
    convention would silently drift.
    """
    cfg = cfg or RiskConfig()
    out = []
    status = position_stop_status(pos, quote, cfg)
    stop, phase, label = status["stop"], status["phase"], status["label"]
    pnl_pct = status["pnl_pct"]

    if quote.price <= stop:
        out.append({
            "type": "STOP", "ticker": pos.ticker,
            "text": (f"🛑 {pos.ticker} hit its stop intraday: {quote.price:,.0f} "
                     f"<= stop {stop:,.0f} ({label}, phase {phase}) | "
                     f"P&L {pnl_pct:+.1f}%. EOD run will queue the SELL — "
                     f"act sooner manually if you mirror trades."),
        })

    if quote.prev_close > 0:
        drop_pct = (quote.prev_close - quote.price) / quote.prev_close * 100.0
        limit = arb_lower_limit_pct(quote.prev_close)
        if drop_pct >= limit - 0.5:  # pinned at/near the band
            out.append({
                "type": "ARB", "ticker": pos.ticker,
                "text": (f"🚨 {pos.ticker} is at/near LIMIT DOWN "
                         f"(-{drop_pct:.1f}% vs ARB band -{limit:.0f}%). "
                         f"Sell orders may not fill — expect the stop to gap."),
            })

    if pnl_pct >= cfg.target_profit_pct:
        out.append({
            "type": "TP", "ticker": pos.ticker,
            "text": (f"🎯 {pos.ticker} reached take-profit intraday: "
                     f"{pnl_pct:+.1f}% (target {cfg.target_profit_pct:+.0f}%)."),
        })
    return out


def watchlist_alerts(items, quotes: dict[str, Quote],
                     min_discount_pct: float) -> list[dict]:
    """DIP alerts for watchlist entries whose live price crossed the
    margin-of-safety threshold. ``items`` iterates WatchlistItem."""
    out = []
    for item in items:
        q = quotes.get(item.ticker)
        if q is None or q.price <= 0 or item.fair_value <= 0:
            continue
        disc = item.discount_pct(q.price)
        if disc >= min_discount_pct:
            out.append({
                "type": "DIP", "ticker": item.ticker,
                "text": (f"💎 {item.ticker} intraday dip: {disc:.0f}% below fair "
                         f"({q.price:,.0f} vs {item.fair_value:,.0f})"
                         + (f" — {item.thesis}" if item.thesis else "")),
            })
    return out


class AlertDedup:
    """Once-per-day-per-(ticker,type) gate, persisted to a tiny JSON file so
    repeated scheduler runs stay silent after the first alert."""

    def __init__(self, path):
        self.path = Path(path)
        self._seen: dict = {}
        if self.path.exists():
            try:
                self._seen = json.loads(self.path.read_text())
            except Exception:
                self._seen = {}

    def filter_new(self, alerts: list[dict], today: str) -> list[dict]:
        day = self._seen.setdefault(today, [])
        fresh = []
        for a in alerts:
            key = f"{a['ticker']}|{a['type']}"
            if key not in day:
                day.append(key)
                fresh.append(a)
        # prune old days so the file never grows
        self._seen = {today: day}
        return fresh

    def save(self):
        try:
            self.path.parent.mkdir(exist_ok=True)
            self.path.write_text(json.dumps(self._seen))
        except Exception:
            pass
