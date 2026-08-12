"""
Natural-language-ish queries over the paper trader's closed-trade log.

HONESTY NOTE: this is a keyword/pattern parser, NOT real natural-language
understanding -- no LLM call, no ambiguity resolution beyond simple regex
and phrase matching. It recognizes a fixed vocabulary (a ticker, a time
window like "this month"/"last 30 days", win/loss filters, best/worst
sorting) well enough for a Telegram ``/ask <text>`` command to feel
conversational, and falls back to "show everything" when nothing specific
is recognized -- it never silently misreads a query as something else.

Queries run over ``PaperTrader.log`` -- the list of closed-trade dicts
already appended in ``PaperTrader.step()`` (keys: date, ticker, entry,
exit, entry_date, shares, pnl_pct, reason).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass
class LogQuery:
    ticker: str | None = None
    since: str | None = None    # ISO date, inclusive
    until: str | None = None    # ISO date, inclusive
    outcome: str | None = None  # "win" | "loss"
    sort: str | None = None     # "best" | "worst" | "recent"
    limit: int | None = None


_TICKER_RE = re.compile(r"\b([A-Z]{2,5})(?:\.JK)?\b")
_LAST_N_DAYS_RE = re.compile(r"last (\d+) days?", re.IGNORECASE)
_LIMIT_RE = re.compile(r"\b(top|best|worst) (\d+)\b", re.IGNORECASE)

_STOPWORDS = {
    "HOW", "DID", "MY", "TRADES", "TRADE", "THIS", "LAST", "SHOW", "ME",
    "WHAT", "IS", "THE", "ON", "IN", "FOR", "WEEK", "MONTH", "YEAR",
    "TODAY", "YESTERDAY", "WIN", "RATE", "BEST", "WORST", "TOP", "ALL",
    "AND", "DAYS", "PNL", "P", "L", "SINCE", "FROM", "TO", "ABOUT",
}


def parse_query(text: str, today: date | None = None) -> LogQuery:
    """Best-effort structured query from a free-text question. Unrecognized
    words are ignored, not errored on -- a query like 'how did I do?' with
    nothing specific just returns everything."""
    today = today or date.today()
    raw = text.strip()

    query = LogQuery()

    # -- outcome ---------------------------------------------------------
    if re.search(r"\b(loss|losses|losing|rugi)\b", raw, re.IGNORECASE):
        query.outcome = "loss"
    elif re.search(r"\b(win|wins|winning|profit|untung)\b", raw, re.IGNORECASE):
        query.outcome = "win"

    # -- sort/limit --------------------------------------------------------
    limit_match = _LIMIT_RE.search(raw)
    if limit_match:
        query.sort = "best" if limit_match.group(1).lower() in ("top", "best") else "worst"
        query.limit = int(limit_match.group(2))
    elif re.search(r"\bbest\b", raw, re.IGNORECASE):
        query.sort = "best"
        query.limit = 1
    elif re.search(r"\bworst\b", raw, re.IGNORECASE):
        query.sort = "worst"
        query.limit = 1
    else:
        query.sort = "recent"

    # -- time window ---------------------------------------------------------
    n_days = _LAST_N_DAYS_RE.search(raw)
    if n_days:
        query.since = (today - timedelta(days=int(n_days.group(1)))).isoformat()
    elif re.search(r"\btoday\b", raw, re.IGNORECASE):
        query.since = query.until = today.isoformat()
    elif re.search(r"\byesterday\b", raw, re.IGNORECASE):
        y = (today - timedelta(days=1)).isoformat()
        query.since = query.until = y
    elif re.search(r"\bthis week\b", raw, re.IGNORECASE):
        query.since = (today - timedelta(days=7)).isoformat()
    elif re.search(r"\blast month\b", raw, re.IGNORECASE):
        first_of_this_month = today.replace(day=1)
        last_of_prev_month = first_of_this_month - timedelta(days=1)
        query.since = last_of_prev_month.replace(day=1).isoformat()
        query.until = last_of_prev_month.isoformat()
    elif re.search(r"\bthis month\b", raw, re.IGNORECASE):
        query.since = today.replace(day=1).isoformat()
    elif re.search(r"\bthis year\b|\bytd\b", raw, re.IGNORECASE):
        query.since = today.replace(month=1, day=1).isoformat()

    # -- ticker -----------------------------------------------------------
    # Matched against the ORIGINAL casing: a word already typed in caps
    # ("how did BBCA do") is a real signal it's a ticker, not just any
    # 2-5 letter word that happens to uppercase into something plausible.
    for word in _TICKER_RE.findall(raw):
        if word not in _STOPWORDS:
            query.ticker = word
            break

    return query


def filter_trades(log: list[dict], query: LogQuery) -> list[dict]:
    """Apply ``query`` to the raw trade log. Trades are matched on their
    EXIT date (the ``date`` key) -- the day the trade actually closed and
    entered the record, not when it was opened."""
    out = log
    if query.ticker:
        wanted = query.ticker.upper()
        out = [t for t in out if t.get("ticker", "").upper().split(".")[0] == wanted]
    if query.since:
        out = [t for t in out if str(t.get("date", "")) >= query.since]
    if query.until:
        out = [t for t in out if str(t.get("date", "")) <= query.until]
    if query.outcome == "win":
        out = [t for t in out if t.get("pnl_pct", 0.0) > 0]
    elif query.outcome == "loss":
        out = [t for t in out if t.get("pnl_pct", 0.0) <= 0]

    if query.sort == "best":
        out = sorted(out, key=lambda t: t.get("pnl_pct", 0.0), reverse=True)
    elif query.sort == "worst":
        out = sorted(out, key=lambda t: t.get("pnl_pct", 0.0))
    else:
        out = sorted(out, key=lambda t: str(t.get("date", "")), reverse=True)

    if query.limit is not None:
        out = out[:query.limit]
    return out


def summarize(trades: list[dict]) -> dict:
    n = len(trades)
    if n == 0:
        return {"n": 0, "n_wins": 0, "win_rate_pct": 0.0, "avg_pnl_pct": 0.0,
                "best": None, "worst": None}
    pnls = [t.get("pnl_pct", 0.0) for t in trades]
    n_wins = sum(1 for p in pnls if p > 0)
    best = max(trades, key=lambda t: t.get("pnl_pct", 0.0))
    worst = min(trades, key=lambda t: t.get("pnl_pct", 0.0))
    return {"n": n, "n_wins": n_wins, "win_rate_pct": n_wins / n * 100.0,
           "avg_pnl_pct": sum(pnls) / n, "best": best, "worst": worst}


def answer(text: str, log: list[dict], today: date | None = None) -> str:
    """The single entry point: parse the question, filter/sort the log,
    and format a short reply -- what a Telegram ``/ask`` handler would call
    directly."""
    query = parse_query(text, today=today)
    matches = filter_trades(log, query)

    if not matches:
        return "No matching trades found."

    if query.limit is not None and query.sort in ("best", "worst"):
        lines = []
        for t in matches:
            lines.append(f"{t.get('date', '?')} {t.get('ticker', '?')}: "
                         f"{t.get('pnl_pct', 0.0):+.1f}% ({t.get('reason', '')})")
        return "\n".join(lines)

    stats = summarize(matches)
    lines = [
        f"{stats['n']} trade(s), win rate {stats['win_rate_pct']:.0f}%, "
        f"avg {stats['avg_pnl_pct']:+.1f}%/trade",
    ]
    if stats["best"]:
        b = stats["best"]
        lines.append(f"  best:  {b.get('ticker', '?')} {b.get('pnl_pct', 0.0):+.1f}%")
    if stats["worst"]:
        w = stats["worst"]
        lines.append(f"  worst: {w.get('ticker', '?')} {w.get('pnl_pct', 0.0):+.1f}%")
    return "\n".join(lines)
