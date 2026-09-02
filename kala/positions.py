"""
Position state with persistent peak tracking.

The trailing stop is only as good as the peak it ratchets against, and that
peak has to survive between runs (you check your portfolio once a day, not in a
long-lived process). ``PositionStore`` is a tiny JSON-backed store that
persists ``peak_price`` so the trailing logic actually works day to day.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class Position:
    ticker: str
    entry_price: float
    shares: float
    peak_price: float | None = None

    def __post_init__(self):
        # A brand-new position's peak is its entry until the market prints higher.
        if self.peak_price is None:
            self.peak_price = self.entry_price

    def update_peak(self, price: float) -> float:
        """Ratchet the peak upward only; a lower print never lowers it."""
        self.peak_price = max(self.peak_price, price)
        return self.peak_price


class PositionStore:
    def __init__(self, path, positions: dict[str, Position] | None = None):
        self.path = Path(path)
        self._positions: dict[str, Position] = positions or {}

    # ---- persistence -------------------------------------------------------
    @classmethod
    def load(cls, path) -> "PositionStore":
        path = Path(path)
        if not path.exists():
            return cls(path)
        raw = json.loads(path.read_text(encoding="utf-8"))
        positions = {t: Position(**rec) for t, rec in raw.items()}
        return cls(path, positions)

    def save(self) -> None:
        """Atomic write, same tmp-then-replace discipline as paper_state.json.

        ``peak_price`` is the whole reason this store exists, and it cannot be
        recomputed after the fact from a daily run — it is a running maximum
        accumulated across sessions. A plain ``write_text`` truncates before it
        writes, so an interrupted save destroys exactly the state that has no
        other source. ``os.replace`` is atomic on POSIX and Windows alike.
        """
        data = {t: asdict(p) for t, p in self._positions.items()}
        payload = json.dumps(data, indent=2, sort_keys=True)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, self.path)

    # ---- access ------------------------------------------------------------
    def add(self, position: Position) -> None:
        if position.ticker in self._positions:
            raise ValueError(f"position already exists for {position.ticker}")
        self._positions[position.ticker] = position

    def get(self, ticker: str) -> Position | None:
        return self._positions.get(ticker)

    def remove(self, ticker: str) -> None:
        self._positions.pop(ticker, None)

    def __len__(self) -> int:
        return len(self._positions)

    def __iter__(self):
        return iter(self._positions.values())
