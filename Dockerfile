# Generic container image for the Kala Telegram bot.
#
# What's generic here: the Python environment, dependency install, and a
# heartbeat-based HEALTHCHECK. What's NOT here, on purpose (see DOCKER.md):
# a reverse proxy / TLS termination, a specific host firewall, backup
# destinations, or any secrets — those depend on the actual server this
# runs on, which only you know.

FROM python:3.11-slim

WORKDIR /app

# build-essential/libxml2-dev/libxslt-dev: safety net for lxml if a
# prebuilt wheel isn't available for the target architecture; harmless
# otherwise (see DEPLOY_VPS.md's non-Docker install notes, same reasoning).
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libxml2-dev libxslt-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# paper_state.json / runner_config.json / results/ are read from THIS
# working directory at their existing hardcoded relative paths (see
# telegram_bot.py's STATE_PATH/CONFIG_PATH) -- docker-compose.yml bind-
# mounts them individually onto those exact paths so trading history and
# config survive a container recreate, with no code changes needed.
# heartbeat.txt is deliberately NOT persisted -- it's per-container
# liveness state, and a fresh container correctly starts with no
# heartbeat until its first poll cycle.

HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD python healthcheck.py || exit 1

CMD ["python", "telegram_bot.py"]
