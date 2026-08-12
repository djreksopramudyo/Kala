"""
Docker HEALTHCHECK entry point — exits 0 if the bot's heartbeat is fresh,
1 otherwise (a stale/missing heartbeat fails the container healthcheck,
which triggers a restart under the Dockerfile's HEALTHCHECK directive or
docker-compose's ``restart: unless-stopped`` + healthcheck combo).

Usage:
    python healthcheck.py
    python healthcheck.py --path /app/heartbeat.txt --max-age 300
"""

from __future__ import annotations

import argparse
import sys

from kala.heartbeat import DEFAULT_MAX_AGE_SECONDS, DEFAULT_PATH, heartbeat_is_fresh


def main() -> int:
    ap = argparse.ArgumentParser(description="Check the bot's liveness heartbeat")
    ap.add_argument("--path", default=DEFAULT_PATH)
    ap.add_argument("--max-age", type=float, default=DEFAULT_MAX_AGE_SECONDS)
    args = ap.parse_args()

    if heartbeat_is_fresh(args.path, max_age_seconds=args.max_age):
        return 0
    print(f"heartbeat stale or missing at {args.path}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
