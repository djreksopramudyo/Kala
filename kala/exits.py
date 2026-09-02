"""
Exit engine — the home of the three original regression bugs, now fixed.

  1. URGENCY NEVER DOWNGRADES. The old code did ``urgency = '...'`` in sequence,
     so a later weak rule (MACD -> CONSIDER) overwrote an earlier strong one
     (stop-loss -> URGENT). Here every rule contributes, and the final urgency
     is the MAX over all fired rules.
  2. DEATH CROSS IS AN EVENT. "DEATH CROSS today" only fires on the actual
     crossing bar. Merely being below trend is a quiet [ADVISORY], not an exit.
  3. RSI PANIC IS ADVISORY. Dumping into an RSI<25 capitulation low was the old
     behaviour; now it is informational only and never forces a sale.

Reasons are tagged ``[URGENT]`` / ``[CONSIDER]`` / ``[ADVISORY]``. Advisory
reasons inform but never set ``exit_signal`` or raise urgency above ADVISORY.

  4. (v3.3) ONLY VALIDATED RULES FORCE A SALE. The four rules that were never
     part of any out-of-sample validation — MACD-bearish, RSI-overbought-in-
     profit, bearish-market-while-losing, and score-collapse — are ADVISORY
     now. They used to fire CONSIDER, which papertrade auto-sells on, and an
     A/B backtest on identical entries (compare_exit_engines.py, 55 tickers /
     5y) measured what that cost: the validated exit set earned +0.37%/trade
     (PF 1.10) while the live 8-rule set LOST -0.21%/trade (PF 0.91) — the
     MACD rule alone caused 63% of all exits and cut average holds from 12.6
     to 5.3 days, ejecting winners before the +8% target and doubling cost
     drag. Selling remains driven by: governing stop, take-profit,
     death-cross event, and the max-holding-period check applied by the
     papertrade/backtest layer (it needs bars-held context this function
     doesn't have).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import IntEnum

from . import indicators as ind
from .config import RiskConfig

# Tunables that aren't worth a config field yet.
MACD_BEARISH_HIST_PCT = -0.10  # normalized histogram below this -> bearish
RSI_OVERSOLD = 25.0
RSI_OVERBOUGHT = 75.0


class Urgency(IntEnum):
    """Ordered so ``max()`` gives the most severe fired rule."""

    NONE = 0
    ADVISORY = 1
    CONSIDER = 2
    URGENT = 3


@dataclass
class ExitDecision:
    exit_signal: bool
    urgency: Urgency
    reasons: list[str] = field(default_factory=list)


def _is_nan(x) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x))


def governing_stop(entry_price: float, peak_price: float, entry_atr, cfg: RiskConfig):
    """Return ``(stop_price, phase, label)``.

    The stop is the *governing* (highest / tightest) of the applicable rules and
    is FLOORED so it can never sit wider than ``hard_stop_pct`` below entry. With
    trailing disabled, only the phase-1 floor logic applies.
    """
    hard = entry_price * (1.0 + cfg.hard_stop_pct / 100.0)

    have_atr = not _is_nan(entry_atr)
    if not have_atr:
        atr_stop = hard  # no ATR available -> fall back to the hard stop
    else:
        atr_stop = entry_price - cfg.atr_stop_multiple * entry_atr

    base = max(atr_stop, hard)  # never wider than the hard floor

    # Name which rule is actually governing. "fixed/atr stop" was the same
    # string whether ATR was used or missing, so a position running on the
    # fallback looked identical to one whose ATR stop happened to be tighter
    # -- and every position bought through /buy before v4.4 has entry_atr
    # None. The volatility-scaled stop those positions are supposed to have
    # is simply not running, and nothing said so.
    if not have_atr:
        base_label = "hard stop (NO ATR — fallback)"
    elif atr_stop > hard:
        base_label = "atr stop"
    else:
        base_label = "hard stop (floor; atr stop was wider)"

    if not cfg.trailing_enabled:
        return base, 1, base_label

    peak_gain = (peak_price - entry_price) / entry_price * 100.0

    if peak_gain >= cfg.tight_trigger_pct:
        stop, phase, label = peak_price * (1 - cfg.tight_distance_pct / 100.0), 4, "tight trail"
    elif peak_gain >= cfg.trail_start_pct:
        stop, phase, label = peak_price * (1 - cfg.trailing_distance_pct / 100.0), 3, "trail"
    elif peak_gain >= cfg.breakeven_trigger_pct:
        stop, phase, label = entry_price, 2, "breakeven"
    else:
        stop, phase, label = base, 1, base_label

    return max(stop, base), phase, label


def evaluate_exit(
    ticker: str,
    entry_price: float,
    features,
    peak_price: float,
    entry_atr=None,
    market_status: str | None = None,
    score: float | None = None,
    cfg: RiskConfig | None = None,
) -> ExitDecision:
    """Evaluate all exit rules for one position. See module docstring."""
    cfg = cfg or RiskConfig()

    price = float(features["Close"].iloc[-1])
    sma_fast = features["sma_fast"].iloc[-1]
    sma_slow = features["sma_slow"].iloc[-1]
    rsi = features["rsi"].iloc[-1]
    hist_pct = features["macd_hist_pct"].iloc[-1]
    death_today = bool(ind.cross_below(features["sma_fast"], features["sma_slow"]).iloc[-1])

    profit_pct = (price - entry_price) / entry_price * 100.0

    reasons: list[str] = []
    urgency = Urgency.NONE
    exit_signal = False

    def fire(level: Urgency, text: str, *, is_exit: bool):
        nonlocal urgency, exit_signal
        reasons.append(f"[{level.name}] {text}")
        urgency = max(urgency, level)
        if is_exit:
            exit_signal = True

    # 1. Governing stop (hard / ATR / trailing) — the only true URGENT money rule.
    stop, phase, label = governing_stop(entry_price, peak_price, entry_atr, cfg)
    if price <= stop:
        fire(Urgency.URGENT,
             f"governing stop hit: {price:.2f} <= {stop:.2f} ({label}, phase {phase})",
             is_exit=True)

    # 2. Take profit.
    if profit_pct >= cfg.target_profit_pct:
        fire(Urgency.CONSIDER, f"target profit reached (+{profit_pct:.1f}%)", is_exit=True)

    # 3. Death cross — EVENT vs STATE.
    if death_today:
        fire(Urgency.URGENT, "DEATH CROSS today (fast crossed below slow)", is_exit=True)
    elif not _is_nan(sma_fast) and not _is_nan(sma_slow) and sma_fast < sma_slow:
        fire(Urgency.ADVISORY, "Below trend (fast under slow, no fresh cross)", is_exit=False)

    # Rules 4-8 below are ADVISORY as of v3.3 (see module docstring §4):
    # never validated out-of-sample, and measured to be net-harmful when
    # allowed to auto-sell. They still inform /review; they never force.

    # 4. MACD momentum (scale-invariant histogram) — ADVISORY.
    if not _is_nan(hist_pct) and hist_pct < MACD_BEARISH_HIST_PCT:
        fire(Urgency.ADVISORY, f"MACD bearish (hist {hist_pct:.3f}%)", is_exit=False)

    # 5. RSI panic — ADVISORY ONLY (don't sell the capitulation low).
    if not _is_nan(rsi) and rsi < RSI_OVERSOLD:
        fire(Urgency.ADVISORY, f"RSI oversold {rsi:.1f} (panic, not an exit)", is_exit=False)

    # 6. RSI overbought while in profit — ADVISORY.
    if not _is_nan(rsi) and rsi > RSI_OVERBOUGHT and profit_pct > 5.0:
        fire(Urgency.ADVISORY, f"RSI overbought {rsi:.1f} with profit", is_exit=False)

    # 7. Bearish market while losing — ADVISORY.
    #    'UNAVAILABLE' (IHSG fetch failed) counts here too: being blind to the
    #    tape is not a reason to sit more comfortably on a loser than we would
    #    if we could see it. Warm-up 'UNKNOWN'/None are untouched, so no
    #    backtest number moves.
    if (market_status in ("BEARISH", "MODERATE_BEAR", "UNAVAILABLE")
            and profit_pct < -2.0):
        label = ("bearish market" if market_status != "UNAVAILABLE"
                 else "market regime unavailable")
        fire(Urgency.ADVISORY, f"{label} while losing ({profit_pct:.1f}%)", is_exit=False)

    # 8. Composite score collapsed — ADVISORY.
    if score is not None and score < 35.0:
        fire(Urgency.ADVISORY, f"composite score weak ({score:.0f})", is_exit=False)

    return ExitDecision(exit_signal=exit_signal, urgency=urgency, reasons=reasons)
