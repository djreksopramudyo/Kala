"""Make the repository root importable no matter how pytest is invoked.

WHY THIS FILE EXISTS
--------------------
``python -m pytest`` prepends the current directory to ``sys.path``; the bare
``pytest`` console script does not. With pytest's default import mode the
directory that gets added is the TEST file's directory (``tests/``), not the
repository root — so ``import kala`` and ``import archive_sentiment``
resolve under one invocation and raise ModuleNotFoundError under the other:

    python -m pytest -q     ->  1700 passed
    pytest -q               ->  ModuleNotFoundError: No module named 'kala'

Two test modules relied on the first form without saying so, and the failure
names the module rather than the invocation, which points at the wrong thing
entirely. pytest loads a root ``conftest.py`` before collecting anything, so
putting the path insertion here fixes both forms permanently and removes the
need for every test file to repeat it.

(The newer test modules each insert ROOT themselves. That is now redundant and
is left alone — it is harmless, and it is what let them pass under both forms
while the older two did not.)
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
