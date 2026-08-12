"""
Live-vs-backtest edge tracker: is the LIVE track record still consistent
with the numbers that were validated in backtests?

CANONICAL VALIDATION STATUS lives in PROJECT_STATUS.md (repo root) — the
single source of truth for "what's proven / what isn't". This docstring is
the detailed, code-adjacent trace of HOW that verdict was reached; if the
two ever disagree, PROJECT_STATUS.md wins and this should be updated.

*** STATUS AS OF 2026-07-20: UNVALIDATED — retraction CONFIRMED by two
independent follow-up tests (see "SETTLED" below), not just suspected. ***
Sequence of what actually happened, in order, because the middle step was
wrong and it matters why:

  1. --tick-spread on the full universe: no edge (t=-1.35, then confirmed
     at full sample size n>8,800, t between -1.91 and +0.28). Solid finding,
     still stands.
  2. run_walkforward.py --min-price 1000 (576 tickers): looked like a real,
     well-powered edge (n=2,338, t=3.38, excess-return t=4.79 — stronger
     than raw, arguing against pure beta capture). This is what got shipped
     as validated=True.
  3. RETRACTED. compare_exit_engines.py --tick-spread --max-tickers 576,
     which applies entry vetoes (incl. the new min_price_idr gate) POINT-IN-
     TIME per bar — the same thing live trading actually does — measured
     -0.43%/trade, t=-3.06, n=3,433. Directly contradicts step 2.

Why: run_walkforward.py's --min-price filters on each ticker's LATEST close
only (its own docstring says so — "a listing-quality floor, not point-in-
time"). A ticker priced >= 1,000 TODAY keeps every historical trade in the
"validated" bucket even from years when it traded at 400-800 rupiah. That's
a look-ahead / hindsight filter: today's price is partly a record of which
stocks went UP, so filtering on it retroactively selects for stocks that
already appreciated — inflating historical returns with no real signal
skill required. compare_exit_engines.py's vetoes apply per-bar, so they
don't have this leak — and they're also the thing entries.py actually
enforces live. Two more differences stack on top (run_walkforward.py used
3y history by default vs compare_exit_engines.py's 5y, and the walk-forward
runs never had --apply-entry-vetoes on, so the other guardrails — RSI/
parabolic/distribution/thin-volume/bear-regime — were off), so the -0.43%
number isn't a clean isolated test of price alone either. Nothing here is
settled; see the "what would settle it" note below.

`EntryConfig.veto_cheap_stock` / `min_price_idr` (kala/config.py) is
KEPT ON by default despite the retraction — tick-floor spread costs are
still objectively worse for sub-2,000-rupiah stocks (a flat 0.10% spread
assumption understates the real cost 2-7x there), which is a sound reason
to avoid that tier on cost grounds alone. What's retracted is specifically
the CLAIM that this tier has a demonstrated positive edge — it does not,
under the one point-in-time test run so far.

SETTLED (2026-07-20), via two controlled run_walkforward.py isolating runs
on top of the compare_exit_engines.py retraction above:
  * --tick-spread --min-price 1000 --apply-entry-vetoes (period/ticker-filter
    held fixed vs the original positive run, only vetoes added): t dropped
    3.38 -> 1.00, n dropped 2,338 -> 936 -- vetoes alone ate ~60% of what was
    counted as "edge." Still not proof by itself: --min-price's look-ahead
    filter was still active underneath the vetoes.
  * --tick-spread --apply-entry-vetoes, --min-price REMOVED (full 519-ticker
    universe, only entries.py's point-in-time min_price_idr=1000 veto left
    filtering price): EV/trade -0.03% to +0.00%, t=-0.09 to 0.00 -- dead
    flat, "NO OOS EDGE." Same conclusion as compare_exit_engines.py's
    -0.43%/t=-3.06 (that one has more power: n=3,433 vs n~1,070, 5y vs 3y —
    the gap between the two negative-ish numbers is just power, not
    disagreement).
Two independently-run tests now agree: no demonstrated edge at >= IDR 1,000,
or anywhere else, once price is filtered point-in-time instead of on
today's close. Don't reflip validated back to True from a single run in
the future either way — this whole episode is the reason that rule exists.

How the comparison works (once re-validated)
---------------------------------------------
``trade_stats`` (kala.walkforward) pools the live per-trade returns with
THE SAME definitions the A/B script uses, then a one-sample t-test asks: "if
the true edge were still exactly the backtest's EV, how surprising is the
live mean?"  t = (live_mean - expected_ev) / (live_std / sqrt(n)).

Verdicts (EV is the headline, everything else is displayed for context):
  * validated=False              -> UNVALIDATED (see status note above)
  * n < MIN_TRADES_FOR_VERDICT    -> TOO EARLY (numbers shown, no judgment)
  * |t| < 1                       -> ON TRACK (consistent with the backtest)
  * 1 <= |t| < 2                  -> WATCH (drifting, not yet significant)
  * |t| >= 2                      -> DIVERGING (investigate: re-run
                                     compare_exit_engines.py + walk-forward)

Where the expected numbers come from — and how to refresh them
--------------------------------------------------------------
DEFAULT_EXPECTATIONS below holds the compare_exit_engines.py arm-B numbers
from the 2026-07-20 retraction run (point-in-time vetoes, tick-floor costs,
5y, 519 tickers) — the most methodologically sound measurement so far, kept
for reference only while validated=False. They are not magic constants;
after a re-validation that actually clears the bar AND survives a point-in-
time (not latest-close) price filter, replace them (and flip validated to
True) via runner_config.json's "edge_expectations" — config overrides these
defaults key-by-key, so partial overrides are fine.
"""

