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
from dataclasses import dataclass

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


@dataclass(frozen=True)
class Delivery:
    """How much of a message actually reached the chat.

    ``send_telegram`` returned a bare bool, and long messages are split into
    several requests. A failure on the second of three chunks therefore left
    the first one delivered and returned False — indistinguishable from
    nothing being sent, and from the reader's side indistinguishable from a
    complete message, because the part that arrived does not say it was a
    part. The daily message carries the tickets first and the friction and
    scorecard sections last, so the tail is what goes missing.
    """
    ok: bool = False
    sent_chunks: int = 0
    total_chunks: int = 0
    error: str | None = None

    @property
    def partial(self) -> bool:
        return 0 < self.sent_chunks < self.total_chunks

    def describe(self) -> str:
        if self.ok:
            return f"delivered ({self.sent_chunks}/{self.total_chunks} parts)"
        if self.partial:
            return (f"PARTIALLY delivered — {self.sent_chunks} of "
                    f"{self.total_chunks} parts reached the chat, the rest was "
                    f"lost ({self.error}). The message on your phone is cut "
                    f"off and does not say so.")
        if self.error:
            return f"NOT delivered ({self.error})"
        return "NOT delivered (Telegram not configured)"


CHUNK_CHARS = 3900  # Telegram caps at 4096; the '(i/N) ' label fits in the rest


def send_telegram_detailed(token: str, chat_id: str, text: str,
                           timeout: int = 15) -> Delivery:
    """Send `text`, reporting how many parts got through.

    Chunks are labelled ``(i/N)`` when there is more than one, so a missing
    tail is visible in the chat itself rather than only in a log the reader
    would have to think to check.
    """
    chunks = [text[i:i + CHUNK_CHARS] for i in range(0, len(text), CHUNK_CHARS)] or [""]
    total = len(chunks)
    if not token or not chat_id:
        print("[notify] Telegram not configured — printing instead:\n" + text)
        return Delivery(ok=False, sent_chunks=0, total_chunks=total)

    sent = 0
    for i, chunk in enumerate(chunks, 1):
        body = f"({i}/{total}) {chunk}" if total > 1 else chunk
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": body},
                timeout=timeout,
            )
            r.raise_for_status()
            sent += 1
        except Exception as e:  # noqa: BLE001 - reported, not swallowed
            d = Delivery(ok=False, sent_chunks=sent, total_chunks=total,
                         error=f"{type(e).__name__}: {e}")
            print(f"[notify] {d.describe()} — printing the whole message "
                  f"instead:\n" + text)
            return d
    return Delivery(ok=True, sent_chunks=sent, total_chunks=total)


def send_telegram(token: str, chat_id: str, text: str, timeout: int = 15) -> bool:
    """Send `text` to the chat. Returns True only when EVERY part got through.

    Kept for the callers that only need a yes/no. Use
    ``send_telegram_detailed`` where a partly-delivered message matters — the
    bool cannot tell "nothing sent" from "half sent", and those are different
    problems.
    """
    return send_telegram_detailed(token, chat_id, text, timeout).ok
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
