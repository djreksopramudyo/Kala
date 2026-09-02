"""A half-delivered daily message must not read as a delivered one.

Long messages are split across several Telegram requests. A failure on the
second of three left the first sitting in the chat and returned a bare
``False`` — which cannot tell "nothing sent" from "half sent", and those are
different problems. From the reader's side the difference is invisible: the
part that arrived does not say it was a part, and the daily message puts the
tickets first and the friction/scorecard sections last, so the tail is exactly
what goes missing.

``daily_run`` then discarded the return value entirely and logged "Run
complete. N tickets, 0 errors." The persistent record — the file anyone opens
after a quiet week — could not distinguish a delivered run from an undelivered
one.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kala import notify  # noqa: E402
from kala.notify import (  # noqa: E402
    CHUNK_CHARS,
    Delivery,
    send_telegram,
    send_telegram_detailed,
)


class _Resp:
    def __init__(self, ok):
        self.ok = ok

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError("502 Bad Gateway")


def _post_failing_after(n_ok: int, sent: list[str]):
    def post(url, json=None, timeout=None):
        ok = len(sent) < n_ok
        if ok:
            sent.append(json["text"])
        return _Resp(ok)
    return post


def _three_chunk_message() -> str:
    return "HEAD\n" + ("x" * (CHUNK_CHARS * 2 + 100))


def test_a_partial_send_is_reported_as_partial(monkeypatch):
    sent: list[str] = []
    monkeypatch.setattr(notify.requests, "post", _post_failing_after(1, sent))

    d = send_telegram_detailed("tok", "chat", _three_chunk_message())

    assert d.total_chunks == 3          # non-vacuity: it really did split
    assert d.sent_chunks == 1
    assert d.ok is False
    assert d.partial is True
    assert "PARTIALLY" in d.describe()
    assert len(sent) == 1               # and one chunk really is in the chat


def test_nothing_sent_is_not_reported_as_partial(monkeypatch):
    sent: list[str] = []
    monkeypatch.setattr(notify.requests, "post", _post_failing_after(0, sent))

    d = send_telegram_detailed("tok", "chat", _three_chunk_message())

    assert d.sent_chunks == 0
    assert d.partial is False           # the distinction the bool could not make
    assert "NOT delivered" in d.describe()


def test_a_full_send_reports_every_part(monkeypatch):
    sent: list[str] = []
    monkeypatch.setattr(notify.requests, "post", _post_failing_after(99, sent))

    d = send_telegram_detailed("tok", "chat", _three_chunk_message())

    assert d.ok is True
    assert d.sent_chunks == d.total_chunks == 3
    assert d.partial is False
    assert "delivered (3/3 parts)" in d.describe()


def test_split_messages_are_labelled_so_a_missing_tail_shows(monkeypatch):
    """The fix that reaches the reader: the chat itself says (i/N)."""
    sent: list[str] = []
    monkeypatch.setattr(notify.requests, "post", _post_failing_after(99, sent))

    send_telegram_detailed("tok", "chat", _three_chunk_message())

    assert sent[0].startswith("(1/3) ")
    assert sent[1].startswith("(2/3) ")
    assert sent[2].startswith("(3/3) ")
    # Still inside Telegram's 4096 limit once the label is added.
    assert all(len(c) <= 4096 for c in sent)


def test_a_single_chunk_message_is_not_labelled(monkeypatch):
    """No (1/1) noise on the ordinary short message."""
    sent: list[str] = []
    monkeypatch.setattr(notify.requests, "post", _post_failing_after(99, sent))

    send_telegram_detailed("tok", "chat", "short daily message")

    assert sent == ["short daily message"]


def test_unconfigured_credentials_are_not_a_partial_send(capsys):
    d = send_telegram_detailed("", "", "anything")
    assert d.ok is False and d.sent_chunks == 0 and d.partial is False
    assert "not configured" in d.describe().lower()
    assert "anything" in capsys.readouterr().out   # still printed, as before


def test_the_bool_wrapper_still_answers_yes_or_no(monkeypatch):
    """Three existing callers rely on the bool; it must keep working."""
    sent: list[str] = []
    monkeypatch.setattr(notify.requests, "post", _post_failing_after(99, sent))
    assert send_telegram("tok", "chat", "hi") is True

    sent2: list[str] = []
    monkeypatch.setattr(notify.requests, "post", _post_failing_after(1, sent2))
    # A PARTIAL send is False, not True -- "some of it arrived" is not success.
    assert send_telegram("tok", "chat", _three_chunk_message()) is False


def test_daily_run_records_the_delivery_outcome():
    """The log is the record read after a quiet week; it must carry this."""
    src = (ROOT / "daily_run.py").read_text(encoding="utf-8")
    assert "delivery = send_telegram_detailed(tg_token, tg_chat_id, msg)" in src
    assert "errors.append(f\"telegram: {delivery.describe()}\")" in src
    assert "Telegram: {delivery.describe()}" in src


def test_describe_never_returns_an_empty_string():
    """It goes straight into a log line; a blank would read as 'fine'."""
    for d in (Delivery(), Delivery(ok=True, sent_chunks=1, total_chunks=1),
              Delivery(sent_chunks=1, total_chunks=3, error="boom"),
              Delivery(total_chunks=2, error="boom")):
        assert d.describe().strip()
