"""Last-good price cache: save/load round-trip + fallback semantics."""

import numpy as np
import pandas as pd

from kala import datacache


def _df(n=5, level=1000.0):
    idx = pd.bdate_range("2026-07-01", periods=n)
    return pd.DataFrame({"Open": np.full(n, level), "High": np.full(n, level * 1.01),
                         "Low": np.full(n, level * 0.99), "Close": np.full(n, level),
                         "Volume": np.full(n, 1e6)}, index=idx)


def test_save_then_load_round_trips(tmp_path):
    datacache.save_frame("ANTM.JK", _df(), cache_dir=tmp_path)
    got = datacache.load_frame("ANTM.JK", cache_dir=tmp_path)
    assert got is not None
    pd.testing.assert_frame_equal(got, _df())


def test_load_miss_returns_none(tmp_path):
    assert datacache.load_frame("NOPE.JK", cache_dir=tmp_path) is None


def test_save_empty_is_noop(tmp_path):
    datacache.save_frame("X.JK", pd.DataFrame(), cache_dir=tmp_path)
    assert datacache.load_frame("X.JK", cache_dir=tmp_path) is None


def test_with_fallback_prefers_live_and_refreshes_cache(tmp_path):
    live = _df(level=2000.0)
    out = datacache.with_fallback("A.JK", live, cache_dir=tmp_path)
    pd.testing.assert_frame_equal(out, live)
    # cache now holds the live frame
    pd.testing.assert_frame_equal(datacache.load_frame("A.JK", cache_dir=tmp_path), live)


def test_with_fallback_serves_cache_when_live_empty(tmp_path):
    # `today` is pinned because with_fallback now bounds the cache by AGE
    # (see test_datacache_staleness.py). Without it this test would silently
    # start failing once the fixture's fixed dates drifted past the limit in
    # real time — a test that depends on the wall clock, which is how the
    # unbounded read went unnoticed in the first place.
    datacache.save_frame("A.JK", _df(level=1500.0), cache_dir=tmp_path)
    out = datacache.with_fallback("A.JK", None, cache_dir=tmp_path,
                                  today=pd.Timestamp("2026-07-06"))
    assert out is not None
    assert out["Close"].iloc[-1] == 1500.0


def test_with_fallback_none_when_live_and_cache_both_miss(tmp_path):
    assert datacache.with_fallback("GONE.JK", None, cache_dir=tmp_path) is None


def test_load_corrupt_cache_is_a_miss_not_an_error(tmp_path):
    (tmp_path / "BAD.JK.pkl").write_text("not a pickle")
    assert datacache.load_frame("BAD.JK", cache_dir=tmp_path) is None


def test_safe_name_handles_caret_and_dots(tmp_path):
    datacache.save_frame("^JKSE", _df(), cache_dir=tmp_path)
    assert datacache.load_frame("^JKSE", cache_dir=tmp_path) is not None
