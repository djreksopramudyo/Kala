"""
Run DEPLOY_CHECKLIST.md's mechanical checks in one command.

Read-only: nothing here writes a file, sends a message, or spends money.
Run it on the machine that actually runs the bot — checking your laptop tells
you nothing about your VPS.

Usage:
    python preflight.py
    python preflight.py --config runner_config.json --state paper_state.json
    python preflight.py --skip-timers        # not on the deployment host

Exit code is 0 when nothing FAILED (warnings still exit 0), 1 otherwise, so
it can gate a deploy script.
"""

from __future__ import annotations

import argparse
import json
import sys

from kala.preflight import format_checks, load_json, run_all


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="runner_config.json")
    ap.add_argument("--state", default="paper_state.json")
    ap.add_argument("--skip-timers", action="store_true",
                    help="skip the systemd unit checks")
    args = ap.parse_args(argv)

    loaded = {}
    for label, path in (("config", args.config), ("state", args.state)):
        try:
            loaded[label] = load_json(path)
        except json.JSONDecodeError as e:
            # A corrupt file is itself the finding — the bot would otherwise
            # fail at startup with a much less obvious error than this. Name
            # the file that is actually broken, not whichever was read first.
            print(f"❌ {path} is not valid JSON: {e}", file=sys.stderr)
            return 1
    cfg, state = loaded["config"], loaded["state"]

    checks = run_all(cfg, state, skip_timers=args.skip_timers)
    print(format_checks(checks))
    return 1 if any(c.failed for c in checks) else 0


if __name__ == "__main__":
    sys.exit(main())
