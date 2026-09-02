"""Did you trade the strategy you tested?

WHY THIS EXISTS
---------------
The 2026-08 sweeps established a configuration whose expectancy lives in a
right tail: the median trade is NEGATIVE, the win rate is about a third, and it
pays only by holding losers long enough to collect a minority of large winners.
Cutting a loser early converts it into a different strategy — measurably a
worse one, since that is precisely what the exit-ladder grid measured.

So a forward test can fail for two completely different reasons, and the P&L
alone cannot tell them apart:

  * the strategy does not work, or
  * the strategy was never run.

Every closed trade in the paper log to date carries ``reason = "manual sell"``.
Not one was closed by the engine. If that persists, a year of forward testing
measures the operator, not the hypothesis — and the honest time to discover
that is early, not after the year.

This module answers one question: **of the positions that closed, which ones
did the system close, and what did the others cost?**

WHAT THE COUNTERFACTUAL IS, AND IS NOT
--------------------------------------
For a hand-closed trade it asks: had this been held to the configured holding
limit, what would it have returned? That is a comparison against the RULE, not
against hindsight — the rule was fixed in advance, so the comparison is fair.

It is NOT a claim that holding was the better choice on any single trade. Any
one manual exit can beat the rule by luck. The aggregate over many trades is
the number that means something, and even that only says what the rule would
have done on the trades you actually took.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .config import CostModel

# What closed the position.
HOLDING_LIMIT = "holding_limit"   # the configured max holding period
ENGINE = "engine"                 # a price rule: stop, target, trailing, death cross
MANUAL = "manual"                 # a human
UNKNOWN = "unknown"               # no reason recorded (pre-v3.4 entries)


def classify_exit(reason: str | None) -> str:
    """Which agent closed a position, from the log's ``reason`` string.

    Deliberately conservative: anything unrecognised is MANUAL rather than
    engine, because over-crediting the engine is the error that would hide the
    very problem this module exists to surface.
    """
    if reason is None:
        return UNKNOWN
    text = str(reason).strip()
    if not text:
        return UNKNOWN
    low = text.lower()
    if "max holding period" in low or "holding limit" in low:
        return HOLDING_LIMIT
    # papertrade queues engine exits with an urgency prefix from evaluate_exit
    if text.startswith("[URGENT]") or text.startswith("[CONSIDER]"):
        return ENGINE
    return MANUAL


@dataclass
class DisciplineSummary:
    n_closed: int = 0
    by_agent: dict = field(default_factory=dict)          # agent -> count
    pnl_by_agent: dict = field(default_factory=dict)      # agent -> mean pnl_pct
    hold_by_agent: dict = field(default_factory=dict)     # agent -> mean calendar days
    n_without_entry_date: int = 0

    @property
    def system_share(self) -> float:
        """Fraction of closes the system made. 0.0 means you are the strategy."""
        if not self.n_closed:
            return 0.0
        n_sys = self.by_agent.get(HOLDING_LIMIT, 0) + self.by_agent.get(ENGINE, 0)
        return n_sys / self.n_closed


def _hold_days(entry, exit_) -> int | None:
    try:
        return (pd.Timestamp(exit_).normalize() - pd.Timestamp(entry).normalize()).days
    except Exception:
        return None


def summarise_discipline(log: list[dict]) -> DisciplineSummary:
    """Who closed what, and how each group performed."""
    s = DisciplineSummary(n_closed=len(log))
    buckets: dict[str, list[dict]] = {}
    for t in log:
        buckets.setdefault(classify_exit(t.get("reason")), []).append(t)

    for agent, rows in buckets.items():
        s.by_agent[agent] = len(rows)
        pnls = [float(r["pnl_pct"]) for r in rows if r.get("pnl_pct") is not None]
        s.pnl_by_agent[agent] = (sum(pnls) / len(pnls)) if pnls else float("nan")
        holds = [d for r in rows
                 if (d := _hold_days(r.get("entry_date"), r.get("date"))) is not None]
        s.hold_by_agent[agent] = (sum(holds) / len(holds)) if holds else float("nan")

    s.n_without_entry_date = sum(1 for t in log if not t.get("entry_date"))
    return s


@dataclass
class Counterfactual:
    n_compared: int = 0
    n_skipped: int = 0                 # no entry_date, or no price history
    actual_mean: float = float("nan")  # what the hand-closed trades returned
    rule_mean: float = float("nan")    # what holding to the limit would have
    per_trade: list = field(default_factory=list)

    @property
    def delta(self) -> float:
        """Rule minus actual. Positive means cutting early COST you."""
        return self.rule_mean - self.actual_mean


def _bars_from(history: pd.DataFrame, entry_date, holding_days: int):
    """Close ``holding_days`` bars after entry, or the last bar if the history
    ends first. Returns (price, bars_available)."""
    idx = history.index
    entry_ts = pd.Timestamp(entry_date).normalize()
    after = idx[idx >= entry_ts]
    if len(after) == 0:
        return None, 0
    pos = idx.get_loc(after[0])
    target = min(pos + holding_days, len(idx) - 1)
    return float(history["Close"].iloc[target]), target - pos


def counterfactual_hold(log: list[dict], histories: dict[str, pd.DataFrame],
                        holding_days: int = 60,
                        costs: CostModel | None = None,
                        min_bars: int | None = None) -> Counterfactual:
    """For each MANUALLY closed trade, what would the rule have returned?

    ``min_bars`` guards the honest edge case: a trade whose history has not yet
    run ``holding_days`` bars cannot be compared, because the rule has not
    finished with it. Those are skipped, not scored against a truncated window.
    Defaults to ``holding_days`` — a strict comparison.
    """
    costs = costs or CostModel()
    need = holding_days if min_bars is None else min_bars
    cf = Counterfactual()
    actual, ruled = [], []

    for t in log:
        if classify_exit(t.get("reason")) != MANUAL:
            continue
        ticker, entry_date = t.get("ticker"), t.get("entry_date")
        hist = histories.get(ticker)
        if not entry_date or hist is None or len(hist) == 0:
            cf.n_skipped += 1
            continue
        price, bars = _bars_from(hist, entry_date, holding_days)
        if price is None or bars < need:
            cf.n_skipped += 1
            continue

        entry_px = float(t["entry"])
        if entry_px <= 0:
            cf.n_skipped += 1
            continue
        # Same cost treatment as a real exit: the sell leg is net of fees,
        # tax and half the spread, so the two numbers are comparable.
        net_exit = price * costs.sell_multiplier(price)
        rule_pct = (net_exit / entry_px - 1.0) * 100.0
        act_pct = float(t["pnl_pct"])

        actual.append(act_pct)
        ruled.append(rule_pct)
        cf.per_trade.append({
            "ticker": ticker, "entry_date": entry_date,
            "actual_pct": act_pct, "rule_pct": rule_pct,
            "delta": rule_pct - act_pct, "bars_held_by_rule": bars,
        })

    cf.n_compared = len(actual)
    if actual:
        cf.actual_mean = sum(actual) / len(actual)
        cf.rule_mean = sum(ruled) / len(ruled)
    return cf


def format_report(s: DisciplineSummary, cf: Counterfactual | None = None,
                  holding_days: int = 60) -> str:
    lines = ["DISCIPLINE — who closed the positions", "=" * 52]
    if not s.n_closed:
        return "\n".join(lines + ["", "No closed trades yet."])

    order = [HOLDING_LIMIT, ENGINE, MANUAL, UNKNOWN]
    label = {HOLDING_LIMIT: "holding limit (the rule)", ENGINE: "engine (stop/target)",
             MANUAL: "MANUAL (you)", UNKNOWN: "no reason recorded"}
    lines.append(f"{'closed by':<26}{'n':>5}{'share':>8}{'mean P&L':>11}{'mean days':>11}")
    for agent in order:
        n = s.by_agent.get(agent, 0)
        if not n:
            continue
        pnl, hold = s.pnl_by_agent.get(agent), s.hold_by_agent.get(agent)
        pnl_s = f"{pnl:+.2f}%" if pnl == pnl else "n/a"
        hold_s = f"{hold:.0f}" if hold == hold else "n/a"
        lines.append(f"{label[agent]:<26}{n:>5}{n / s.n_closed * 100:>7.0f}%"
                     f"{pnl_s:>11}{hold_s:>11}")
    lines.append("-" * 52)
    lines.append(f"system closed {s.system_share * 100:.0f}% of positions")

    if s.system_share == 0.0 and s.n_closed >= 5:
        lines.append("")
        lines.append("WARNING: the engine has never closed a position. A forward test "
                     "under these\nconditions measures your judgement, not the "
                     "strategy — the two cannot be\nseparated afterwards from P&L "
                     "alone.")

    if cf is not None and cf.n_compared:
        lines += ["", f"COUNTERFACTUAL — hand-closed trades vs holding {holding_days} bars",
                  "=" * 52,
                  f"compared: {cf.n_compared}   skipped (no date / too recent): {cf.n_skipped}",
                  f"  your exits returned  {cf.actual_mean:+.2f}%/trade",
                  f"  the rule would have  {cf.rule_mean:+.2f}%/trade",
                  f"  difference           {cf.delta:+.2f} pts"]
        if cf.delta > 0:
            lines.append("\nHolding to the rule would have done better on these trades. "
                         "That is one\nsample of the trades you happened to take, not "
                         "proof for any single exit.")
        else:
            lines.append("\nYour exits beat the rule on these trades. Worth knowing, and "
                         "not yet worth\nacting on: a handful of trades cannot "
                         "distinguish judgement from luck.")
    elif cf is not None:
        lines += ["", "COUNTERFACTUAL: nothing comparable yet — every hand-closed trade "
                  "either lacks\nan entry date or is too recent to have run the full "
                  "holding period."]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Two numbers the P&L column does not show on its own.
# ---------------------------------------------------------------------------

@dataclass
class Payoff:
    """Break-even arithmetic. Answers "am I actually ahead, or just busy?"."""
    n: int = 0
    n_wins: int = 0
    avg_win_pct: float = float("nan")
    avg_loss_pct: float = float("nan")     # positive magnitude
    payoff: float = float("nan")           # avg win / avg loss
    win_rate_pct: float = float("nan")
    breakeven_win_rate_pct: float = float("nan")
    expectancy_pct: float = float("nan")

    @property
    def margin_pts(self) -> float:
        """Win rate minus the rate this payoff needs to break even."""
        return self.win_rate_pct - self.breakeven_win_rate_pct


def payoff_arithmetic(log: list[dict]) -> Payoff:
    """Where the money actually comes from, on closed trades only.

    A payoff below 1.0 is not a problem by itself — it just sets the win rate
    the system has to clear. Stating both together is the point: "56% of my
    trades win" means nothing until you know 54.8% was the break-even line.
    """
    pnls = [float(t["pnl_pct"]) for t in log if t.get("pnl_pct") is not None]
    p = Payoff(n=len(pnls))
    wins = [x for x in pnls if x > 0]
    losses = [-x for x in pnls if x <= 0]
    p.n_wins = len(wins)
    if not pnls or not wins or not losses:
        return p
    p.avg_win_pct = sum(wins) / len(wins)
    p.avg_loss_pct = sum(losses) / len(losses)
    p.payoff = p.avg_win_pct / p.avg_loss_pct
    p.win_rate_pct = len(wins) / len(pnls) * 100.0
    p.breakeven_win_rate_pct = p.avg_loss_pct / (p.avg_win_pct + p.avg_loss_pct) * 100.0
    p.expectancy_pct = (p.win_rate_pct / 100.0 * p.avg_win_pct
                        - (1 - p.win_rate_pct / 100.0) * p.avg_loss_pct)
    return p


@dataclass
class HorizonGap:
    """How far the trades actually taken sit from the horizon that was tested."""
    rule_days: int = 60
    n_with_dates: int = 0
    n_reached_rule: int = 0
    median_hold_days: float = float("nan")
    max_hold_days: int = 0
    buckets: list = field(default_factory=list)   # (label, n, mean_pct, median_pct)


def holding_horizon_gap(log: list[dict], rule_days: int = 60,
                        bounds=((0, 7), (8, 14), (15, 30), (31, 10_000)),
                        ) -> HorizonGap:
    """Compare realised holding periods against the configured limit.

    ``n_reached_rule`` is the number that matters most and needs no statistics:
    a strategy validated at ``rule_days`` has not been run at all if nothing
    was held that long.

    The per-bucket P&L is reported because it is the first thing anyone asks
    for, and it must be read with the caveat ``format_report`` prints beside
    it: an exit ladder closes losers early by construction, so longer buckets
    are pre-selected for survivors. The gradient is NOT evidence that patience
    pays.
    """
    g = HorizonGap(rule_days=rule_days)
    rows = []
    for t in log:
        if t.get("pnl_pct") is None:
            continue
        d = _hold_days(t.get("entry_date"), t.get("date"))
        if d is None:
            continue
        rows.append((d, float(t["pnl_pct"])))

    g.n_with_dates = len(rows)
    if not rows:
        return g
    holds = sorted(d for d, _ in rows)
    g.n_reached_rule = sum(1 for d in holds if d >= rule_days)
    mid = len(holds) // 2
    g.median_hold_days = (holds[mid] if len(holds) % 2
                          else (holds[mid - 1] + holds[mid]) / 2)
    g.max_hold_days = holds[-1]

    for lo, hi in bounds:
        vals = sorted(p for d, p in rows if lo <= d <= hi)
        if not vals:
            continue
        m = len(vals) // 2
        label = f"{lo}-{hi} d" if hi < 10_000 else f"{lo}+ d"
        g.buckets.append((label, len(vals), sum(vals) / len(vals),
                          vals[m] if len(vals) % 2 else (vals[m - 1] + vals[m]) / 2))
    return g


def format_horizon_and_payoff(g: HorizonGap, p: Payoff) -> str:
    lines = []
    if p.n and p.payoff == p.payoff:
        lines += ["", "PAYOFF — is this ahead, or just busy?", "=" * 52,
                  f"  avg win / avg loss   {p.avg_win_pct:+.2f}% / -{p.avg_loss_pct:.2f}%"
                  f"   payoff {p.payoff:.2f}",
                  f"  win rate             {p.win_rate_pct:.1f}%",
                  f"  break-even win rate  {p.breakeven_win_rate_pct:.1f}%"
                  f"   -> margin {p.margin_pts:+.1f} pts",
                  f"  expectancy           {p.expectancy_pct:+.3f}% per trade "
                  f"over {p.n} trade(s)"]
        if abs(p.margin_pts) < 5.0:
            lines.append("\n  That margin is inside the noise for this many trades. The "
                         "result is\n  'break-even', not 'slightly profitable'.")

    if g.n_with_dates:
        lines += ["", f"HOLDING HORIZON — tested at {g.rule_days} bars", "=" * 52,
                  f"  median hold {g.median_hold_days:.0f} d   "
                  f"longest {g.max_hold_days} d   "
                  f"reached {g.rule_days} bars: {g.n_reached_rule} of {g.n_with_dates}"]
        if g.n_reached_rule == 0:
            lines.append(f"\n  NOT ONE trade reached the horizon the strategy was "
                         f"validated at.\n  Whatever these {g.n_with_dates} trades "
                         f"measure, it is not that strategy.")
        if g.buckets:
            lines += ["", f"  {'bucket':<12}{'n':>4}{'mean':>10}{'median':>10}"]
            for label, n, mean, med in g.buckets:
                lines.append(f"  {label:<12}{n:>4}{mean:>9.2f}%{med:>9.2f}%")
            lines.append("\n  READ THIS BEFORE THE TABLE ABOVE: a stop-loss closes losers"
                         " early by\n  construction, so the longer buckets are pre-selected"
                         " for trades that\n  never hit the stop. A rising gradient here is"
                         " what that mechanism\n  produces on its own. It is NOT evidence"
                         " that holding longer pays.")
    return "\n".join(lines)


@dataclass
class AtrCoverage:
    """How many OPEN positions can actually run the volatility-scaled stop."""
    n_total: int = 0
    n_missing: int = 0
    missing: list = field(default_factory=list)   # tickers

    @property
    def pct_missing(self) -> float:
        return (self.n_missing / self.n_total * 100.0) if self.n_total else 0.0


def atr_coverage(positions: dict) -> AtrCoverage:
    """Which open positions are stuck on the hard-stop fallback.

    ``governing_stop`` falls back to ``hard_stop_pct`` when ``entry_atr`` is
    missing. That fallback is safe and deliberate, and it is also NOT the
    strategy: the phase-1 stop is supposed to be ``entry - multiple * ATR``,
    which is tighter than the floor on a quiet name and identical to it on a
    volatile one. A book where every position lacks ATR is running one stop
    rule where it thinks it is running another, and no per-position display
    said so — the label read "fixed/atr stop" either way.
    """
    c = AtrCoverage(n_total=len(positions))
    for ticker, pos in positions.items():
        atr = pos.get("entry_atr") if isinstance(pos, dict) else getattr(pos, "entry_atr", None)
        if atr is None or (isinstance(atr, float) and atr != atr):
            c.n_missing += 1
            c.missing.append(ticker)
    c.missing.sort()
    return c


def format_atr_coverage(c: AtrCoverage) -> str:
    if not c.n_total:
        return ""
    lines = ["", "ATR COVERAGE — can the volatility stop actually run?", "=" * 52,
             f"  open positions {c.n_total}   without entry_atr: {c.n_missing} "
             f"({c.pct_missing:.0f}%)"]
    if c.n_missing:
        lines.append(f"  {', '.join(c.missing)}")
        lines.append("\n  These run on the hard-stop floor, not the ATR stop. Safe, but "
                     "not the\n  rule that was tested. entry_atr is recorded from v4.4 "
                     "onward; positions\n  opened before that keep None until they close.")
    return "\n".join(lines)