from __future__ import annotations

import math
from collections import Counter
from datetime import date

from .walkforward import trade_stats

# 2026-07-20 compare_exit_engines.py retraction run: --tick-spread
# --max-tickers 576, arm B (live exit engine), point-in-time entry vetoes
# incl. the new min_price_idr gate, 5y, 519 tickers. n=3,433, t=-3.09. See
# module docstring for why this contradicts (and takes priority over) the
# earlier run_walkforward.py --min-price 1000 result.
DEFAULT_EXPECTATIONS: dict = {
    "ev_pct": -0.43,        # expected mean net return per closed trade
    "win_rate_pct": 35.0,   # same run/row as ev_pct; refine from your own A/B output
    "avg_hold_days": 14.4,  # arm B, same run
    "validated": False,     # 2026-07-20: RETRACTED. The apparent >= IDR
                            # 1,000 edge was measured with a look-ahead flaw
                            # (ticker-level latest-close filter, not
                            # point-in-time). See module docstring for the
                            # full sequence and what would settle it.
}

MIN_TRADES_FOR_VERDICT = 10


def reason_bucket(reason: str) -> str:
    """Fold a free-text exit reason into a short category. Single source of
    truth — compare_exit_engines.py imports this same function, so the live
    mix and the backtest mix are bucketed identically."""
    r = (reason or "").lower()
    if "manual" in r:
        return "manual"
    if "target profit" in r:
        return "take-profit"
    if "stop" in r:
        return "stop"
    if "death cross" in r:
        return "death-cross"
    if "max holding" in r:
        return "max-hold"
    if "macd" in r:
        return "macd-reversal"
    if "overbought" in r:
        return "rsi-overbought"
    if "bearish market" in r:
        return "bear-while-losing"
    if "score weak" in r:
        return "score-collapse"
    if "eod" in r or "end of data" in r:
        return "eod"
    return "other"


def merged_expectations(cfg: dict | None = None) -> dict:
    """DEFAULT_EXPECTATIONS overridden key-by-key from runner_config.json's
    "edge_expectations" (missing keys keep their defaults)."""
    out = dict(DEFAULT_EXPECTATIONS)
    for k, v in ((cfg or {}).get("edge_expectations") or {}).items():
        if k in out:
            out[k] = v
    return out


def _hold_days(entry: str | None, exit_: str | None) -> int | None:
    """Calendar days between two ISO dates; None if either is missing or
    unparseable (log entries written before entry_date was recorded)."""
    try:
        return (date.fromisoformat(str(exit_)) - date.fromisoformat(str(entry))).days
    except (TypeError, ValueError):
        return None


def _pnl_pct(entry: dict) -> float | None:
    """A log entry's net return, or None if it doesn't carry a usable one.

    Deliberately NOT defaulting to 0.0. A missing pnl_pct is an entry we
    cannot score, not a trade that broke even — and 0.0 is a real
    observation: it inflates n (which gates MIN_TRADES_FOR_VERDICT), pulls
    ev_pct toward zero, shrinks the std the t-statistic divides by, and
    counts as a loss in win_rate (wins are r > 0). Every current writer in
    papertrade.py populates the field, so this is defence, not a live fix —
    but this log is long-lived, persisted state whose schema HAS grown
    before (entry_date arrived in v3.4, which is exactly why _hold_days
    below has to tolerate its absence). Same discipline as hold time:
    skip what can't be scored and report how many contributed.
    """
    val = entry.get("pnl_pct")
    if val is None:
        return None
    try:
        val = float(val)
    except (TypeError, ValueError):
        return None
    return None if val != val else val  # NaN is not a return either


