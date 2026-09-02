"""Documented claims must not drift away from the repository they describe.

Finding 18 was a printed instruction whose own output the printer would then
reject, found by RUNNING the instruction rather than reading it. The documents
are the same risk at larger scale: 6,600 lines of CHANGES.md and
PROJECT_STATUS.md, with a summary quoting counts, filenames and commands from
all of it, every figure synced by hand.

`check_docs.py` is that check. These tests exercise it — including, for each
check, a deliberately broken input, because a consistency checker that can only
ever pass is the most reassuring kind of nothing.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import check_docs  # noqa: E402


@pytest.fixture
def fake_root(tmp_path, monkeypatch):
    """A repository of one or two scripts, so the checker's own logic can be
    tested without depending on what happens to be installed here.

    The tests below used to run against the real scripts, and the environment
    decided what they proved: on a machine missing an optional dependency,
    ``--help`` crashed and the assertions passed or failed for reasons that had
    nothing to do with the checker.
    """
    monkeypatch.setattr(check_docs, "ROOT", tmp_path)
    check_docs.script_help.cache_clear()
    check_docs.source_flags.cache_clear()
    yield tmp_path
    check_docs.script_help.cache_clear()
    check_docs.source_flags.cache_clear()


def _script(root: Path, name: str, body: str) -> None:
    (root / name).write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")


WORKING = """
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--period")
    p.parse_args()
"""

# Imports something that is not there, exactly like a study script on a machine
# without pyportfolioopt — and still NAMES its real flags in its own source.
CRASHING = """
    import no_such_module_anywhere
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--period")
    p.parse_args()
