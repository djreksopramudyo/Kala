"""The default archiving universe: open positions plus the watchlist.

WHY THIS IS ITS OWN MODULE
--------------------------
Three archivers (``archive_sentiment``, ``archive_fundamentals``,
``foreign_flow_monitor``) each carried their own near-identical copy of this
logic, and each copy ended both reads with ``except Exception: pass``. That
meant a missing state file, a wrong working directory, and a watchlist
truncated by an interrupted save all produced the same result as a user with
nothing to archive: an empty universe and not one word about it.

For a point-in-time archive that silence is expensive in a way an ordinary bug
is not. The archive's whole purpose is that today's snapshot is the only
chance to record what today looked like; a day archived with a silently empty
universe is a hole that cannot be backfilled later, and nothing in the data
marks it as a hole rather than a quiet day.

The degrade-rather-than-crash decision is kept — one unreadable source should
not abort an archiving run that could still record the other. What changes is
that every degraded read is named, with the path it actually resolved to,
which is the fact that separates "nothing researched yet" from "running in the
wrong directory".
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Universe:
    tickers: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)   # every non-clean read
    n_from_positions: int = 0
    n_from_watchlist: int = 0
    positions_read: bool = False   # the source was read without incident
    watchlist_read: bool = False

    @property
    def fully_sourced(self) -> bool:
        """True when both sources were read cleanly. A caller that archives
        anyway should still know this was not a complete read."""
        return self.positions_read and self.watchlist_read


def default_universe(state_path, watchlist_path, start_capital: float = 10_000_000,
                     warn=None) -> Universe:
    """Union of open paper positions and watchlist names, with reasons.

    Never raises. Every source that does not read cleanly appends a note and
    contributes nothing, so the caller can decide whether an incomplete
    universe is worth archiving.
    """
    warn = warn or (lambda msg: print(msg, file=sys.stderr))
    u = Universe()
    tickers: set[str] = set()

    state_path = Path(state_path)
    try:
        from .papertrade import PaperTrader
        if not state_path.exists():
            # PaperTrader.load answers a missing file with a fresh, empty
            # trader. That is right for a first run and indistinguishable
            # from a wrong path, so the distinction is drawn here instead.
            u.notes.append(f"no paper state at {state_path.resolve()}")
        else:
            pt = PaperTrader.load(str(state_path), start_capital=start_capital)
            names = set(pt.positions)
            tickers |= names
            u.n_from_positions = len(names)
            u.positions_read = True
    except Exception as e:  # noqa: BLE001 - reported, not swallowed
        u.notes.append(f"{state_path.resolve()} exists but could not be read "
                       f"({e}); it is damaged, not empty")

    watchlist_path = Path(watchlist_path)
    try:
        from .watchlist import WatchlistStore
        store = WatchlistStore.load(watchlist_path)
        if store.load_note:                      # file absent
            u.notes.append(store.load_note)
        else:
            names = {item.ticker for item in store}
            tickers |= names
            u.n_from_watchlist = len(names)
            u.watchlist_read = True
    except Exception as e:  # noqa: BLE001 - reported, not swallowed
        u.notes.append(f"{watchlist_path.resolve()} exists but could not be read "
                       f"({e}); it is damaged, not empty")

    u.tickers = sorted(tickers)
    for note in u.notes:
        warn(f"WARNING: {note} — that source contributed 0 tickers to this run.")
    if u.notes and u.tickers:
        warn(f"WARNING: archiving {len(u.tickers)} ticker(s) from an incomplete "
             f"universe. A point-in-time archive cannot be backfilled, so this "
             f"day will be short those names permanently.")
    return u
