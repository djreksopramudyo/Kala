"""
Drawdown circuit breaker — stop opening NEW positions after the account has
fallen far enough from its high-water mark.

WHAT IT DOES AND, MORE IMPORTANTLY, WHAT IT NEVER DOES
--------------------------------------------------------
It gates ONE thing: whether new buys may be opened. It has no ability to sell
and is deliberately given none. A breaker that liquidated on a drawdown would
convert paper losses into realized ones at the single worst moment, which is
the opposite of risk control. Existing positions keep being managed by the
normal stop-loss / trailing-stop / max-holding rules, untouched.

Integration is by the same principle: ``daily_run`` passes ``allocation=0``
to ``PaperTrader.step`` when halted. ``size_position`` already returns 0 for a
non-positive allocation, so no new order can be sized, while stage 1 (fill
pending) and stage 2 (evaluate exits) run exactly as before. Nothing in
``papertrade.py`` had to change to support this.

WHY THIS PARTICULAR SAFEGUARD
-------------------------------
Sixteen hypotheses have been tested on this universe and none survived the
alpha check (PROJECT_STATUS.md). When there is no measured edge, there is
also nothing to "trade your way out of" a losing streak with — expected
return per trade is ~zero before costs and negative after. Capping how much
can be lost before new risk stops being added is the only structural
protection left. This is a LOSS-LIMITING device, not a return-improving one,
and it should never be described as the latter.

DEFAULT IS OFF
--------------
``BreakerConfig.enabled`` defaults to False. This changes how real money
behaves, so it must be switched on deliberately by the account owner, never
silently inherited by upgrading the code.

DRAWDOWN IS MEASURED NET OF DEPOSITS AND WITHDRAWALS
------------------------------------------------------
Raw equity is the wrong series to measure a trading drawdown on: withdrawing
cash lowers equity without any trading loss having occurred, and would trip a
naive breaker for no reason. So the breaker tracks the peak of
``equity - net_contributions`` (deposits minus withdrawals, cumulative) — the
same deposit-neutrality principle ``kala.twr`` applies to returns, applied
here to the high-water mark. A deposit raises equity and contributions
together, leaving drawdown unchanged, which is correct: adding money does not
undo a loss.

HYSTERESIS
----------
Halting and resuming at the same threshold makes the breaker chatter on and
off around it. ``resume_drawdown_pct`` is therefore lower than
``halt_drawdown_pct``: once halted, trading stays halted until the drawdown
has genuinely recovered, not merely wobbled back over the line.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BreakerConfig:
    """OFF by default — see the module docstring. ``halt_drawdown_pct`` and
    ``resume_drawdown_pct`` are positive percentages of decline from the
    deposit-adjusted peak."""
    enabled: bool = False
    halt_drawdown_pct: float = 15.0
    resume_drawdown_pct: float = 10.0


@dataclass(frozen=True)
class BreakerState:
    adjusted_equity: float = 0.0     # equity net of cumulative contributions
    peak: float = 0.0                # high-water mark of the above (ratchets up only)
    drawdown_pct: float = 0.0
    halted: bool = False
    changed: bool = False            # True on the transition bar (halt or resume)
    reason: str = ""


def evaluate_breaker(equity: float, net_contributions: float = 0.0,
                     stored_peak: float | None = None,
                     was_halted: bool = False,
                     cfg: BreakerConfig | None = None) -> BreakerState:
    """Decide whether new buys are allowed.

    ``equity``             current total account value (cash + positions)
    ``net_contributions``  cumulative deposits MINUS withdrawals to date
    ``stored_peak``        previous high-water mark, None on first run
    ``was_halted``         whether the breaker was already tripped (hysteresis)

    The peak only ever ratchets UP. Letting it fall with equity would move the
    goalposts down in exactly the market where the breaker is supposed to
    fire, and it could never trip at all.
    """
    cfg = cfg or BreakerConfig()
    adjusted = float(equity) - float(net_contributions)
    peak = adjusted if stored_peak is None else max(float(stored_peak), adjusted)

    # Hysteresis only works while resume sits BELOW halt. Inverted (an easy
    # mistake — both fields are "a drawdown percentage") the breaker flips
    # state every single day at a constant drawdown: halt at 10%, then
    # 12% > 15% is False so it resumes, then 12% >= 10% so it halts again.
    # New buys are permitted on every other one of those days, which is the
    # opposite of what the setting was reached for. Clamping cannot chatter:
    # the breaker degrades to a plain threshold, still protective.
    resume_pct = min(float(cfg.resume_drawdown_pct), float(cfg.halt_drawdown_pct))
    misconfig = ""
    if resume_pct != float(cfg.resume_drawdown_pct):
        misconfig = (f"⚠️ CONFIG: resume_drawdown_pct "
                     f"({cfg.resume_drawdown_pct:.0f}%) is above "
                     f"halt_drawdown_pct ({cfg.halt_drawdown_pct:.0f}%), which "
                     f"would make the breaker flip on and off daily. Using "
                     f"{resume_pct:.0f}% for both — fix runner_config.json. ")

    if peak > 0:
        drawdown = max(0.0, (peak - adjusted) / peak * 100.0)
    else:
        # Degenerate (zero/negative peak): report no drawdown and do NOT halt.
        # Failing OPEN is deliberate — silently freezing the system because of
        # a transient data problem is a worse failure than one extra buy, and
        # the reason string below makes the condition visible rather than
        # swallowed.
        drawdown = 0.0

    if not cfg.enabled:
        return BreakerState(adjusted_equity=adjusted, peak=peak,
                            drawdown_pct=drawdown, halted=False, changed=False,
                            reason="Circuit breaker disabled (enabled=False).")

    if peak <= 0:
        return BreakerState(adjusted_equity=adjusted, peak=peak, drawdown_pct=0.0,
                            halted=False, changed=was_halted,
                            reason=misconfig + "Peak equity is not positive — "
                                   "cannot measure drawdown; NOT halting (fails "
                                   "open by design).")

    # First run with the breaker on: the high-water mark anchors to TODAY. If
    # the account is already underwater, "drawdown 0.0%" is a statement about
    # the peak this file has SEEN, not about the account's history — say so,
    # or enabling a safety device reads as confirmation nothing is wrong.
    first_run = ""
    if stored_peak is None:
        first_run = ("First run: high-water mark anchored to today's equity, "
                     "so any drawdown already suffered before now is not "
                     "counted. ")

    if was_halted:
        # Stay halted until the drawdown recovers past the LOWER resume line.
        halted = drawdown > resume_pct
        if halted:
            reason = (f"Still halted: drawdown {drawdown:.1f}% is above the "
                      f"{resume_pct:.0f}% resume level.")
        else:
            reason = (f"RESUMED: drawdown recovered to {drawdown:.1f}%, at or below "
                      f"the {resume_pct:.0f}% resume level. New buys "
                      f"allowed again.")
        return BreakerState(adjusted_equity=adjusted, peak=peak,
                            drawdown_pct=drawdown, halted=halted,
                            changed=not halted, reason=misconfig + reason)

    halted = drawdown >= cfg.halt_drawdown_pct
    if halted:
        reason = (f"HALTED: drawdown {drawdown:.1f}% reached the "
                  f"{cfg.halt_drawdown_pct:.0f}% limit. No NEW positions will be "
                  f"opened. Existing positions are still managed normally "
                  f"(stops and exits unaffected); nothing is force-sold. Trading "
                  f"resumes automatically once drawdown recovers to "
                  f"{cfg.resume_drawdown_pct:.0f}%.")
    else:
        reason = (f"OK: drawdown {drawdown:.1f}% of the "
                  f"{cfg.halt_drawdown_pct:.0f}% limit.")
    return BreakerState(adjusted_equity=adjusted, peak=peak, drawdown_pct=drawdown,
                        halted=halted, changed=halted,
                        reason=misconfig + first_run + reason)


# ---------------- persistence (deliberately a sidecar, not paper_state) ---------
# The high-water mark lives in its OWN small file rather than inside
# paper_state.json. That state file holds the entire trading history and undo
# stacks and is written atomically for a reason; adding a field to it to
# support an optional safety feature is risk this feature does not need. If
# this sidecar is lost or corrupt, the breaker simply re-anchors its peak to
# today's equity — no false halt, no crash.

def load_breaker_state(path: str | Path) -> tuple[float | None, bool]:
    """Return ``(stored_peak, was_halted)``; ``(None, False)`` if unreadable."""
    try:
        raw = json.loads(Path(path).read_text())
        peak = raw.get("peak")
        return (float(peak) if peak is not None else None,
                bool(raw.get("halted", False)))
    except (FileNotFoundError, json.JSONDecodeError, ValueError, TypeError, OSError):
        return None, False


def save_breaker_state(path: str | Path, state: BreakerState) -> None:
    """Atomic write, same tmp-then-replace discipline paper_state.json uses."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps({
        "peak": state.peak,
        "halted": state.halted,
        "drawdown_pct": state.drawdown_pct,
        "adjusted_equity": state.adjusted_equity,
    }, indent=2))
    tmp.replace(p)


def format_breaker(state: BreakerState, cfg: BreakerConfig | None = None) -> str:
    cfg = cfg or BreakerConfig()
    if not cfg.enabled:
        return "🔌 Circuit breaker: OFF"
    icon = "🛑" if state.halted else ("✅" if state.changed else "🟢")
    return (f"{icon} Circuit breaker: drawdown {state.drawdown_pct:.1f}% "
            f"(peak {state.peak:,.0f}, now {state.adjusted_equity:,.0f})\n"
            f"   {state.reason}")
