"""
Turn-of-month effect — the tenth hypothesis, and the first calendar-based
(not price/volume/flow/volatility) mechanism tried.

WHY THIS IS DIFFERENT FROM EVERYTHING ELSE IN THE ZOO
-------------------------------------------------------
Every prior hypothesis (see PROJECT_STATUS.md) scores a stock off its OWN
price/volume/flow history — direction (momentum, mean-reversion), flow
(bandarmology), or magnitude of movement (low-volatility). This one ignores
the stock's own history entirely and scores purely off the CALENDAR: it
prefers entries in the first few trading days of a month, agnostic to any
price action. This is the classic "turn-of-month" (TOM) anomaly (Ariel 1987;
Lakonishok & Smidt 1988): a large share of a market's long-run return has
historically clustered around month boundaries, plausibly tied to
institutional cash flows — payroll investing, mutual fund subscriptions,
pension contributions — that are mechanically concentrated at month-start,
not stock-specific skill.

WHY ONLY HALF THE CLASSIC DEFINITION IS IMPLEMENTED
-----------------------------------------------------
The textbook Ariel/Lakonishok-Smidt window is "the LAST trading day of month
M through the first ``N_START_DAYS`` of month M+1." Only the second half is
implemented here. The first half — "is today the last trading day of its
month" — cannot be answered safely from a rolling backtest window without a
real, independently-known exchange trading-day calendar: a naive
implementation (e.g. "is this the last row of its month in the DataFrame")
would silently answer that question using whether MORE ROWS FOR THAT MONTH
EXIST FURTHER DOWN THE ARRAY — i.e. it peeks at whether trading continued
later in the month, which is future information relative to any bar that
isn't literally the final bar of the whole dataset. That is exactly the
shape of bug ``kala/edge.py``/PROJECT_STATUS.md already retracted a
"validated" result over once (the look-ahead min-price filter). "First N
trading days of the month," by contrast, is answerable in real time purely
from a running count since the month started (``groupby().cumcount()``,
verified point-in-time safe below) — no future rows involved. Rather than
risk a subtle repeat of that bug to get the full classic window, this ships
the half that's provably safe and leaves the other half as a clearly-labeled
gap (see PROJECT_STATUS.md) for whoever wants to wire in a real IDX/NYSE
trading-day calendar later.

Price-only in the trivial sense of needing no price at all — it needs only
the DatetimeIndex every OHLCV frame already carries, so it is free and has
zero data-quality risk (unlike a Ramadan-effect variant of this same idea,
which was considered and deliberately NOT shipped alongside this: Indonesia's
Kemenag announces Ramadan's start by moon-sighting, not pure calculation, and
no reliable historical table of those exact dates could be verified from
this session's network access — see the conversation this was built in.
Don't hardcode a guessed Hijri calendar; get a verified official table or an
installed, caveated conversion library first).

THE HONEST ACID TEST
---------------------
This is the TENTH hypothesis/market-combination-generating idea run through
this harness (see PROJECT_STATUS.md — nine tried already, none survived).
Multiple-testing risk is now substantial: judge any positive result against
``kala.overfitting`` (PBO / deflated Sharpe) and the alpha-vs-benchmark
excess check, not a single good-looking t-stat. A real turn-of-month effect,
if it exists in this universe, should also show up as roughly MARKET-WIDE
(most/all names moving together near month boundaries) rather than
stock-specific — so also sanity-check whether the excess (alpha) check
approaches zero even if the raw check is positive; that would mean "the
whole market rallies at month-start," which is a real, tradeable
regularity but arguably shows up already in a static buy-and-hold allocation
and isn't really "stock-picking," similar in spirit to the beta-capture
caveat on prior results.

STATUS: TESTED 2026-07-24 on real data (IDX: 53 tickers/10y/tick-floored
costs; US: 57 sharia large-caps/10y vs SPUS) -- NO OOS EDGE on either
market. IDX: confidently NEGATIVE with real power (raw t=-2.79, alpha
t=-4.01, n=4195). US: raw t=10.54 (the single highest raw t-stat recorded
anywhere in this project -- the same beta-capture shape every US run
shows, and unsurprising here since a market-wide calendar effect is close
to "was invested during the window" by construction), but alpha lands at
t=0.78 (n=3707) -- noise-level, not a real effect. Confidently-negative on
one market, noise-flat on the other -- the SAME cross-market shape
`long_momentum` showed, and read the same way: evidence AGAINST a real
transferable effect, not for one. See PROJECT_STATUS.md, "Turn-of-month
calendar effect result", for the full numbers -- not restated here so they
can't go stale in two places. DO NOT TRADE THIS.
"""

from __future__ import annotations

import pandas as pd

from .strategies import Strategy, register_strategy

# Ariel's classic window's safe half: the first N trading days of a calendar
# month score highest. A round, pre-declared number (matches the "first
# three days" component of the textbook definition) chosen before any test
# was run, not fit to a result.
N_START_DAYS = 3
# No price lookback is needed at all -- the feature is derived purely from
# the DatetimeIndex, which every window already carries in full. A small
# nonzero warmup is kept anyway only so the harness has at least one full
# prior month of context before the first entry, not because the feature
# itself requires it.
WARMUP_BARS = 5


def compute_features_turn_of_month(df: pd.DataFrame) -> pd.DataFrame:
    """Add ``tom_rank_in_month``: a running count of trading days since the
    start of the current calendar month (0 on the first trading day of the
    month, 1 on the second, ...). ``groupby(...).cumcount()`` is a forward
    scan that, for the value at row t, depends only on how many PRIOR rows
    in row t's own month appeared before it -- never on how many rows exist
    later in the month or dataset. No look-ahead risk."""
    feats = df.copy()
    month = feats.index.to_period("M")
    feats["tom_rank_in_month"] = pd.Series(month, index=feats.index).groupby(month).cumcount()
    return feats


def score_turn_of_month(feats: pd.DataFrame) -> pd.Series:
    """0-100: 100 on the first ``N_START_DAYS`` trading days of any month, 0
    otherwise. Binary and calendar-only -- entirely determined by the row's
    own date, never by price. No NaN case: the rank is always defined."""
    rank = feats["tom_rank_in_month"]
    return (rank < N_START_DAYS).astype(float) * 100.0


TURN_OF_MONTH = register_strategy(Strategy(
    name="turn_of_month",
    compute_features=compute_features_turn_of_month,
    score=score_turn_of_month,
    default_threshold=50.0,
    default_thresholds_grid=(50.0,),   # binary score -- only one meaningful cut
    warmup_bars=WARMUP_BARS,
    description=("Turn-of-month effect: score the first few trading days of "
                 "each calendar month highest, agnostic to any price action -- "
                 "the FIRST calendar-based (not price/volume/flow/volatility) "
                 "hypothesis tried. Free, zero data-quality risk. TESTED "
                 "2026-07-24: confidently NEGATIVE on IDX (alpha t=-4.01), "
                 "noise-level on US (alpha t=0.78) — the same cross-market "
                 "sign-flip pattern long_momentum showed, evidence against a "
                 "real transferable effect. Do not trade this. See "
                 "PROJECT_STATUS.md."),
))
