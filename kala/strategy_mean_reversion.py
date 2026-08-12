"""
Mean-reversion strategy — a genuinely DIFFERENT hypothesis from the momentum
score, registered in the strategy zoo (kala.strategies) as
"mean_reversion".

WHY THIS ONE
------------
Momentum (buy strength, ride the trend) is the ONLY mechanism this project
has tested so far, across every variant tried (composite score, ML
walk-forward, entry-veto sweeps) — all of them failed the same walk-forward
+ alpha bar. Mean reversion (buy weakness, bet on a snap-back to the
average) is mechanically the OPPOSITE bet, not a parameter tweak on the
same idea, so it deserves its own honest test rather than being lumped in
with "momentum variants that didn't work."

STATUS: UNTESTED. This module only defines the signal; it has NOT been run
through walk_forward_strategy yet. Until it has, and clears |t| >= 2 on
BOTH raw and benchmark-excess OOS return on the unfiltered universe (the
same bar momentum didn't clear — see PROJECT_STATUS.md), treat this exactly
like every other unvalidated idea: interesting to test, not to trade.

MECHANISM
---------
Score is HIGH when a stock is trading well BELOW its recent average
(negative z-score of price vs. a rolling mean) AND its RSI reads oversold
— i.e. the opposite reading from momentum's score, which rewards being
ABOVE the average with a strong RSI. Entry/exit mechanics (stop-loss,
take-profit, trailing stop, costs, vetoes) are the SAME shared
infrastructure every strategy in the zoo uses — only the entry score
differs, which is exactly the point of the zoo design: isolate the ONE
variable actually being tested.
"""

from __future__ import annotations

import pandas as pd

from . import indicators as ind
from .strategies import Strategy, register_strategy

SMA_PERIOD = 20
RSI_PERIOD = 14
ZSCORE_PERIOD = 20
ATR_PERIOD = 14


def compute_features_mean_reversion(df: pd.DataFrame) -> pd.DataFrame:
    """Point-in-time features: rolling mean/std and RSI, all backward-only
    (same contract as scoring.compute_features — see its docstring)."""
    feats = df.copy()
    close = feats["Close"]

    feats["sma_mid"] = ind.sma(close, SMA_PERIOD)
    rolling_std = close.rolling(ZSCORE_PERIOD).std()
    # z-score of price vs its own rolling mean -- how many std devs away
    # from "normal" this stock is trading right now. std==0 (a dead/halted
    # name) -> NaN, not a divide-by-zero crash; NaN scores naturally veto
    # via the same "s == s rejects NaN" guard backtest.py already uses.
    feats["zscore"] = (close - feats["sma_mid"]) / rolling_std.replace(0, float("nan"))
    feats["rsi"] = ind.rsi(close, RSI_PERIOD)
    feats["atr"] = ind.atr(feats["High"], feats["Low"], close, ATR_PERIOD)

    return feats


def score_mean_reversion(feats: pd.DataFrame) -> pd.Series:
    """0-100: high score = price is FAR BELOW its recent mean AND RSI is
    oversold — the bet is a bounce back UP toward the mean, the mirror
    image of momentum's 'reward strength' scoring."""
    z = feats["zscore"]
    rsi = feats["rsi"]

    # Z-score component (0-60): z <= -2.5 (2.5 std below mean) -> full
    # score; z >= 0 (at/above the mean — no dip to revert from) -> zero.
    z_component = ((-z) / 2.5).clip(0.0, 1.0) * 60.0

    # RSI oversold component (0-40): RSI 20 -> full, RSI 50 (neutral) -> zero.
    rsi_component = ((50.0 - rsi) / 30.0).clip(0.0, 1.0) * 40.0

    return (z_component + rsi_component).clip(0.0, 100.0)


MEAN_REVERSION = register_strategy(Strategy(
    name="mean_reversion",
    compute_features=compute_features_mean_reversion,
    score=score_mean_reversion,
    default_threshold=60.0,
    default_thresholds_grid=(40.0, 50.0, 60.0, 70.0, 80.0),
    description=("Buys weakness (negative z-score + oversold RSI), betting on "
                 "reversion toward the mean -- opposite mechanism from momentum. "
                 "UNTESTED as of registration -- run walk_forward_strategy before "
                 "trusting anything about it."),
))
