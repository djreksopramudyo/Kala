"""
Watchlist with thesis memory and fair-value alerts.

The value-investing loop this enables: your fundamental screen finds a quality
company that is currently too expensive -> you park it here WITH the fair value
and a one-line thesis -> when the price later dips below your margin-of-safety
threshold, the daily check raises an alert and you can act on research you
already did. Without persistence, the screener recomputes everything and
remembers nothing — this is the memory.

Same JSON-store pattern as ``positions.PositionStore``.

A NOTE ON EMPTINESS
-------------------
``len(store) == 0`` used to mean four different things at once: you have not
built a watchlist yet; the process is running in a directory where the file
is not; the file was truncated by a crash during a non-atomic save; or the
watchlist really is empty. Callers received the same number in every case and
several of them swallowed the difference entirely.

Two changes keep those apart. ``save`` writes through a temp file so a crash
can no longer produce the third state at all, and ``load_or_report`` names the
resolved path and the reason whenever the answer is zero — so an operator can
tell "nothing researched yet" from "looking in the wrong place".
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path


@dataclass
class WatchlistItem:
    ticker: str
    fair_value: float                 # your estimate of intrinsic value / share
    score: float | None = None        # screener score at the time of adding
    thesis: str = ""                  # one-liner: WHY this is on the list
    added: str = field(default_factory=lambda: date.today().isoformat())
    source: str = ""                  # e.g. "fundamental_screen"

    def discount_pct(self, price: float) -> float:
        """How far below fair value the price sits, in percent.
        Positive = trading BELOW fair value (a discount)."""
        return (self.fair_value - price) / self.fair_value * 100.0


class WatchlistStore:
    def __init__(self, path, items: dict[str, WatchlistItem] | None = None):
        self.path = Path(path)
        self._items: dict[str, WatchlistItem] = items or {}
        # Why this store is empty, when it is. None means "loaded cleanly" —
        # including a clean load of a genuinely empty file.
        self.load_note: str | None = None

    # ---- persistence -------------------------------------------------------
    @classmethod
    def load(cls, path) -> "WatchlistStore":
        """Read the watchlist, raising on a file that exists but will not parse.

        The raise is deliberate and is not softened here: a damaged watchlist
        is not an empty one, and the callers that let it crash them are the
        ones behaving correctly. ``load_or_report`` exists for the callers
        that must survive it.
        """
        path = Path(path)
        if not path.exists():
            store = cls(path)
            store.load_note = f"no file at {path.resolve()}"
            return store
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls(path, {t: WatchlistItem(**rec) for t, rec in raw.items()})

    def save(self) -> None:
        """Atomic write, same tmp-then-replace discipline as paper_state.json.

        The watchlist is research output — a fair value and a thesis you sat
        down and worked out. A plain ``write_text`` truncates the target
        before it writes, so an interrupted save leaves that research nowhere
        on disk. ``os.replace`` is atomic on POSIX and Windows alike, so the
        previous watchlist survives intact until the new one is fully written.
        """
        payload = json.dumps({t: asdict(i) for t, i in self._items.items()},
                             indent=2, sort_keys=True)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, self.path)

    # ---- access ------------------------------------------------------------
    def add(self, item: WatchlistItem, replace: bool = True) -> None:
        """Add or (by default) update an entry. A refreshed fair value should
        replace a stale one; pass ``replace=False`` to forbid overwrites."""
        if not replace and item.ticker in self._items:
            raise ValueError(f"{item.ticker} already on the watchlist")
        self._items[item.ticker] = item

    def get(self, ticker: str) -> WatchlistItem | None:
        return self._items.get(ticker)

    def remove(self, ticker: str) -> None:
        self._items.pop(ticker, None)

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self):
        return iter(self._items.values())

    # ---- alerts ------------------------------------------------------------
    def alerts(self, prices: dict[str, float], min_discount_pct: float = 15.0) -> list[dict]:
        """Given current prices, return the entries now trading at least
        ``min_discount_pct`` below their saved fair value — i.e. the dips worth
        re-checking. Sorted deepest discount first. Tickers without a price are
        skipped (not everything trades every day)."""
        out = []
        for item in self._items.values():
            price = prices.get(item.ticker)
            if price is None or price <= 0 or item.fair_value <= 0:
                continue
            disc = item.discount_pct(price)
            if disc >= min_discount_pct:
                out.append({
                    "ticker": item.ticker,
                    "price": price,
                    "fair_value": item.fair_value,
                    "discount_pct": disc,
                    "thesis": item.thesis,
                    "added": item.added,
                    "score": item.score,
                })
        out.sort(key=lambda d: d["discount_pct"], reverse=True)
        return out


def load_or_report(path, warn=None) -> WatchlistStore:
    """Load a watchlist for a caller that must not crash, and say what happened.

    Three call sites (``archive_sentiment``, ``archive_fundamentals``,
    ``foreign_flow_monitor``) build their ticker universe from open positions
    plus the watchlist, and deliberately degrade to "this source contributes
    nothing" rather than aborting a whole archiving run. That decision is
    sound and is preserved here.

    What is not preserved is the silence. ``except Exception: pass`` rendered a
    truncated file, a wrong working directory and a genuinely empty watchlist
    as the same zero, and for a point-in-time archive that zero is permanent —
    yesterday's snapshot cannot be taken again tomorrow. So every non-clean
    read is reported with the path it actually resolved to, which is the one
    fact that distinguishes the cases.
    """
    warn = warn or (lambda msg: print(msg, file=sys.stderr))
    path = Path(path)
    try:
        store = WatchlistStore.load(path)
    except Exception as e:  # noqa: BLE001 - reported, not swallowed
        store = WatchlistStore(path)
        store.load_note = (f"{path.resolve()} exists but could not be read ({e}); "
                           f"it is damaged, not empty")
        warn(f"WARNING: watchlist unreadable — {store.load_note}. "
             f"Contributing 0 names to this run.")
        return store

    if store.load_note:  # file absent
        warn(f"NOTE: {store.load_note} — contributing 0 watchlist names. "
             f"Run kala_fundamental_only.py to build one, or check that "
             f"this process is running from the repository root.")
    return store
