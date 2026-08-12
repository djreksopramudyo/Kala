"""
run_walkforward.py tests: pure-logic pieces + the warehouse cache path,
with yfinance mocked out (no network in tests).
"""

import numpy as np
import pandas as pd
import pytest

import run_walkforward as rw


def _df(n=500, level=1000.0, start="2022-01-03", zero_volume_tail=False, end_today=False):
    if end_today:
        idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
    else:
        idx = pd.bdate_range(start, periods=n)
    vol = np.full(n, 1e6)
    if zero_volume_tail:
        vol[-60:] = 0.0
    return pd.DataFrame(
        {"Open": np.full(n, level), "High": np.full(n, level * 1.01),
         "Low": np.full(n, level * 0.99), "Close": np.full(n, level),
         "Volume": vol}, index=idx)


# ---------------- _passes_filters --------------------------------------------

def test_passes_filters_accepts_clean_liquid_history():
    assert rw._passes_filters(_df(), min_price=50.0)


def test_passes_filters_rejects_too_short_history():
    assert not rw._passes_filters(_df(n=100), min_price=50.0)


def test_passes_filters_rejects_below_min_price():
    assert not rw._passes_filters(_df(level=40.0), min_price=50.0)


def test_passes_filters_rejects_mostly_untraded_tail():
    assert not rw._passes_filters(_df(zero_volume_tail=True), min_price=50.0)


def test_passes_filters_rejects_none():
    assert not rw._passes_filters(None, min_price=50.0)


# ---------------- _period_to_start_iso ----------------------------------------

def test_period_to_start_iso_parses_plain_years():
    end = pd.Timestamp("2026-07-20")
    assert rw._period_to_start_iso("3y", end) == "2023-07-20"
    assert rw._period_to_start_iso("5y", end) == "2021-07-20"


def test_period_to_start_iso_none_for_non_year_periods():
    end = pd.Timestamp("2026-07-20")
    assert rw._period_to_start_iso("ytd", end) is None
    assert rw._period_to_start_iso("max", end) is None
    assert rw._period_to_start_iso("6mo", end) is None


# ---------------- fetch() with the warehouse cache ----------------------------

def test_fetch_without_warehouse_unchanged(monkeypatch):
    """Default behavior (no warehouse_path) must be untouched."""
    dfs_raw = {"A.JK": _df(), "B.JK": _df()}

    class FakeMultiCol:
        def __getitem__(self, t):
            return dfs_raw[t]

    monkeypatch.setattr(rw.yf, "download", lambda *a, **k: FakeMultiCol())
    got = rw.fetch(["A.JK", "B.JK"], "3y")
    assert set(got) == {"A.JK", "B.JK"}


def test_fetch_with_warehouse_caches_and_skips_second_fetch(tmp_path, monkeypatch):
    calls = {"n": 0}

    def fake_download(tickers, **kwargs):
        calls["n"] += 1
        return _df(n=800, end_today=True)   # single ticker -> yfinance returns the df directly

    monkeypatch.setattr(rw.yf, "download", fake_download)
    db = tmp_path / "wh.db"

    first = rw.fetch(["A.JK"], "3y", warehouse_path=str(db))
    assert "A.JK" in first
    assert calls["n"] == 1

    # second call: warehouse should already cover the period -> no re-download
    second = rw.fetch(["A.JK"], "3y", warehouse_path=str(db))
    assert "A.JK" in second
    assert calls["n"] == 1, "second fetch should have been served entirely from the warehouse"


def _df_with_dividends(n=500, level=1000.0, start="2022-01-03", div_every=63, div_amt=15.0):
    idx = pd.bdate_range(start, periods=n)
    divs = np.zeros(n)
    divs[::div_every] = div_amt
    return pd.DataFrame(
        {"Open": np.full(n, level), "High": np.full(n, level * 1.01),
         "Low": np.full(n, level * 0.99), "Close": np.full(n, level),
         "Volume": np.full(n, 1e6), "Dividends": divs}, index=idx)


