"""Liveness heartbeat tests: file-based freshness check for the Docker
HEALTHCHECK to poll (see heartbeat.py's module docstring)."""

from kala.heartbeat import (
    heartbeat_age_seconds,
    heartbeat_is_fresh,
    write_heartbeat,
)


def test_write_then_age_is_near_zero(tmp_path):
    p = tmp_path / "hb.txt"
    write_heartbeat(p, now=1000.0)
    assert heartbeat_age_seconds(p, now=1000.0) == 0.0


def test_age_reflects_elapsed_time(tmp_path):
    p = tmp_path / "hb.txt"
    write_heartbeat(p, now=1000.0)
    assert heartbeat_age_seconds(p, now=1100.0) == 100.0


def test_age_is_none_when_file_missing(tmp_path):
    p = tmp_path / "nope.txt"
    assert heartbeat_age_seconds(p) is None


def test_age_is_none_for_corrupt_contents(tmp_path):
    p = tmp_path / "hb.txt"
    p.write_text("not-a-number")
    assert heartbeat_age_seconds(p) is None


def test_is_fresh_true_within_window(tmp_path):
    p = tmp_path / "hb.txt"
    write_heartbeat(p, now=1000.0)
    assert heartbeat_is_fresh(p, max_age_seconds=300, now=1200.0)


def test_is_fresh_false_outside_window(tmp_path):
    p = tmp_path / "hb.txt"
    write_heartbeat(p, now=1000.0)
    assert not heartbeat_is_fresh(p, max_age_seconds=300, now=1400.0)


def test_is_fresh_false_when_missing(tmp_path):
    p = tmp_path / "nope.txt"
    assert not heartbeat_is_fresh(p)


def test_is_fresh_false_for_future_dated_heartbeat(tmp_path):
    """Clock skew / a corrupted future timestamp must not read as fresh."""
    p = tmp_path / "hb.txt"
    write_heartbeat(p, now=2000.0)
    assert not heartbeat_is_fresh(p, max_age_seconds=300, now=1000.0)


def test_write_heartbeat_overwrites_previous_value(tmp_path):
    p = tmp_path / "hb.txt"
    write_heartbeat(p, now=1000.0)
    write_heartbeat(p, now=2000.0)
    assert heartbeat_age_seconds(p, now=2000.0) == 0.0
