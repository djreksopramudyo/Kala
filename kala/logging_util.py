"""
Shared logger — so data-path failures leave a trace instead of vanishing.

Silent ``except Exception: pass`` on a fetch/parse path is how bugs hide:
the /checkstop NaN misfire, a delisted ticker, a transient yfinance 403 —
all of them used to disappear with no record, leaving you to reverse-engineer
"why is this number wrong?" from nothing. ``log_swallowed()`` keeps the
best-effort behavior (a failed quote must not crash the run) while writing
ONE line to results/kala.log so the failure is diagnosable after the
fact.

Logging must never itself break a run, so every setup step is defensive.
"""

from __future__ import annotations

import logging
from pathlib import Path

_LOG_PATH = Path(__file__).resolve().parent.parent / "results" / "kala.log"


def get_logger(name: str = "kala") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:                      # configure once per process
        return logger
    logger.setLevel(logging.INFO)
    try:
        _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(_LOG_PATH, encoding="utf-8")
        fh.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logger.addHandler(fh)
    except Exception:
        pass                                 # never let logging setup crash a run
    logger.propagate = False
    return logger


def log_swallowed(context: str, exc: BaseException) -> None:
    """Record a best-effort error that is being intentionally swallowed.
    Keeps the run alive; leaves a diagnosable trace."""
    try:
        get_logger().warning("swallowed error in %s: %s: %s",
                             context, type(exc).__name__, exc)
    except Exception:
        pass
