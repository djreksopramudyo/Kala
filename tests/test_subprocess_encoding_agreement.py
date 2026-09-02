"""Parent and child must agree on an encoding, not each pick the locale's.

Reproduced from the Windows failure this test exists because of:

    UnicodeDecodeError: 'utf-8' codec can't decode byte 0x97 in position 1607
    TypeError: argument of type 'NoneType' is not iterable

0x97 is an em-dash in cp1252. The first fix pinned only the PARENT's decoder
(`encoding="utf-8"`), which made things worse rather than better: previously
both ends used cp1252 and agreed by accident; afterwards the child still
encoded its stdout with the Windows codepage while the parent decoded UTF-8.
`--help` output is full of em-dashes from this project's docstrings, so every
subprocess test broke.

Worse, the decode failure happens on subprocess's reader THREAD, so `stdout`
comes back as None and the test dies with `TypeError: NoneType is not
iterable` — an error that names nothing about encodings at all.

Two things are needed and the first fix only did one:
  * PYTHONIOENCODING in the child, so it encodes what the parent decodes;
  * errors="replace", so a surprise can never produce stdout=None and a
    misleading TypeError instead of a readable assertion.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# A child that prints an em-dash, like every --help in this project.
CHILD = "import sys; print('exit-profile — legacy or forward_test')"


def test_the_mismatch_is_real_and_reproduces_here():
    """Force the child to emit cp1252 while the parent decodes UTF-8.

    This is the Windows default pairing, made explicit so it fails on Linux
    too. Without it the fix below would be untested on this machine.
    """
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "cp1252"          # what Windows does implicitly
    try:
        out = subprocess.run([sys.executable, "-c", CHILD], capture_output=True,
                             text=True, encoding="utf-8", env=env)
    except UnicodeDecodeError:
        return                       # raised outright -- the bug, most directly
    # Otherwise the decode died on subprocess's reader thread (stdout is None,
    # which is what produced the TypeError on Windows) or the em-dash is
    # mangled. All three are the bug; none is a clean read.
    assert out.stdout is None or "—" not in out.stdout


def test_pinning_the_child_encoding_fixes_it():
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    out = subprocess.run([sys.executable, "-c", CHILD], capture_output=True,
                         text=True, encoding="utf-8", errors="replace", env=env)
    assert out.stdout is not None
    assert "—" in out.stdout               # the em-dash survives intact


def test_errors_replace_turns_a_surprise_into_a_readable_result():
    """Even with a mismatch, the caller gets a string rather than None."""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "cp1252"
    out = subprocess.run([sys.executable, "-c", CHILD], capture_output=True,
                         text=True, encoding="utf-8", errors="replace", env=env)
    assert out.stdout is not None               # never None -> never TypeError
    assert "exit-profile" in out.stdout         # the ASCII part is still usable


# ---- and the same discipline everywhere it matters ------------------------

SUBPROCESS_MODULES = ("tests/test_cli_flag_parity.py",
                      "tests/test_walkforward_exit_profile.py",
                      "tests/test_state_files_are_durable.py",
                      "tests/test_pytest_invocation_parity.py")


def _calls(text: str):
    """Every subprocess.run(...) call's argument text, paren-balanced."""
    for m in re.finditer(r"subprocess\.run\(", text):
        start = text.index("(", m.start())
        depth, i = 0, start
        while i < len(text):
            if text[i] == "(":
                depth += 1
            elif text[i] == ")":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        yield text[start:i + 1]


@pytest.mark.parametrize("module", SUBPROCESS_MODULES)
def test_every_subprocess_call_pins_both_ends(module):
    text = (ROOT / module).read_text(encoding="utf-8")
    calls = list(_calls(text))
    assert calls, f"{module} was listed as shelling out but has no calls"
    for call in calls:
        assert "encoding=" in call, f"{module}: parent decoder not pinned:\n{call}"
        assert "env=" in call, f"{module}: child encoder not pinned:\n{call}"
        assert "errors=" in call, (
            f"{module}: without errors= a decode failure yields stdout=None "
            f"and a TypeError that names nothing:\n{call}")


@pytest.mark.parametrize("module", SUBPROCESS_MODULES)
def test_the_helper_actually_sets_pythonioencoding(module):
    text = (ROOT / module).read_text(encoding="utf-8")
    # Match the ASSIGNMENT, not the word. An earlier version of this assertion
    # found "PYTHONIOENCODING" in the helper's own docstring and read the prose
    # after it -- the same match-the-comment mistake as the encoding scanner.
    assert re.search(r'\[["\']PYTHONIOENCODING["\']\]\s*=\s*["\']utf-8["\']',
                     text), f"{module} never assigns PYTHONIOENCODING=utf-8"
