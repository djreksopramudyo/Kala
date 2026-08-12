"""
Strategy registry — pluggable signals over the EXISTING validation harness.

WHY THIS EXISTS
---------------
``backtest_ticker`` already accepts a ``score_override`` Series instead of
computing ``composite_score`` itself (that's how run_ml_walkforward.py tests
a fitted model). But there was no shared, discoverable way to define a new
hypothesis and get it through walk_forward/costs/vetoes/alpha-check for
free — every new idea meant hand-wiring score_override into a fresh script,
one accidental step away from silently skipping a discipline the validated
harness already enforces (point-in-time features, honest costs, OOS folds).

A ``Strategy`` here is just ``compute_features`` + ``score`` blessed into one
named, registered object. Register it once; every existing validation tool
(backtest_ticker, walk_forward, compare_exit_engines, the signal auditor)
can run it identically to how they already run the default momentum score.

USAGE
-----
    from kala.strategies import Strategy, register_strategy

    def my_features(df): ...      # same contract as scoring.compute_features
    def my_score(feats): ...      # same contract as scoring.composite_score

    register_strategy(Strategy(
        name="my_idea", compute_features=my_features, score=my_score,
        default_threshold=60.0, description="..."))

Then validate it with the SAME rigor as everything else:

    from kala.strategies import get_strategy, walk_forward_strategy
    report = walk_forward_strategy(get_strategy("my_idea"), dfs, benchmark=bench)
    print(report.summary_text())

No new hypothesis is trustworthy until it clears the same bar the momentum
score didn't: |t| >= 2 on BOTH raw and benchmark-excess OOS return, on the
unfiltered universe, confirmed more than one way. See PROJECT_STATUS.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pandas as pd

from .walkforward import DEFAULT_THRESHOLDS, WalkForwardReport, walk_forward


@dataclass(frozen=True)
class Strategy:
    """A named, registered (features, score) pair — the unit the walk-forward
    harness validates. ``compute_features``/``score`` must be POINT-IN-TIME
    (see scoring.py's module docstring for why that's non-negotiable): the
    value at bar t may depend only on data up to and including bar t."""
    name: str
    compute_features: Callable[[pd.DataFrame], pd.DataFrame]
    score: Callable[[pd.DataFrame], pd.Series]
    default_threshold: float
    description: str = ""
    default_thresholds_grid: tuple = DEFAULT_THRESHOLDS
    # Bars of history the harness must prepend BEFORE each entry window so this
    # strategy's longest-lookback feature is already defined at the first entry
    # bar. Short-horizon signals (trend/RSI/ROC) are fine with the harness's
    # default 60; a long-horizon feature (e.g. 12-month momentum) needs its full
    # lookback here or it computes all-NaN on every fold and never trades. See
    # walk_forward_strategy, which passes this through as ``warmup_bars``.
    warmup_bars: int = 60
    # True if this strategy's compute_features reads a "Dividends" column.
    # Most strategies need only OHLCV, and fetch() strips everything else by
    # default to keep the warehouse cache schema stable — a strategy that
    # needs more must say so explicitly, or its feature is silently all-NaN
    # and it looks like a null result instead of a missing-data one.
    needs_dividends: bool = False


_REGISTRY: dict[str, Strategy] = {}


def register_strategy(strat: Strategy) -> Strategy:
    """Register (or re-register, e.g. in a test) a strategy by name."""
    _REGISTRY[strat.name] = strat
    return strat


def get_strategy(name: str) -> Strategy:
    try:
        return _REGISTRY[name]
    except KeyError as e:
        raise KeyError(f"unknown strategy '{name}'; available: {list_strategies()}") from e


def list_strategies() -> list[str]:
    return sorted(_REGISTRY)


def score_series(strategy: Strategy, df: pd.DataFrame) -> pd.Series:
    """compute_features + score in one call, on the frame AS GIVEN — for
    inspecting a strategy's raw score (e.g. plotting it). NOT used by
    walk_forward_strategy internally: the harness recomputes the score fresh
    on each fold's own sliced window instead (see evaluate_window's
    docstring for why — EMA-based features are not slice-invariant, so a
    score computed once on full history and reindexed would silently differ
    from what backtest_ticker computes on the window it actually trades)."""
    feats = strategy.compute_features(df)
    return strategy.score(feats)


def score_all(strategy: Strategy, dfs: dict[str, pd.DataFrame]) -> dict[str, pd.Series]:
    """{ticker: score_series} for every ticker — for inspection only (see
    score_series's docstring); walk_forward_strategy does not use this."""
    return {ticker: score_series(strategy, df) for ticker, df in dfs.items()}


def walk_forward_strategy(strategy: Strategy, dfs: dict[str, pd.DataFrame],
                          benchmark: pd.DataFrame | None = None,
                          thresholds=None, **kwargs) -> WalkForwardReport:
    """Run ``strategy`` through the exact same walk_forward harness the
    default momentum score was validated (and retracted) through. The score
    is computed fresh on each fold's sliced window (via evaluate_window's
    ``strategy=`` hook) — identical treatment to how composite_score is
    computed, so this strategy gets the same point-in-time guarantees AND
    the same numeric behavior (see evaluate_window's docstring on EMA
    slice-invariance).

    ``thresholds`` defaults to ``strategy.default_thresholds_grid`` — a
    strategy whose score isn't 0-100 (e.g. a z-score) MUST pass its own
    grid; the momentum default (50-75) would be meaningless on it.

    ``cfg``: if omitted, a default ``Config()`` is built with its baseline
    threshold set to ``strategy.default_threshold`` (the walk-forward
    "fixed baseline" comparison arm). Pass your own ``cfg`` to override
    that explicitly — it is used exactly as given, no magic.

    ``warmup_bars`` defaults to ``strategy.warmup_bars`` so a long-lookback
    signal gets enough history prepended before each entry window to be
    defined at all (otherwise it computes all-NaN on every fold and silently
    trades zero times). An explicit ``warmup_bars=`` kwarg still wins.
    """
    cfg = kwargs.pop("cfg", None)
    if cfg is None:
        from dataclasses import replace

        from .config import Config
        cfg = replace(Config(), backtest=replace(
            Config().backtest, score_entry_threshold=strategy.default_threshold))
    kwargs.setdefault("warmup_bars", strategy.warmup_bars)
    return walk_forward(dfs, cfg=cfg, benchmark=benchmark,
                        thresholds=thresholds or strategy.default_thresholds_grid,
                        strategy=strategy, **kwargs)


# ---------------------------------------------------------------------------
# The existing validated (now UNVALIDATED — see PROJECT_STATUS.md) signal,
# registered as the baseline entry so it's just one more zoo member, not a
# hardcoded special case.
# ---------------------------------------------------------------------------

from .scoring import composite_score as _momentum_score  # noqa: E402
from .scoring import compute_features as _momentum_features  # noqa: E402

MOMENTUM = register_strategy(Strategy(
    name="momentum",
    compute_features=_momentum_features,
    score=_momentum_score,
    default_threshold=60.0,
    description=("Original composite score (trend + RSI + ROC). "
                 "UNVALIDATED as of 2026-07-20 -- no OOS edge survived honest "
                 "costs. See PROJECT_STATUS.md before trusting this one."),
))
