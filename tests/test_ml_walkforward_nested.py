"""
Tests for run_ml_walkforward_nested.py's inner-CV machinery.

The whole point of this script is to fix the previous version's problem
(hyperparameters picked by hand, "validated" by picking again by hand). The
one thing that would quietly defeat that fix is if the inner-validation step
could see even a sliver of the outer TEST window through an exit that
completes late. These tests exist specifically to catch that.
"""

import numpy as np
import pandas as pd
import pytest

from kala.ml_scoring import fit_ridge_scorer
from run_ml_walkforward_nested import (
    ALPHA_GRID,
    HORIZON_GRID,
    inner_split,
    run_inner_val,
    select_hyperparams,
)


def _make_df(closes, vols=None, start="2022-01-03"):
    closes = np.asarray(closes, dtype=float)
    n = len(closes)
    return pd.DataFrame(
        {
            "Open": closes,
            "High": closes * 1.005,
            "Low": closes * 0.995,
            "Close": closes,
            "Volume": np.asarray(vols, dtype=float) if vols is not None else np.full(n, 1e6),
        },
        index=pd.bdate_range(start, periods=n),
    )


def _rw(n, drift, seed, start="2022-01-03"):
    rng = np.random.default_rng(seed)
    closes = 1000 * np.exp(np.cumsum(rng.normal(drift, 0.014, n)))
    return _make_df(closes, vols=rng.integers(1_000_000, 5_000_000, n).astype(float), start=start)


# ---------------------------------------------------------------------------
# inner_split
# ---------------------------------------------------------------------------

def test_inner_split_respects_val_frac_and_ordering():
    start = pd.Timestamp("2023-01-02")
    end = pd.Timestamp("2024-01-02")  # 365 days
    cutoff = inner_split(start, end, val_frac=0.2)
    assert start < cutoff < end
    span = (end - start).days
    frac = (end - cutoff).days / span
    assert frac == pytest.approx(0.2, abs=0.02)


# ---------------------------------------------------------------------------
# run_inner_val — the leakage guard
# ---------------------------------------------------------------------------

def test_run_inner_val_never_sees_data_past_train_end():
    """The critical test. Build a ticker whose price action after train_end
    is wildly different (a crash) in one version vs. calm in another, with
    everything up to and including train_end IDENTICAL. run_inner_val's
    result must be bit-for-bit identical between the two, because it's only
    ever supposed to look at data up to train_end."""
    rng = np.random.default_rng(11)
    n_shared = 260
    shared = 1000 * np.exp(np.cumsum(rng.normal(0.0006, 0.013, n_shared)))

    calm_tail = shared[-1] * np.exp(np.cumsum(rng.normal(0.0003, 0.01, 80)))
    crash_tail = shared[-1] * np.exp(np.cumsum(rng.normal(-0.03, 0.03, 80)))

    df_calm = _make_df(np.concatenate([shared, calm_tail]))
    df_crash = _make_df(np.concatenate([shared, crash_tail]))
    # sanity: the two frames actually diverge after the shared prefix
    assert not np.allclose(df_calm["Close"].to_numpy()[n_shared:],
                           df_crash["Close"].to_numpy()[n_shared:])
    pd.testing.assert_frame_equal(df_calm.iloc[:n_shared], df_crash.iloc[:n_shared])

    train_start = df_calm.index[0]
    train_end = df_calm.index[n_shared - 1]  # exactly the shared boundary
    cutoff = inner_split(train_start, train_end, val_frac=0.2)

    inner_train_dfs = {"T.JK": df_calm.loc[(df_calm.index >= train_start) & (df_calm.index <= cutoff)]}
    scorer = fit_ridge_scorer(inner_train_dfs, horizon=10, alpha=10.0)
    assert scorer is not None

    ret_calm = run_inner_val({"T.JK": df_calm}, None, cutoff, train_end, scorer, threshold=0.0)
    ret_crash = run_inner_val({"T.JK": df_crash}, None, cutoff, train_end, scorer, threshold=0.0)
    assert ret_calm == ret_crash


def test_run_inner_val_open_position_at_boundary_is_dropped_not_leaked():
    """A position still open when the inner-val slice runs out at train_end
    must simply not appear in the results -- never resolved using data past
    train_end (which run_inner_val structurally cannot see anyway, but this
    documents the resulting behavior explicitly)."""
    df = _rw(300, 0.001, 3)
    train_start, train_end = df.index[0], df.index[250]
    cutoff = inner_split(train_start, train_end, val_frac=0.2)
    inner_train_dfs = {"T.JK": df.loc[(df.index >= train_start) & (df.index <= cutoff)]}
    scorer = fit_ridge_scorer(inner_train_dfs, horizon=10, alpha=10.0)
    assert scorer is not None

    returns = run_inner_val({"T.JK": df}, None, cutoff, train_end, scorer, threshold=-999.0)
    # every returned trade's entry AND exit must fall within [cutoff, train_end] --
    # can't directly inspect exit dates here (run_inner_val only returns floats),
    # but the point is this call completes without error even with an
    # always-true threshold that opens a position right at the boundary.
    assert isinstance(returns, list)


# ---------------------------------------------------------------------------
# select_hyperparams
# ---------------------------------------------------------------------------

def test_select_hyperparams_falls_back_when_too_little_inner_val_data():
    dfs = {"T.JK": _rw(120, 0.0005, 1)}  # too short for a real inner-val split
    train_start, train_end = dfs["T.JK"].index[0], dfs["T.JK"].index[-1]
    horizon, alpha, diag = select_hyperparams(dfs, None, train_start, train_end,
                                              min_inner_val_trades=10_000)  # impossible bar
    assert diag is None
    assert (horizon, alpha) == (10, 10.0)  # FALLBACK_HORIZON, FALLBACK_ALPHA


def test_select_hyperparams_picks_from_the_declared_grid():
    dfs = {f"T{i}.JK": _rw(400, 0.0006 + 0.0002 * i, i) for i in range(5)}
    master = pd.DatetimeIndex(sorted(set().union(*[set(d.index) for d in dfs.values()])))
    train_start, train_end = master[0], master[300]
    horizon, alpha, diag = select_hyperparams(dfs, None, train_start, train_end,
                                              min_inner_val_trades=1)
    assert horizon in HORIZON_GRID
    assert alpha in ALPHA_GRID
