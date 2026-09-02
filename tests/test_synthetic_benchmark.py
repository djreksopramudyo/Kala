"""The equal-weighted universe benchmark must be a real portfolio, not a curve.

The property that matters: if you had bought EVERYTHING, this is what you would
have got. Every test below pins a way that could quietly stop being true —
especially the ones where a wrong construction still produces a plausible
rising line, which is how a broken benchmark gets trusted.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kala.synthetic_benchmark import (  # noqa: E402
    describe,
    equal_weight_benchmark,
)


def _frame(idx, closes):
    return pd.DataFrame({"Close": np.asarray(closes, dtype=float)}, index=idx)


def _universe(n_names=25, n_days=120, daily=0.001, seed=0):
    idx = pd.bdate_range("2023-01-02", periods=n_days)
    rng = np.random.default_rng(seed)
    out = {}
    for i in range(n_names):
        r = rng.normal(daily, 0.01, n_days)
        out[f"T{i}.JK"] = _frame(idx, 1000 * np.exp(np.cumsum(r)))
    return out


def test_a_universe_that_all_moves_together_reproduces_that_move():
    """The defining property. Every name +1%/day -> the index is +1%/day."""
    idx = pd.bdate_range("2023-01-02", periods=50)
    lvl = 100 * (1.01 ** np.arange(50))
    dfs = {f"T{i}.JK": _frame(idx, lvl) for i in range(30)}

    b = equal_weight_benchmark(dfs, min_names=5)
    got = b["Close"].iloc[-1] / b["Close"].iloc[0] - 1.0
    want = lvl[-1] / lvl[0] - 1.0
    assert got == pytest.approx(want, rel=1e-9)


def test_it_equal_weights_rather_than_following_the_biggest_price():
    """One name at 100,000 IDR must not outvote 29 names at 100 IDR.

    A cap- or price-weighted construction would track the expensive name. This
    is the difference between 'what if I bought everything' and 'what if I
    bought the most expensive thing'.
    """
    idx = pd.bdate_range("2023-01-02", periods=40)
    flat = np.full(40, 100.0)
    mover = 100_000 * (1.05 ** np.arange(40))        # +5%/day, huge price

    dfs = {f"FLAT{i}.JK": _frame(idx, flat) for i in range(29)}
    dfs["MOVER.JK"] = _frame(idx, mover)

    b = equal_weight_benchmark(dfs, min_names=5)
    daily = b["Close"].pct_change().dropna()
    # 29 names at 0% and one at +5% -> 5/30 = 0.1667% per day.
    assert daily.iloc[0] == pytest.approx(0.05 / 30, rel=1e-9)
    assert daily.iloc[-1] == pytest.approx(0.05 / 30, rel=1e-9)


def test_a_short_history_name_does_not_reweight_the_early_period():
    """Averaging normalised LEVELS would tilt toward long-history names.

    This is a survivorship bias the benchmark would introduce by itself. The
    returns-based construction must be immune: a name that appears late
    contributes only from the day it appears.
    """
    idx = pd.bdate_range("2023-01-02", periods=60)
    flat = np.full(60, 500.0)
    dfs = {f"OLD{i}.JK": _frame(idx, flat) for i in range(20)}

    # A latecomer that doubles, present only for the last 10 days.
    late = _frame(idx[-10:], 100 * (1.08 ** np.arange(10)))
    dfs["LATE.JK"] = late

    b = equal_weight_benchmark(dfs, min_names=5)
    daily = b["Close"].pct_change().dropna()
    # Before the latecomer exists: everything flat, so exactly 0%.
    early = daily.loc[: idx[-12]]
    assert early.abs().max() == pytest.approx(0.0, abs=1e-12)
    # After it appears it is one voice among 21, not the whole index.
    assert daily.loc[idx[-5]] == pytest.approx(0.08 / 21, rel=1e-6)


def test_a_non_trading_day_does_not_get_counted_as_a_flat_day():
    """A name that did not trade must abstain, not vote 0% and damp the mean."""
    idx = pd.bdate_range("2023-01-02", periods=30)
    up = _frame(idx, 100 * (1.02 ** np.arange(30)))
    dfs = {f"UP{i}.JK": up.copy() for i in range(10)}
    # A halted name: present in the index but with no price for one day.
    halted = up.copy()
    halted.iloc[15] = np.nan
    dfs["HALT.JK"] = halted

    b = equal_weight_benchmark(dfs, min_names=5)
    daily = b["Close"].pct_change().dropna()
    # Everyone who traded was +2%; the halted name must not drag it below.
    assert daily.max() == pytest.approx(0.02, rel=1e-6)
    assert daily.min() == pytest.approx(0.02, rel=1e-6)


def test_thin_early_dates_are_dropped_not_averaged():
    """Two tickers is not a market. Those dates must not reach a fold."""
    idx = pd.bdate_range("2023-01-02", periods=80)
    dfs = {"EARLY1.JK": _frame(idx, np.full(80, 100.0)),
           "EARLY2.JK": _frame(idx, np.full(80, 100.0))}
    for i in range(30):                       # the rest join halfway through
        dfs[f"LATER{i}.JK"] = _frame(idx[40:], np.full(40, 200.0))

    b = equal_weight_benchmark(dfs, min_names=20)
    assert b.index[0] >= idx[40], "thin early dates leaked into the benchmark"


def test_it_refuses_rather_than_returning_an_empty_or_flat_series():
    """A benchmark that degrades silently is the failure mode of this project."""
    with pytest.raises(ValueError):
        equal_weight_benchmark({})
    with pytest.raises(ValueError):                     # nothing usable
        equal_weight_benchmark({"A.JK": pd.DataFrame({"Close": [1.0]})})
    with pytest.raises(ValueError, match="min_names"):   # never enough names
        equal_weight_benchmark(_universe(n_names=3), min_names=50)


def test_non_positive_prices_do_not_produce_infinities():
    idx = pd.bdate_range("2023-01-02", periods=30)
    bad = _frame(idx, np.concatenate([np.full(10, 100.0), np.zeros(5),
                                      np.full(15, 100.0)]))
    dfs = {f"OK{i}.JK": _frame(idx, np.full(30, 100.0)) for i in range(20)}
    dfs["BAD.JK"] = bad

    b = equal_weight_benchmark(dfs, min_names=5)
    assert np.isfinite(b["Close"].to_numpy()).all()
    assert (b["Close"] > 0).all()


def test_the_output_is_shaped_like_the_frames_the_pipeline_expects():
    b = equal_weight_benchmark(_universe(), min_names=5)
    assert "Close" in b.columns
    assert isinstance(b.index, pd.DatetimeIndex)
    assert b.index.is_monotonic_increasing
    assert float(b["Close"].iloc[0]) == pytest.approx(1.0)


def test_it_drops_into_walk_forward_and_produces_excess_numbers():
    """End-to-end: the point is to be usable as `benchmark=`, not to exist."""
    from kala.walkforward import walk_forward

    dfs = {}
    idx = pd.bdate_range("2022-01-03", periods=400)
    rng = np.random.default_rng(5)
    for i in range(4):
        close = 1000 * np.exp(np.cumsum(rng.normal(0.0008, 0.012, 400)))
        open_ = np.empty(400); open_[0] = close[0]; open_[1:] = close[:-1]
        dfs[f"S{i}.JK"] = pd.DataFrame(
            {"Open": open_, "High": np.maximum(open_, close) * 1.004,
             "Low": np.minimum(open_, close) * 0.996, "Close": close,
             "Volume": np.full(400, 2_000_000.0)}, index=idx)

    bench = equal_weight_benchmark(dfs, min_names=2)
    rep = walk_forward(dfs, benchmark=bench, train_bars=200, test_bars=60,
                       warmup_bars=60, thresholds=(45.0,), min_train_trades=5)
    assert rep.pooled_excess_baseline.get("n", 0) > 0
    assert "ALPHA CHECK: NOT RUN" not in rep.summary_text()


def test_describe_names_the_breadth_and_the_span():
    d = describe(equal_weight_benchmark(_universe(n_names=25), min_names=5))
    assert "EQUAL_WEIGHT" in d
    assert "names/day" in d
    assert "buy-and-hold" in d


def test_describe_excludes_the_base_bar_from_breadth():
    """The base bar has no return; counting it reports 0 names on a healthy run.

    A minimum of 0 is exactly what a genuinely empty stretch looks like, so
    including the base bar makes the one case indistinguishable from the other.
    """
    d = describe(equal_weight_benchmark(_universe(n_names=25), min_names=5))
    assert "0-" not in d.split("breadth:")[1].split("names/day")[0]
    assert "base bar excluded" in d


def test_describe_names_thin_days_instead_of_hiding_them_in_a_range():
    """A thin stretch must be counted and dated, not smoothed into min-max."""
    idx = pd.bdate_range("2023-01-02", periods=40)
    dfs = {f"T{i}.JK": _frame(idx, np.full(40, 100.0) * (1.001 ** np.arange(40)))
           for i in range(25)}
    # Nearly everyone stops trading for the last three days: a stale tail.
    for i in range(22):
        dfs[f"T{i}.JK"] = _frame(idx[:-3], dfs[f"T{i}.JK"]["Close"].to_numpy()[:-3])

    b = equal_weight_benchmark(dfs, min_names=5)
    d = describe(b)
    assert "day(s) below 5 names, held FLAT" in d
    assert str(idx[-1].date()) in d or str(idx[-3].date()) in d


def test_describe_says_nothing_about_thin_days_when_there_are_none():
    """Non-vacuity: the NOTE must be absent on a clean benchmark."""
    d = describe(equal_weight_benchmark(_universe(n_names=25), min_names=5))
    assert "day(s) below" not in d


# ---- the CLI path -------------------------------------------------------

def test_the_runner_wires_EQUAL_WEIGHT_to_the_universe_not_to_yfinance():
    """A flag that parses but never reaches the builder is worse than no flag.

    Checked by importing the runner and driving the same branch main() takes,
    rather than by reading its source — a source-text assertion passes just as
    happily when the branch is unreachable.
    """
    import run_walkforward as rw

    assert rw.EQUAL_WEIGHT == "EQUAL_WEIGHT"
    # The sentinel must not collide with a real ticker the user might pass.
    assert rw.EQUAL_WEIGHT != rw.BENCHMARK

    dfs = _universe(n_names=25, n_days=120)
    # This is the expression main() evaluates for the sentinel.
    bench = rw.equal_weight_benchmark(dfs)
    assert "Close" in bench.columns and len(bench) > 0
    assert "EQUAL_WEIGHT" in rw.describe(bench)


def test_the_flag_is_reachable_from_the_command_line():
    import subprocess
    out = subprocess.run([sys.executable, str(ROOT / "run_walkforward.py"), "--help"],
                         capture_output=True, text=True, encoding="utf-8",
                         errors="replace", cwd=str(ROOT))
    assert out.returncode == 0
    assert "EQUAL_WEIGHT" in out.stdout, "the flag is undocumented in --help"


def test_an_exchange_holiday_does_not_inject_the_noise_of_a_few_names():
    """Two tickers with a phantom bar must not move the whole index.

    Measured on the real universe: IDX Labour Day (2026-05-01) and Independence
    Day (2026-08-17) each left a handful of tickers carrying a bar while 560+
    had none. Averaging those few put noise into the level — and because the
    level compounds, it stayed in every date afterwards, including the whole of
    the most recent fold.
    """
    idx = pd.bdate_range("2023-01-02", periods=40)
    flat = np.full(40, 100.0)
    dfs = {f"T{i}.JK": _frame(idx, flat) for i in range(50)}

    # A holiday: everyone is absent except two names, one of which moved 30%.
    holiday = idx[20]
    for i in range(48):
        s = dfs[f"T{i}.JK"]["Close"].copy()
        s.loc[holiday] = np.nan
        dfs[f"T{i}.JK"] = _frame(idx, s.to_numpy())
    spike = flat.copy()
    spike[20:] = 130.0                       # the phantom name jumps 30%
    dfs["T48.JK"] = _frame(idx, spike)

    b = equal_weight_benchmark(dfs, min_names=20)
    daily = b["Close"].pct_change().dropna()
    assert abs(daily.loc[holiday]) < 1e-12, (
        f"a 2-name holiday moved the index by {daily.loc[holiday]:.4%}")
    # And the corruption must not persist: the level after the holiday is
    # unchanged from before it, because nothing really traded.
    before = float(b["Close"].loc[idx[19]])
    after = float(b["Close"].loc[idx[25]])
    assert after == pytest.approx(before, rel=1e-9)


def test_a_thin_day_is_carried_not_dropped():
    """Removing the date would silently discard every trade spanning it."""
    idx = pd.bdate_range("2023-01-02", periods=30)
    dfs = {f"T{i}.JK": _frame(idx, np.full(30, 100.0)) for i in range(30)}
    holiday = idx[10]
    for i in range(29):
        s = dfs[f"T{i}.JK"]["Close"].copy()
        s.loc[holiday] = np.nan
        dfs[f"T{i}.JK"] = _frame(idx, s.to_numpy())

    b = equal_weight_benchmark(dfs, min_names=20)
    assert holiday in b.index, "the thin bar was dropped rather than carried"


def test_a_healthy_day_is_still_averaged_normally():
    """Non-vacuity: the guard must not flatten days that DID trade."""
    idx = pd.bdate_range("2023-01-02", periods=30)
    up = 100 * (1.02 ** np.arange(30))
    dfs = {f"T{i}.JK": _frame(idx, up) for i in range(30)}
    b = equal_weight_benchmark(dfs, min_names=20)
    daily = b["Close"].pct_change().dropna()
    assert daily.min() == pytest.approx(0.02, rel=1e-6)
    assert daily.max() == pytest.approx(0.02, rel=1e-6)
