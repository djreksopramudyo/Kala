r"""
Throwaway: prove the Telegram chain works, independent of trading logic.

Run once:
    .\.venv\Scripts\python.exe ping_check.py

If your phone buzzes, then config -> token -> Telegram all work, and any future
SILENCE from intraday_watch.py means "nothing to report" (no positions / no
event), NOT "broken". Delete this file afterwards.
"""

import json
from datetime import datetime
from pathlib import Path

from kala.notify import send_telegram

cfg = json.loads(Path("runner_config.json").read_text(encoding="utf-8"))
ok = send_telegram(
    cfg.get("telegram_token", ""),
    cfg.get("telegram_chat_id", ""),
    f"✅ Kala test ping {datetime.now():%H:%M:%S} — "
    f"if you can read this, Telegram alerts are wired correctly.",
)
print("SENT — check your phone." if ok
      else "NOT sent — token/chat_id missing or wrong (see message above).")
