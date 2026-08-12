"""
Watchlist with thesis memory and fair-value alerts.

The value-investing loop this enables: your fundamental screen finds a quality
company that is currently too expensive -> you park it here WITH the fair value
and a one-line thesis -> when the price later dips below your margin-of-safety
threshold, the daily check raises an alert and you can act on research you
already did. Without persistence, the screener recomputes everything and
remembers nothing — this is the memory.

Same JSON-store pattern as ``positions.PositionStore``.
"""

from __future__ import annotations

import json
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

    # ---- persistence -------------------------------------------------------
    @classmethod
    def load(cls, path) -> "WatchlistStore":
        path = Path(path)
        if not path.exists():
            return cls(path)
        raw = json.loads(path.read_text())
        return cls(path, {t: WatchlistItem(**rec) for t, rec in raw.items()})

    def save(self) -> None:
        self.path.write_text(
            json.dumps({t: asdict(i) for t, i in self._items.items()},
                       indent=2, sort_keys=True)
        )

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
