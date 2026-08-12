# Running Kala on a VPS (no laptop required)

Moves both the Telegram bot and the 17:00 WIB daily cycle off your laptop
onto a small always-on Linux server, so you can use the bot from your phone
whenever, without your PC being on. No code changes are needed for this —
the project has no Windows-specific code (checked: no `subprocess`/`os.system`
calls, and its own "current time" concept is computed as UTC+7 directly, not
read from the OS clock), so it runs identically on Linux.

**Before anything else: rotate your Telegram bot token.** If you're moving
to a server that's reachable and running 24/7, an old/leaked token is a
bigger liability than it was on a laptop that's only sometimes on. In
Telegram, message @BotFather → `/revoke` → get a NEW token. On this server
the token does **not** go in `runner_config.json` — it goes in a root-owned
secrets file that systemd injects as an environment variable (step 6a
below), so it never sits in a file that gets zipped, copied, or shared. The
code reads `KALA_TELEGRAM_TOKEN` / `KALA_TELEGRAM_CHAT_ID` from the
environment first and falls back to the config file only if they're unset.
Do this rotation even if you think you already did it once.

## 0. Pick a provider and create the smallest Ubuntu box

Any of these work — pick whichever you already have an account with:

- DigitalOcean / Linode / Vultr: cheapest paid droplet (~$4-6/mo), Ubuntu 22.04 or 24.04 LTS.
- Oracle Cloud "Always Free" ARM tier: free forever if available in your
  region at signup (availability varies; if it's out of capacity, try again
  later or fall back to a paid option).

