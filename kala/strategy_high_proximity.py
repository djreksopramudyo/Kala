"""
52-week-high proximity — the George & Hwang (2004) anchoring anomaly, and
a genuinely DISTINCT price signal from every momentum variant already ruled
out.

WHY THIS IS NOT JUST MOMENTUM AGAIN
-------------------------------------
The failed momentum strategies (see PROJECT_STATUS.md) score a stock on its
trailing RETURN — how much it went up over some window. This scores a stock
on how close its price sits to its own trailing 52-WEEK HIGH, regardless of
the path it took to get there. George & Hwang's finding was specifically
that the 52-week-high ratio PREDICTS FUTURE RETURNS BETTER THAN trailing-
return momentum does, and that the two are empirically distinct: a stock can
have strong 12-month momentum yet sit well below its high (it ran up then
pulled back), or weak momentum yet sit right at its high (slow steady grind).
The proposed mechanism is anchoring/under-reaction: traders treat the 52-week
high as a reference point and are reluctant to bid a stock through it, so
good news near the high gets impounded slowly — a behavioral story, not a
trend-following one. Price-only, point-in-time safe, free yfinance data.

HONEST PRIOR, STATED UP FRONT
-------------------------------
This project has now ruled out twelve hypothesis/market combinations,
including three flavors of momentum. The base rate for "the next price
signal is the one that works" is, empirically in this project, low. George-
Hwang is a real published anomaly, but (a) most of its documented strength
is US large-cap and cross-sectional, (b) anchoring effects are exactly the
kind that arbitrage away as a market matures, and (c) it will face the same
IDX tick-floored costs that flipped momentum negative. Treat a positive
result as "worth a confirming test," never "found it," and judge it on the
EXCESS (alpha-vs-benchmark) check, not raw return — a signal that only buys
stocks near their highs is long a rising market almost by definition, the
same beta-capture trap the alpha check exists to catch (see the momentum and
low-volatility results in PROJECT_STATUS.md).

STATUS: TESTED 2026-07-24 -- NULL on BOTH markets, no edge. IDX (48 usable
tickers, 10y, tick-floored): weak null, raw t=-1.38, alpha t=-1.45
(n=1689) -- not a confident negative, just no signal. US sharia large-caps
(clean re-run, all 57 tickers + SPUS, 10y): raw t=9.12 "EDGE CONFIRMED" is
the usual mega-cap beta-capture mirage; the alpha check strips it to noise
(t=-0.56, n=5416) -- BETA, NOT ALPHA. (A first US attempt was invalid --
Yahoo throttled 41 tickers + the benchmark -- and was re-run clean.) See
PROJECT_STATUS.md, "Two more additions" -> Results, for detail -- not
restated here so numbers can't go stale in two places. Do not trade this.
"""

from __future__ import annotations

import pandas as pd

from .strategies import Strategy, register_strategy

HIGH_WINDOW = 252        # ~52 weeks of trading days
# The score maps the nearness ratio (close / trailing-52w-high) to 0-100.
# A stock AT its high (ratio 1.0) saturates at 100; one ``FLOOR_DISCOUNT``
# or more below its high floors at 0. Chosen round and wide, pre-declared,
# not fit to a result: George-Hwang's signal is the ratio itself, so this is
# just a monotone rescaling of it into the harness's 0-100 convention.
FLOOR_DISCOUNT = 0.30    # 30% below the high -> score 0
# History the harness must prepend so the trailing-252 high is defined at the
# first entry bar (else all-NaN early and zero trades on a fold — the trap the
# long-horizon momentum strategy hit; see its docstring).
WARMUP_BARS = HIGH_WINDOW + 10


def compute_features_high_proximity(df: pd.DataFrame) -> pd.DataFrame:
    """Add ``high_nearness``: close / trailing ``HIGH_WINDOW``-bar rolling max
    of close. ``rolling(...).max()`` looks only backward, so the value at bar
    t uses data through t alone — no look-ahead. NaN for the first
    ``HIGH_WINDOW`` bars (not enough history), which the score turns into
    'no entry'. By construction the ratio is in (0, 1]: the current close is
    always <= the max that includes it."""
    feats = df.copy()
    close = feats["Close"]
    rolling_high = close.rolling(HIGH_WINDOW).max()
    feats["high_nearness"] = close / rolling_high
    return feats


def score_high_proximity(feats: pd.DataFrame) -> pd.Series:
    """0-100: higher = closer to the 52-week high. A stock at its high
    (nearness 1.0) scores 100; at or below ``1 - FLOOR_DISCOUNT`` of its
    high, 0; linear between. NaN nearness (too little history) stays NaN,
    read by the backtest as 'do not enter'."""
    nearness = feats["high_nearness"]
    floor = 1.0 - FLOOR_DISCOUNT
    score = (nearness - floor) / (1.0 - floor)
    return score.clip(0.0, 1.0) * 100.0


HIGH_PROXIMITY = register_strategy(Strategy(
    name="high_proximity",
    compute_features=compute_features_high_proximity,
    score=score_high_proximity,
    default_threshold=60.0,
    default_thresholds_grid=(40.0, 50.0, 60.0, 70.0, 80.0),
    warmup_bars=WARMUP_BARS,
    description=("52-week-high proximity (George-Hwang anchoring anomaly): "
                 "score each stock by how close its price sits to its trailing "
                 "52-week high, a signal empirically DISTINCT from trailing-"
                 "return momentum. Price-only, point-in-time safe, no paid "
                 "data. TESTED 2026-07-24: NULL on both markets — weak IDX null "
                 "(alpha t=-1.45), US beta-not-alpha (raw t=9.12 → alpha "
                 "t=-0.56). Do not trade. See PROJECT_STATUS.md."),
))
