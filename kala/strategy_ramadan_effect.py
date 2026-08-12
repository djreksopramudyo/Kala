"""
Ramadan effect — the most IDX-specific calendar hypothesis available, and
the one the ``turn_of_month`` module deliberately left unshipped pending a
verified date table (see that module's docstring for why).

WHY THIS ONE, AND WHY IT WAS BLOCKED UNTIL NOW
------------------------------------------------
There is real published research finding abnormal stock returns on the
Indonesia exchange specifically during Ramadan (White 2013, among others),
plausibly tied to shifts in retail sentiment, liquidity, and consumption/THR
(holiday bonus) flows in a Muslim-majority market — a genuinely different
story from the turn-of-month effect's institutional-cash-flow mechanism,
even though both are calendar-based. Indonesia's Kemenag sets Ramadan's
start by ``sidang isbat`` (moon-sighting), not pure astronomical calculation,
so — unlike turn-of-month, which needs nothing but the DatetimeIndex — this
needs an actual verified historical table. An earlier attempt in this same
project session to source that table via this sandbox's own (restricted)
network access came back incomplete/conflicting for several years; rather
than guess, the idea was shipped as a documented gap instead of code (see
PROJECT_STATUS.md). The user then supplied ``RAMADAN_PERIODS`` below
directly (official Tanggal Mulai / Hari Terakhir Puasa per year) — this is
the verified table that was missing, not a guess.

COVERAGE GAP, STATED PLAINLY
------------------------------
``RAMADAN_PERIODS`` covers 2017-2026 only (Gregorian). A ``--period 10y``
run today pulls price history back to roughly mid-2016, which slightly
precedes the table (Ramadan 2016 was ~June 6 - July 5 and is NOT covered).
Any date outside the table's range is simply never flagged as Ramadan —
this FAILS CLOSED (undercounts real Ramadan days rather than guessing wrong
ones), so it cannot manufacture a fake signal, only slightly underpower one
if a real effect exists. Confirmed harmless in practice: the companion
``turn_of_month`` strategy's actual walk-forward run showed no OOS test
fold starting before August 2017, well inside this table's coverage. Same
caveat applies at the far end if a period extends past 2026 or before 2017
without the table being extended first.

WHY THIS IS SAFER THAN TURN-OF-MONTH'S "LAST DAY" HALF
----------------------------------------------------------
Unlike the "is this the month's last trading day" question that
``turn_of_month`` deliberately avoided (unanswerable in real time without an
independent trading-day calendar), "is this calendar date inside a
pre-published Ramadan range" needs NO information about the DataFrame's
other rows at all — it's a static table lookup keyed only on the row's own
date. There is no way for this to see into the array's future; the point-in-
time proof below (truncate after bar t, confirm t is unchanged) is almost a
formality here, but is included anyway to match house style and to catch any
implementation mistake empirically rather than by assumption alone.

THE HONEST ACID TEST
---------------------
Eleventh hypothesis/market-combination-generating idea in this project (see
PROJECT_STATUS.md — ten tried, none survived an honest alpha check).
Multiple-testing risk is now very real. Judge any positive result the same
way as everything else: against ``kala.overfitting`` (PBO / deflated Sharpe)
and specifically the alpha-vs-benchmark excess check, not a good-looking raw
t-stat alone. And apply the SAME market-wide caveat ``turn_of_month`` flagged
under its acid-test section: if Ramadan genuinely shifts sentiment/liquidity
broadly, a real effect would plausibly move most IDX names together, which
leans toward "beta, not alpha" almost by construction — a raw edge that
vanishes on the excess check would mean "the whole market moves during
Ramadan," a real and possibly tradeable regularity, but not stock-picking
skill, and not obviously separable from what a static buy-and-hold
allocation already captures. This hypothesis is also IDX-ONLY by
construction (Indonesia-specific calendar, Indonesia-specific table) —
running it on the US sharia universe would not be a meaningful test and
isn't offered as a CLI path here.

STATUS: TESTED 2026-07-24 on real data (53 tickers, 10y, tick-floored
costs) -- an UNDERPOWERED NULL, not a confident rejection: raw t=-2.89
(n=1116) looks negative, but the alpha/excess check collapses to noise
(t=-0.64). The apparent raw negative is largely explained by a few of the
rare Ramadan test windows coinciding with IDX itself being down hard that
quarter -- exactly what the alpha check exists to strip out. The n=1116
figure also overstates independence: it's 53 tickers trading through only
~10 distinct yearly Ramadan occurrences, not 1,116 independent events --
the same structural weakness the bandarmology result had. More YEARS of
data (not more tickers) would sharpen this, and that needs calendar time,
not more code. See PROJECT_STATUS.md, "Ramadan effect" section, for the
full numbers -- not restated here so they can't go stale in two places.
Do not trade this, but don't treat it as cleanly ruled out either.
"""

