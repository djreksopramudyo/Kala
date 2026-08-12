"""
Notifications: turn the day's decisions into one Telegram message.

Setup (once, ~3 minutes):
  1. In Telegram, talk to @BotFather -> /newbot -> copy the bot TOKEN.
  2. Send your new bot any message, then open
     https://api.telegram.org/bot<TOKEN>/getUpdates and copy your chat "id".
  3. Provide both, EITHER via runner_config.json OR — preferred for a
     server — via the environment variables KALA_TELEGRAM_TOKEN and
     KALA_TELEGRAM_CHAT_ID (see resolve_telegram_credentials). The env
     vars WIN over the config file when both are set, so the secret can live
     only in a root-owned systemd drop-in and never in a file that gets
     zipped, copied, or accidentally shared.

`format_daily_message` is pure (tested); `send_telegram` is the only network
call and degrades to printing if unconfigured — automation never dies because
Telegram is down.
"""

from __future__ import annotations

import os

import requests

TOKEN_ENV = "KALA_TELEGRAM_TOKEN"
CHAT_ID_ENV = "KALA_TELEGRAM_CHAT_ID"


_PLACEHOLDER_PREFIX = "SET_VIA_"


def _is_placeholder(value: str) -> bool:
    """True for the literal instructional text runner_config.json.example
    ships (e.g. "SET_VIA_KALA_TELEGRAM_TOKEN_ENV_VAR_INSTEAD"). A user who
    copies the example file without editing it ends up with that string
    sitting in a real config, and it must NOT be treated as a credential —
    without this check it silently reaches Telegram's API as a bogus token
    and fails with an opaque 404, instead of the clear "credentials missing"
    message main() prints when token/chat_id are genuinely empty."""
    return value.strip().upper().startswith(_PLACEHOLDER_PREFIX)


def resolve_telegram_credentials(cfg: dict | None = None) -> tuple[str, str]:
    """Return (token, chat_id), preferring the environment over the config
    file. Order for each value independently:
      1. env var (KALA_TELEGRAM_TOKEN / KALA_TELEGRAM_CHAT_ID)
      2. the matching key in `cfg` (runner_config.json), if provided,
         UNLESS it's still the unedited example placeholder text (treated
         as not set)

    Why env-first: on a server the token should live only in a root-owned
    systemd drop-in (mode 600), never in runner_config.json — which has a
    long history of ending up inside shared zips. Keeping the config path as
    a fallback means an existing laptop setup keeps working unchanged; the
    env vars simply override it when present. An env var set to empty string
    is treated as 'not set' so a stray blank export can't blank out a
    working config value."""
    cfg = cfg or {}
    cfg_token = str(cfg.get("telegram_token", "") or "")
    cfg_chat_id = str(cfg.get("telegram_chat_id", "") or "")
    if _is_placeholder(cfg_token):
        cfg_token = ""
    if _is_placeholder(cfg_chat_id):
        cfg_chat_id = ""
    token = os.environ.get(TOKEN_ENV, "").strip() or cfg_token
    chat_id = os.environ.get(CHAT_ID_ENV, "").strip() or cfg_chat_id
    return token, chat_id


def format_daily_message(report: dict, summary: dict | None = None,
                         market_status: str | None = None,
                         extra_alerts: list | None = None) -> str:
    """One human-ready message: what filled today, what to do tomorrow."""
    lines = [f"📊 Kala — {report.get('date', '')}"]
    if market_status:
        lines.append(f"Market: {market_status}")

    tickets = report.get("tickets", [])
    if tickets:
        lines.append("\n🎫 ORDERS FOR TOMORROW'S OPEN (paper — mirror manually if desired):")
        for t in tickets:
            lines.append(f"  • {t}")
    else:
        lines.append("\nNo new orders for tomorrow.")

    if report.get("fills"):
        lines.append("\n✅ Filled today:")
        lines += [f"  • {f}" for f in report["fills"]]

    if extra_alerts:
        lines.append("\n💎 Watchlist dips (re-check thesis before buying!):")
        for a in extra_alerts:
            lines.append(f"  • {a['ticker']}: {a['discount_pct']:.0f}% below fair "
                         f"(IDR {a['price']:,.0f} vs {a['fair_value']:,.0f})")

    # Before the account summary and never truncated: a holding whose exit
    # rules did not run is the one thing in this message that needs acting on
    # by hand, and its absence from the ticket list looks exactly like "no
    # signal today".
    if report.get("unevaluated"):
        lines.append("\n🔴 NOT CHECKED TODAY — verify these yourself:")
        for u in report["unevaluated"]:
            lines.append(f"  • {u}")

    if report.get("skipped"):
        lines.append("\n⏭️ Skipped: " + "; ".join(report["skipped"][:5]))

    if summary:
        lines.append(f"\n💼 Paper account: equity IDR {summary['equity']:,.0f} "
                     f"({summary['return_pct']:+.2f}%) | cash IDR {summary['cash']:,.0f} | "
                     f"{summary['open_positions']} open, {summary['closed_trades']} closed, "
                     f"win rate {summary['win_rate_pct']:.0f}%")
        if "alpha_pct" in summary:
            beat = "beating" if summary["alpha_pct"] >= 0 else "TRAILING"
            lines.append(f"📈 vs IHSG buy-and-hold: {summary['benchmark_return_pct']:+.2f}% "
                         f"-> alpha {summary['alpha_pct']:+.2f}% ({beat} the index)")
    lines.append("\n⚠️ Signals, not advice. Check news before acting.")
    return "\n".join(lines)


def send_telegram(token: str, chat_id: str, text: str, timeout: int = 15) -> bool:
    """Send `text` to the chat. Returns True on success; on any failure (or if
    token/chat_id are empty) it prints the message instead and returns False,
    so the daily run still completes."""
    if not token or not chat_id:
        print("[notify] Telegram not configured — printing instead:\n" + text)
        return False
    try:
        # Telegram caps messages at 4096 chars; split politely.
        for chunk_start in range(0, len(text), 3900):
            chunk = text[chunk_start:chunk_start + 3900]
            r = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": chunk},
                timeout=timeout,
            )
            r.raise_for_status()
        return True
    except Exception as e:
        print(f"[notify] Telegram send failed ({e}) — printing instead:\n" + text)
        return False
