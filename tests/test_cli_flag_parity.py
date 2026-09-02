"""Both research entry points share fetch(), so they must share its flags.

Three times now a documented command has failed on an unrecognised argument
because a flag was added to one script and not the other. The failure is loud,
which is the good case — but it wastes a run, and on a long download that is
expensive. Pin the invariant instead of remembering it.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ("run_walkforward.py", "diagnose_exit_param_sweep.py")

# Flags that belong to the shared fetch() path — if fetch() grows an argument,
# every script that calls it should be able to reach it.
FETCH_FLAGS = ("--warehouse", "--min-price", "--period", "--trust-short-cache",
               "--tickers", "--max-tickers")



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

def _help(script: str) -> str:
    out = subprocess.run([sys.executable, str(ROOT / script), "--help"],
                         capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT),
        env=_utf8_env(), errors="replace")
    assert out.returncode == 0, out.stderr
    return out.stdout


@pytest.mark.parametrize("script", SCRIPTS)
@pytest.mark.parametrize("flag", FETCH_FLAGS)
def test_every_fetch_flag_is_reachable_from_both_scripts(script, flag):
    assert flag in _help(script), (
        f"{script} calls fetch() but does not expose {flag} — a documented "
        "command using it will fail on an unrecognised argument")


def test_trust_short_cache_actually_reaches_fetch():
    """Exposing the flag is not the same as wiring it."""
    src = (ROOT / "run_walkforward.py").read_text(encoding="utf-8")
    assert "trust_short_cache=args.trust_short_cache" in src

    sweep = (ROOT / "diagnose_exit_param_sweep.py").read_text(encoding="utf-8")
    assert "trust_short_cache=args.trust_short_cache" in sweep