You just need: Ubuntu, 1 vCPU, 512MB-1GB RAM (this project is not compute
heavy — it's I/O bound on network calls), a public IP, and SSH access.

## 1. SSH in and create a dedicated user

Don't run this as root day-to-day.

```bash
ssh root@YOUR_SERVER_IP
adduser --disabled-password --gecos "" kala
mkdir -p /opt/kala
chown kala:kala /opt/kala
```

## 2. Install Python and system packages

```bash
apt update
apt install -y python3 python3-venv python3-pip git build-essential libxml2-dev libxslt-dev python3-dev
```

(`libxml2-dev`/`libxslt-dev`/`build-essential` are a safety net for `lxml` —
usually unnecessary on x86_64 since prebuilt wheels exist, but harmless to
have if pip needs to compile it.)

## 3. Set the server's timezone to WIB

```bash
timedatectl set-timezone Asia/Jakarta
```

The app's own "now" is always computed as UTC+7 regardless of this setting
(see `kala_daily_trader.py`'s `get_indonesian_time()`), so this step
only matters for the systemd **timer** in step 6, which fires on the
server's local wall clock. If you'd rather leave the server on UTC, that's
fine too — just change the timer's `17:00:00` to `10:00:00`.

## 4. Copy the project over

From your laptop (adjust the local path to wherever your project folder is):

```bash
scp -r "D:\Side Projects\Kala" kala@YOUR_SERVER_IP:/opt/kala
```

(On Windows, run that from PowerShell with OpenSSH installed, or use
WinSCP/FileZilla if you prefer a GUI.) This brings your **existing**
`paper_state.json` and `runner_config.json` along — your trading history and
config aren't lost, they just move.

If you'd rather start this VPS with a clean track record instead of
carrying over history, skip copying `paper_state.json` and let
`PaperTrader.load()` create a fresh one from `start_capital_idr` on first
run (see `HOW_IT_WORKS.md`'s "set my equity" section) — or run
`reset_paper.py --capital <amount> --sync-config` once you're on the server.

## 5. Create the venv and install dependencies

```bash
su - kala
cd /opt/kala
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
exit   # back to root
```

Sanity check before wiring up systemd:

```bash
su - kala -c "cd /opt/kala && .venv/bin/python -m pytest -q"
```

All tests should pass exactly as they did on your laptop — nothing here is
platform-specific.

## 6. Put the Telegram token in a root-owned secrets file (as root)

This is the whole point of the "super safe" setup: the token lives ONLY
here, readable only by root, and is never in `runner_config.json`.

```bash
mkdir -p /etc/kala
cat > /etc/kala/telegram.env <<'EOF'
KALA_TELEGRAM_TOKEN=paste-your-NEW-rotated-token-here
KALA_TELEGRAM_CHAT_ID=paste-your-chat-id-here
EOF
chmod 600 /etc/kala/telegram.env
chown root:root /etc/kala/telegram.env
```

Notes:
- No quotes around the values, no spaces around the `=` — systemd's
  `EnvironmentFile` format is literal `KEY=VALUE` lines.
- Both `kala-bot.service` and `kala-daily.service` read this same
  file (they both send Telegram messages).
- Because it's `chmod 600` root-owned, the unprivileged `kala` user the
  services run as can't even read it directly — systemd reads it as root and
  injects the values into each process's environment at start. That's
  stricter than a normal file the app opens itself.
- Leave `telegram_token` / `telegram_chat_id` BLANK (or absent) in
  `runner_config.json` on this server. The env vars win regardless, but a
  blank config file means the secret genuinely isn't duplicated anywhere.

## 7. Install the systemd units

Copy the five files from this project's `deploy/` folder:

```bash
cp /opt/kala/deploy/kala-bot.service          /etc/systemd/system/
cp /opt/kala/deploy/kala-daily.service        /etc/systemd/system/
cp /opt/kala/deploy/kala-daily.timer          /etc/systemd/system/
cp /opt/kala/deploy/kala-fundamentals.service /etc/systemd/system/
cp /opt/kala/deploy/kala-fundamentals.timer   /etc/systemd/system/
systemctl daemon-reload
```

Start the always-on bot and enable it to survive reboots:

```bash
systemctl enable --now kala-bot.service
systemctl status kala-bot.service
```

Enable the daily-cycle timer (this does NOT run it immediately — it just
schedules the 17:00 WIB firing):

```bash
systemctl enable --now kala-daily.timer
systemctl list-timers kala-daily.timer   # confirm the next fire time
```

Enable the monthly fundamental-archive timer the same way. This is what
lets the one still-open research question in `PROJECT_STATUS.md`
(fundamental-value tilt) eventually get resolved — it needs snapshots
taken real calendar time apart, so this timer just needs to keep firing
every month; nothing else acts on the data yet:

```bash
systemctl enable --now kala-fundamentals.timer
systemctl list-timers kala-fundamentals.timer   # confirm the next fire time
```

## 8. Verify

- From your phone, message the bot: `/status`. If it replies, the always-on
  service works AND the token secrets file was read correctly. (If the bot
  is silent, `journalctl -u kala-bot.service` will show either
  "Telegram credentials missing" — the env file wasn't found or is
  malformed — or a startup error.)
- Test the daily cycle without waiting for 17:00:
  ```bash
  systemctl start kala-daily.service
  journalctl -u kala-daily.service -f
  ```
- Check ongoing bot logs anytime:
  ```bash
  journalctl -u kala-bot.service -f
  ```

## 9. Basic hygiene (worth doing, not optional-optional)

```bash
ufw allow OpenSSH
ufw enable
```

That's the whole surface area this needs open — the bot only makes
*outbound* connections to Telegram and Yahoo Finance, so no inbound ports
need to be opened for it to work. If you SSH in with a password today,
switch to key-based auth and disable password login
(`PasswordAuthentication no` in `/etc/ssh/sshd_config`, then
`systemctl restart sshd`) — a bot holding your Telegram token and trading
config is worth locking the front door properly.

## 10. Back up your state periodically

`paper_state.json` is now the only copy of your trading history — it's not
being pulled back to your laptop automatically anymore. A simple weekly
pull is enough:

```bash
scp kala@YOUR_SERVER_IP:/opt/kala/paper_state.json ./backups/paper_state_$(date +%Y%m%d).json
```

Run that from your laptop (or set up a `cron` job on the server that copies
it to cheap object storage) on whatever cadence you're comfortable with.

## Updating the code later

When I hand you a new zip of changed files: `scp` the changed files up to
`/opt/kala/` (matching paths — a file from `kala/foo.py` in the zip
goes to `/opt/kala/kala/foo.py`), then:

```bash
# optional but recommended: confirm the update didn't break anything
su - kala -c "cd /opt/kala && .venv/bin/python -m pytest -q"
# reload the always-on bot with the new code
systemctl restart kala-bot.service
```

The daily timer picks up code changes automatically on its next scheduled
fire — no restart needed for it specifically, since each run starts a fresh
process.

## Rotating the token later

If you ever need to change the token again (leak, or just good hygiene),
edit the secrets file and restart both services — nothing in the app code or
`runner_config.json` changes:

```bash
nano /etc/kala/telegram.env      # paste the new token/chat id
systemctl restart kala-bot.service
# the daily timer's next run picks up the new value automatically
```
