"""A killed mutation harness must not leave a source file mutated.

Every harness restored its file in a ``finally``. That covers an exception and
a Ctrl-C. It does not cover SIGKILL — and a 10-minute timeout killed
`repro/mutate_live_threshold.py` mid-run, leaving `kala_daily_trader.py`
carrying M8:

    <     if score > buy_threshold:      # the mutation
    ---
    >     if score >= buy_threshold:     # the real code

The visible symptom was one unrelated-looking test failing afterwards. The
invisible one is worse: a zip built from a tree in that state ships a mutated
live trading file, and nothing says so.

These tests kill a real subprocess mid-mutation — with ``Popen.kill()``, which
is SIGKILL on POSIX and TerminateProcess on Windows, neither of which lets a
``finally``, an ``atexit`` hook or a signal handler run — and assert the next
invocation puts the file back.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "repro"))

from _mutation_guard import (  # noqa: E402
    SENTINEL_NAME,
    mutated,
    restore_if_interrupted,
    run_mutations,
    sentinel_path,
)

ORIGINAL = "value = 1\n"
MUTANT = "value = 999\n"


@pytest.fixture
def tree(tmp_path):
    (tmp_path / "src.py").write_text(ORIGINAL, encoding="utf-8")
    return tmp_path


# ---------------------------------------------------------------------------
# the happy path still restores, and leaves no litter
# ---------------------------------------------------------------------------

def test_a_normal_mutation_restores_and_removes_the_sentinel(tree):
    with mutated(tree, "src.py", MUTANT):
        assert (tree / "src.py").read_text(encoding="utf-8") == MUTANT
        assert sentinel_path(tree).exists(), "no sentinel while mutated"
    assert (tree / "src.py").read_text(encoding="utf-8") == ORIGINAL
    assert not sentinel_path(tree).exists()


def test_an_exception_inside_the_block_still_restores(tree):
    with pytest.raises(RuntimeError), mutated(tree, "src.py", MUTANT):
        raise RuntimeError("pytest blew up")
    assert (tree / "src.py").read_text(encoding="utf-8") == ORIGINAL
    assert not sentinel_path(tree).exists()


# ---------------------------------------------------------------------------
# the case `finally` cannot cover
# ---------------------------------------------------------------------------

def test_a_killed_run_leaves_a_sentinel_and_the_next_run_restores(tree):
    """The actual failure, reproduced by killing a real process.

    ``Popen.kill()`` rather than ``signal.SIGKILL``: the constant does not exist
    on Windows, where ``kill()`` calls TerminateProcess instead. Both give the
    process no chance to run a ``finally``, an ``atexit`` hook or a handler, so
    the test's premise holds on either platform — which is the premise. Nothing
    inside the dying process can put the file back; the recovery has to be
    something already on disk before the file was touched.
    """
    script = tree / "victim.py"
    script.write_text(textwrap.dedent(f"""
        import sys, time
        sys.path.insert(0, {str(ROOT / "repro")!r})
        from _mutation_guard import mutated
        with mutated({str(tree)!r}, "src.py", {MUTANT!r}):
            print("mutated", flush=True)
            time.sleep(60)
    """), encoding="utf-8")

    # The context manager closes the pipe before the tmp tree is torn down;
    # Windows will not remove a directory something still holds a handle to.
    with subprocess.Popen([sys.executable, str(script)], stdout=subprocess.PIPE,
                          text=True, encoding="utf-8") as proc:
        assert proc.stdout.readline().strip() == "mutated"
        proc.kill()
        proc.wait(timeout=30)

    # The tree is exactly as the killed run left it.
    assert (tree / "src.py").read_text(encoding="utf-8") == MUTANT
    assert sentinel_path(tree).exists()

    restored = restore_if_interrupted(tree)
    assert restored == "src.py"
    assert (tree / "src.py").read_text(encoding="utf-8") == ORIGINAL
    assert not sentinel_path(tree).exists()


def test_the_recovery_is_reported_not_silent(tree, capsys):
    """A quietly self-healing repair hides that a run was killed at all."""
    sentinel_path(tree).write_text(
        json.dumps({"file": "src.py", "original": ORIGINAL}), encoding="utf-8")
    (tree / "src.py").write_text(MUTANT, encoding="utf-8")

    run_mutations(tree, [], lambda tests: [], ("tests/none.py",))
    out = capsys.readouterr().out
    assert "was killed" in out and "src.py" in out
    assert (tree / "src.py").read_text(encoding="utf-8") == ORIGINAL


def test_nothing_is_reported_when_no_run_was_interrupted(tree, capsys):
    """Non-vacuity: the notice must not appear on every run."""
    assert restore_if_interrupted(tree) is None
    run_mutations(tree, [], lambda tests: [], ("tests/none.py",))
    assert "was killed" not in capsys.readouterr().out


def test_a_damaged_sentinel_stops_everything_rather_than_guessing(tree):
    """Half a record of the original is not something to improvise around."""
    sentinel_path(tree).write_text("{not json", encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        restore_if_interrupted(tree)
    assert "cannot be read" in str(e.value)


def test_the_sentinel_is_on_disk_before_the_file_is_touched(tree):
    """The ordering is the whole mechanism.

    Written after, a kill in the gap loses the original entirely.
    """
    order = []
    real_write = Path.write_text

    def spy(self, data, *a, **k):
        if self.name in ("src.py", SENTINEL_NAME, SENTINEL_NAME + ".tmp"):
            order.append(self.name)
        return real_write(self, data, *a, **k)

    import _mutation_guard as g
    orig_ws = g._write_sentinel
    g._write_sentinel = lambda root, rel, original: (
        order.append(SENTINEL_NAME), orig_ws(root, rel, original))[1]
    try:
        Path.write_text = spy
        with mutated(tree, "src.py", MUTANT):
            pass
    finally:
        Path.write_text = real_write
        g._write_sentinel = orig_ws
    assert order.index(SENTINEL_NAME) < order.index("src.py"), order


# ---------------------------------------------------------------------------
# every harness must actually use it
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("harness", sorted(
    p.name for p in (ROOT / "repro").glob("mutate_*.py")))
def test_every_harness_goes_through_the_guard(harness):
    """One unguarded harness is enough to leave the tree mutated."""
    src = (ROOT / "repro" / harness).read_text(encoding="utf-8")
    assert "run_mutations" in src, f"{harness} does not use the shared runner"
    assert "_mutation_guard" in src


def test_there_is_more_than_one_harness_to_check():
    """Guard the guard: a glob that matched nothing would pass silently."""
    assert len(list((ROOT / "repro").glob("mutate_*.py"))) >= 5


def test_no_sentinel_is_left_in_the_repository():
    """If this fails, a harness died mid-run and the tree may be mutated."""
    assert not sentinel_path(ROOT).exists(), (
        "a mutation run was interrupted — run any repro/mutate_*.py to restore")
