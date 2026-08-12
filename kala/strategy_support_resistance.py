"""
Support/resistance proximity — the classic retail day-trading level concept,
operationalized on daily bars and put through the same harness that ruled out
the previous eleven hypotheses.

WHAT IS BEING TESTED
--------------------
The claim, as usually taught: price reverses at levels it has reversed at
before, so buying near a level that has held REPEATEDLY is better than buying
at random. Operationalized here exactly as the folk method describes it:

  1. find swing lows (pivot lows) in trailing history;
  2. cluster nearby pivots into ZONES, not exact lines ("it can bounce
     anywhere in this zone");
  3. count how many times each zone was touched — a zone needs at least
     ``MIN_TOUCHES`` before it is trusted at all ("I don't want to bet on a
     level the market has only hit once");
  4. score highest when price sits close to a strong, well-touched support
     zone; score nothing when the nearest zone is weak, far away, or has
     been sliced through ("the moment price slices a level, I delete it").

THE LOOK-AHEAD TRAP THIS MODULE EXISTS TO AVOID
-------------------------------------------------
A pivot low at bar i is only recognizable as a pivot once ``PIVOT_K`` bars
AFTER i have printed — you cannot know bar i was the local bottom until the
market has turned back up and stayed up. Backtests of support/resistance
routinely get this wrong: they detect pivots on the full series and then
"trade" them at the pivot bar, which is knowledge from the future and
manufactures an edge that cannot be captured live. ``compute_features``
therefore only uses pivots whose confirmation bar (pivot bar + ``PIVOT_K``)
is at or before the bar being scored. ``test_strategy_support_resistance.py``
tests this specifically, because it is the single most likely way for this
strategy to produce a fake positive.

HONEST PRIOR, STATED UP FRONT
-------------------------------
Low. Two of this signal's cousins are already in the zoo and both came back
null: ``mean_reversion`` (buy when price is far below a moving average) and
``high_proximity`` (score by nearness to the 52-week high). "Buy near a
price floor" overlaps substantially with the first — expect the two scores to
be correlated, and do not read a positive result here as independent
confirmation of anything. This is also the most heavily data-mined pattern in
retail trading: it has been taught for decades to millions of people, which is
precisely the condition under which an exploitable edge should already be
gone.

Two further caveats specific to this test:

  * The popular version of this method is INTRADAY (1-5 minute bars). This
    tests the daily-bar version, because that is the data this project has.
    A null here does not disprove the intraday claim; it tests whether the
    level concept carries any predictive content at daily frequency.
  * "Break and retest" and "failed breakout" are separate hypotheses, not
    tested here. Their closest existing analogues in the zoo — ``momentum``
    (continuation after a break) and ``mean_reversion`` (fade an extreme) —
    are both already null.

Judge this on the EXCESS (alpha-vs-benchmark) t-stat, not raw return. A
strategy that buys dips in a rising market is long beta by construction, the
same trap that made momentum and low-volatility look good before the alpha
check stripped them (see PROJECT_STATUS.md).

STATUS: TESTED 2026-08-03 -- CONFIDENTLY NEGATIVE. IDX (53 tickers, 5y,
tick-floored): raw t=-3.52, alpha t=-3.40, n=1432 OOS trades -- not a weak or
underpowered null, both raw and excess agree in sign and clear |t|>3.4 on a
large sample. Buying near a well-touched daily support zone lost money, both
in isolation and against the benchmark held over the same days. Consistent
with its two closest cousins already in the zoo, mean_reversion (t=-3.9) and
high_proximity (null): all three "price relative to a reference level"
framings have now failed on this universe. Does NOT test the intraday
version of the method (no intraday IDX data available) -- says nothing about
day-trading timeframes specifically, only that the level concept carries no
predictive content at daily frequency here. See PROJECT_STATUS.md,
"Support/resistance result". Do not trade this.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .strategies import Strategy, register_strategy

# Bars on each side of a bar that must be higher for it to count as a swing
# low. Also the CONFIRMATION LAG: a pivot at bar i is unusable until bar i+K.
PIVOT_K = 5
# How far back to look for pivots when building the zone map. One trading
# year -- long enough to accumulate repeat touches, short enough that a level
# from three years ago isn't treated as live.
LOOKBACK = 252
# Pivots whose prices are within this fraction of each other collapse into one
# zone. This is the "zones, not lines" rule; 2% is a round pre-declared choice,
# not tuned to a result.
ZONE_PCT = 0.02
# A zone must have been touched at least this many times to be traded. The
# folk rule is "at least two touches"; taken literally.
MIN_TOUCHES = 2
# How close price must be to a zone to count as "at" it, as a fraction of
# price. Beyond this the proximity component scores zero.
NEAR_PCT = 0.03
# Touch count at which zone strength saturates. Two touches is the minimum
# (half credit), four or more is full credit.
STRONG_TOUCHES = 4
# A candidate pivot must sit at least this far below the surrounding window's
# high to count as a real swing low. Without it, a FLAT price stretch makes
# every bar a "pivot" (each bar trivially equals the window minimum), and an
# illiquid stock that simply did not move for weeks manufactures a zone with
# dozens of "touches" -- a fake maximum-strength support level built from no
# swings at all. That failure mode is common in this universe, not exotic.
MIN_SWING_PCT = 0.01

WARMUP_BARS = LOOKBACK + PIVOT_K + 10


def _cluster_zones(prices: list[float], zone_pct: float) -> list[tuple[float, int]]:
    """Collapse a list of pivot prices into ``(zone_level, n_touches)`` pairs.

    Sorted single pass: a price joins the current zone while it stays within
    ``zone_pct`` of that zone's LOWEST member, which bounds each zone's width
    at ``zone_pct`` instead of letting a long chain of near-neighbours drift
    into one arbitrarily wide zone. ``zone_level`` is the mean of its members.
    """
    if not prices:
        return []
    ordered = sorted(prices)
    zones: list[tuple[float, int]] = []
    current = [ordered[0]]
    for p in ordered[1:]:
        if current[0] > 0 and (p - current[0]) / current[0] <= zone_pct:
            current.append(p)
        else:
            zones.append((sum(current) / len(current), len(current)))
            current = [p]
    zones.append((sum(current) / len(current), len(current)))
    return zones


def _separate_pivots(positions: np.ndarray, min_gap: int) -> np.ndarray:
    """Keep only pivots at least ``min_gap`` bars apart, earliest first.

    Two bars one day apart at nearly the same low are ONE swing being counted
    twice, not two independent tests of a level. Left unchecked this inflates
    touch counts (the strategy's entire strength measure) on exactly the kind
    of choppy, thinly-traded name where the level means least.
    """
    kept: list[int] = []
    for pos in positions:
        if not kept or pos - kept[-1] >= min_gap:
            kept.append(int(pos))
    return np.array(kept, dtype=int)


def compute_features_support_resistance(df: pd.DataFrame) -> pd.DataFrame:
    """Add ``sr_dist`` and ``sr_touches``.

    ``sr_dist``    (close - zone_level) / close for the nearest qualifying
                   SUPPORT zone: ~0 means price is sitting on the zone,
                   positive means above it, slightly negative means price has
                   just penetrated it.
    ``sr_touches`` how many pivots formed that zone.

    Both NaN when no qualifying zone exists (too little history, or nothing
    with enough touches within reach), which the score reads as "no entry".

    POINT-IN-TIME: the centered rolling min below deliberately looks forward
    -- that is what makes a swing low a swing low -- so the pivot list is
    then filtered to ``pivot_pos <= t - PIVOT_K`` at every bar t. Nothing the
    market had not yet confirmed by bar t can influence bar t's score.
    """
    feats = df.copy()
    low = feats["Low"]
    close = feats["Close"]
    n = len(feats)

    # A bar is a pivot low if it is the minimum of the window centered on it
    # AND that window actually rises away from it by MIN_SWING_PCT (a real V,
    # not a flat stretch -- see MIN_SWING_PCT). This READS THE FUTURE by
    # construction; the confirmation lag applied in the loop below is what
    # makes its use legitimate.
    window = 2 * PIVOT_K + 1
    centered_min = low.rolling(window, center=True).min()
    # Depth is measured against the surrounding LOWS, not the intrabar highs:
    # a bar is only a swing low if neighbouring TROUGHS sit meaningfully above
    # it. Comparing against High instead would let a stock with a steady
    # intraday range qualify on every bar of a dead-flat stretch.
    centered_max_low = low.rolling(window, center=True).max()
    swing_depth = (centered_max_low - low) / low.where(low > 0)
    is_pivot = ((low <= centered_min) & centered_min.notna()
                & (swing_depth >= MIN_SWING_PCT))

    pivot_pos = _separate_pivots(np.flatnonzero(is_pivot.to_numpy()), PIVOT_K)
    pivot_price = low.to_numpy()[pivot_pos]

    dist = np.full(n, np.nan)
    touches = np.full(n, np.nan)
    close_arr = close.to_numpy(dtype=float)

    for t in range(n):
        newest_allowed = t - PIVOT_K          # confirmation lag -- the whole point
        if newest_allowed < 0:
            continue
        oldest_allowed = t - LOOKBACK
        sel = (pivot_pos >= oldest_allowed) & (pivot_pos <= newest_allowed)
        if not sel.any():
            continue
        c = close_arr[t]
        if not np.isfinite(c) or c <= 0:
            continue

        best_d = None
        best_touches = 0
        for level, n_touch in _cluster_zones(list(pivot_price[sel]), ZONE_PCT):
            if n_touch < MIN_TOUCHES:
                continue
            # Support means at or below price. A zone slightly ABOVE price is
            # still eligible (price has just dipped into it); one far above is
            # broken support -- excluded, per "when a level slices, drop it".
            if level > c * (1.0 + NEAR_PCT):
                continue
            d = (c - level) / c
            if best_d is None or abs(d) < abs(best_d):
                best_d, best_touches = d, n_touch

        if best_d is not None:
            dist[t] = best_d
            touches[t] = best_touches

    feats["sr_dist"] = dist
    feats["sr_touches"] = touches
    return feats


def score_support_resistance(feats: pd.DataFrame) -> pd.Series:
    """0-100: high when price sits close to a heavily-touched support zone.

    Two multiplied components, so BOTH must be present -- being near a weak
    zone or far from a strong one scores near zero, matching the stated rule
    that a level is only worth trading when it is both close and proven:

      proximity  1.0 at the zone, falling linearly to 0 at ``NEAR_PCT`` away
      strength   0.5 at ``MIN_TOUCHES``, rising to 1.0 at ``STRONG_TOUCHES``

    NaN inputs (no qualifying zone) propagate to NaN = do not enter.
    """
    dist = feats["sr_dist"]
    touches = feats["sr_touches"]

    proximity = (1.0 - (dist.abs() / NEAR_PCT)).clip(0.0, 1.0)
    span = max(STRONG_TOUCHES - MIN_TOUCHES, 1)
    strength = (0.5 + 0.5 * (touches - MIN_TOUCHES) / span).clip(0.0, 1.0)
    # The touch minimum is also enforced when zones are built, but it is
    # re-applied here so the rule holds for ANY caller of this function
    # (score_series, the signal auditor, a plot) rather than depending on
    # having gone through compute_features first.
    strength = strength.where(touches >= MIN_TOUCHES, 0.0)
    return proximity * strength * 100.0


SUPPORT_RESISTANCE = register_strategy(Strategy(
    name="support_resistance",
    compute_features=compute_features_support_resistance,
    score=score_support_resistance,
    default_threshold=50.0,
    # The score is 0-100 but concentrated near 0 (most bars are not sitting on
    # a strong zone), so the momentum grid's 50-75 would rarely trade. This
    # grid reaches lower to give the signal a fair chance to produce trades.
    default_thresholds_grid=(20.0, 30.0, 40.0, 50.0, 60.0),
    warmup_bars=WARMUP_BARS,
    description=("Support/resistance proximity: cluster confirmed swing lows "
                 "into zones, require repeat touches, score by nearness to the "
                 "nearest strong support zone. Daily-bar version of the classic "
                 "retail level method. Pivot detection is lagged by PIVOT_K bars "
                 "to avoid the look-ahead that makes most S/R backtests fake. "
                 "TESTED 2026-08-03: CONFIDENTLY NEGATIVE (raw t=-3.52, alpha "
                 "t=-3.40, n=1432). Do not trade. See PROJECT_STATUS.md."),
))
