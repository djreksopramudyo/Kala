"""The price cache must not serve last month's close as today's price.

load_frame() had no age bound at all. A frame cached 47 days earlier came
back indistinguishable from a fresh one, and _last_close() handed it to
/rebalance and /buy as the current price.

That is worse than the missing-price case fixed earlier: plan_rebalance now
REFUSES to plan when a held name can't be priced, but a stale price is a
price, so the guard never fires and the plan comes out fully populated and
entirely confident — on numbers from a month ago.

The scan path was already defended (kala_daily_trader.STALE_DATA_DAYS flags
a frozen ticker); everything reading through _last_close was not.
"""

import numpy as np
import pandas as pd
import pytest

from kala import datacache

TODAY = pd.Timestamp("2026-08-05")


def _df(last_bar: str, n: int = 20, level: float = 5000.0):
    idx = pd.bdate_range(end=pd.Timestamp(last_bar), periods=n)
    return pd.DataFrame({"Open": np.full(n, level), "High": np.full(n, level * 1.01),
                         "Low": np.full(n, level * 0.99), "Close": np.full(n, level),
                         "Volume": np.full(n, 3e6)}, index=idx)


def test_fresh_cache_is_served(tmp_path):
    datacache.save_frame("OK.JK", _df("2026-08-04"), cache_dir=tmp_path)
    got = datacache.load_frame("OK.JK", cache_dir=tmp_path,
                               max_age_days=7, today=TODAY)
    assert got is not None


def test_month_old_cache_is_refused(tmp_path):
    """The regression: 47 days old, served as if current."""
    datacache.save_frame("STALE.JK", _df("2026-06-19"), cache_dir=tmp_path)
    got = datacache.load_frame("STALE.JK", cache_dir=tmp_path,
                               max_age_days=7, today=TODAY)
    assert got is None


def test_exactly_at_the_limit_is_still_served(tmp_path):
    datacache.save_frame("EDGE.JK", _df("2026-07-29"), cache_dir=tmp_path)
    got = datacache.load_frame("EDGE.JK", cache_dir=tmp_path,
                               max_age_days=7, today=TODAY)
    assert got is not None, "7 days old with a 7-day limit must pass"


def test_one_day_past_the_limit_is_refused(tmp_path):
    datacache.save_frame("EDGE.JK", _df("2026-07-28"), cache_dir=tmp_path)
    got = datacache.load_frame("EDGE.JK", cache_dir=tmp_path,
                               max_age_days=7, today=TODAY)
    assert got is None


def test_no_bound_means_no_bound(tmp_path):
    """load_frame stays a pure loader when max_age_days is omitted, so a
    caller can still inspect the cache regardless of age."""
    datacache.save_frame("OLD.JK", _df("2020-01-10"), cache_dir=tmp_path)
    assert datacache.load_frame("OLD.JK", cache_dir=tmp_path) is not None


def test_with_fallback_bounds_age_by_default(tmp_path):
    """The resilience path must be safe WITHOUT the caller remembering."""
    datacache.save_frame("STALE.JK", _df("2026-06-19"), cache_dir=tmp_path)
    got = datacache.with_fallback("STALE.JK", None, cache_dir=tmp_path,
                                  today=TODAY)
    assert got is None


def test_with_fallback_still_prefers_a_good_live_fetch(tmp_path):
    datacache.save_frame("T.JK", _df("2026-06-19"), cache_dir=tmp_path)
    live = _df("2026-08-05", level=6000.0)
    got = datacache.with_fallback("T.JK", live, cache_dir=tmp_path, today=TODAY)
    assert got is not None
    assert got["Close"].iloc[-1] == 6000.0


# ------------------------------------------------------------- age helper ---

def test_age_helper_counts_calendar_days():
    # 2026-07-31 is a Friday; TODAY is Wednesday 2026-08-05.
    assert datacache.frame_age_days(_df("2026-07-31"), today=TODAY) == 5


def test_age_helper_handles_tz_aware_index():
    """A tz-aware index must not raise on the subtraction — that would turn
    a staleness check into a swallowed exception and an unbounded read."""
    df = _df("2026-07-31")
    df.index = df.index.tz_localize("Asia/Jakarta")
    assert datacache.frame_age_days(df, today=TODAY) == 5


@pytest.mark.parametrize("bad", [None, pd.DataFrame()])
def test_age_helper_returns_none_for_unusable_input(bad):
    assert datacache.frame_age_days(bad, today=TODAY) is None


def test_unreadable_age_is_treated_as_too_old(tmp_path):
    """If the age can't be established, the frame must be refused rather
    than waved through — failing open is what created this bug."""
    df = _df("2026-08-04")
    df.index = range(len(df))          # not a DatetimeIndex
    datacache.save_frame("WEIRD.JK", df, cache_dir=tmp_path)
    got = datacache.load_frame("WEIRD.JK", cache_dir=tmp_path,
                               max_age_days=7, today=TODAY)
    assert got is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
