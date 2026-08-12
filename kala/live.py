"""
Bridge between the tested engine and the legacy script API.

``evaluate_position`` runs the real ``kala.exits`` engine over a price
history and returns the exact dict shape the old ``check_exit_signals`` produced,
so ``check_my_stocks.py`` / ``monitor_portfolio`` keep working unchanged — but
now backed by logic that (a) never downgrades urgency, (b) treats the death
cross as an event, and (c) uses a scale-invariant MACD threshold.

The legacy ``urgency`` strings are preserved: URGENT / CONSIDER / NORMAL.
"""

from __future__ import annotations

import math

import pandas as pd

from .config import RiskConfig
from .exits import Urgency, evaluate_exit, governing_stop
from .scoring import composite_score, compute_features

_URGENCY_TO_STR = {
    Urgency.URGENT: "URGENT",
    Urgency.CONSIDER: "CONSIDER",
    Urgency.ADVISORY: "NORMAL",
    Urgency.NONE: "NORMAL",
}


def _trailing_view(entry_price, peak_price, entry_atr, cfg):
    """Return the legacy trailing_* sub-dict from the governing stop."""
    stop, phase, label = governing_stop(entry_price, peak_price, entry_atr, cfg)
    locked_pct = (stop - entry_price) / entry_price * 100.0
    peak_profit_pct = (peak_price - entry_price) / entry_price * 100.0
    return {
        "trailing_stop_price": stop,
        "trailing_stop_pct": locked_pct,
        "phase": phase,
        "phase_name": label,
        "profit_locked_pct": locked_pct,
        "peak_price": peak_price,
        "peak_profit_pct": peak_profit_pct,
    }


def evaluate_position(
    ticker: str,
    entry_price: float,
    history: pd.DataFrame,
    peak_price: float | None = None,
    market_status: str | None = None,
    technical_data: dict | None = None,
    cfg: RiskConfig | None = None,
) -> dict:
    """Evaluate one open position. ``history`` is an OHLCV frame (capitalised
    columns, oldest-first) such as yfinance returns.

    Returns the legacy ``check_exit_signals`` dict contract.
    """
    cfg = cfg or RiskConfig()

    feats = compute_features(history)
    current_price = float(feats["Close"].iloc[-1])
    if peak_price is None:
        peak_price = current_price
    peak_price = max(peak_price, current_price)

    entry_atr = feats["atr"].iloc[-1]
    if isinstance(entry_atr, float) and math.isnan(entry_atr):
        entry_atr = None

    score = composite_score(feats).iloc[-1]
    score = None if (score != score) else float(score)  # NaN -> None

    decision = evaluate_exit(
        ticker=ticker,
        entry_price=entry_price,
        features=feats,
        peak_price=peak_price,
        entry_atr=entry_atr,
        market_status=market_status,
        score=score,
        cfg=cfg,
    )

    trailing = _trailing_view(entry_price, peak_price, entry_atr, cfg)
    profit_pct = (current_price - entry_price) / entry_price * 100.0

    return {
        "ticker": ticker,
        "entry_price": entry_price,
        "current_price": current_price,
        "profit_pct": profit_pct,
        "profit_idr": current_price - entry_price,
        "exit_signal": decision.exit_signal,
        "urgency": _URGENCY_TO_STR[decision.urgency],
        "reasons": decision.reasons,
        "technical_data": technical_data or {},
        "score": score,
        **{k: trailing[k] for k in (
            "trailing_stop_price", "trailing_stop_pct", "profit_locked_pct",
            "peak_price", "peak_profit_pct",
        )},
        "trailing_phase": trailing["phase"],
        "trailing_phase_name": trailing["phase_name"],
    }
