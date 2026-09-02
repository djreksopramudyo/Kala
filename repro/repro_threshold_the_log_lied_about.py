#!/usr/bin/env python3
"""The daily log printed one entry threshold; the scanner bought at another.

Run it:  python repro/repro_threshold_the_log_lied_about.py

THE TWO LINES
-------------
``daily_run.main`` (unchanged)::

    trade_cfg = config_for_profile(cfg.get("exit_profile"))
    ...
    log("exit profile: FORWARD_TEST — no stop/target/trailing, "
        f"entry score >= {trade_cfg.backtest.score_entry_threshold:.0f}, ...")

``kala_daily_trader.get_live_signal`` (before this fix)::

    buy_threshold = _Config().backtest.score_entry_threshold  # 60, always

``_Config()`` is the bare default. It never read runner_config.json. So under
``exit_profile: forward_test`` the log said 80 on every run and the scanner
labelled everything from 60 upward a BUY — which the paper trader then buys.

WHY IT MATTERS
--------------
The +1.71%/trade headline was measured at baseline threshold 80, over 5,241
trades. A live bot entering at 60 takes trades that measurement does not
contain. The whole of Finding 13 is that the running configuration matches no
measurement; this is one more axis where that was true, and the one the daily
log actively claimed was fine.

The comment above that log line reads: "a strategy change this large must
never be something you have to read the source to discover."
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for candidate in (ROOT, ROOT.parent):
    if (candidate / "kala").is_dir():
        sys.path.insert(0, str(candidate))
        break
else:
    raise SystemExit(
        "cannot find the kala package next to this script — run it from "
        "the project root: python repro/repro_threshold_the_log_lied_about.py")

from kala.config import Config, config_for_profile, live_config  # noqa: E402
from kala_daily_trader import signal_for_score  # noqa: E402

SCORES = [88, 80, 76, 68, 61, 55, 40]


def table(cutoff: float, label: str) -> None:
    print(f"\n  buy cutoff = {cutoff:.0f}   ({label})")
    print("    score  label")
    for s in SCORES:
        sig = signal_for_score(s, cutoff)
        mark = "  <- bought" if sig in ("BUY", "STRONG BUY") else ""
        print(f"    {s:>5}  {sig:<12}{mark}")


def main() -> int:
    print("=" * 74)
    print("WHAT runner_config.json SAYS vs WHAT THE SCANNER DID")
    print("=" * 74)

    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "runner_config.json"
        p.write_text(json.dumps({"exit_profile": "forward_test"}),
                     encoding="utf-8")

        logged = config_for_profile("forward_test").backtest.score_entry_threshold
        old_decided = Config().backtest.score_entry_threshold      # the old line
        new_decided = live_config(p).backtest.score_entry_threshold

        print("\n  runner_config.json : exit_profile = forward_test")
        print(f"  daily_run LOGGED   : entry score >= {logged:.0f}")
        print(f"  scanner USED (old) : {old_decided:.0f}   <-- the defect")
        print(f"  scanner USES (new) : {new_decided:.0f}")

        print(f"\n{'=' * 74}\nTHE TRADES THAT DIFFER\n{'=' * 74}")
        table(old_decided, "old — hardcoded legacy default")
        table(new_decided, "new — resolved from the configured profile")

        print("\n  Every score in 60-79 was entered by a bot whose own log said")
        print("  the cutoff was 80. The +1.71%/trade measurement was taken at")
        print("  80 over 5,241 trades and contains none of them.")

        p.write_text(json.dumps({"daily_capital_idr": 5_000_000}),
                     encoding="utf-8")
        unchanged = live_config(p).backtest.score_entry_threshold
        print(f"\n{'=' * 74}\nNO PROFILE SET — NOTHING CHANGES\n{'=' * 74}")
        print(f"  no exit_profile key -> cutoff {unchanged:.0f}, identical to the")
        print("  hardcoded Config() this replaces. A bot that has not opted in")
        print("  behaves exactly as before, which is the only safe way to ship")
        print("  a change to a live entry rule.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
