"""
Clock tests -- the WIB-not-server-time guarantee.

The bug these guard: on a UTC host, naive datetime.now()/date.today()
returned UTC, so is_idx_open() and 'today' were up to 7h off -- the
condition that produced the 00:30-WIB NaN-quote misfire.
"""

import os
from datetime import datetime, timezone
from unittest import mock

from kala import clock


def test_now_wib_is_seven_hours_ahead_of_utc():
    # freeze a known UTC instant; WIB (UTC+7, no DST) must read +7h
    fixed_utc = datetime(2026, 7, 20, 17, 30, tzinfo=timezone.utc)  # 17:30 UTC
    with mock.patch("kala.clock.datetime") as m:
        m.now.side_effect = lambda tz=None: fixed_utc.astimezone(tz)
        now = clock.now_wib()
    assert now.hour == 0 and now.minute == 30    # next day 00:30 WIB
    assert now.day == 21
    assert now.tzinfo is None                    # naive, per contract


def test_today_wib_rolls_over_before_utc_midnight():
    """17:30 UTC on the 20th is already the 21st in WIB -- a trade logged
    'now' must carry the 21st, not the 20th."""
    fixed_utc = datetime(2026, 7, 20, 17, 30, tzinfo=timezone.utc)
    with mock.patch("kala.clock.datetime") as m:
        m.now.side_effect = lambda tz=None: fixed_utc.astimezone(tz)
        assert clock.today_str_wib() == "2026-07-21"


def test_market_tz_default_is_jakarta():
    with mock.patch.dict(os.environ, {}, clear=False):
        os.environ.pop("KALA_TZ", None)
        assert str(clock.market_tz()) == "Asia/Jakarta"


def test_market_tz_env_override():
    with mock.patch.dict(os.environ, {"KALA_TZ": "UTC"}):
        assert str(clock.market_tz()) == "UTC"


def test_date_str_today_uses_wib():
    """papertrade.date_str_today must delegate to the WIB clock, so every
    logged trade date is a Jakarta date regardless of server timezone."""
    from kala import papertrade
    fixed_utc = datetime(2026, 7, 20, 17, 30, tzinfo=timezone.utc)
    with mock.patch("kala.clock.datetime") as m:
        m.now.side_effect = lambda tz=None: fixed_utc.astimezone(tz)
        assert papertrade.date_str_today() == "2026-07-21"
