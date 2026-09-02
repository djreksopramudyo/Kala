"""No text I/O may rely on the platform's default encoding.

`Path.read_text()` and `open()` without `encoding=` use the locale codepage.
That is UTF-8 on this project's Linux CI and cp1252 on the Windows machine the
author actually runs it on, so identical code passes in one place and raises in
the other:

    UnicodeDecodeError: 'charmap' codec can't decode byte 0x8f in position 7618

The byte was a warning emoji in `daily_run.py`, read by two tests that check
its source. Same class as the `pytest` vs `python -m pytest` split found the
same day: code written against one environment's defaults.

`subprocess.run(..., text=True)` is the same hazard twice over — the parent
decodes with the locale codepage AND a Python child encodes its stdout with
one, so the two can disagree even when each is individually "fine".

The whole suite passes under `-X warn_default_encoding -W error::EncodingWarning`.
This test is the cheap always-on version of that check: it scans source, so a
regression fails at the line that introduced it rather than only on Windows.
"""

from __future__ import annotations

import io
import re
import sys
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {"__pycache__", ".venv", "venv", ".git", ".pytest_cache", "results",
             "deploy", "repro"}

# Binary modes never take an encoding, and neither does a path-only read.
_TEXT_IO = re.compile(r"\.(read_text|write_text)\(")
_OPEN = re.compile(r"(?<![.\w])open\(")
_SUBPROC_TEXT = re.compile(r"text=True")


def _sources() -> list[Path]:
    return [p for p in sorted(ROOT.rglob("*.py"))
            if not any(part in SKIP_DIRS for part in p.relative_to(ROOT).parts)]


def _code_only(text: str) -> str:
    """Blank out comments and string literals, keeping byte offsets.

    Without this the scanner matches its own docstring — and every other
    module's prose about encodings — which would make it noisy enough to be
    switched off, which is how guards die.
    """
    out = list(text)
    try:
        toks = tokenize.generate_tokens(io.StringIO(text).readline)
        for tok in toks:
            if tok.type not in (tokenize.STRING, tokenize.COMMENT):
                continue
            (r1, c1), (r2, c2) = tok.start, tok.end
            lines = text.splitlines(keepends=True)
            begin = sum(len(x) for x in lines[:r1 - 1]) + c1
            end = sum(len(x) for x in lines[:r2 - 1]) + c2
            for i in range(begin, min(end, len(out))):
                if out[i] != "\n":
                    out[i] = " "
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return text          # unparseable: scan it raw rather than skip it
    return "".join(out)


def _call_args(line: str, start: int) -> str:
    """The argument text of the call opening at ``start``, paren-balanced."""
    depth, i = 0, start
    while i < len(line):
        if line[i] == "(":
            depth += 1
        elif line[i] == ")":
            depth -= 1
            if depth == 0:
                return line[start:i + 1]
        i += 1
    return line[start:]          # continues on the next line; caller handles it


def _offenders(pattern: re.Pattern, extra_ok=()) -> list[str]:
    bad = []
    for path in _sources():
        text = _code_only(path.read_text(encoding="utf-8"))
        for m in pattern.finditer(text):
            args = _call_args(text, text.index("(", m.start()))
            if "encoding=" in args or any(k in args for k in extra_ok):
                continue
            line_no = text[:m.start()].count("\n") + 1
            snippet = text[m.start():m.start() + 60].split("\n")[0]
            bad.append(f"{path.relative_to(ROOT)}:{line_no}: {snippet}")
    return bad


def test_no_read_text_or_write_text_without_an_encoding():
    bad = _offenders(_TEXT_IO)
    assert not bad, ("these use the platform default encoding:\n  "
                     + "\n  ".join(bad))


def test_no_text_mode_open_without_an_encoding():
    # "b" covers rb/wb/ab and any binary mode, which take no encoding.
    bad = _offenders(_OPEN, extra_ok=('"rb"', "'rb'", '"wb"', "'wb'",
                                      '"ab"', "'ab'", 'b"', "b'"))
    assert not bad, ("these open() calls use the platform default encoding:\n  "
                     + "\n  ".join(bad))


_SUBPROC_CALL = re.compile(
    r"subprocess\.(?:run|Popen|check_output|check_call|call)\s*\(")


def test_no_subprocess_text_mode_without_an_encoding():
    bad = []
    for path in _sources():
        text = _code_only(path.read_text(encoding="utf-8"))
        calls = [(mm.end() - 1, mm.start()) for mm in _SUBPROC_CALL.finditer(text)]
        for m in _SUBPROC_TEXT.finditer(text):
            # The ENCLOSING call, not merely the nearest "subprocess." token.
            #
            # This used to back up to the nearest `subprocess.` within 400
            # characters, which lands on `subprocess.PIPE` for the extremely
            # ordinary `subprocess.Popen(..., stdout=subprocess.PIPE,
            # text=True, encoding="utf-8")`. The scan then read the wrong
            # argument list, found no encoding=, and reported a CORRECT call as
            # a violation. A guard that accuses working code is the one people
            # learn to silence.
            args = None
            for paren, start in calls:
                if start > m.start():
                    break
                span = _call_args(text, paren)
                if paren < m.start() <= paren + len(span) + 1:
                    args = span
            if args is None or "encoding=" in args:
                continue
            line_no = text[:m.start()].count("\n") + 1
            bad.append(f"{path.relative_to(ROOT)}:{line_no}")
    assert not bad, ("subprocess text=True without encoding= — parent and child "
                     "can disagree on Windows:\n  " + "\n  ".join(bad))


def test_the_scanner_actually_scans_something():
    """Non-vacuity: an empty file list would make all three tests pass."""
    srcs = _sources()
    assert len(srcs) > 50, len(srcs)
    names = {p.name for p in srcs}
    for expected in ("daily_run.py", "conftest.py"):
        assert expected in names


def test_the_scanner_detects_a_real_offender(tmp_path, monkeypatch):
    """A guard that cannot fail is not a guard — prove it fires."""
    offender = tmp_path / "bad_module.py"
    offender.write_text("from pathlib import Path\n"
                        "x = Path('a.txt').read_text()\n", encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "ROOT", tmp_path)
    bad = _offenders(_TEXT_IO)
    assert any("bad_module.py" in b for b in bad), bad



def test_the_subprocess_scan_reads_the_enclosing_call_not_the_nearest_token():
    """`stdout=subprocess.PIPE` used to defeat the backwards search.

    The scan backed up to the nearest `subprocess.` and landed on `PIPE`, then
    parsed the wrong argument list and reported a correct call as a violation.
    A guard that accuses working code teaches people to silence it.
    """
    good = ('import subprocess\n'
            'p = subprocess.Popen(["x"], stdout=subprocess.PIPE,\n'
            '                     text=True, encoding="utf-8")\n')
    bad = ('import subprocess\n'
           'p = subprocess.Popen(["x"], stdout=subprocess.PIPE,\n'
           '                     text=True)\n')

    def offenders(src):
        text = _code_only(src)
        calls = [(mm.end() - 1, mm.start()) for mm in _SUBPROC_CALL.finditer(text)]
        hits = []
        for m in _SUBPROC_TEXT.finditer(text):
            args = None
            for paren, start in calls:
                if start > m.start():
                    break
                span = _call_args(text, paren)
                if paren < m.start() <= paren + len(span) + 1:
                    args = span
            if args is None or "encoding=" in args:
                continue
            hits.append(m.start())
        return hits

    assert offenders(good) == [], "a correct call was reported as a violation"
    assert offenders(bad), "non-vacuity: a real offender must still be caught"
