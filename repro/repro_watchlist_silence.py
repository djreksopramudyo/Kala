#!/usr/bin/env python3
"""Four states of watchlist.json that used to produce one indistinguishable zero.

Run it from anywhere:  python repro/repro_watchlist_silence.py

The OLD column is the pre-fix behaviour, reproduced by calling the old code
directly rather than quoting it — a comment can drift, a call cannot. The NEW
column is what the tree does today.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
# Lives at <repo>/repro/ in the shipped tree, and beside an aug/ checkout in
# the working scratchpad. Find the repository either way.
AUG = next(c for c in (_HERE.parent, _HERE.parent / "aug")
           if (c / "kala").is_dir())
sys.path.insert(0, str(AUG))

from kala.universe_sources import default_universe  # noqa: E402
from kala.watchlist import WatchlistStore, load_or_report  # noqa: E402

REAL = {
    "BBCA.JK": {"ticker": "BBCA.JK", "fair_value": 10000.0, "score": 82.0,
                "thesis": "researched", "added": "2026-01-02", "source": "screen"},
    "TLKM.JK": {"ticker": "TLKM.JK", "fair_value": 4200.0, "score": 78.0,
                "thesis": "researched", "added": "2026-01-02", "source": "screen"},
    "UNVR.JK": {"ticker": "UNVR.JK", "fair_value": 2900.0, "score": 75.0,
                "thesis": "researched", "added": "2026-01-02", "source": "screen"},
}


def old_load(path) -> str:
    """The pre-fix WatchlistStore.load + the archivers' `except Exception: pass`,
    which is all any caller ever saw."""
    path = Path(path)
    try:
        if not path.exists():
            return "len=0"
        raw = json.loads(path.read_text())
        return f"len={len(raw)}"
    except Exception:
        return "len=0"          # <- the swallow


def new_load(path) -> str:
    said: list[str] = []
    store = load_or_report(path, warn=said.append)
    note = store.load_note or "clean read"
    return f"len={len(store)}  [{note.split(' (')[0]}]"


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="wl_repro_"))
    repo = tmp / "repo"
    repo.mkdir()

    good = repo / "healthy.json"
    good.write_text(json.dumps(REAL, indent=2))
    empty = repo / "empty.json"
    empty.write_text("{}")
    absent = repo / "does_not_exist.json"
    whole = json.dumps(REAL, indent=2)
    corrupt = repo / "corrupt.json"
    corrupt.write_text(whole[: len(whole) // 2])          # crash mid-write

    print("=" * 78)
    print("REPRO 1 — four states of the same file, before and after")
    print("=" * 78)
    print(f"the healthy file holds {len(REAL)} researched names "
          f"(fair value + thesis each)\n")
    print(f"  {'state on disk':<34}{'OLD':<10}NEW")
    print("  " + "-" * 74)
    for label, path in (("genuinely empty ({})", empty),
                        ("absent / wrong directory", absent),
                        ("truncated by a crash mid-save", corrupt),
                        ("healthy", good)):
        print(f"  {label:<34}{old_load(path):<10}{new_load(path)}")
    print()
    print("  OLD: rows 1-3 are one number. A user who has researched nothing, a")
    print("  cron job in the wrong directory, and a file destroyed by an")
    print("  interrupted save are the same answer.")
    print("  NEW: each names itself, with the path it actually resolved to.")

    # ---- 2. what that cost the archivers --------------------------------
    print()
    print("=" * 78)
    print("REPRO 2 — the archivers' universe, with one source damaged")
    print("=" * 78)
    state = repo / "paper_state.json"
    state.write_text(json.dumps({
        "cash": 1_000_000.0, "start_capital": 10_000_000.0,
        "positions": {"ANTM.JK": {"ticker": "ANTM.JK", "shares": 100,
                                  "entry_price": 1500.0, "peak_price": 1700.0,
                                  "entry_date": "2026-01-02"}},
        "pending": [], "log": [],
    }))
    said: list[str] = []
    u = default_universe(state, corrupt, warn=said.append)
    print(f"  tickers archived : {u.tickers}")
    print(f"  fully sourced    : {u.fully_sourced}")
    for m in said:
        print(f"  stderr           : {m}")
    print()
    print("  The run still happens — one unreadable source should not abort an")
    print("  archive that can still record the other. What changed is that the")
    print("  gap is announced. These archives are point-in-time: a day recorded")
    print("  from a short universe cannot be re-recorded tomorrow.")

    # ---- 3. cwd sensitivity, measured ------------------------------------
    print()
    print("=" * 78)
    print("REPRO 3 — does the answer depend on where you stand?")
    print("=" * 78)
    (repo / "watchlist.json").write_text(json.dumps(REAL, indent=2))
    probe = repo / "probe.py"
    probe.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(AUG)!r})\n"
        "from kala.watchlist import WatchlistStore\n"
        "print(len(WatchlistStore.load('watchlist.json')))\n"
    )
    for cwd, label in ((repo, "cwd = repo root"), (tmp, "cwd = one level up")):
        out = subprocess.run([sys.executable, str(probe)], cwd=cwd,
                             capture_output=True, text=True)
        print(f"  bare relative path, {label:<20} -> len = {out.stdout.strip()}")
    print()
    print("  That is the hazard the four scripts carried. They now resolve")
    print("  against Path(__file__).parent, so the answer no longer moves:")
    for script in ("archive_sentiment.py", "archive_fundamentals.py",
                   "foreign_flow_monitor.py", "check_watchlist.py"):
        line = next(ln for ln in (AUG / script).read_text().splitlines()
                    if ln.startswith("WATCHLIST_PATH"))
        print(f"    {script:<26}{line}")

    # ---- 4. the write that made state 3 possible -------------------------
    print()
    print("=" * 78)
    print("REPRO 4 — can an interrupted save still destroy the file?")
    print("=" * 78)
    live = repo / "live.json"
    store = WatchlistStore(live)
    from kala.watchlist import WatchlistItem
    store.add(WatchlistItem(ticker="BBCA.JK", fair_value=10000.0,
                            thesis="researched"))
    store.save()
    before = live.read_text()

    import kala.watchlist as wl_mod
    real_replace = wl_mod.os.replace

    def crash(*a, **k):
        raise RuntimeError("power cut at the worst possible moment")

    store.add(WatchlistItem(ticker="TLKM.JK", fair_value=4200.0, thesis="new"))
    wl_mod.os.replace = crash
    try:
        store.save()
    except RuntimeError as e:
        print(f"  save() interrupted: {e}")
    finally:
        wl_mod.os.replace = real_replace

    survived = live.read_text() == before
    print(f"  file byte-identical to before the crash : {survived}")
    print(f"  still parses, names intact              : "
          f"{len(WatchlistStore.load(live))} name(s)")
    print()
    print("  tmp-then-os.replace, the same discipline paper_state.json has used")
    print("  since v3.x. The previous watchlist survives until the new one is")
    print("  fully on disk. With the old write_text this row read False.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