def test_fetch_needs_dividends_keeps_dividends_column(monkeypatch):
    """The gap this was built to close: a strategy that declares
    needs_dividends must actually get a Dividends column, not the stripped
    5-column OHLCV frame every other strategy gets."""
    calls = {}

    def fake_download(tickers, **kwargs):
        calls.update(kwargs)
        return _df_with_dividends()

    monkeypatch.setattr(rw.yf, "download", fake_download)
    got = rw.fetch(["A.JK"], "3y", needs_dividends=True)
    assert "A.JK" in got
    assert "Dividends" in got["A.JK"].columns
    assert calls.get("actions") is True


def test_fetch_without_needs_dividends_still_strips_extra_columns(monkeypatch):
    """The default path must still return only the 5-column OHLCV frame even
    when the underlying data happens to carry more (e.g. a vendor quirk) --
    needs_dividends is opt-in, not automatic."""
    monkeypatch.setattr(rw.yf, "download",
                        lambda *a, **k: _df_with_dividends())
    got = rw.fetch(["A.JK"], "3y")
    assert list(got["A.JK"].columns) == ["Open", "High", "Low", "Close", "Volume"]


def test_fetch_needs_dividends_missing_column_falls_back_to_zero(monkeypatch):
    """If actions=True doesn't actually yield a Dividends column for some
    ticker (a vendor quirk, not this project's fault), fall back to an
    all-zero column rather than crash the whole fetch."""
    def fake_download(tickers, **kwargs):
        df = _df_with_dividends()
        return df.drop(columns=["Dividends"])

    monkeypatch.setattr(rw.yf, "download", fake_download)
    got = rw.fetch(["A.JK"], "3y", needs_dividends=True)
    assert "A.JK" in got
    assert (got["A.JK"]["Dividends"] == 0.0).all()


def test_freshness_target_is_a_trading_day_not_raw_today():
    """Regression for a real production bug: the cache-coverage check compared
    against the raw calendar date, so on a Saturday it demanded a bar dated
    Saturday -- which cannot exist, because the market was shut. Every weekend
    and holiday therefore forced a full re-download of the whole universe and
    burned yfinance rate limit (this project has been throttled by Yahoo
    mid-study for exactly this kind of avoidable traffic).

    Pinned on FIXED dates so it verifies the behavior no matter which day the
    suite happens to run on."""
    sat = pd.Timestamp("2026-07-25")          # Saturday
    sun = pd.Timestamp("2026-07-26")          # Sunday
    wed = pd.Timestamp("2026-07-22")          # Wednesday

    # weekend -> must not demand a weekend-dated bar
    assert rw._freshness_target_iso(sat) < "2026-07-25"
    assert rw._freshness_target_iso(sun) < "2026-07-25"
    # and the target itself must be a weekday
    for d in (sat, sun, wed):
        assert pd.Timestamp(rw._freshness_target_iso(d)).weekday() < 5

    # with 1 business day of slack, Wednesday's target is Tuesday
    assert rw._freshness_target_iso(wed, slack_bdays=1) == "2026-07-21"


def test_warehouse_cache_hits_on_a_weekend(tmp_path, monkeypatch):
    """End-to-end version of the bug: data whose newest bar is FRIDAY must
    satisfy the coverage check when 'today' is Saturday, instead of triggering
    a pointless re-download."""
    calls = {"n": 0}
    friday = pd.Timestamp("2026-07-24")
    saturday = pd.Timestamp("2026-07-25")

    def fake_download(tickers, **kwargs):
        calls["n"] += 1
        idx = pd.bdate_range(end=friday, periods=800)
        return pd.DataFrame(
            {"Open": np.full(800, 1000.0), "High": np.full(800, 1010.0),
             "Low": np.full(800, 990.0), "Close": np.full(800, 1000.0),
             "Volume": np.full(800, 1e6)}, index=idx)

    monkeypatch.setattr(rw.yf, "download", fake_download)
    # freeze "today" on the Saturday
    monkeypatch.setattr(rw.pd.Timestamp, "today", staticmethod(lambda: saturday))

    db = tmp_path / "wh.db"
    rw.fetch(["A.JK"], "3y", warehouse_path=str(db))
    assert calls["n"] == 1
    rw.fetch(["A.JK"], "3y", warehouse_path=str(db))
    assert calls["n"] == 1, "weekend re-download: the cache-freshness bug is back"


