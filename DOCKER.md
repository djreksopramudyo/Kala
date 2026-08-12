# Running Kala with Docker

An alternative to `DEPLOY_VPS.md`'s bare-systemd install — containerized,
for anyone who'd rather manage this as a Docker service than a systemd
unit. Covers the same two processes (the Telegram bot's long-poll loop,
and the once-daily scan/exit-management cycle).

## Scope: what's here vs. what's genuinely yours to fill in

This setup (`Dockerfile`, `docker-compose.yml`, `.dockerignore`,
`healthcheck.py`, `kala/heartbeat.py`) covers the parts that are the
same regardless of which server you run this on: the Python environment,
dependency install, a liveness heartbeat + `HEALTHCHECK` so a wedged
process gets restarted automatically, and a bind-mount pattern so trading
history survives a container recreate.

**Deliberately not covered**, because they depend on a real server this
project has no way to know about: a reverse proxy or TLS (this bot doesn't
serve HTTP, so you likely don't need one, but if you add a webhook-based
Telegram integration later you will), host firewall rules, a backup
destination for `paper_state.json` (local `cp`? an S3-compatible bucket?
that's a choice, not a default), resource limits sized to your actual VPS
tier, and any real alerting integration (Prometheus/Grafana, Uptime Robot,
a Slack/PagerDuty webhook on healthcheck failure) — `heartbeat_is_fresh()`
in `kala/heartbeat.py` is the one generic primitive any of those would
be built on top of; wiring an actual alert is a few lines once you've
picked a service.

## Quick start

```bash
cd /path/to/this/project

# secrets -- NOT committed (see .dockerignore)
cat > .env <<'EOF'
KALA_TELEGRAM_TOKEN=your-bot-token
KALA_TELEGRAM_CHAT_ID=your-chat-id
EOF

# bring your existing state along, or start clean
touch paper_state.json runner_config.json   # if starting clean, or copy in existing ones
mkdir -p results

docker compose up -d --build
docker compose logs -f bot   # watch it come online
```

## How persistence works

`telegram_bot.py` reads `paper_state.json`/`runner_config.json` from its
own working directory at fixed relative paths (`STATE_PATH`/`CONFIG_PATH`
in the source) — no code changes were needed for Docker. `docker-compose.yml`
bind-mounts your host copies of those exact files onto the same paths
inside the container, so `docker compose down && docker compose up` (or a
container recreate on redeploy) doesn't lose your trading history. The
heartbeat file (`heartbeat.txt`) is deliberately NOT persisted — it's
per-container liveness state, and a fresh container correctly starts with
no heartbeat until its first poll cycle completes.

## Healthcheck

The bot's poll loop touches `heartbeat.txt` once per cycle (~every 30s).
`healthcheck.py` fails (exit 1) if that file is missing or older than 5
minutes, which the Dockerfile wires into `HEALTHCHECK` — check status with:

```bash
docker inspect --format='{{json .State.Health}}' <container> | python3 -m json.tool
```

Combined with `restart: unless-stopped` in the compose file, a wedged
process (network stack deadlock, an unhandled exception outside the poll
loop's own try/except) gets restarted automatically instead of silently
going dark until someone happens to check Telegram.

## The daily cycle service

The `daily` service in `docker-compose.yml` is a minimal shell loop that
fires `daily_run.py` once at 17:00 WIB and then sleeps past that minute so
it doesn't double-fire. It's a placeholder, not a real scheduler — if you
already run other cron-based infrastructure, replace it with your
orchestrator's native scheduling (a Kubernetes CronJob, a proper cron
sidecar image, etc.) instead of this loop.
