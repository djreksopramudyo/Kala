"""`pytest` and `python -m pytest` must collect the same suite.

They did not. `python -m pytest` prepends the current directory to sys.path;
the bare `pytest` console script does not, and pytest's default import mode
adds the TEST file's directory rather than the repository root. Two modules
imported `kala` / `archive_sentiment` at module scope and so raised
ModuleNotFoundError under the bare form only:

    python -m pytest -q   ->  1700 passed
    pytest -q             ->  ModuleNotFoundError: No module named 'kala'

The failure names the missing module, which points at a broken install rather
than at the invocation — an expensive place to start debugging. A root
conftest.py fixes both forms; this test is what stops it regressing, because
the whole suite passing under one form says nothing about the other.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# The two that actually broke, plus one newer module that always worked —
# so a regression that somehow only affects the old style still shows up.
MODULES = ("tests/test_alpha_watchlist.py",
           "tests/test_archive_sentiment.py",
           "tests/test_state_files_are_durable.py")



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

def _console_script() -> str | None:
    """THIS environment's `pytest` executable, next to the interpreter running
    the test — not whatever `pytest` PATH happens to resolve to, which in a
    subprocess can be a different install without the project's dependencies
    and would fail for a reason that has nothing to do with sys.path."""
    bindir = Path(sys.executable).parent
    for name in ("pytest", "pytest.exe"):          # posix, windows
        cand = bindir / name
        if cand.exists():
            return str(cand)
    return None


def test_the_root_conftest_exists_and_inserts_the_repo_root():
    conftest = ROOT / "conftest.py"
    assert conftest.exists(), "root conftest.py is what makes bare pytest work"
    body = conftest.read_text(encoding="utf-8")
    assert "sys.path.insert" in body
    assert "Path(__file__).resolve().parent" in body


@pytest.mark.parametrize("module", MODULES)
def test_bare_pytest_can_collect_every_module(module):
    """Run the console script, not `python -m`, from the repo root."""
    script = _console_script()
    if script is None:
        pytest.skip("no pytest console script beside this interpreter")
    # _utf8_env() also drops PYTHONPATH: inheriting one would import the repo
    # for the wrong reason and the test would pass without conftest.py doing
    # anything at all.
    out = subprocess.run(
        [script, "--collect-only", "-q", "-p", "no:cacheprovider", module],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", env=_utf8_env(),
        errors="replace")
    assert out.returncode == 0, (
        f"bare `pytest` cannot collect {module}:\n{out.stdout[-1500:]}\n"
        f"{out.stderr[-500:]}")
    # Non-vacuity: returncode 0 with "0 tests collected" would otherwise pass.
    # (Do NOT scan stdout for the word "error" — collected test NAMES contain
    #  it, e.g. test_main_returns_error_when_no_tickers.)
    m = re.search(r"(\d+) tests? collected", out.stdout)
    assert m and int(m.group(1)) > 0, out.stdout[-800:]


@pytest.mark.parametrize("module", MODULES)
def test_python_dash_m_pytest_can_collect_every_module(module):
    out = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q",
         "-p", "no:cacheprovider", module],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", env=_utf8_env(),
        errors="replace")
    assert out.returncode == 0, (
        f"`python -m pytest` cannot collect {module}:\n{out.stdout[-1500:]}")
    m = re.search(r"(\d+) tests? collected", out.stdout)
    assert m and int(m.group(1)) > 0, out.stdout[-800:]
