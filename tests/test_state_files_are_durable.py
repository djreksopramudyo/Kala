"""State the app writes must survive a crash, a move, and a rebuild.

Four ways the researched watchlist could vanish without anything reporting a
loss, all live before 2026-08:

  1. ``save()`` truncated the target before writing it, so an interrupted save
     left the file empty or half-written.
  2. ``load()`` answered a missing file with an empty store, so a process
     running in the wrong directory looked exactly like a user who had not
     researched anything yet.
  3. Three archivers ended both of their reads with ``except Exception: pass``,
     collapsing a damaged file into that same empty result -- and their
     archives are point-in-time, so the day they skipped cannot be re-archived.
  4. ``docker-compose.yml`` mounted paper_state.json and runner_config.json
     but not watchlist.json, which the weekly screen writes inside the
     container. Every ``up --build`` discarded it.

Each test below fails if its defect is reinserted; that was checked by
reinserting each one.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kala import positions as positions_mod  # noqa: E402
from kala import watchlist as watchlist_mod  # noqa: E402
from kala.positions import Position, PositionStore  # noqa: E402
from kala.universe_sources import default_universe  # noqa: E402
from kala.watchlist import WatchlistItem, WatchlistStore, load_or_report  # noqa: E402


def _utf8_env() -> dict:
    """Environment for a subprocess whose stdout this test decodes as UTF-8.

    The parent passes encoding="utf-8"; on Windows a Python child writing to a
    pipe encodes with the locale codepage instead, so the two ends disagree and
    any non-ASCII in --help output (this project's docstrings are full of
    em-dashes) comes back mangled or raises. Setting PYTHONIOENCODING makes the
    child agree with the parent on every platform.
    """
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("PYTHONPATH", None)
    return env

def _item(ticker: str, fair_value: float = 5000.0) -> WatchlistItem:
    return WatchlistItem(ticker=ticker, fair_value=fair_value, score=80.0,
                         thesis="researched", added="2026-01-02", source="screen")


def _paper_state(tickers: list[str]) -> str:
    return json.dumps({
        "cash": 1_000_000.0,
        "start_capital": 10_000_000.0,
        "positions": {t: {"ticker": t, "shares": 100, "entry_price": 1000.0,
                          "entry_date": "2026-01-02", "peak_price": 1100.0}
                      for t in tickers},
        "pending": [],
        "log": [],
    })


# --------------------------------------------------------------------------
# 1. the write cannot destroy what is already on disk
# --------------------------------------------------------------------------

def _boom(*a, **k):
    raise RuntimeError("power cut")


def test_watchlist_survives_a_crash_during_save(tmp_path, monkeypatch):
    path = tmp_path / "watchlist.json"
    store = WatchlistStore(path)
    store.add(_item("BBCA.JK"))
    store.save()
    before = path.read_text(encoding="utf-8")
    assert "BBCA.JK" in before          # non-vacuity: there IS something to lose

    store.add(_item("TLKM.JK"))
    monkeypatch.setattr(watchlist_mod.os, "replace", _boom)
    with pytest.raises(RuntimeError):
        store.save()

    # The crash happened at the swap, so the previous watchlist is byte-identical.
    assert path.read_text(encoding="utf-8") == before
    assert len(WatchlistStore.load(path)) == 1


def test_positions_survive_a_crash_during_save(tmp_path, monkeypatch):
    path = tmp_path / "positions.json"
    store = PositionStore(path)
    store.add(Position(ticker="BBCA.JK", entry_price=9000.0, shares=100))
    store.get("BBCA.JK").update_peak(11000.0)
    store.save()
    before = path.read_text(encoding="utf-8")
    assert "11000" in before            # non-vacuity: the peak is on disk

    store.add(Position(ticker="TLKM.JK", entry_price=4000.0, shares=200))
    monkeypatch.setattr(positions_mod.os, "replace", _boom)
    with pytest.raises(RuntimeError):
        store.save()

    assert path.read_text(encoding="utf-8") == before
    # peak_price has no other source -- it is a running maximum across runs.
    assert PositionStore.load(path).get("BBCA.JK").peak_price == 11000.0


@pytest.mark.parametrize("kind", ["watchlist", "positions"])
def test_a_successful_save_leaves_no_tmp_file_behind(tmp_path, kind):
    if kind == "watchlist":
        store = WatchlistStore(tmp_path / "watchlist.json")
        store.add(_item("BBCA.JK"))
    else:
        store = PositionStore(tmp_path / "positions.json")
        store.add(Position(ticker="BBCA.JK", entry_price=9000.0, shares=100))
    store.save()
    assert [p.name for p in tmp_path.glob("*.tmp")] == []


def test_save_creates_a_missing_parent_directory(tmp_path):
    store = WatchlistStore(tmp_path / "nested" / "deep" / "watchlist.json")
    store.add(_item("BBCA.JK"))
    store.save()
    assert len(WatchlistStore.load(store.path)) == 1


# --------------------------------------------------------------------------
# 2. an absent file is not an empty one
# --------------------------------------------------------------------------

def test_absent_watchlist_is_distinguishable_from_an_empty_one(tmp_path):
    empty_path = tmp_path / "watchlist.json"
    empty_path.write_text("{}", encoding="utf-8")

    absent = WatchlistStore.load(tmp_path / "not_here.json")
    empty = WatchlistStore.load(empty_path)

    # Same length -- this is exactly why the length alone was not enough.
    assert len(absent) == len(empty) == 0
    assert empty.load_note is None
    assert absent.load_note is not None
    # The resolved path is the fact that separates "wrong directory" from
    # "nothing researched yet", so it has to be in the message.
    assert str((tmp_path / "not_here.json").resolve()) in absent.load_note


def test_a_damaged_watchlist_still_raises_for_callers_that_should_crash(tmp_path):
    path = tmp_path / "watchlist.json"
    path.write_text('{"BBCA.JK": {"ticker": "BBCA.JK", "fai', encoding="utf-8")   # truncated
    with pytest.raises(json.JSONDecodeError):
        WatchlistStore.load(path)


def test_load_or_report_names_the_path_and_the_damage(tmp_path):
    path = tmp_path / "watchlist.json"
    path.write_text('{"BBCA.JK": {"ticker": "BBCA.JK", "fai', encoding="utf-8")
    said: list[str] = []

    store = load_or_report(path, warn=said.append)

    assert len(store) == 0                       # it does degrade, as before
    assert said, "a damaged watchlist was swallowed without a word"
    assert str(path.resolve()) in said[0]
    assert "damaged, not empty" in said[0]


def test_load_or_report_is_silent_on_a_clean_read(tmp_path):
    path = tmp_path / "watchlist.json"
    store = WatchlistStore(path)
    store.add(_item("BBCA.JK"))
    store.save()
    said: list[str] = []

    loaded = load_or_report(path, warn=said.append)

    assert len(loaded) == 1
    assert said == []


# --------------------------------------------------------------------------
# 3. the archivers' shared universe reports every degraded source
# --------------------------------------------------------------------------

def test_universe_reports_both_sources_when_neither_exists(tmp_path):
    said: list[str] = []
    u = default_universe(tmp_path / "paper_state.json", tmp_path / "watchlist.json",
                         warn=said.append)

    assert u.tickers == []
    assert len(u.notes) == 2, u.notes
    assert not u.fully_sourced
    assert len(said) == 2
    assert all(str(tmp_path) in m for m in said)


def test_universe_keeps_the_readable_source_and_flags_the_incompleteness(tmp_path):
    state = tmp_path / "paper_state.json"
    state.write_text(_paper_state(["BBCA.JK", "TLKM.JK"]), encoding="utf-8")
    damaged = tmp_path / "watchlist.json"
    damaged.write_text('{"UNVR.JK": {"ticker', encoding="utf-8")
    said: list[str] = []

    u = default_universe(state, damaged, warn=said.append)

    # Non-vacuity: the point of degrading is that the OTHER source still lands.
    assert u.tickers == ["BBCA.JK", "TLKM.JK"]
    assert u.n_from_positions == 2
    assert u.positions_read and not u.watchlist_read
    assert not u.fully_sourced
    # An incomplete point-in-time archive is written anyway -- but never quietly.
    assert any("cannot be backfilled" in m for m in said), said


def test_universe_is_silent_when_both_sources_read_cleanly(tmp_path):
    state = tmp_path / "paper_state.json"
    state.write_text(_paper_state(["BBCA.JK"]), encoding="utf-8")
    wl = WatchlistStore(tmp_path / "watchlist.json")
    wl.add(_item("UNVR.JK"))
    wl.save()
    said: list[str] = []

    u = default_universe(state, wl.path, warn=said.append)

    assert u.tickers == ["BBCA.JK", "UNVR.JK"]
    assert u.fully_sourced
    assert said == []


# --------------------------------------------------------------------------
# 4. the scripts look beside themselves, not beside the caller
# --------------------------------------------------------------------------

ANCHORED_SCRIPTS = ("archive_sentiment.py", "archive_fundamentals.py",
                    "foreign_flow_monitor.py", "check_watchlist.py")


@pytest.mark.parametrize("script", ANCHORED_SCRIPTS)
def test_state_paths_are_anchored_to_the_repo_not_the_cwd(script, tmp_path):
    """Read the constants from a subprocess started somewhere else entirely.

    Importing in-process would resolve against the test runner's cwd, which
    happens to be the repo -- the bug would pass. Only a foreign cwd shows it.
    """
    probe = tmp_path / "probe.py"
    probe.write_text(
        "import importlib, sys\n"
        f"sys.path.insert(0, {str(ROOT)!r})\n"
        f"m = importlib.import_module({script[:-3]!r})\n"
        "print(m.WATCHLIST_PATH)\n"
    , encoding="utf-8")
    out = subprocess.run([sys.executable, str(probe)], cwd=tmp_path,
                         capture_output=True, text=True, encoding="utf-8", env=_utf8_env(),
        errors="replace")
    assert out.returncode == 0, out.stderr
    resolved = Path(out.stdout.strip())
    assert resolved.is_absolute(), f"{script} resolves watchlist.json against cwd"
    assert resolved.parent == ROOT


# --------------------------------------------------------------------------
# 5. the container keeps what the container writes
# --------------------------------------------------------------------------

# Files the running app writes and must not lose on `docker compose up --build`.
PERSISTED_STATE = ("paper_state.json", "runner_config.json", "watchlist.json")


def test_compose_mounts_every_state_file_the_app_writes():
    text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    mounts = [ln.split("#", 1)[0].strip().lstrip("- ").strip()
              for ln in text.splitlines()
              if ln.strip().startswith("- ./")]
    assert mounts, "no bind mounts found -- the parse is wrong, not the file"
    for name in PERSISTED_STATE:
        assert any(m.startswith(f"./{name}:") for m in mounts), (
            f"{name} is written inside the container but never mounted; a "
            f"rebuild discards it and every reader reports it as empty")


def test_docker_setup_does_not_seed_json_with_touch():
    """`touch` leaves a zero-byte file, and zero bytes is not valid JSON."""
    text = (ROOT / "DOCKER.md").read_text(encoding="utf-8")
    for name in PERSISTED_STATE:
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("touch ") and name in stripped:
                pytest.fail(f"DOCKER.md seeds {name} with `touch`: {stripped!r}")


def test_zero_byte_state_files_do_not_load(tmp_path):
    """The reason the line above matters, pinned as behaviour rather than prose."""
    path = tmp_path / "watchlist.json"
    path.write_text("", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        WatchlistStore.load(path)


def test_the_documented_seed_actually_loads(tmp_path):
    """`{}` is the right seed for the watchlist; `{}` is NOT for paper_state."""
    wl = tmp_path / "watchlist.json"
    wl.write_text("{}", encoding="utf-8")
    assert len(WatchlistStore.load(wl)) == 0     # documented seed works

    from kala.papertrade import PaperTrader
    state = tmp_path / "paper_state.json"
    state.write_text("{}", encoding="utf-8")
    with pytest.raises(KeyError):
        PaperTrader.load(str(state), start_capital=10_000_000)
