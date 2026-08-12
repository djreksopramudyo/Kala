"""
Broker-concentration strategy — a refinement of foreign_flow, registered in
the strategy zoo (kala.strategies) as "broker_concentration".

WHY THIS ONE
------------
foreign_flow (kala/strategy_foreign_flow.py) asks "is foreign money net-
buying this stock unusually strongly." This asks a second, genuinely
different question of the SAME already-fetched data: "is that buying
concentrated in one broker, or spread across many?" A day where one broker
accounts for most of the foreign net flow reads differently from a day
where many small brokers each contribute a little — the former looks more
like a single informed/institutional decision, the latter more like
diffuse, less-informed flow. Costs ZERO extra API calls: the per-broker
breakdown this needs is already inside the same investor=f response
fetch_daily_foreign_net sums into foreign_net_value; kala.invezgo_fetch's
fetch loop computes foreign_top_broker_share from it and the archive
stores it alongside foreign_net_value.

STATUS: UNTESTED — but no longer BLOCKED ON DATA. The 2-year Invezgo archive
exists and merges cleanly (results/broker_flow.db, 16,304 rows / 68 tickers),
so this can be run whenever you want; it simply has not been. Note before you
do: foreign_flow, which supplies half this score, WAS run on that archive
(2026-08-10) and came back with no raw edge and an excess result that failed
every robustness check — see PROJECT_STATUS.md "Foreign-flow OOS result". The
conviction refinement here is applied on top of a component now measured as
weak, so temper expectations accordingly. Until it clears |t| >= 2 on BOTH raw
and benchmark-excess OOS return on the unfiltered universe, treat it exactly
like every other unvalidated idea.

MECHANISM
---------
Score is HIGH when BOTH conditions hold: foreign flow is net POSITIVE
(buying, not selling — concentrated selling shouldn't score high for a BUY
signal) AND that flow is concentrated in relatively few brokers. Built as a
50/50 blend of foreign_flow's own z-score component and the raw
concentration share (already 0-1) — a day that's both strongly-buying-for-
this-stock AND concentrated scores near 100; a day that's buying but
diffuse, or concentrated but net-selling/flat, scores in the middle or low.

DATA CONTRACT
-------------
Expects BOTH ``foreign_net_value`` and ``foreign_top_broker_share`` merged
onto the OHLCV frame — call ``attach_foreign_flow`` twice (once per
column; it's generic over which archive column it merges) before
backtesting. Either column absent/all-NaN degrades the score to NaN,
which the backtest reads as "never enters" — same safe degrade-to-no-
trade contract as foreign_flow, not a crash or a silently wrong signal.
"""

from __future__ import annotations

import pandas as pd

from .strategies import Strategy, register_strategy
from .strategy_foreign_flow import compute_features_foreign_flow

SHARE_COLUMN = "foreign_top_broker_share"


def compute_features_broker_concentration(df: pd.DataFrame) -> pd.DataFrame:
    """Reuses foreign_flow's z-score features (flow_z) and adds the raw
    concentration share alongside. Point-in-time: the share itself is
    already a same-day figure (no look-ahead — it's derived from that
    day's own broker breakdown, same as foreign_net_value), and flow_z's
    windows are backward-only as documented in strategy_foreign_flow.py."""
    feats = compute_features_foreign_flow(df)
    feats["top_broker_share"] = df[SHARE_COLUMN] if SHARE_COLUMN in df.columns else float("nan")
    return feats


def score_broker_concentration(feats: pd.DataFrame) -> pd.Series:
    """0-100: 50/50 blend of foreign_flow's z-score component and raw
    concentration share. Both must be present and both must point the
    same direction (strong relative buying, concentrated in few brokers)
    to score near 100 -- either one being weak/absent caps the score."""
    z = feats["flow_z"]
    share = feats["top_broker_share"]

    flow_component = (z / 2.5).clip(0.0, 1.0) * 100.0
    share_component = share.clip(0.0, 1.0) * 100.0

    return (0.5 * flow_component + 0.5 * share_component)


BROKER_CONCENTRATION = register_strategy(Strategy(
    name="broker_concentration",
    compute_features=compute_features_broker_concentration,
    score=score_broker_concentration,
    default_threshold=60.0,
    default_thresholds_grid=(40.0, 50.0, 60.0, 70.0, 80.0),
    description=("Buys days that are BOTH unusually strong foreign net "
                 "buying (vs this stock's own norm) AND concentrated in "
                 "relatively few brokers (vs diffuse) -- refines foreign_flow "
                 "with a conviction signal, zero extra API cost (same "
                 "already-fetched per-broker data). UNTESTED -- the archive "
                 "now exists, so this is runnable, but note foreign_flow "
                 "(half of this score) tested NOT VALIDATED on it 2026-08-10."),
))
