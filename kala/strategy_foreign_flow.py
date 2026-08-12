"""
Foreign-flow strategy — "follow the smart money," a mechanically DIFFERENT
hypothesis from both momentum and mean-reversion, registered in the strategy
zoo (kala.strategies) as "foreign_flow".

WHY THIS ONE
------------
Momentum and mean-reversion both score off PRICE/VOLUME alone — two opposite
bets on the same kind of data, both failed the walk-forward + alpha bar (see
PROJECT_STATUS.md). Foreign net flow is a different KIND of input entirely:
order flow — who is actually net-buying the stock (foreign institutional
money, via kala.invezgo_fetch's broker data) — rather than what the price
chart did. That independence is the whole point of testing it.

STATUS: TESTED 2026-08-10, NOT VALIDATED. It has now been run through
walk_forward_strategy on the real 2-year Invezgo archive (29 tickers, n=125
OOS trades — the first adequately-powered pass; the 2026-07 attempts had
n=23-25 and correctly printed INCONCLUSIVE). It did NOT clear the bar:

  * RAW return: no edge at all — EV -0.05%/trade, PF 0.99, t=-0.04.
  * EXCESS vs IHSG: nominally +1.45%/trade, but the clustered t is 0.52, the
    deflated Sharpe is 0.274 (5 thresholds tried), the median excess is
    NEGATIVE, and the win rate is 47% — so the positive mean rests on a few
    large winners.
  * The selected threshold swung 50 -> 80 between consecutive folds, and the
    FIXED baseline beat the walk-forward selection. Both are overfitting
    signatures.
  * Both OOS folds sat inside a -9.4% / -20.8% IHSG drawdown, so this says
    nothing about rising markets.

The bar is unchanged (|t| >= 2 on BOTH raw and benchmark-excess OOS return,
confirmed more than one way — the same bar momentum and mean-reversion did NOT
clear). Treat this as what it is: measured, and negative-to-inconclusive. Not
to trade. The raw-negative/excess-positive split is the shape of a DEFENSIVE
characteristic, which is a different hypothesis and untested — 468 trading days
that are entirely downtrend cannot separate it from chance. See
PROJECT_STATUS.md "Foreign-flow OOS result" for the full numbers.

MECHANISM
---------
Score is HIGH when foreign money has been NET BUYING this stock, unusually
strongly RELATIVE TO THE STOCK'S OWN RECENT NORM. The self-normalization (a
rolling z-score of cumulative flow, not the raw IDR figure) matters: BBCA's
daily foreign flow dwarfs a small-cap's in absolute rupiah, so a raw
threshold would just rank by market cap. The z-score asks "is foreign buying
strong FOR THIS STOCK right now," which is comparable across the universe.

DATA CONTRACT
-------------
compute_features expects a ``foreign_net_value`` column already merged onto
the OHLCV frame (use ``attach_foreign_flow`` below before backtesting). When
that column is ABSENT or all-NaN — a ticker with no broker-flow coverage —
the score is NaN everywhere, which the backtest treats as "never enters"
(the same ``s == s`` NaN guard every strategy relies on). So an
un-backfilled universe degrades to "no trades," never to a crash or a
silently-wrong signal.
"""

from __future__ import annotations

import pandas as pd

from .logging_util import log_swallowed
from .strategies import Strategy, register_strategy

CUM_WINDOW = 5       # trading days of flow to accumulate (smooths daily noise)
ZSCORE_WINDOW = 20   # window the cumulative flow is normalized against
FLOW_COLUMN = "foreign_net_value"

# Fraction of CUM_WINDOW that must be REAL observations before a cumulative
# flow figure is published at all. Missing days are summed as 0, so without a
# floor a single observed day could carry a 5-day total — see the rationale in
# compute_features_foreign_flow. 0.6 (3 of 5) keeps ordinary single-day gaps
# usable while refusing to score a window that is mostly fabricated.
MIN_WINDOW_COVERAGE = 0.6
MIN_WINDOW_OBS = max(1, round(CUM_WINDOW * MIN_WINDOW_COVERAGE))


def attach_foreign_flow(dfs: dict[str, pd.DataFrame], archive, source: str = "invezgo",
                        column: str = FLOW_COLUMN) -> dict[str, pd.DataFrame]:
    """Left-join each ticker's stored ``column`` from a ``BrokerFlowArchive``
    onto its OHLCV frame, aligned by date. Returns NEW frames (inputs
    untouched). A ticker with no rows in the archive comes back unchanged
    (no flow column) — the strategy then scores it NaN and never trades it,
    so a partially-backfilled archive is safe to run as-is.

    ``archive`` is any object with ``read(ticker, source=...) -> DataFrame |
    None`` exposing ``column`` (i.e. kala.broker_flow_archive.BrokerFlowArchive)."""
    out: dict[str, pd.DataFrame] = {}
    for ticker, df in dfs.items():
        stored = None
        try:
            stored = archive.read(ticker, source=source)
        except Exception as e:
            # A schema mismatch or corrupt file used to vanish here and read as
            # "this ticker has no flow rows" — a BROKEN archive was
            # indistinguishable from an empty one. Still non-fatal (a partial
            # archive must stay runnable), but no longer silent.
            log_swallowed(f"attach_foreign_flow({ticker}, source={source})", e)
            stored = None
        merged = df.copy()
        if stored is not None and column in stored.columns and len(stored):
            # reindex the archive series onto the OHLCV index (dates the
            # backtest actually trades); days with no broker row stay NaN.
            flow = stored[column]
            flow = flow[~flow.index.duplicated(keep="last")]
            merged[column] = flow.reindex(merged.index)
        out[ticker] = merged
    return out


