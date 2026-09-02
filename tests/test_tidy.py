"""Tests for tidy_repo — the plan must be conservative: archive only old
generated output and known stray artifacts, delete only regenerable caches,
and never touch live state, config, or source."""

import time
from pathlib import Path

from tidy_repo import apply_plan, plan_tidy

OLD = time.time() - 90 * 86400
FRESH = time.time() - 2 * 86400


def _touch(path: Path, mtime: float | None = None, content: str = "x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if mtime is not None:
        import os
        os.utime(path, (mtime, mtime))
    return path


def _fake_repo(tmp_path: Path) -> Path:
    _touch(tmp_path / "paper_state.json")
    _touch(tmp_path / "runner_config.json")
    _touch(tmp_path / "daily_run.py")
    _touch(tmp_path / "walkforward_result.txt")
    _touch(tmp_path / "kala_entry_veto_realism.patch")
    _touch(tmp_path / "paper_state_backup_20260709_210202.json")
    _touch(tmp_path / "results" / "old_scan.csv", mtime=OLD)
    _touch(tmp_path / "results" / "fresh_scan.csv", mtime=FRESH)
    _touch(tmp_path / "results" / "daily_run.log", mtime=OLD)
    _touch(tmp_path / "results" / ".walkforward_done_2026Q3", mtime=OLD)
    _touch(tmp_path / "results" / ".backtest_done_202606", mtime=OLD)
    (tmp_path / "kala" / "__pycache__").mkdir(parents=True)
    (tmp_path / ".pytest_cache").mkdir()
    (tmp_path / ".venv" / "lib" / "__pycache__").mkdir(parents=True)
    return tmp_path


def test_plan_archives_only_old_results_and_known_artifacts(tmp_path):
    root = _fake_repo(tmp_path)
    plan = plan_tidy(root, age_days=30)
    archived = {src.name for kind, src, _ in plan if kind == "archive"}
    assert archived == {"old_scan.csv", "walkforward_result.txt",
                        "kala_entry_veto_realism.patch",
                        "paper_state_backup_20260709_210202.json"}


def test_plan_never_touches_live_state_config_source_or_markers(tmp_path):
    root = _fake_repo(tmp_path)
    touched = {src.name for _, src, _ in plan_tidy(root, age_days=30)}
    for protected in ("paper_state.json", "runner_config.json", "daily_run.py",
                      "daily_run.log", ".walkforward_done_2026Q3",
                      ".backtest_done_202606", "fresh_scan.csv"):
        assert protected not in touched


def test_plan_deletes_caches_but_not_inside_venv(tmp_path):
    root = _fake_repo(tmp_path)
    deleted = [src for kind, src, _ in plan_tidy(root) if kind == "delete"]
    assert any(d.name == "__pycache__" and ".venv" not in d.parts for d in deleted)
    assert any(d.name == ".pytest_cache" for d in deleted)
    assert not any(".venv" in d.parts for d in deleted)


def test_apply_moves_and_deletes_exactly_the_plan(tmp_path):
    root = _fake_repo(tmp_path)
    apply_plan(plan_tidy(root, age_days=30))
    assert not (root / "results" / "old_scan.csv").exists()
    assert (root / "results" / "archive" / "old_scan.csv").exists()   # moved, not deleted
    assert (root / "results" / "fresh_scan.csv").exists()
    assert (root / "paper_state.json").exists()
    assert not (root / "kala" / "__pycache__").exists()
    assert (root / ".venv" / "lib" / "__pycache__").exists()


def test_apply_never_overwrites_existing_archive(tmp_path):
    root = _fake_repo(tmp_path)
    _touch(root / "results" / "archive" / "old_scan.csv", content="earlier archive")
    apply_plan(plan_tidy(root, age_days=30))
    assert (root / "results" / "archive" / "old_scan.csv").read_text(encoding="utf-8") == "earlier archive"
    assert (root / "results" / "archive" / "old_scan_1.csv").exists()
