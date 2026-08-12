"""
Multi-horizon sign-sum trend — the AHL / time-series-momentum construction,
reduced to the one component this project has not already tested.

WHAT IS BEING TESTED, AND WHAT IS DELIBERATELY LEFT OUT
---------------------------------------------------------
The published trend-following recipe (Moskowitz-Ooi-Pedersen 2012 "Time
Series Momentum"; Lemperiere et al. 2014 "Two Centuries of Trend Following";
the AHL whiteboard description) has three separable parts:

  1. a MULTI-HORIZON SIGN-SUM signal: for each lookback L, take
     sign(close_t - close_{t-L}), and add the signs up;
  2. VOLATILITY-SCALED position sizing (position ~ score * risk / vol);
  3. LONG AND SHORT exposure across MANY uncorrelated markets.

Only (1) is tested here, on purpose:

  * (2) was already tested on this project's real data as a standalone
    question (Moreira-Muir volatility targeting, see PROJECT_STATUS.md ->
    "Volatility targeting"): a real return cost on both clean IDX windows,
    not justified by the drawdown reduction. Bundling a separately-rejected
    component into a new signal would make a null result uninterpretable --
    you would not know which half failed.
  * (3) is not available. This universe is long-only (shorting IDX equities
    is restricted, and short-selling is broadly impermissible under the
    sharia screen this project's universe is built on), and it is ~50
    correlated Indonesian equities rather than 700 mutually uncorrelated
    futures markets.

That third point is the honest caveat on this entire test, and it is not a
small one. **The 140-year trend-following record is a DIVERSIFICATION
result.** Commodities, FX, bonds and equity indices trend for different
structural reasons (hedging pressure, carry, macro cycles) and are not
mutually correlated, so a portfolio of many weak trend signals compounds
into a strong one. A long-only trend filter on a single correlated equity
basket is a market-timing overlay on one beta -- a mechanically different
thing that happens to share a formula. A null here says nothing about
whether diversified futures trend following works; it says whether this
particular signal shape carries information on THIS universe.

WHY IT IS STILL WORTH A RUN
-----------------------------
The signal shape is genuinely untested here, and sits in a gap between two
things that were tested:

  * ``momentum`` (composite trend + RSI + ROC, days-to-weeks): no OOS edge;
  * ``long_momentum`` (12-1, i.e. 252 back to 21 days): confidently
    negative (raw t=-3.05, alpha t=-2.43).

This one is SIGN-BASED rather than magnitude-based (so a single explosive
move cannot dominate the score, which is the property trend followers
actually claim matters), aggregates FOUR horizons instead of one, and those
horizons (5-42 days) sit between the two windows already ruled out.

HONEST PRIOR
------------
Poor. Two of the three components above have already failed on this
universe individually, the third is unavailable, and this is the sixteenth
hypothesis through the same harness -- every additional test raises the
chance that one clears |t|>=2 by luck alone. Judge it on the EXCESS
(alpha-vs-benchmark) t-stat, not raw return: a long-only trend filter is
long the market whenever the market is rising, which is exactly the
beta-capture pattern the alpha check exists to strip.

STATUS: TESTED 2026-08-03 -- NULL-TO-NEGATIVE, not tradeable either way. IDX
(53 tickers, 5y, tick-floored): the walk-forward-TRAINED threshold arm came
back flat (raw t=-0.38, alpha t=+0.22, n=1882) -- but that arm almost always
selected the strictest rule on the grid (thr=90, all four horizons must
agree). The naive FIXED threshold of 60 (the loose "majority of horizons
agree" rule most people would actually trade, applied uniformly with no
per-fold retuning) came back confidently NEGATIVE (raw t=-2.66, alpha
t=-2.50, n=3009). Read together: training did not find real structure, it
retreated to the thinnest, strictest trade subset where a real negative
effect became too noisy to distinguish from zero -- exactly the overfitting
failure mode the walk-forward harness's baseline-vs-trained comparison
exists to catch. There is no version of this signal worth trading: strict
does nothing, loose loses money with statistical power. See
PROJECT_STATUS.md, "Multi-horizon trend result". Do not trade this.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .strategies import Strategy, register_strategy

# The four lookbacks from the published description: roughly 1 week, 2 weeks,
# 1 month, 2 months of trading days. Pre-declared, taken from the source
# material rather than searched over -- fitting these to a result on this
# universe would be exactly the overfitting this project exists to avoid.
LOOKBACKS = (5, 10, 21, 42)

# History the harness must prepend so the longest lookback is defined at the
# first entry bar (otherwise the feature is all-NaN early and the strategy
# silently trades zero times -- the trap long_momentum hit; see its docstring).
WARMUP_BARS = max(LOOKBACKS) + 20


def compute_features_multihorizon_trend(df: pd.DataFrame) -> pd.DataFrame:
    """Add ``trend_sign_sum``: the sum over ``LOOKBACKS`` of
    ``sign(close_t - close_{t-L})``.

    Range is -len(LOOKBACKS)..+len(LOOKBACKS). With four lookbacks and no
    exact ties the sum is even (-4, -2, 0, +2, +4), since it equals
    (#up - #down) with #up + #down = 4. Exact ties (a genuinely unchanged
    close, common on thinly-traded IDX names) contribute 0 rather than +1,
    which correctly declines to read a flat stretch as an uptrend.

    POINT-IN-TIME: ``shift(L)`` reaches only backwards, so the value at bar
    t depends on closes at t and t-L alone. NaN until the longest lookback
    is available, which the score passes through as "do not enter".
    """
    feats = df.copy()
    close = feats["Close"]

    total = None
    for lookback in LOOKBACKS:
        # sign() of NaN is NaN, so early bars stay NaN and propagate through
        # the sum -- the signal is simply undefined until it has the history.
        leg = np.sign(close - close.shift(lookback))
        total = leg if total is None else total + leg

    feats["trend_sign_sum"] = total
    return feats


def score_multihorizon_trend(feats: pd.DataFrame) -> pd.Series:
    """Map the sign-sum linearly onto the harness's 0-100 convention.

    With four lookbacks: +4 (every horizon up) -> 100, 0 (mixed) -> 50,
    -4 (every horizon down) -> 0. A monotone rescaling of the raw signal --
    no extra shape is introduced, so the threshold the harness trains is
    directly interpretable as "how many horizons must agree".

    Note this makes 50, not 0, the neutral point; the strategy's threshold
    grid is set accordingly (a momentum-style 50-75 grid would otherwise
    mean something quite different here).
    """
    n = len(LOOKBACKS)
    return (feats["trend_sign_sum"] + n) / (2.0 * n) * 100.0


MULTIHORIZON_TREND = register_strategy(Strategy(
    name="multihorizon_trend",
    compute_features=compute_features_multihorizon_trend,
    score=score_multihorizon_trend,
    default_threshold=60.0,
    # The score takes only 5 discrete values (0/25/50/75/100), so thresholds
    # are chosen to land BETWEEN levels and select genuinely distinct rules:
    #   20 -> sum >= -2   (at least one horizon up; very loose)
    #   40 -> sum >=  0   (no net downtrend)
    #   60 -> sum >= +2   (majority of horizons up)
    #   90 -> sum == +4   (unanimous)
    # A denser grid would waste folds testing duplicate rules.
    default_thresholds_grid=(20.0, 40.0, 60.0, 90.0),
    warmup_bars=WARMUP_BARS,
    description=("Multi-horizon sign-sum trend (time-series momentum / AHL "
                 "construction): sum sign(close_t - close_{t-L}) over L in "
                 "5/10/21/42 days. TESTED 2026-08-03: NULL-TO-NEGATIVE -- "
                 "trained threshold arm flat (t=-0.38/+0.22, retreated to the "
                 "strictest rule), naive fixed threshold confidently NEGATIVE "
                 "(t=-2.66/-2.50, n=3009). Do not trade. See PROJECT_STATUS.md."),
))