def test_warehouse_refetches_when_cached_history_is_too_short(tmp_path, monkeypatch):
    """Second bug found alongside the weekend one: a cache entry with a FRESH
    tail but not enough history to cover the requested start matched neither
    the hit branch nor the re-fetch branch, so the ticker silently vanished
    from the study -- quietly shrinking the universe, which is worse than an
    extra download. It must be re-fetched instead."""
    calls = {"n": 0}
    bars = {"n": 300}          # first call: short history

    def fake_download(tickers, **kwargs):
        calls["n"] += 1
        return _df(n=bars["n"], end_today=True)

    monkeypatch.setattr(rw.yf, "download", fake_download)
    db = tmp_path / "wh.db"

    # warm the cache with only ~300 bars (>1y but well under 3y)
    rw.fetch(["A.JK"], "3y", warehouse_path=str(db))
    assert calls["n"] == 1

    # now ask for 3y again: the cached tail is fresh but the history is too
    # short, so it must re-fetch rather than drop A.JK on the floor.
    bars["n"] = 800
    got = rw.fetch(["A.JK"], "3y", warehouse_path=str(db))
    assert calls["n"] == 2, "too-short cache should trigger a re-fetch"
    assert "A.JK" in got, "ticker silently vanished instead of being re-fetched"


def test_fetch_with_warehouse_still_fetches_uncovered_tickers(tmp_path, monkeypatch):
    def fake_download(tickers, **kwargs):
        if len(tickers) == 1:
            return _df(n=800, end_today=True)
        class FakeMultiCol:
            def __getitem__(self, t):
                return _df(n=800, end_today=True)
        return FakeMultiCol()

    monkeypatch.setattr(rw.yf, "download", fake_download)
    db = tmp_path / "wh.db"

    rw.fetch(["A.JK"], "3y", warehouse_path=str(db))       # warms the cache for A only
    got = rw.fetch(["A.JK", "B.JK"], "3y", warehouse_path=str(db))
    assert set(got) == {"A.JK", "B.JK"}   # B still gets fetched despite A being cached


def test_fetch_with_warehouse_skips_cache_for_non_year_period(tmp_path, monkeypatch):
    """'ytd'/'max' can't be turned into a fixed start date, so every call
    must go straight to yfinance -- never silently serve wrong-range data."""
    calls = {"n": 0}

    def fake_download(tickers, **kwargs):
        calls["n"] += 1
        return _df(n=500)   # single ticker -> yfinance returns the df directly

    monkeypatch.setattr(rw.yf, "download", fake_download)
    db = tmp_path / "wh.db"
    rw.fetch(["A.JK"], "max", warehouse_path=str(db))
    rw.fetch(["A.JK"], "max", warehouse_path=str(db))
    assert calls["n"] == 2


# ---------------- --strategy CLI wiring ----------------------------------------

def _random_walk_df(n=500, seed=1, drift=0.0008, start="2022-01-03"):
    idx = pd.bdate_range(start, periods=n)
    rng = np.random.default_rng(seed)
    close = 1000.0 * np.exp(np.cumsum(rng.normal(drift, 0.015, n)))
    return pd.DataFrame(
        {"Open": close, "High": close * 1.01, "Low": close * 0.99,
         "Close": close, "Volume": np.full(n, 2_000_000.0)}, index=idx)


def test_main_defaults_to_momentum_strategy(monkeypatch, capsys):
    def fake_download(tickers, **kwargs):
        if isinstance(tickers, list) and len(tickers) > 1:
            class FakeMultiCol:
                def __getitem__(self, t):
                    return _random_walk_df()
            return FakeMultiCol()
        return _random_walk_df()

    monkeypatch.setattr(rw.yf, "download", fake_download)
    monkeypatch.setattr("sys.argv", ["run_walkforward.py", "--tickers", "A.JK", "B.JK",
                                     "--train-bars", "200", "--test-bars", "60"])
    rc = rw.main()
    assert rc == 0
    out = capsys.readouterr().out
    assert "strategy: momentum" in out
    assert "UNTESTED" not in out


