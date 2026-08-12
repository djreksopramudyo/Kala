"""
Reset the paper-trading account to a clean starting capital.

Destructive: this discards all open positions, pending orders, and trade
history in paper_state.json. It exists for exactly one situation — starting
an honest new track record (e.g. after a real change to signal logic, so old
trades from a different strategy don't get counted as if they validate the
new one).

Safety:
  * The current paper_state.json is backed up (never silently deleted) to
    paper_state_backup_<timestamp>.json before anything is overwritten.
  * Requires typed confirmation unless --yes is passed. This is a script,
    not a bot command, on purpose — a destructive action like this shouldn't
    be one accidental tap away on a phone.
  * --sync-config also syncs runner_config.json's start_capital_idr and
    daily_capital_idr to the same figure, so those numbers stop lying about
    what the account can actually do. (papertrade.py always clamps the
    day's buy allocation to actual cash regardless of what the config says
    — see PaperTrader.step: `allocation = min(allocation, self.cash)` — but
    the config value is still what /status and the dashboard display, and
    it had drifted to 39,000,000 against ~26,000 in actual cash.)

Usage:
    python reset_paper.py --capital 5000000
    python reset_paper.py --capital 5000000 --sync-config
    python reset_paper.py --capital 5000000 --yes          # skip the prompt
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _summarize(raw: dict) -> str:
    n_pos = len(raw.get("positions", {}))
    tickers = ", ".join(raw.get("positions", {}).keys()) or "none"
    n_log = len(raw.get("log", []))
    return (f"cash={raw.get('cash', 0):,.0f}  start_capital={raw.get('start_capital', 0):,.0f}  "
           f"open_positions={n_pos} ({tickers})  closed_trades_logged={n_log}")


def read_current_state(root: Path = ROOT) -> dict | None:
    """The raw dict currently in paper_state.json, or None if it doesn't
    exist yet. Used by callers (the CLI, the bot's /reset) to show what
    would be discarded BEFORE asking for confirmation."""
    p = root / "paper_state.json"
    return json.loads(p.read_text()) if p.exists() else None


def perform_reset(capital: float, sync_config: bool = True, root: Path = ROOT) -> dict:
    """Do the actual reset: back up the old state (if any), write a fresh
    one, optionally sync the config. No prompting, no printing — the pure
    core both the CLI and the Telegram bot's /reset command call, so a
    single tested implementation backs both entry points.

    Returns {"backed_up_to": str|None, "old_summary": str|None,
             "config_synced": bool}.
    """
    if capital <= 0:
        raise ValueError("capital must be positive")

    state_path = root / "paper_state.json"
    config_path = root / "runner_config.json"

    backed_up_to = None
    old_summary = None
    if state_path.exists():
        raw = json.loads(state_path.read_text())
        old_summary = _summarize(raw)
        backup_path = root / f"paper_state_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        backup_path.write_text(json.dumps(raw, indent=2))
        backed_up_to = backup_path.name

    fresh = {
        "cash": capital,
        "start_capital": capital,
        "positions": {},
        "pending": [],
        "log": [],
        "benchmark_start": None,   # re-recorded automatically on the next run
    }
    state_path.write_text(json.dumps(fresh, indent=2))

    config_synced = False
    if sync_config and config_path.exists():
        cfg = json.loads(config_path.read_text())
        cfg["start_capital_idr"] = capital
        cfg["daily_capital_idr"] = capital
        config_path.write_text(json.dumps(cfg, indent=2))
        config_synced = True

    return {"backed_up_to": backed_up_to, "old_summary": old_summary,
           "config_synced": config_synced}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--capital", type=float, required=True, help="new starting capital, IDR")
    ap.add_argument("--sync-config", action="store_true",
                    help="also set runner_config.json's start_capital_idr and daily_capital_idr to this figure")
    ap.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    args = ap.parse_args()

    if args.capital <= 0:
        print("--capital must be positive.", file=sys.stderr)
        return 1

    raw = read_current_state()
    if raw is not None:
        print(f"Current paper_state.json: {_summarize(raw)}")
    else:
        print("No existing paper_state.json -- this will create a fresh one.")

    print(f"About to reset to: cash=start_capital={args.capital:,.0f} IDR, "
         f"0 positions, 0 pending orders, empty trade log.")
    if not args.yes:
        reply = input("Type 'yes' to confirm: ").strip().lower()
        if reply != "yes":
            print("Aborted -- nothing changed.")
            return 1

    result = perform_reset(args.capital, sync_config=args.sync_config)
    if result["backed_up_to"]:
        print(f"Backed up old state to {result['backed_up_to']}")
    print(f"paper_state.json reset to {args.capital:,.0f} IDR, clean slate.")
    if args.sync_config:
        if result["config_synced"]:
            print(f"runner_config.json start_capital_idr / daily_capital_idr synced to {args.capital:,.0f}")
        else:
            print("runner_config.json not found -- skipped --sync-config.", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
