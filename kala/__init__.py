"""kala — a small, tested quant toolkit for IDX swing trading.

Public API is intentionally flat::

    from kala.config import Config, RiskConfig, BacktestConfig, CostModel, EntryConfig
    from kala.indicators import rsi, atr, adx, obv, macd, cross_below
    from kala.scoring import compute_features, composite_score
    from kala.entries import evaluate_entry
    from kala.exits import evaluate_exit, governing_stop, Urgency
    from kala.positions import Position, PositionStore
    from kala.watchlist import WatchlistItem, WatchlistStore
    from kala.backtest import backtest_ticker
"""

from . import (  # noqa: F401
    backtest,
    backtest_live_exits,
    config,
    entries,
    exits,
    indicators,
    ml_scoring,
    news,
    notify,
    papertrade,
    positions,
    regime,
    scoring,
    watchlist,
)

__all__ = ["backtest", "backtest_live_exits", "config", "entries", "exits", "indicators",
           "positions", "scoring", "watchlist", "papertrade", "notify", "regime",
           "ml_scoring", "news"]
__version__ = "0.2.0"