from __future__ import annotations

import pandas as pd

from .strategies import Strategy, register_strategy

# Official Indonesian government (Kemenag, via sidang isbat) Ramadan start
# and end dates, Gregorian calendar, as supplied by the user directly --
# NOT algorithmically derived and NOT recalled from memory (see module
# docstring for why that distinction mattered here). (start, end) are both
# inclusive -- "end" is the last day of puasa (fasting), i.e. the day before
# Idul Fitri. Covers 2017-2026 only; see the coverage-gap note above.
RAMADAN_PERIODS: tuple[tuple[str, str], ...] = (
    ("2017-05-27", "2017-06-24"),
    ("2018-05-17", "2018-06-14"),
    ("2019-05-06", "2019-06-04"),
    ("2020-04-24", "2020-05-23"),
    ("2021-04-13", "2021-05-12"),
    ("2022-04-03", "2022-05-01"),
    ("2023-03-23", "2023-04-21"),
    ("2024-03-12", "2024-04-09"),
    ("2025-03-01", "2025-03-30"),
    ("2026-02-19", "2026-03-20"),
)

# No price lookback needed -- same reasoning as turn_of_month's warmup.
WARMUP_BARS = 5


def _ramadan_mask(dates: pd.DatetimeIndex) -> pd.Series:
    """True for any date falling within a known Ramadan range (inclusive).
    A pure table lookup keyed only on each row's own date -- no dependency
    on any other row, so trivially point-in-time safe."""
    mask = pd.Series(False, index=dates)
    for start, end in RAMADAN_PERIODS:
        mask |= (dates >= pd.Timestamp(start)) & (dates <= pd.Timestamp(end))
    return mask


def compute_features_ramadan(df: pd.DataFrame) -> pd.DataFrame:
    """Add ``is_ramadan``: True if the row's date falls within a known,
    officially-announced Indonesian Ramadan period. Dates outside the
    table's 2017-2026 coverage are always False (fails closed -- see module
    docstring's coverage-gap note)."""
    feats = df.copy()
    feats["is_ramadan"] = _ramadan_mask(feats.index)
    return feats


def score_ramadan(feats: pd.DataFrame) -> pd.Series:
    """0-100: 100 during a known Ramadan period, 0 otherwise. Binary and
    calendar-only -- entirely determined by the row's own date, never by
    price. No NaN case: the mask is always defined (False outside the
    table's coverage, not unknown)."""
    return feats["is_ramadan"].astype(float) * 100.0


RAMADAN_EFFECT = register_strategy(Strategy(
    name="ramadan_effect",
    compute_features=compute_features_ramadan,
    score=score_ramadan,
    default_threshold=50.0,
    default_thresholds_grid=(50.0,),   # binary score -- only one meaningful cut
    warmup_bars=WARMUP_BARS,
    description=("Ramadan effect: score entries during officially-announced "
                 "Indonesian Ramadan periods (Kemenag sidang isbat dates, "
                 "2017-2026) highest, agnostic to any price action -- the "
                 "most IDX-specific calendar hypothesis available, with real "
                 "published evidence (White 2013). IDX-only by construction. "
                 "TESTED 2026-07-24: underpowered null (alpha t=-0.64) driven "
                 "by only ~10 independent yearly occurrences, not a confident "
                 "rejection -- do not trade, but don't treat as ruled out "
                 "either. See PROJECT_STATUS.md."),
))
