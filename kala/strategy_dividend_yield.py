"""
Dividend yield — the last untested SIGNAL idea, and the only value-adjacent
factor this project can test without the point-in-time fundamentals it lacks.

WHY THIS ONE IS TESTABLE WHEN VALUE/QUALITY ARE NOT
-----------------------------------------------------
The highest-evidence factors in finance (value, quality, earnings drift) are
all blocked here for the same reason: they need point-in-time FUNDAMENTALS,
and this project has no verified history of what a company's reported figures
looked like on a past date (see `kala/fundamental_archive.py` — the archive
exists but needs calendar time to accumulate).

Trailing dividend yield escapes that trap. A dividend is a CASH EVENT with a
known date: on the day it is paid, the amount is public and final, and it is
never restated the way an earnings figure can be. So "sum of dividends paid in
the last 12 months, divided by today's price" is computable from free price +
dividend history and is genuinely point-in-time safe — no look-ahead, no
restatement risk, no vendor needed. It is also a partial VALUE proxy (a high
yield usually means a low price relative to distributions), which is why it's
worth testing even though it isn't the pure value factor.

It has a second, non-statistical relevance here: dividend income is
uncontroversially permissible for a sharia investor, and the portfolio this
project serves is a long-horizon buy-and-hold one where distributions matter
more than they would to a trader.

HONEST PRIOR — AND THE SPECIFIC TRAP TO WATCH
------------------------------------------------
Fourteenth hypothesis. Thirteen came back null. More specifically, the danger
with dividend yield is the YIELD TRAP: yield is dividends divided by price, so
it mechanically SPIKES when the price collapses. A screen for "highest yield"
therefore selects partly for "recently crashed," which is close to the
mean-reversion strategy this project already tested and found actively
NEGATIVE (see PROJECT_STATUS.md — buying oversold weakness lost money with
t=-3.91). If this strategy shows a positive raw result, check whether it is
just that failed trade in disguise before believing it.

The score therefore CAPS at a moderate yield rather than rewarding extremes
monotonically: a 3-6% yield reads as a healthy distribution, while a 25% yield
almost always means the price has collapsed or a one-off special dividend was
paid, neither of which is the effect this is trying to capture. That cap is
declared up front, not tuned to a result.

DATA REQUIREMENT
----------------
Unlike every other strategy in the zoo, this needs a ``Dividends`` column
alongside OHLCV (yfinance supplies it via ``actions=True``). If the column is
missing the feature is all-NaN and the strategy simply never trades, rather
than silently scoring everything zero — a missing input must not look like a
real "no dividend" reading.

STATUS: TESTED 2026-07-25 on real data (53 tickers, 10y, tick-floored costs,
after fixing a real fetch() gap -- see DATA REQUIREMENT above and
PROJECT_STATUS.md for the bug) -- NO OOS EDGE, and a CLEAN rejection: raw
t=-2.75, alpha t=-2.56 (n=1988), agreeing in sign, both clearing |t|>2.5.
Unlike every US raw number elsewhere in this project, this is not a
beta-capture mirage that dies on the alpha check -- it is negative both ways.
Plausible mechanism, matching the yield-trap risk this docstring flagged
before testing: the taper-down guard stops the most extreme cases, but a
5-15% trailing yield can still often mean "price fell partway, not yet cut"
rather than a healthy payer -- the same mean-reversion-flavored trade this
project already found negative elsewhere (t=-3.91). Fourteenth hypothesis;
still none survive an honest alpha check. DO NOT TRADE THIS. See
PROJECT_STATUS.md, "Survivorship check, sizing sweep, and dividend yield",
for the full numbers -- not restated here so they can't go stale in two
places.
"""

from __future__ import annotations

import pandas as pd

from .strategies import Strategy, register_strategy

LOOKBACK = 252           # ~12 months of dividends
# Yield anchors, declared before any test was run. A stock paying at or above
# FULL_SCORE_YIELD of its price over the trailing year saturates the score;
# below MIN_YIELD it scores zero. Above CAP_YIELD the score is DEDUCTED back
# toward zero -- see the yield-trap discussion in the module docstring.
MIN_YIELD = 0.01         # 1%/yr -- below this, not a meaningful distribution
FULL_SCORE_YIELD = 0.05  # 5%/yr -- a healthy sustainable payer
CAP_YIELD = 0.15         # >15%/yr -- almost always a crashed price or a special
WARMUP_BARS = LOOKBACK + 10


def compute_features_dividend_yield(df: pd.DataFrame) -> pd.DataFrame:
    """Add ``trailing_yield``: dividends paid over the trailing ``LOOKBACK``
    bars divided by the current close. ``rolling(...).sum()`` looks only
    backward and a dividend is final on its payment date, so the value at bar
    t uses data through t alone — no look-ahead, no restatement risk.

    If the frame has no ``Dividends`` column the feature is all-NaN (the
    strategy then never trades), deliberately distinct from a real 0.0 yield:
    a missing data source must not masquerade as a genuine 'pays nothing'."""
    feats = df.copy()
    if "Dividends" not in feats.columns:
        feats["trailing_yield"] = pd.Series(float("nan"), index=feats.index)
        return feats
    divs = feats["Dividends"].fillna(0.0)
    trailing = divs.rolling(LOOKBACK).sum()
    close = feats["Close"].replace(0.0, pd.NA)
    feats["trailing_yield"] = trailing / close
    return feats


def score_dividend_yield(feats: pd.DataFrame) -> pd.Series:
    """0-100, rising from ``MIN_YIELD`` to ``FULL_SCORE_YIELD`` and then FALLING
    back toward zero above ``CAP_YIELD``. The downslope is the yield-trap guard:
    an extreme trailing yield nearly always means the denominator (price)
    collapsed, which would turn this into the mean-reversion trade already shown
    to lose money here. NaN yield stays NaN -> 'do not enter'."""
    y = feats["trailing_yield"]
    span = FULL_SCORE_YIELD - MIN_YIELD
    rising = ((y - MIN_YIELD) / span).clip(0.0, 1.0)
    # taper: full credit up to CAP_YIELD, then linearly down to 0 by 2*CAP_YIELD
    taper = (1.0 - (y - CAP_YIELD) / CAP_YIELD).clip(0.0, 1.0)
    taper = taper.where(y > CAP_YIELD, 1.0)
    return (rising * taper * 100.0).where(y.notna())


DIVIDEND_YIELD = register_strategy(Strategy(
    name="dividend_yield",
    compute_features=compute_features_dividend_yield,
    score=score_dividend_yield,
    default_threshold=50.0,
    default_thresholds_grid=(30.0, 40.0, 50.0, 60.0, 70.0),
    warmup_bars=WARMUP_BARS,
    needs_dividends=True,
    description=("Trailing-12-month dividend yield: the only value-adjacent "
                 "factor testable without point-in-time fundamentals, since a "
                 "paid dividend is a dated cash event that is never restated. "
                 "Score tapers DOWN above an extreme yield to avoid the yield "
                 "trap. TESTED 2026-07-25: NO OOS EDGE, a clean rejection -- "
                 "raw t=-2.75, alpha t=-2.56, agreeing in sign (not the usual "
                 "beta-capture mirage). Fourteenth hypothesis rejected. Do not "
                 "trade this. See PROJECT_STATUS.md."),
))