"""


# ---------------------------------------------------------------------------
# the repository as it stands
# ---------------------------------------------------------------------------

def test_no_documented_claim_contradicts_the_repository():
    r = subprocess.run([sys.executable, "check_docs.py"], cwd=ROOT,
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    out = r.stdout + r.stderr
    # 0 = everything checked and clean. 2 = clean as far as it got, but some
    # script would not run here; that is an environment gap, not a wrong
    # document, and the run says which script and why.
    assert "PROBLEM(S)" not in out, out
    assert r.returncode in (0, 2), out
    if r.returncode == 2:
        assert "COULD NOT BE RUN" in out or "UNVERIFIED" in out, out


def test_it_actually_checks_a_meaningful_number_of_commands():
    """Guard the guard: a regex that matched nothing would pass silently."""
    rep = check_docs.check_commands(check_docs.docs())
    assert rep.problems == []
    total = rep.n_checked + rep.n_from_source
    assert total >= 20, f"only {total} commands found — the extractor is broken"


def test_it_reads_more_than_one_document():
    assert len(check_docs.docs()) >= 5


# ---------------------------------------------------------------------------
# each check, against something deliberately wrong
# ---------------------------------------------------------------------------

def test_a_wrong_line_count_is_caught():
    good = (ROOT / "AUDIT_SUMMARY.md").read_text(encoding="utf-8")
    import re
    broken = re.sub(r"`CHANGES\.md` \([\d,]+ lines\)",
                    "`CHANGES.md` (99,999 lines)", good, count=1)
    assert broken != good
    problems = check_docs.check_line_counts(broken)
    assert any("CHANGES.md" in p and "99,999" in p for p in problems), problems


def test_a_missing_line_count_is_caught():
    """Deleting the claim must not read as the claim being satisfied."""
    assert check_docs.check_line_counts("nothing here at all")


def test_a_wrong_test_file_count_is_caught():
    broken = "| Tests passing | 2,051 (2 skipped, 9999 files) |"
    problems = check_docs.check_test_counts(broken)
    assert any("9999" in p for p in problems), problems


def test_a_missing_test_count_claim_is_caught():
    """Deleting the claim must not read as the claim being satisfied.

    Found by mutation: the line-count check had this guard and the test-count
    check did not, so removing the claim entirely made the checker pass.
    """
    assert check_docs.check_test_counts("no counts in here")


def test_a_broken_path_reference_is_caught():
    problems = check_docs.check_path_references(
        {"FAKE.md": "see `repro/does_not_exist.py` for details"})
    assert any("does_not_exist" in p for p in problems), problems


def test_a_real_path_reference_passes():
    """Non-vacuity: it must not flag files that are there."""
    assert check_docs.check_path_references(
        {"FAKE.md": "see `repro/fold_concentration.py`"}) == []


def test_an_unknown_flag_in_a_documented_command_is_caught(fake_root):
    _script(fake_root, "real.py", WORKING)
    rep = check_docs.check_commands(
        {"FAKE.md": "run `python real.py --not-a-real-flag 3`"})
    assert rep.n_checked == 1
    assert any("--not-a-real-flag" in p for p in rep.problems), rep.problems


def test_a_documented_command_for_a_missing_script_is_caught(fake_root):
    rep = check_docs.check_commands(
        {"FAKE.md": "run `python no_such_script.py --period 5y`"})
    assert any("does not exist" in p for p in rep.problems), rep.problems


def test_a_real_command_passes(fake_root):
    """Non-vacuity again — and this is the exact shape of finding 18."""
    _script(fake_root, "real.py", WORKING)
    rep = check_docs.check_commands({"FAKE.md": "`python real.py --period 8y`"})
    assert rep.n_checked == 1 and rep.problems == [] and rep.unverified == []


def test_an_illustrative_command_name_is_exempt_but_nothing_else_is(fake_root):
    """`python foo.py --flag` in prose describes a shape, not a command.

    The first version of this checker flagged three of those in its own
    release notes. The fix is an explicit exemption, not prose contorted to
    satisfy a regex — and it must stay narrow.
    """
    ok = check_docs.check_commands(
        {"FAKE.md": "every documented `python foo.py --flag` command"})
    assert ok.problems == [] and ok.n_checked == 0, "the placeholder was counted"
    bad = check_docs.check_commands({"FAKE.md": "`python bar.py --flag`"})
    assert any("does not exist" in p for p in bad.problems), bad.problems


def test_hand_parsed_flags_are_exempt_but_only_by_name(fake_root, monkeypatch):
    """The escape hatch must not become a blanket exemption for the script."""
    _script(fake_root, "manual.py", WORKING)
    monkeypatch.setattr(check_docs, "HAND_PARSED",
                        {("manual.py", "--capital"): "parsed inline"})
    ok = check_docs.check_commands({"FAKE.md": "`python manual.py --capital 3e6`"})
    assert ok.problems == []
    bad = check_docs.check_commands({"FAKE.md": "`python manual.py --made-up 1`"})
    assert any("--made-up" in p for p in bad.problems), bad.problems


def test_the_hand_parsed_escape_hatch_is_empty():
    """Every entry it ever held was a script that would not describe its own
    flag and swallowed `--help`. An exemption is a place a real error hides."""
    assert check_docs.HAND_PARSED == {}, (
        "a new exemption was added — it needs a reason in the source and a "
        "check that the flag is not simply undocumented")


# ---------------------------------------------------------------------------
# a script that will not run has said NOTHING about its flags
# ---------------------------------------------------------------------------
#
# The checker ran each script's `--help` and read stdout+stderr as the flag
# list, without looking at the exit status. On a machine without pyportfolioopt
# the four study scripts print a traceback instead of a usage line, and every
# documented flag came back as
#
#     PROJECT_STATUS.md: `python weighting_study.py --period` — weighting_study
#     .py does not accept --period
#
# — seventeen of them, all false, all accusing working code. It is this audit's
# own signature defect (a failure rendering as an ordinary negative result)
# committed by the tool written to find it.

def test_a_script_that_cannot_run_is_not_reported_as_rejecting_its_flags(fake_root):
    _script(fake_root, "crasher.py", CRASHING)
    rep = check_docs.check_commands({"FAKE.md": "`python crasher.py --period 8y`"})
    assert rep.problems == [], rep.problems
    assert rep.unverified == [], rep.unverified
    assert rep.n_checked == 0 and rep.n_from_source == 1
    assert "crasher.py" in rep.unrunnable
    assert "no_such_module_anywhere" in rep.unrunnable["crasher.py"]


def test_the_reason_a_script_would_not_run_is_reported_not_swallowed(fake_root):
    """"It could not be checked" is a result. Silence is the bug."""
    _script(fake_root, "crasher.py", CRASHING)
    rep = check_docs.check_commands({"FAKE.md": "`python crasher.py --period 8y`"})
    why = rep.unrunnable["crasher.py"]
    assert "--help exited" in why and "ModuleNotFoundError" in why, why


def test_a_flag_absent_from_an_unrunnable_scripts_source_is_unverified_not_clean(fake_root):
    """The other half: falling back to source text must not pass everything.

    A flag named nowhere in a script that would not run is an open question —
    reported as unverified, which exits 2, rather than either an accusation or
    a silent pass.
    """
    _script(fake_root, "crasher.py", CRASHING)
    rep = check_docs.check_commands({"FAKE.md": "`python crasher.py --invented 1`"})
    assert rep.problems == []
    assert any("--invented" in u for u in rep.unverified), rep.unverified


def test_a_timeout_is_a_failure_to_check_not_an_empty_flag_list(fake_root, monkeypatch):
    """`--help` that never returns used to yield "" — in which no flag appears,
    so every documented flag on that script was reported as rejected."""
    _script(fake_root, "slow.py", WORKING)

    def boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="slow.py", timeout=300)

    monkeypatch.setattr(check_docs.subprocess, "run", boom)
    check_docs.script_help.cache_clear()
    rep = check_docs.check_commands({"FAKE.md": "`python slow.py --period 8y`"})
    assert rep.problems == []
    assert "did not finish" in rep.unrunnable["slow.py"]


@pytest.mark.parametrize("report,expected", [
    ({}, 0),
    ({"problems": ["a claim the repo contradicts"]}, 1),
    ({"unverified": ["a claim nothing could settle"]}, 2),
    ({"unrunnable": {"study.py": "--help exited 1: ModuleNotFoundError"}}, 2),
])
def test_the_exit_status_says_which_of_the_three_outcomes_happened(
        monkeypatch, capsys, report, expected):
    """0 clean, 1 contradicted, 2 incomplete.

    A run that could not check something must not exit the same way as a run
    that checked it and found nothing wrong. That collapse is what let 39
    documented commands go unexamined while the checker printed a tidy summary
    line about them.
    """
    monkeypatch.setattr(sys, "argv", ["check_docs.py"])
    monkeypatch.setattr(check_docs, "docs", lambda: {"A.md": ""})
    monkeypatch.setattr(check_docs, "check_line_counts", lambda s: [])
    monkeypatch.setattr(check_docs, "check_test_counts", lambda s: [])
    monkeypatch.setattr(check_docs, "check_path_references", lambda d: [])
    monkeypatch.setattr(check_docs, "check_commands", lambda d: check_docs.CommandReport(
        list(report.get("problems", ())), list(report.get("unverified", ())),
        1, 0, dict(report.get("unrunnable", {}))))
    assert check_docs.main() == expected
    if expected == 2:
        out = capsys.readouterr().out
        assert "COULD NOT BE RUN" in out or "UNVERIFIED" in out, out


# ---------------------------------------------------------------------------
# the flag that needed the exemption turned out to be silently ignorable
# ---------------------------------------------------------------------------

def _override(*argv):
    import daily_run
    return daily_run.parse_capital_override(list(argv))


def test_the_capital_override_still_works():
    assert _override("--capital", "3000000") == 3_000_000.0
    assert _override("--capital=3000000") == 3_000_000.0
    assert _override() is None


@pytest.mark.parametrize("typo", ["--captial", "-capital", "--Capital",
                                  "--capitol", "--cap"])
def test_a_mistyped_capital_flag_is_refused_not_ignored(typo):
    """The original defect.

    ``if "--capital" in sys.argv`` ran at the STORED capital — 4.7M instead of
    the 3M asked for — with no line in the log mentioning capital at all. The
    only symptom was that evening's position sizing being wrong.
    """
    import daily_run
    with pytest.raises(SystemExit) as e:
        _override(typo, "3000000")
    assert "unknown option" in str(e.value)
    assert isinstance(e.value, daily_run.BadArgument)


def test_the_equals_form_is_not_silently_dropped():
    """Every other script here accepts --flag=value; this one ignored it."""
    assert _override("--capital=250000") == 250_000.0


@pytest.mark.parametrize("argv,fragment", [
    (("--capital",), "needs an amount"),
    (("--capital", "banyak"), "not a number"),
    (("--capital", "0"), "must be positive"),
    (("--capital", "-5"), "must be positive"),
    (("3000000",), "unexpected argument"),
])
def test_an_unusable_capital_argument_raises(argv, fragment):
    with pytest.raises(SystemExit) as e:
        _override(*argv)
    assert fragment in str(e.value)


def test_the_last_capital_wins_rather_than_the_first():
    """Two overrides is a mistake, but a defined one — not the first silently
    beating the second."""
    assert _override("--capital", "1000", "--capital=2000") == 2000.0


# ---------------------------------------------------------------------------
# ...and it could not say what its own flag was
# ---------------------------------------------------------------------------
#
# `daily_run.py --help` hit the unknown-option branch and exited 1. The one
# script here whose only option is hand-typed was the one script that refused to
# describe it — and check_docs.py was reading that refusal AS the help text,
# passing because the word `--capital` appears inside the complaint about
# `--help`. Two defects holding each other up.

@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_daily_run_answers_help_instead_of_refusing_it(flag, capsys):
    import daily_run
    with pytest.raises(SystemExit) as e:
        _override(flag)
    assert e.value.code == 0
    assert not isinstance(e.value, daily_run.BadArgument)
    out = capsys.readouterr().out
    assert "usage:" in out and "--capital" in out


def test_help_does_not_start_the_evening_run(monkeypatch, capsys):
    """`--help` used to be parsed AFTER the screen had already been logged."""
    import daily_run

    def started():
        raise AssertionError("the run began before the command line was read")

    monkeypatch.setattr(daily_run, "load_config", started)
    monkeypatch.setattr(sys, "argv", ["daily_run.py", "--help"])
    with pytest.raises(SystemExit) as e:
        daily_run.main()
    assert e.value.code == 0
    assert "usage:" in capsys.readouterr().out


def test_an_unusable_argument_fails_before_the_run_starts(monkeypatch):
    """A typo'd override used to be caught only after an evening's worth of
    output had been logged — including the expectation block, which then read
    as if it applied to the run that was about to be refused."""
    import daily_run

    def started():
        raise AssertionError("the run began before the command line was read")

    monkeypatch.setattr(daily_run, "load_config", started)
    monkeypatch.setattr(sys, "argv", ["daily_run.py", "--captial", "3000000"])
    with pytest.raises(daily_run.BadArgument) as e:
        daily_run.main()
    assert "unknown option" in str(e.value)
