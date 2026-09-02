"""The guard that turns a wrong key into a failure instead of a tidy NaN table.

The first version of ``compare_exit_profiles_cached.py`` read the pooled stats
with ``.get(key, float("nan"))`` and the WRONG key names — ``trade_stats``
returns ``ev_pct``/``t_stat``, not ``mean``/``t``. Every cell printed NaN, the
table stayed neatly aligned, and the run looked like a measurement that had
come back empty rather than a script that was broken.

That is the same shape as the vacuous mutation harness and the vacuous sweep
assertions before it, so the guard is pinned rather than remembered.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from compare_exit_profiles_cached import (  # noqa: E402
    _need,
    load_cache,
    rank_by_turnover,
)


def test_a_present_key_is_returned():
    assert _need({"ev_pct": 1.25}, "ev_pct", "here") == 1.25


def test_a_missing_key_raises_instead_of_defaulting():
    with pytest.raises(KeyError) as e:
        _need({"ev_pct": 1.0, "n": 3}, "mean", "legacy")
    msg = str(e.value)
    assert "mean" in msg
    assert "ev_pct" in msg and "n" in msg      # says what IS there
    assert "do not print a default" in msg


def test_the_real_stat_keys_are_the_ones_the_script_asks_for():
    """Bind the script to trade_stats' actual contract, not to my memory of it."""
    from kala.walkforward import trade_stats
    stats = trade_stats([1.0, -2.0, 3.0])
    for key in ("n", "ev_pct", "median_pct", "win_rate_pct", "t_stat"):
        assert _need(stats, key, "contract") is not None


def test_an_empty_cache_directory_yields_no_universe(tmp_path, monkeypatch):
    import compare_exit_profiles_cached as mod
    monkeypatch.setattr(mod, "CACHE", tmp_path)
    dfs, bench = load_cache(min_bars=1, exclude=set())
    assert dfs == {} and bench is None


def test_short_histories_are_excluded_by_min_bars(tmp_path, monkeypatch):
    import pandas as pd

    import compare_exit_profiles_cached as mod
    idx = pd.bdate_range("2024-01-01", periods=50)
    pd.DataFrame({"Close": range(50)}, index=idx).to_pickle(tmp_path / "SHORT.JK.pkl")
    idx2 = pd.bdate_range("2020-01-01", periods=900)
    pd.DataFrame({"Close": range(900)}, index=idx2).to_pickle(tmp_path / "LONG.JK.pkl")
    monkeypatch.setattr(mod, "CACHE", tmp_path)

    dfs, _ = load_cache(min_bars=800, exclude=set())

    assert list(dfs) == ["LONG.JK"]          # non-vacuity: one DID survive


def test_the_benchmark_is_returned_not_just_skipped(tmp_path, monkeypatch):
    """Without it the excess/alpha column is empty — the only column that
    separates stock-picking from having been long during a rally."""
    import pandas as pd

    import compare_exit_profiles_cached as mod
    idx = pd.bdate_range("2020-01-01", periods=900)
    pd.DataFrame({"Close": range(900)}, index=idx).to_pickle(tmp_path / "LONG.JK.pkl")
    pd.DataFrame({"Close": range(900)}, index=idx).to_pickle(
        tmp_path / f"{mod.BENCHMARK_TICKER}.pkl")
    monkeypatch.setattr(mod, "CACHE", tmp_path)

    dfs, bench = load_cache(min_bars=800, exclude=set())

    assert bench is not None and len(bench) == 900
    assert mod.BENCHMARK_TICKER not in dfs      # and not traded as a stock


def test_the_liquidity_split_ranks_by_median_turnover_not_price(monkeypatch, tmp_path):
    """A high-priced, barely-traded name must land in the ILLIQUID half.

    Ranking on price alone would put an expensive thin stock among the liquid
    names, which inverts the whole discriminator: survivorship exposure tracks
    turnover, not share price.
    """
    import pandas as pd

    import compare_exit_profiles_cached as mod

    idx = pd.bdate_range("2020-01-01", periods=900)
    frames = {
        # expensive but thin -> low turnover
        "PRICEY.JK": pd.DataFrame({"Close": [50_000.0] * 900, "Volume": [100] * 900},
                                  index=idx),
        # cheap but heavily traded -> high turnover
        "BUSY.JK": pd.DataFrame({"Close": [100.0] * 900, "Volume": [50_000_000] * 900},
                                index=idx),
    }
    ranked = rank_by_turnover(frames)

    assert ranked[0] == "BUSY.JK"        # turnover, not price, decides
    assert ranked[-1] == "PRICEY.JK"
    assert mod.BENCHMARK_TICKER not in ranked