def test_main_runs_mean_reversion_strategy_end_to_end(monkeypatch, capsys):
    def fake_download(tickers, **kwargs):
        if isinstance(tickers, list) and len(tickers) > 1:
            class FakeMultiCol:
                def __getitem__(self, t):
                    return _random_walk_df()
            return FakeMultiCol()
        return _random_walk_df()

    monkeypatch.setattr(rw.yf, "download", fake_download)
    monkeypatch.setattr("sys.argv", ["run_walkforward.py", "--tickers", "A.JK", "B.JK",
                                     "--strategy", "mean_reversion",
                                     "--train-bars", "200", "--test-bars", "60"])
    rc = rw.main()
    assert rc == 0
    out = capsys.readouterr().out
    assert "strategy: mean_reversion" in out
    assert "UNTESTED" in out
    assert "WALK-FORWARD VALIDATION" in out


def test_main_rejects_veto_ranging_stock_without_apply_entry_vetoes(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["run_walkforward.py", "--tickers", "A.JK",
                                     "--veto-ranging-stock"])
    rc = rw.main()
    assert rc == 1
    err = capsys.readouterr().err
    assert "--apply-entry-vetoes" in err


def test_main_runs_with_veto_ranging_stock_end_to_end(monkeypatch, capsys):
    """Smoke test for the regime-conditional-momentum wiring: --veto-ranging-stock
    plus --apply-entry-vetoes should thread through to EntryConfig and complete
    without error (ADX needs High/Low, present in _random_walk_df)."""
    def fake_download(tickers, **kwargs):
        if isinstance(tickers, list) and len(tickers) > 1:
            class FakeMultiCol:
                def __getitem__(self, t):
                    return _random_walk_df()
            return FakeMultiCol()
        return _random_walk_df()

    monkeypatch.setattr(rw.yf, "download", fake_download)
    monkeypatch.setattr("sys.argv", ["run_walkforward.py", "--tickers", "A.JK", "B.JK",
                                     "--apply-entry-vetoes", "--veto-ranging-stock",
                                     "--train-bars", "200", "--test-bars", "60"])
    rc = rw.main()
    assert rc == 0
    out = capsys.readouterr().out
    assert "WALK-FORWARD VALIDATION" in out


def test_main_uses_custom_benchmark_ticker(monkeypatch, capsys):
    calls = []

    def fake_download(tickers, **kwargs):
        if isinstance(tickers, list) and len(tickers) > 1:
            class FakeMultiCol:
                def __getitem__(self, t):
                    return _random_walk_df()
            return FakeMultiCol()
        calls.append(tickers)
        return _random_walk_df()

    monkeypatch.setattr(rw.yf, "download", fake_download)
    monkeypatch.setattr("sys.argv", ["run_walkforward.py", "--tickers", "A.JK", "B.JK",
                                     "--train-bars", "200", "--test-bars", "60",
                                     "--benchmark", "^JKSII"])
    rc = rw.main()
    assert rc == 0
    assert "^JKSII" in calls          # custom ticker actually requested from yfinance
    out = capsys.readouterr().out
    assert "benchmark: ^JKSII" in out
    assert "default IHSG" not in out  # only shown when using the default


def test_main_universe_us_samples_from_us_sharia_stocks(monkeypatch, capsys):
    """--universe us (no --tickers given) must pull the default sample from
    kala.universe.US_SHARIA_STOCKS, not the IDX list -- proves the flag
    actually swaps the universe rather than just accepting it silently."""
    from kala.universe import US_SHARIA_STOCKS

    requested = []

    def fake_download(tickers, **kwargs):
        if isinstance(tickers, list) and len(tickers) > 1:
            requested.append(tickers)
            class FakeMultiCol:
                def __getitem__(self, t):
                    return _random_walk_df()
            return FakeMultiCol()
        return _random_walk_df()          # single-ticker benchmark call

    monkeypatch.setattr(rw.yf, "download", fake_download)
    monkeypatch.setattr("sys.argv", ["run_walkforward.py", "--universe", "us",
                                     "--max-tickers", "5", "--min-price", "1",
                                     "--train-bars", "200", "--test-bars", "60"])
    rc = rw.main()
    assert rc == 0
    tickers_requested = requested[0]
    assert tickers_requested       # something was requested
    assert all(t in US_SHARIA_STOCKS for t in tickers_requested)
    assert not any(t.endswith(".JK") for t in tickers_requested)


