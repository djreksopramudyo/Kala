#!/usr/bin/env python3
"""Are you trading the strategy you tested?

Reads the paper log and reports who actually closed each position — the holding
limit, an engine exit rule, or you — and what the hand-closed ones would have
returned had they been held to the configured limit instead.

Run it monthly during a forward test. Its job is to catch the failure mode that
P&L cannot: a strategy that never got run, reported as a strategy that did not
work.

    python discipline_report.py                    # who closed what
    python discipline_report.py --counterfactual   # plus the cost of deviating
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from kala.config import CostModel, config_for_profile
from kala.discipline import (
    MANUAL,
    atr_coverage,
    classify_exit,
    counterfactual_hold,
    format_atr_coverage,
    format_horizon_and_payoff,
    format_report,
    holding_horizon_gap,
    payoff_arithmetic,
    summarise_discipline,
)

STATE_PATH = Path(__file__).resolve().parent / "paper_state.json"
CONFIG_PATH = Path(__file__).resolve().parent / "runner_config.json"


def _holding_days_from_config() -> int:
    """The holding limit the LIVE profile uses, so the counterfactual compares
    against the rule actually in force rather than a hardcoded guess."""
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        cfg = {}
    try:
        return config_for_profile(cfg.get("exit_profile")).backtest.holding_max_days
    except ValueError as e:
        print(f"WARNING: {e}. Falling back to the legacy holding limit.",
              file=sys.stderr)
        return config_for_profile("legacy").backtest.holding_max_days


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--state", default=str(STATE_PATH))
    ap.add_argument("--counterfactual", action="store_true",
                    help="download price history and compute what holding to the "
                         "limit would have returned on the hand-closed trades")
    ap.add_argument("--holding-days", type=int, default=None,
                    help="override the holding limit used for the comparison "
                         "(default: whatever the live exit_profile uses)")
    ap.add_argument("--period", default="2y", help="history to fetch (default 2y)")
    args = ap.parse_args()

    path = Path(args.state)
    if not path.exists():
        print(f"No paper state at {path.resolve()}", file=sys.stderr)
        return 1
    _state = json.loads(path.read_text(encoding="utf-8"))
    log = _state.get("log", [])
    positions = _state.get("positions", {})

    holding = args.holding_days or _holding_days_from_config()
    summary = summarise_discipline(log)

    cf = None
    if args.counterfactual:
        manual = sorted({t["ticker"] for t in log
                         if classify_exit(t.get("reason")) == MANUAL and t.get("ticker")})
        if not manual:
            print("No hand-closed trades to compare.")
        else:
            import yfinance as yf
            print(f"Fetching {len(manual)} ticker(s) for the comparison...")
            hist = {}
            for tk in manual:
                try:
                    d = yf.download(tk, period=args.period, auto_adjust=True,
                                    progress=False)
                    if d is not None and len(d):
                        if hasattr(d.columns, "get_level_values"):
                            d.columns = d.columns.get_level_values(0)
                        hist[tk] = d
                except Exception as e:  # noqa: BLE001 - reported, not swallowed
                    print(f"  {tk}: no history ({e})", file=sys.stderr)
            cf = counterfactual_hold(log, hist, holding_days=holding,
                                     costs=CostModel())

    print()
    print(format_report(summary, cf, holding_days=holding))
    # Break-even arithmetic and the gap to the tested horizon. Both are
    # computed from the log alone, so they work offline and do not depend on
    # --counterfactual having a network.
    print(format_horizon_and_payoff(holding_horizon_gap(log, rule_days=holding),
                                    payoff_arithmetic(log)))
    print(format_atr_coverage(atr_coverage(positions)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
