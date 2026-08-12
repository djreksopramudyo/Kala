"""
Long-horizon (12-1 month) momentum — the "one more shot," and deliberately a
STRUCTURALLY different one from everything that already failed.

WHY THIS, AFTER FOUR NULLS
--------------------------
The four hypotheses ruled out so far (see PROJECT_STATUS.md) all operate on
the SAME time scale: daily / short-horizon signals rebalanced fast. The
original ``momentum`` strategy scores off trend+RSI+ROC measured over days-
to-weeks. This one changes the STRUCTURE, not just the indicator: it is the
classic academic momentum factor — rank by the trailing 12-MONTH return,
SKIPPING the most recent month (the "12-1", ~252 trading days back to ~21
days back). That skip is not cosmetic: the most recent month carries a
well-documented SHORT-TERM REVERSAL that pollutes raw 12-month momentum, so
excluding it is what makes this the long-horizon factor rather than a slow
version of the signal that already failed.

It is price-only, so — unlike a fundamental tilt — there is NO look-ahead
risk from restated data, and it needs no paid feed: 5-10y of free yfinance
history is enough. The feature is backward-only (``shift`` into the past),
the same non-negotiable point-in-time contract as ``kala.scoring``.

HONEST CAVEAT, STATED UP FRONT
------------------------------
This is the FIFTH hypothesis tested on this project's harness. Every extra
strategy you try raises the chance that one clears |t|>=2 by luck alone
(multiple testing). So this is NOT validated by a single good-looking run:
judge it against the overfitting machinery this project already has
(``kala.overfitting`` — PBO / deflated Sharpe), the alpha-vs-benchmark
excess-return check (not just raw return), and stability ACROSS folds, not
one lucky window. Treat a positive result as "worth a confirming test," not
"found the edge." And note the harness applies this per-ticker via a trained
threshold ("buy when THIS stock's long-horizon momentum is high"), which
approximates but is not identical to a true cross-sectional top-decile
portfolio — a real cross-sectional test would be the natural follow-up if
this clears the bar.

STATUS: TESTED 2026-07-23 on real data (10y, 53 tickers, tick-floored costs)
-- NO OOS EDGE, and a clean, well-powered NEGATIVE (t=-3.05 raw, t=-2.43
alpha/excess, n=3043). See PROJECT_STATUS.md, "Long-horizon momentum
result", for the numbers -- not restated here so they can't go stale in two
places. (The first attempt showed 0 trades on every fold; that was a
harness warmup bug, fixed by the ``warmup_bars`` field below, not a result.)
"""

from __future__ import annotations

import pandas as pd

from .strategies import Strategy, register_strategy

LOOKBACK = 252   # ~12 months of trading days (the momentum window's far edge)
SKIP = 21        # ~1 month skipped at the near edge (drops short-term reversal)
FULL_SCORE_RETURN = 0.50   # an 11-month return of +50% maps to the max score of 100
# History the harness must prepend before each entry window so mom_12_1 (which
# reaches LOOKBACK bars back) is already defined at the first entry bar. Without
# this the default 60-bar warmup leaves the feature all-NaN and the strategy
# trades ZERO times on every fold. LOOKBACK + SKIP + a small margin.
WARMUP_BARS = LOOKBACK + SKIP + 10


def compute_features_longhorizon(df: pd.DataFrame) -> pd.DataFrame:
    """Add ``mom_12_1``: the return from ~12 months ago to ~1 month ago,
    i.e. Close.shift(SKIP) / Close.shift(LOOKBACK) - 1. Both terms are PAST
    values (shift is backward), so the figure at bar t uses only data through
    t — no look-ahead. NaN for the first ``LOOKBACK`` bars (not enough
    history), which the score turns into 'no entry'."""
    feats = df.copy()
    close = feats["Close"]
    past_near = close.shift(SKIP)
    past_far = close.shift(LOOKBACK)
    feats["mom_12_1"] = past_near / past_far - 1.0
    return feats


def score_longhorizon(feats: pd.DataFrame) -> pd.Series:
    """0-100: higher = stronger long-horizon momentum. Only POSITIVE momentum
    scores (this is a buy-strength factor); a +50% 11-month return or better
    saturates at 100. Negative or NaN momentum -> 0/NaN, which the backtest
    reads as 'do not enter'."""
    mom = feats["mom_12_1"]
    return (mom / FULL_SCORE_RETURN).clip(0.0, 1.0) * 100.0


LONGHORIZON_MOMENTUM = register_strategy(Strategy(
    name="long_momentum",
    compute_features=compute_features_longhorizon,
    score=score_longhorizon,
    default_threshold=50.0,
    default_thresholds_grid=(30.0, 40.0, 50.0, 60.0, 70.0),
    warmup_bars=WARMUP_BARS,
    description=("Classic 12-1 month momentum factor (trailing ~11-month "
                 "return, skipping the most recent month to drop short-term "
                 "reversal). Price-only, point-in-time safe, no paid data. "
                 "A structurally different horizon from the failed short-term "
                 "'momentum'. TESTED 2026-07-23: NO OOS EDGE, negative with real "
                 "power (see PROJECT_STATUS.md) -- do not trade this."),
))