def test_main_universe_us_explicit_tickers_override_default_sample(monkeypatch, capsys):
    """--tickers still wins over --universe when both are given -- --universe
    only controls the DEFAULT sample, same relationship as ALL_SHARIA_STOCKS."""
    def fake_download(tickers, **kwargs):
        if isinstance(tickers, list) and len(tickers) > 1:
            class FakeMultiCol:
                def __getitem__(self, t):
                    return _random_walk_df()
            return FakeMultiCol()
        return _random_walk_df()

    monkeypatch.setattr(rw.yf, "download", fake_download)
    monkeypatch.setattr("sys.argv", ["run_walkforward.py", "--universe", "us",
                                     "--tickers", "AAPL", "MSFT",
                                     "--train-bars", "200", "--test-bars", "60"])
    rc = rw.main()
    assert rc == 0


def test_main_cost_preset_us_equity_applies_tight_flat_costs(monkeypatch, capsys):
    from kala.config import us_equity_costs

    captured_cfg = {}
    real_wfs = rw.walk_forward_strategy

    def spy_wfs(strategy, dfs, **kwargs):
        captured_cfg["costs"] = kwargs["cfg"].costs
        return real_wfs(strategy, dfs, **kwargs)

    def fake_download(tickers, **kwargs):
        if isinstance(tickers, list) and len(tickers) > 1:
            class FakeMultiCol:
                def __getitem__(self, t):
                    return _random_walk_df()
            return FakeMultiCol()
        return _random_walk_df()

    monkeypatch.setattr(rw.yf, "download", fake_download)
    monkeypatch.setattr(rw, "walk_forward_strategy", spy_wfs)
    monkeypatch.setattr("sys.argv", ["run_walkforward.py", "--tickers", "AAPL", "MSFT",
                                     "--cost-preset", "us_equity", "--min-price", "1",
                                     "--train-bars", "200", "--test-bars", "60"])
    rc = rw.main()
    assert rc == 0
    used = captured_cfg["costs"]
    expected = us_equity_costs()
    assert used.buy_commission == expected.buy_commission
    assert used.half_spread == expected.half_spread
    assert used.spread_mode == "flat"
    out = capsys.readouterr().out
    assert "us_equity preset" in out
    assert "IDR" not in out


def test_main_cost_preset_us_equity_ignores_tick_spread_with_warning(monkeypatch, capsys):
    def fake_download(tickers, **kwargs):
        if isinstance(tickers, list) and len(tickers) > 1:
            class FakeMultiCol:
                def __getitem__(self, t):
                    return _random_walk_df()
            return FakeMultiCol()
        return _random_walk_df()

    monkeypatch.setattr(rw.yf, "download", fake_download)
    monkeypatch.setattr("sys.argv", ["run_walkforward.py", "--tickers", "AAPL", "MSFT",
                                     "--cost-preset", "us_equity", "--tick-spread",
                                     "--min-price", "1",
                                     "--train-bars", "200", "--test-bars", "60"])
    rc = rw.main()
    assert rc == 0
    err = capsys.readouterr().err
    assert "--tick-spread is ignored under --cost-preset us_equity" in err


def test_main_warns_when_benchmark_ticker_has_no_data(monkeypatch, capsys):
    def fake_download(tickers, **kwargs):
        if isinstance(tickers, list) and len(tickers) > 1:
            class FakeMultiCol:
                def __getitem__(self, t):
                    return _random_walk_df()
            return FakeMultiCol()
        return pd.DataFrame()   # benchmark ticker doesn't exist / no data

    monkeypatch.setattr(rw.yf, "download", fake_download)
    monkeypatch.setattr("sys.argv", ["run_walkforward.py", "--tickers", "A.JK", "B.JK",
                                     "--train-bars", "200", "--test-bars", "60",
                                     "--benchmark", "^NOTAREALTICKER"])
    rc = rw.main()
    assert rc == 0     # still completes -- benchmark absence degrades, doesn't crash
    err = capsys.readouterr().err
    assert "no data for benchmark" in err


def test_main_rejects_unknown_strategy(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["run_walkforward.py", "--strategy", "nonexistent"])
    rc = rw.main()
    assert rc == 1
    err = capsys.readouterr().err
    assert "unknown strategy" in err


def test_main_help_lists_available_strategies(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["run_walkforward.py", "--help"])
    with pytest.raises(SystemExit):
        rw.main()
    out = capsys.readouterr().out
    assert "mean_reversion" in out
    assert "momentum" in out
