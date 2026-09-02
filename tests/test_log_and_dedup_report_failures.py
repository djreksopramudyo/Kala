"""Two swallowed writes, one of which the last change made load-bearing.

``daily_run.log()`` discarded every file-write failure. That was tolerable
while the log was a convenience. It stopped being tolerable the moment the
Telegram delivery outcome started being recorded there: a log that cannot be
written is a record that silently does not exist, and "no entries" then reads
as "no runs happened" — which is the exact failure the delivery reporting was
added to prevent. Building on an unchecked foundation is its own bug.

``AlertDedup`` is the milder case and is fixed for consistency: losing it
causes duplicate alerts, not lost data, and duplicates are self-evident. It
now writes atomically and says when it could not.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import daily_run  # noqa: E402
from kala.intraday import AlertDedup  # noqa: E402


def test_a_log_write_failure_is_reported_once(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(daily_run, "LOG_PATH", tmp_path / "nope" / "daily_run.log")
    monkeypatch.setattr(daily_run, "_LOG_FAILED", False)

    def boom(*a, **k):
        raise OSError("read-only file system")
    monkeypatch.setattr(daily_run.Path, "mkdir", boom)

    daily_run.log("first")
    daily_run.log("second")
    daily_run.log("third")

    err = capsys.readouterr()
    assert err.err.count("cannot write") == 1     # once, not once per line
    assert "NOT" in err.err and "recorded" in err.err
    # stdout is unaffected -- the run still reports itself somewhere.
    assert "first" in err.out and "third" in err.out


def test_a_working_log_says_nothing_and_writes_everything(tmp_path, monkeypatch,
                                                          capsys):
    path = tmp_path / "results" / "daily_run.log"
    monkeypatch.setattr(daily_run, "LOG_PATH", path)
    monkeypatch.setattr(daily_run, "_LOG_FAILED", False)

    daily_run.log("hello")

    out = capsys.readouterr()
    assert out.err == ""
    assert "hello" in path.read_text(encoding="utf-8")            # non-vacuity: it really wrote


def test_the_log_creates_a_missing_parent_chain(tmp_path, monkeypatch):
    path = tmp_path / "a" / "b" / "daily_run.log"
    monkeypatch.setattr(daily_run, "LOG_PATH", path)
    monkeypatch.setattr(daily_run, "_LOG_FAILED", False)
    daily_run.log("deep")
    assert path.exists()


# ---- alert dedup ----------------------------------------------------------

def test_dedup_survives_a_crash_during_save(tmp_path, monkeypatch):
    path = tmp_path / "intraday_alerts.json"
    d = AlertDedup(path)
    d.filter_new([{"ticker": "A.JK", "type": "dip"}], "2026-08-17")
    d.save()
    before = path.read_text(encoding="utf-8")
    assert "A.JK" in before                       # non-vacuity

    d.filter_new([{"ticker": "B.JK", "type": "dip"}], "2026-08-17")
    import kala.intraday as mod
    monkeypatch.setattr(mod.os, "replace", lambda *a, **k: (_ for _ in ()).throw(
        RuntimeError("power cut")))
    d.save()                                      # reports, does not raise

    assert path.read_text(encoding="utf-8") == before             # previous state intact


def test_a_failed_dedup_save_says_the_alerts_may_repeat(tmp_path, monkeypatch,
                                                        capsys):
    import kala.intraday as mod
    d = AlertDedup(tmp_path / "intraday_alerts.json")
    d.filter_new([{"ticker": "A.JK", "type": "dip"}], "2026-08-17")
    monkeypatch.setattr(mod.os, "replace", lambda *a, **k: (_ for _ in ()).throw(
        RuntimeError("disk full")))

    d.save()

    err = capsys.readouterr().err
    assert "not saved" in err and "repeat" in err


def test_an_unreadable_dedup_file_says_so_instead_of_resetting_silently(
        tmp_path, capsys):
    path = tmp_path / "intraday_alerts.json"
    path.write_text("{not json", encoding="utf-8")

    d = AlertDedup(path)

    err = capsys.readouterr().err
    assert "unreadable" in err
    assert "repeat" in err
    assert d.filter_new([{"ticker": "A.JK", "type": "dip"}], "2026-08-17")


def test_a_clean_dedup_load_is_silent_and_still_dedups(tmp_path, capsys):
    path = tmp_path / "intraday_alerts.json"
    d = AlertDedup(path)
    assert d.filter_new([{"ticker": "A.JK", "type": "dip"}], "2026-08-17")
    d.save()
    capsys.readouterr()

    d2 = AlertDedup(path)
    assert capsys.readouterr().err == ""
    # the whole point: the second run stays quiet about the same alert
    assert d2.filter_new([{"ticker": "A.JK", "type": "dip"}], "2026-08-17") == []


def test_a_successful_dedup_save_leaves_no_tmp_file(tmp_path):
    d = AlertDedup(tmp_path / "intraday_alerts.json")
    d.filter_new([{"ticker": "A.JK", "type": "dip"}], "2026-08-17")
    d.save()
    assert list(tmp_path.glob("*.tmp")) == []
