"""
Liveness heartbeat — the generic half of "Docker + monitoring."

WHY THIS EXISTS
---------------
The Telegram bot is a long-poll loop with no HTTP server, so there's
nothing for a container orchestrator to ping. The generic, VPS-agnostic
answer is a heartbeat FILE: the bot's poll loop touches it every cycle,
and a healthcheck (``healthcheck.py`` at the repo root, wired into the
Dockerfile's ``HEALTHCHECK`` directive) just checks the file's mtime is
recent. If the process wedges (deadlocks, an unhandled exception outside
the loop's own try/except, whatever), the heartbeat goes stale and Docker
restarts the container.

What's deliberately NOT here: any specific alerting integration
(Prometheus, Grafana, Uptime Robot, a Slack webhook) — those need
credentials and choices only the person running this server can make.
This module gives you the one generic primitive (a freshness check) that
any of those can be built on top of.
"""

from __future__ import annotations

import time
from pathlib import Path

DEFAULT_PATH = "heartbeat.txt"
DEFAULT_MAX_AGE_SECONDS = 300   # 5x the bot's 30s poll interval, some slack for a slow API call


def write_heartbeat(path: str | Path = DEFAULT_PATH, now: float | None = None) -> None:
    """Overwrite the heartbeat file with the current (or injected, for
    tests) unix timestamp. Cheap and atomic enough for this purpose —
    a torn write just means one healthcheck cycle reads a stale-looking
    value, not silent corruption of anything that matters."""
    Path(path).write_text(str(now if now is not None else time.time()), encoding="utf-8")


def heartbeat_age_seconds(path: str | Path = DEFAULT_PATH, now: float | None = None) -> float | None:
    """Seconds since the heartbeat was last written, or None if the file
    doesn't exist yet (e.g. the process hasn't completed its first poll
    cycle) or its contents aren't a valid timestamp."""
    p = Path(path)
    if not p.exists():
        return None
    try:
        written = float(p.read_text(encoding="utf-8").strip())
    except ValueError:
        return None
    return (now if now is not None else time.time()) - written


def heartbeat_is_fresh(path: str | Path = DEFAULT_PATH,
                       max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS,
                       now: float | None = None) -> bool:
    """False if the file is missing, unreadable, or older than
    ``max_age_seconds`` -- the single boolean a healthcheck needs."""
    age = heartbeat_age_seconds(path, now=now)
    return age is not None and 0 <= age <= max_age_seconds
