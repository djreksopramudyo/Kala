#!/usr/bin/env python3
"""A position whose entry date is not a trading bar is held forever, silently.

Run it:  python repro/repro_position_that_never_ages.py

THE MECHANISM
-------------
``papertrade._bars_held`` matched the entry date against the price index by
EXACT date equality and returned a bare ``None`` on any miss. Both callers then
wrote::

    if bars_held is not None and bars_held >= max_days:

so a ``None`` did the same thing as a young position: no exit queued, and no
line in any report. Not in ``exits_queued``, not in ``unevaluated``, not in
``skipped``, not in ``tickets``. The position simply was not there.

WHY THIS IS NOT A CORNER CASE
-----------------------------
Two ordinary routes produce an entry date that is not a bar:

  * ``PaperTrader.manual_buy(ticker, shares, price, date=...)`` accepts any
    date string and validates nothing about it being a trading day.
  * ``daily_run.main()`` has NO trading-day guard. It books fills stamped
    ``today_wib()`` whenever the scheduler fires, and this project has no IDX
    exchange calendar — 2026-05-01 and 2026-08-17 are both market holidays it
    does not know about.

WHY IT MATTERS MOST UNDER THE PROFILE THIS AUDIT RECOMMENDS
-----------------------------------------------------------
Under ``forward_test`` every price-based exit is inert by design, so
``holding_max_days`` is the ONLY rule that closes a position. A position that
cannot be aged under that profile has no exit rule at all — and ``/review``
goes on printing HOLD.

The audit opened with: "it kept on telling me to hold, but then i ended up
only having a profit of less than 1k IDR or even a -5%."
"""

from __future__ import annotations

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
        "the project root: python repro/repro_position_that_never_ages.py")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from kala.config import Config, RiskConfig  # noqa: E402
from kala.papertrade import (  # noqa: E402
    PaperPosition,
    PaperTrader,
    bars_held_or_reason,
)

BARS = 200
MAX_DAYS = 15


def history(n: int = BARS) -> pd.DataFrame:
    c = np.full(n, 1000.0)
    return pd.DataFrame(
        {"Open": c, "High": c * 1.005, "Low": c * 0.995, "Close": c,
         "Volume": np.full(n, 1e6)},
        index=pd.bdate_range("2026-01-05", periods=n))


def forward_test_shape() -> Config:
    """Every price exit inert — holding_max_days is the only rule left."""
    cfg = Config(risk=RiskConfig(trailing_enabled=False, hard_stop_pct=-99.0,
                                 atr_stop_multiple=99.0,
                                 target_profit_pct=999.0,
                                 breakeven_trigger_pct=999.0))
    cfg.backtest.holding_max_days = MAX_DAYS
    return cfg


def old_bars_held(entry_date, hist):
    """The pre-fix implementation, verbatim, so the two can be run side by side."""
    try:
        key = pd.Timestamp(entry_date)
        idx = hist.index
        if getattr(idx, "tz", None) is not None:
            key = key.tz_localize(idx.tz)
        mask = idx.normalize() == key.normalize()
        if not mask.any():
            return None
        return int(len(idx) - 1 - mask.argmax())
    except Exception:
        return None


def main() -> int:
    h = history()
    on_bar = h.index[10].date().isoformat()
    saturday = (h.index[10] + pd.Timedelta(days=5)).date().isoformat()
    assert pd.Timestamp(saturday).weekday() == 5

    print("=" * 76)
    print("THE TWO POSITIONS")
    print("=" * 76)
    print(f"  GOOD.JK  entered {on_bar}  (a Monday — a trading bar)")
    print(f"  GHOST.JK entered {saturday}  (the Saturday five days later)")
    print(f"\n  Identical in every other way. Limit is {MAX_DAYS} bars, and the")
    print(f"  history runs {BARS} bars past the entry. Both are long overdue.")

    print(f"\n{'=' * 76}\nBEFORE — _bars_held matched on EXACT date equality\n{'=' * 76}")
    for name, d in (("GOOD.JK", on_bar), ("GHOST.JK", saturday)):
        print(f"  {name:<9} old _bars_held -> {old_bars_held(d, h)}")
    print("\n  The caller reads `if bars_held is not None and bars_held >= max_days`.")
    print("  None takes the same branch as a two-day-old position.")

    # The old CALL SITE, re-enacted. Both halves are the pre-fix code:
    # `old_bars_held` above is the helper verbatim, and the two lines below
    # are the branch that consumed it —
    #
    #     held = _bars_held(pos.entry_date, h)
    #     if held is not None and held >= max_days:
    #         queue_reason = ...
    #
    # with no else. Re-enacted rather than monkeypatched because the fix added
    # a reporting branch: patching only the helper would let the NEW report
    # line fire and would show the defect as already half-fixed.
    print("\n  what the old branch did with each position:")
    queued_before = []
    for name, d in (("GOOD.JK", on_bar), ("GHOST.JK", saturday)):
        held = old_bars_held(d, h)
        if held is not None and held >= MAX_DAYS:
            queued_before.append(name)
            print(f"    {name:<9} held={held!s:<5} -> queue SELL")
        else:
            print(f"    {name:<9} held={held!s:<5} -> no branch taken, "
                  f"nothing recorded")

    print("\n  queued for sale :", queued_before)
    print("  exits_queued    :",
          [f"{n}: [CONSIDER] max holding period" for n in queued_before])
    print("  unevaluated     : []")
    print("  skipped         : []")
    print("\n  GHOST.JK is in NO list. Not flagged, not warned about, not")
    print("  mentioned. On the daily message it does not exist.")

    with tempfile.TemporaryDirectory() as tmp:
        pt = PaperTrader.load(Path(tmp) / "p.json", start_capital=10_000_000,
                              cfg=forward_test_shape())
        for tkr, ed in (("GOOD.JK", on_bar), ("GHOST.JK", saturday),
                        ("ANCIENT.JK", "2019-01-01")):
            pt.positions[tkr] = PaperPosition(
                ticker=tkr, entry_price=1000.0, shares=100,
                entry_date=ed, peak_price=1000.0)
        after = pt.step({t: h for t in pt.positions}, [],
                        today=h.index[-1].date().isoformat())

        print(f"\n{'=' * 76}\nAFTER\n{'=' * 76}")
        for name, d in (("GOOD.JK", on_bar), ("GHOST.JK", saturday),
                        ("ANCIENT.JK", "2019-01-01")):
            print(f"  {name:<11} -> {bars_held_or_reason(d, h)}")
        print("\n  queued for sale :", sorted(o.ticker for o in pt.pending))
        print("  unevaluated     :", after["unevaluated"])

    print(f"\n{'=' * 76}")
    print("An off-bar entry is not ambiguous — the position started at the next")
    print("open — so it is counted from there, and GHOST.JK now exits like any")
    print("other overdue holding. An entry BEFORE the history window is NOT")
    print("snapped forward: that would measure from the window's start rather")
    print("than the entry, over-count the bars held, and sell the position")
    print("early. Trading a silent non-exit for a silent wrong exit is not a")
    print("fix. It is reported instead, which is the whole point.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