def compute_features_foreign_flow(df: pd.DataFrame) -> pd.DataFrame:
    """Point-in-time features off the merged ``foreign_net_value`` column.
    All windows are backward-only (rolling), so the value at bar t uses only
    flow up to and including t — the same non-negotiable contract as
    scoring.compute_features. If the column is missing, the features are
    created as NaN so ``score`` degrades to 'no signal' rather than raising."""
    feats = df.copy()

    if FLOW_COLUMN not in feats.columns:
        feats["flow_cum"] = float("nan")
        feats["flow_z"] = float("nan")
        return feats

    # A day with no broker row is UNKNOWN flow, not known-zero. This used to
    # read `raw.fillna(0.0).rolling(CUM_WINDOW).sum()`, published whenever the
    # window held >= 1 real observation — so four fabricated zeros and one real
    # day produced a "5-day cumulative flow" indistinguishable from five
    # measured days.
    #
    # The damage was not just dilution, it was SCALE. A summed window shrinks in
    # proportion to how much of it is missing, and flow_z then compares that
    # against a 20-day norm built mostly from fully-covered windows — so a
    # coverage artefact is read as a change in flow. Scattered fetch failures
    # (a 5xx or timeout on one day is skipped by
    # invezgo_fetch.fetch_daily_foreign_net) produce exactly that shape, and
    # they are invisible downstream: covered_range only checks the first and
    # last stored date, so a hole-riddled archive reports as fully covered and
    # is never re-fetched. On a 40%-holey quarter this understated cumulative
    # flow ~60% and flipped flow_z from +1.54 to -1.01 — sustained net BUYING
    # read as net SELLING.
    #
    # Take the mean over the days actually OBSERVED and scale it to the window
    # instead. That is an unbiased estimate of the window's total whatever the
    # coverage, so it is comparable across windows; and min_periods counts only
    # non-NaN days, so a window too thin to estimate from stays NaN — which the
    # backtest already reads as do-not-enter, the same fail-closed choice as
    # the benchmark-regime gate.
    raw = feats[FLOW_COLUMN]
    obs_mean = raw.rolling(CUM_WINDOW, min_periods=MIN_WINDOW_OBS).mean()
    flow_cum = obs_mean * CUM_WINDOW

    roll_mean = flow_cum.rolling(ZSCORE_WINDOW, min_periods=CUM_WINDOW).mean()
    roll_std = flow_cum.rolling(ZSCORE_WINDOW, min_periods=CUM_WINDOW).std()
    feats["flow_cum"] = flow_cum
    # z-score vs the stock's OWN recent flow. std==0 (perfectly flat) -> NaN,
    # not a divide-by-zero, and NaN scores naturally veto entry.
    feats["flow_z"] = (flow_cum - roll_mean) / roll_std.replace(0, float("nan"))
    return feats


def score_foreign_flow(feats: pd.DataFrame) -> pd.Series:
    """0-100: high = foreign money is net-buying this stock unusually strongly
    for its own recent norm. z >= +2.5 (2.5 std above the stock's typical
    flow) -> 100; z <= 0 (average or net-selling) -> 0. NaN where flow data
    is missing, which the backtest reads as 'do not enter'."""
    z = feats["flow_z"]
    return (z / 2.5).clip(0.0, 1.0) * 100.0


FOREIGN_FLOW = register_strategy(Strategy(
    name="foreign_flow",
    compute_features=compute_features_foreign_flow,
    score=score_foreign_flow,
    default_threshold=60.0,
    default_thresholds_grid=(40.0, 50.0, 60.0, 70.0, 80.0),
    description=("Buys sustained, unusually-strong net FOREIGN buying "
                 "(self-normalized z-score of cumulative broker flow) -- an "
                 "order-flow signal independent of price/volume. TESTED "
                 "2026-08-10 on the 2y Invezgo archive, 29 tickers, n=125 OOS "
                 "trades: NO raw edge (EV -0.05%/trade, PF 0.99, t=-0.04). "
                 "Excess-vs-IHSG is nominally +1.45% but fails every "
                 "robustness check (clustered t=0.52, deflated Sharpe=0.274, "
                 "NEGATIVE median, 47% win) and both OOS folds sat in a "
                 "-9.4%/-20.8% drawdown, so nothing is known about rising "
                 "markets. NOT VALIDATED -- do not size on it. See "
                 "PROJECT_STATUS.md 'Foreign-flow OOS result'."),
))
