#!/usr/bin/env python3
"""A daily message that arrives half-delivered, and a log that calls it a success.

Run it from anywhere:  python repro/repro_partial_telegram.py
"""
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
AUG = next(c for c in (_HERE.parent, _HERE.parent / "aug")
           if (c / "kala").is_dir())
sys.path.insert(0, str(AUG))

from kala import notify  # noqa: E402


class FakeResponse:
    def __init__(self, ok: bool):
        self._ok = ok

    def raise_for_status(self):
        if not self._ok:
            raise RuntimeError("502 Bad Gateway")


def main() -> int:
    # A realistic long daily message: tickets, then the friction report, then
    # the scorecard. Three chunks at the 3900-char split.
    part1 = "TICKETS\n" + ("BBCA.JK buy 100 @ 9000\n" * 160)
    part2 = "FRICTION\n" + ("cost line\n" * 380)
    part3 = "SCORECARD\n" + ("vs XIJI +1.2%\n" * 250)
    msg = part1 + part2 + part3
    n_chunks = (len(msg) + 3899) // 3900
    print(f"message length: {len(msg)} chars -> {n_chunks} chunks\n")

    sent: list[str] = []

    def flaky_post(url, json=None, timeout=None):
        # The network dies after the first chunk — the ordinary shape of a
        # transient failure, not a contrived one.
        ok = len(sent) < 1
        if ok:
            sent.append(json["text"])
        return FakeResponse(ok)

    real_post = notify.requests.post
    notify.requests.post = flaky_post
    try:
        result_detail = notify.send_telegram_detailed("token", "chat", msg)
        result = result_detail.ok
    finally:
        notify.requests.post = real_post

    print("=" * 74)
    print("WHAT THE OPERATOR RECEIVES")
    print("=" * 74)
    print(f"  chunks actually delivered : {len(sent)} of {n_chunks}")
    for i, chunk in enumerate(sent, 1):
        print(f"    chunk {i} begins: {chunk[:40]!r}")
    print(f"  send_telegram returned    : {result}")
    print()
    print("  The phone shows one message that begins with TICKETS and simply")
    print("  stops. Nothing in it says a second and third chunk existed. The")
    print("  FRICTION and SCORECARD sections were never delivered.")

    print()
    print("=" * 74)
    print("WHAT THE PERSISTENT RECORD SAYS")
    print("=" * 74)
    src = (AUG / "daily_run.py").read_text()
    i = src.index("    delivery = send_telegram_detailed")
    print(src[i:i + 300].rstrip())
    print()
    print("  OLD: the return value was discarded, so results/daily_run.log said")
    print("  'Run complete. N tickets, 0 errors.' whether the message was")
    print("  delivered whole, in part, or not at all. The failure text went to")
    print("  stdout only -- journald, not the log file anyone opens after a")
    print("  quiet week.")
    print()
    print("  NEW: the delivery is checked, a partial send is counted as a stage")
    print("  error, and the log line carries the outcome:")
    print(f"    Telegram: {result_detail.describe()}")
    print()
    print("  And the chat itself now says it: each part is labelled (i/N), so a")
    print("  message that stops at (1/3) is visibly incomplete on the phone --")
    print("  which is where the reader actually is.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