def test_a_ticker_without_volume_ranks_last_rather_than_crashing():
    """The cache is whatever past runs fetched; one odd frame must not abort."""
    import pandas as pd
    frames = {"OK.JK": pd.DataFrame({"Close": [10.0] * 5, "Volume": [1000] * 5}),
              "NOVOL.JK": pd.DataFrame({"Close": [10.0] * 5})}
    ranked = rank_by_turnover(frames)
    assert ranked == ["OK.JK", "NOVOL.JK"]


def test_split_liquidity_is_reachable_from_the_cli():
    src = (ROOT / "compare_exit_profiles_cached.py").read_text(encoding="utf-8")
    assert '"--split-liquidity"' in src
    assert "return split_liquidity(dfs, bench, args)" in src


def test_sweep_holding_is_reachable_and_reports_per_day(monkeypatch, capsys):
    """The per-day column is the whole point: per-trade rises mechanically."""
    import compare_exit_profiles_cached as mod

    class FakeRep:
        pooled_excess_clustered_t = 3.0
        pooled_excess_dsr = 0.9
        def __init__(self, ev):
            self.pooled_excess_chosen = {"n": 100, "ev_pct": ev}

    # excess per trade doubles with the horizon -> per DAY is flat, not rising
    monkeypatch.setattr(mod, "walk_forward",
                        lambda dfs, cfg, benchmark: FakeRep(cfg.backtest.holding_max_days * 0.1))
    mod.sweep_holding({"A.JK": None}, None, [20, 40, 60])

    out = capsys.readouterr().out
    assert "ex/day" in out

    # Assert on the TABLE ROWS, not just anywhere in the output: the summary
    # line also prints a per-day figure, so a looser check passed even with the
    # column deleted from every row. Mutation testing found that.
    rows = [ln for ln in out.splitlines() if ln.strip().startswith(("20", "40", "60"))]
    assert len(rows) == 3, rows
    for ln in rows:
        assert ln.rstrip().endswith("0.1000"), ln   # per-day is the LAST column
    # per-trade rises 2 -> 4 -> 6 while per-day stays flat: the whole point
    assert "+2.000" in rows[0] and "+6.000" in rows[2]

    assert "All 3 horizons are positive" in out
    assert "best-of-N" in out                 # the argmax caveat travels with it


def test_sweep_holding_is_reachable_from_the_cli():
    src = (ROOT / "compare_exit_profiles_cached.py").read_text(encoding="utf-8")
    assert '"--sweep-holding"' in src
    assert "return sweep_holding(dfs, bench, args.sweep_holding)" in src


def test_a_two_point_sweep_refuses_to_call_it_a_shape(monkeypatch, capsys):
    import compare_exit_profiles_cached as mod

    class FakeRep:
        pooled_excess_clustered_t = 3.0
        pooled_excess_dsr = 0.9
        def __init__(self, ev):
            self.pooled_excess_chosen = {"n": 100, "ev_pct": ev}

    monkeypatch.setattr(mod, "walk_forward",
                        lambda dfs, cfg, benchmark: FakeRep(1.0))
    mod.sweep_holding({"A.JK": None}, None, [20, 40])
    assert "Too few points to read a shape" in capsys.readouterr().out


def test_sweep_holding_flags_a_range_that_is_not_uniformly_positive(monkeypatch,
                                                                    capsys):
    import compare_exit_profiles_cached as mod

    class FakeRep:
        pooled_excess_clustered_t = 0.2
        pooled_excess_dsr = 0.4
        def __init__(self, ev):
            self.pooled_excess_chosen = {"n": 50, "ev_pct": ev}

    monkeypatch.setattr(mod, "walk_forward",
                        lambda dfs, cfg, benchmark: FakeRep(
                            1.0 if cfg.backtest.holding_max_days == 20 else -1.0))
    mod.sweep_holding({"A.JK": None}, None, [10, 20, 30])

    out = capsys.readouterr().out
    assert "2 of 3 horizons are NOT positive" in out
    assert "treat the peak as noise" in out