def live_stats(log: list[dict]) -> dict:
    """Pooled statistics over the paper trader's closed-trade log, using the
    exact trade_stats definitions the backtests use, plus hold-time and the
    exit-reason mix. Hold time is computed only over entries that carry
    entry_date (recorded since v3.4); n_with_hold says how many did.

    Entries without a usable pnl_pct are excluded rather than scored as
    breakeven; n_skipped_no_pnl says how many were dropped, so a silently
    shrinking sample is visible instead of invisible."""
    returns = [r for t in log if (r := _pnl_pct(t)) is not None]
    stats = trade_stats(returns)
    stats["n_skipped_no_pnl"] = len(log) - len(returns)

    holds = [d for t in log
             if (d := _hold_days(t.get("entry_date"), t.get("date"))) is not None]
    stats["avg_hold_days"] = (sum(holds) / len(holds)) if holds else None
    stats["n_with_hold"] = len(holds)
    stats["reasons"] = Counter(reason_bucket(t.get("reason", "")) for t in log)
    return stats


def t_vs_expected(returns_mean: float, returns_std: float, n: int,
                  expected_mean: float) -> float | None:
    """One-sample t statistic of the live mean against the backtest's EV.
    None when it cannot be computed honestly (n < 2 or zero variance)."""
    if n < 2 or returns_std <= 0:
        return None
    return (returns_mean - expected_mean) / (returns_std / math.sqrt(n))


def entry_signal_warning(cfg: dict | None = None) -> str | None:
    """A short banner for anywhere NEW BUY recommendations are shown, while
    the entry signal's validated status (edge_expectations.validated) is
    False. Tied to the SAME flag edge_report() checks — clearing it there
    after a real re-validation silences this everywhere at once, one flag
    instead of several places to remember to update. None when validated."""
    if merged_expectations(cfg).get("validated", True):
        return None
    return ("⚠️ Entry signal UNVALIDATED (see /edge) — the last re-validation "
            "did not clear the bar for an out-of-sample edge. New BUY ideas "
            "below are shown for reference, not confidence.")


def edge_report(log: list[dict], cfg: dict | None = None) -> dict:
    """The full live-vs-backtest comparison as data (formatting belongs to
    the caller). Returns {"live": <live_stats dict>, "expected": <dict>,
    "t_vs_expected": float|None, "verdict": str, "verdict_reason": str}."""
    exp = merged_expectations(cfg)
    live = live_stats(log)
    n = live["n"]

    if not exp.get("validated", True):
        return {"live": live, "expected": exp, "t_vs_expected": None,
                "verdict": "UNVALIDATED",
                "verdict_reason": (
                    "edge_expectations.validated is False — live stats are "
                    "shown for reference, but are NOT compared against a "
                    "trusted baseline. See kala/edge.py's module "
                    "docstring and HOW_IT_WORKS.md.")}

    t = t_vs_expected(live["ev_pct"], live["std_pct"], n, exp["ev_pct"])

    if n < MIN_TRADES_FOR_VERDICT:
        verdict = "TOO EARLY"
        reason = (f"only {n} closed trade(s) — fewer than "
                  f"{MIN_TRADES_FOR_VERDICT}; any comparison would be noise")
    elif t is None:
        verdict = "TOO EARLY"
        reason = "not enough spread in the returns to test against the backtest yet"
    elif abs(t) < 1.0:
        verdict = "ON TRACK"
        reason = (f"live EV {live['ev_pct']:+.2f}% vs backtest {exp['ev_pct']:+.2f}% "
                  f"(t={t:+.2f}) — consistent with the validated edge")
    elif abs(t) < 2.0:
        verdict = "WATCH"
        direction = "below" if t < 0 else "above"
        reason = (f"live EV {live['ev_pct']:+.2f}% runs {direction} backtest "
                  f"{exp['ev_pct']:+.2f}% (t={t:+.2f}) — not significant yet, "
                  f"re-check as more trades close")
    else:
        verdict = "DIVERGING"
        direction = "WORSE than" if t < 0 else "better than"
        reason = (f"live EV {live['ev_pct']:+.2f}% is significantly {direction} "
                  f"backtest {exp['ev_pct']:+.2f}% (t={t:+.2f}, n={n}) — re-run "
                  f"compare_exit_engines.py and the walk-forward before trusting "
                  f"either number")

    return {"live": live, "expected": exp, "t_vs_expected": t,
            "verdict": verdict, "verdict_reason": reason}
