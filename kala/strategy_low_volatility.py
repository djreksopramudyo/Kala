"""
Low-volatility anomaly — the FIRST mechanically distinct hypothesis left
after seven direction-based nulls.

WHY THIS IS DIFFERENT FROM EVERYTHING ALREADY RULED OUT
-------------------------------------------------------
Read PROJECT_STATUS.md: every hypothesis tested so far is about the DIRECTION
of recent price action —

  * ``momentum`` / ``long_momentum``  -> buy STRENGTH (things that went up)
  * ``mean_reversion``                -> buy WEAKNESS (oversold dips)
  * ``foreign_flow`` / ``broker_concentration`` -> follow smart-money FLOW

This one is about none of those. It scores a stock purely on how CALM it has
been — its realized return volatility — and prefers the least volatile names,
agnostic to whether they rose or fell. That is the low-volatility anomaly
(Baker-Bradley-Wurgler 2011; Blitz-van Vliet 2007): empirically, low-vol
stocks have historically earned BETTER risk-adjusted returns than high-vol
"lottery" stocks, the reverse of what CAPM predicts. It is a real, widely
replicated cross-sectional factor, not indicator re-stacking of the signals
that already failed.

It is price-only (free yfinance history, no paid feed), and the feature is
backward-only — realized vol at bar t uses only returns through bar t — so it
carries the same non-negotiable point-in-time contract as ``kala.scoring``
and no look-ahead risk from restated data.

THE HONEST ACID TEST, STATED UP FRONT
-------------------------------------
Low-vol stocks are low-BETA almost by construction, so the danger here is the
MIRROR IMAGE of the momentum result's beta-capture: momentum looked good only
because it rode the market UP; low-vol can look good simply because it holds
less market exposure and so drops less when the market falls. The
alpha-vs-benchmark excess-return check (``excess_returns`` in
``kala.walkforward``) is therefore exactly the right acid test — it measures
each pick against the benchmark held over the SAME window, stripping out "just
had less beta." A raw edge that vanishes in the excess check is not stock-
picking skill; it is a low-beta tilt you could get more cheaply by holding
less of the index. Judge this on the EXCESS numbers, not the raw ones.

And this is the EIGHTH hypothesis run through this harness. Every extra
strategy raises the odds one clears |t|>=2 by luck alone (multiple testing).
So a single good-looking run does NOT validate it: check it against
``kala.overfitting`` (PBO / deflated Sharpe), the excess-return alpha check,
and stability ACROSS folds — not one lucky window. Treat a positive result as
"worth a confirming test," never "found the edge."

STATUS: TESTED 2026-07-24 on real data (IDX: 53 tickers/10y/tick-floored
costs; US: 57 sharia large-caps/10y vs SPUS) -- NO OOS EDGE on either
market, and the most confidently NEGATIVE result of the whole project:
IDX raw t=-6.40, alpha t=-6.70 (n=3531); US raw looks like the same
beta-capture mirage momentum showed (t=8.91) but the alpha check lands at
a real, well-powered NEGATIVE (t=-2.05/-2.19, n~5700) rather than
momentum's noise-level flat. Same sign (negative) on both markets once
alpha-adjusted. See PROJECT_STATUS.md, "Low-volatility anomaly result",
for the full numbers and read -- not restated here so they can't go stale
in two places. DO NOT TRADE THIS.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .strategies import Strategy, register_strategy

VOL_WINDOW = 63          # ~one quarter of trading days over which realized vol is measured
TRADING_DAYS = 252       # annualization factor for daily-return std
# The score maps ANNUALIZED realized vol to 0-100, higher score = calmer stock.
# Anchors chosen to span the plausible range for this universe rather than
# tuned to any result: a very calm name (<= 20%/yr) saturates at 100, a wild
# one (>= 70%/yr) floors at 0, linear in between. These are deliberately round
# and wide so the strategy isn't curve-fit to a particular window.
LOW_VOL_ANN = 0.20       # <= 20% annualized realized vol -> max score (calmest)
HIGH_VOL_ANN = 0.70      # >= 70% annualized realized vol -> zero score (wildest)
# History to prepend before each entry window so realized_vol is already
# defined at the first entry bar. Without enough warmup the rolling std is
# all-NaN early and the strategy never trades on a fold (the same trap the
# long-horizon momentum strategy hit — see its module docstring).
WARMUP_BARS = VOL_WINDOW + 10


def compute_features_low_volatility(df: pd.DataFrame) -> pd.DataFrame:
    """Add ``realized_vol``: annualized standard deviation of daily returns
    over the trailing ``VOL_WINDOW`` bars. ``pct_change`` and ``rolling`` both
    look only backward, so the value at bar t uses data through t alone — no
    look-ahead. NaN for the first ``VOL_WINDOW`` bars (not enough history),
    which the score turns into 'no entry'."""
    feats = df.copy()
    daily_ret = feats["Close"].pct_change()
    feats["realized_vol"] = (
        daily_ret.rolling(VOL_WINDOW).std() * np.sqrt(TRADING_DAYS)
    )
    return feats


def score_low_volatility(feats: pd.DataFrame) -> pd.Series:
    """0-100: higher = CALMER (lower realized vol). A stock at or below
    ``LOW_VOL_ANN`` annualized vol scores 100; at or above ``HIGH_VOL_ANN``,
    0; linear between. NaN vol (too little history) stays NaN, which the
    backtest reads as 'do not enter'. Note the score is INVERSE to vol — this
    is the whole point: reward the boring names, not the exciting ones."""
    vol = feats["realized_vol"]
    span = HIGH_VOL_ANN - LOW_VOL_ANN
    score = (HIGH_VOL_ANN - vol) / span
    return score.clip(0.0, 1.0) * 100.0


LOW_VOLATILITY = register_strategy(Strategy(
    name="low_volatility",
    compute_features=compute_features_low_volatility,
    score=score_low_volatility,
    default_threshold=60.0,
    default_thresholds_grid=(40.0, 50.0, 60.0, 70.0, 80.0),
    warmup_bars=WARMUP_BARS,
    description=("Low-volatility anomaly: score each stock inversely to its "
                 "trailing ~quarter realized (annualized) volatility, "
                 "preferring the CALMEST names regardless of direction. "
                 "Price-only, point-in-time safe, no paid data. TESTED "
                 "2026-07-24 on IDX and US sharia large-caps: confidently "
                 "NEGATIVE on both markets once alpha-adjusted (IDX t=-6.70, "
                 "US t=-2.05/-2.19) — do not trade this. See PROJECT_STATUS.md "
                 "and this module's docstring."),
))
