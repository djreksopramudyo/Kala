"""
Central clock — the market day and market-open question, in WIB not server time.

Everything time-sensitive in this system must agree on WHICH trading day it
is and WHETHER IDX is open right now, and the honest answer is in Jakarta
time (WIB, UTC+7) — never the server's local clock.

The bug this fixes: most cloud VPSes run on UTC. On such a host, the old
``datetime.now()`` / ``date.today()`` calls returned UTC, so:

  * ``is_idx_open()`` thought the market opened/closed up to 7 hours off,
  * a trade logged between 17:00 and 24:00 WIB got yesterday's UTC date,
  * ``/checkstop`` at 00:30 WIB (17:30 UTC the previous day) reasoned about
    the wrong session — the exact window that surfaced the NaN-quote bug.

Routing those decisions through here makes them correct regardless of where
the process runs. ``now_wib()`` returns a NAIVE datetime whose wall-clock
fields ARE WIB, so existing code that compares against naive ``time()``
objects (``is_idx_open``) keeps working unchanged — it just gets the right
clock instead of the server's.

Override the zone with the ``KALA_TZ`` env var (default
``Asia/Jakarta``) only if you have a specific reason; the default is correct
for IDX.
"""

from __future__ import annotations

import os
from datetime import date, datetime
from zoneinfo import ZoneInfo

DEFAULT_TZ = "Asia/Jakarta"


def market_tz() -> ZoneInfo:
    """The IDX market timezone (Asia/Jakarta), overridable via KALA_TZ."""
    return ZoneInfo(os.environ.get("KALA_TZ", DEFAULT_TZ))


def now_wib() -> datetime:
    """Current wall-clock time in the market timezone, as a NAIVE datetime.

    Naive-but-WIB is deliberate: every existing caller treats 'now' as a
    naive local time (``.time()``, ``.weekday()``, ``.date()``), so this is
    a drop-in that just corrects the clock without forcing tz-aware
    arithmetic through the whole codebase.
    """
    return datetime.now(market_tz()).replace(tzinfo=None)


def today_wib() -> date:
    """Today's date in the market timezone."""
    return now_wib().date()


def today_str_wib() -> str:
    """Today's date in the market timezone, ISO (YYYY-MM-DD)."""
    return today_wib().isoformat()
