"""
Rebalancing plan generator — turns "your portfolio has drifted from target"
into "here are the exact lot-level trades to fix it, and here's what the
churn costs."

WHERE THIS SITS, AND WHAT IT IS *NOT*
-------------------------------------
This project spent seven honest tests proving there is no reliable
market-timing/security-selection edge in this universe (see
PROJECT_STATUS.md). This module is the OPPOSITE kind of tool: it makes no
prediction about which stock will go up. It only answers a maintenance
question a long-horizon investor genuinely faces — "I decided on a target
mix; I've drifted; what do I trade to get back, and is it even worth the
transaction cost?"

Disciplined rebalancing is a real, modest, WELL-DOCUMENTED contributor to
long-run risk-adjusted return (it trims what's run up, tops up what's
lagged, and — more importantly — stops a portfolio silently becoming
over-concentrated in one name). It is NOT a return-maximizing signal, and
nothing here should be read as one.

DELIBERATE ANTI-CHURN STANCE
----------------------------
The single most common way rebalancing DESTROYS return is over-trading:
paying real spread+fee+tax to correct a 1% drift that didn't matter.
So this plan:
  * ignores any name still within ``band_pp`` of its target (the honest
    default is "do nothing" — most of the time that's correct);
  * reports the total estimated transaction cost of the whole plan, so the
    decision "is fixing this drift worth IDR X in fees" stays YOURS;
  * is READ-ONLY advice. It returns orders; it never executes them. The
    only way a trade is recorded is still a manual /buy or /sell (same
    "flag, don't act" stance as kala.portfolio_analytics.allocation_drift).

TARGET WEIGHTS NEED NOT SUM TO 100
----------------------------------
If your targets sum to (say) 90, the remaining 10% is treated as an
intended CASH buffer — not force-normalized away. Cash's implicit target
is ``100 - sum(target_weights)``, and drift is always measured against the
whole pot (holdings + investable cash) so it's apples-to-apples.
"""

from __future__ import annotations

from dataclasses import dataclass, field


def default_lot_size(ticker: str) -> int:
    """IDX names (``.JK``) trade in lots of 100 shares; bare US tickers trade
    in single shares. A caller with a different convention can pass its own
    ``lot_size_fn`` to ``plan_rebalance``."""
    return 100 if ticker.upper().endswith(".JK") else 1


@dataclass(frozen=True)
class RebalanceOrder:
    ticker: str
    action: str          # "BUY" | "SELL"
    lots: int
    shares: int
    price: float
    value: float         # gross shares * price (before costs)
    drift_pp: float      # how far over/under target this name was, in pp
    reason: str


@dataclass
class RebalancePlan:
    orders: list[RebalanceOrder] = field(default_factory=list)
    total_buy_value: float = 0.0
    total_sell_value: float = 0.0
    est_cost: float = 0.0            # estimated transaction cost of the whole plan
    cash_before: float = 0.0
    cash_after: float = 0.0
    pot: float = 0.0                 # total portfolio value (holdings + investable cash)
    skipped: list[str] = field(default_factory=list)   # names skipped (no price, etc.)
    note: str = ""

    @property
    def is_noop(self) -> bool:
        return not self.orders


def plan_rebalance(holdings_value: dict[str, float],
                   target_weights: dict[str, float],
                   prices: dict[str, float],
                   cash: float,
                   band_pp: float = 5.0,
                   cost_model=None,
                   investable_cash: float | None = None,
                   lot_size_fn=default_lot_size,
                   unpriced_holdings: list[str] | None = None) -> RebalancePlan:
    """Compute lot-level BUY/SELL orders to move a portfolio toward
    ``target_weights`` (a ``{ticker: percent}`` dict). ``holdings_value`` is
    the current market value per held ticker; ``prices`` the current price
    per share (needed to convert a rupiah delta into whole lots).

    ``band_pp``: names within this many percentage points of target are left
    alone (anti-churn — the honest default is inaction). ``cost_model``: an
    optional ``kala.config.CostModel`` used only to ESTIMATE the plan's total
    transaction cost (reported, never used to secretly drop trades).
    ``investable_cash``: how much of ``cash`` may be deployed into buys
    (default: all of it); the rest is left as an untouched buffer.

    Sells are computed first so their proceeds fund buys; buys are then
    capped at available cash, largest-under-target first, and lot-rounded
    DOWN so the plan never overspends. Returns a ``RebalancePlan`` whose
    ``is_noop`` is True when nothing is worth trading.

    ``unpriced_holdings``: tickers you HOLD but could not price. Pass them —
    do not simply omit them from ``holdings_value``. Every weight here is
    ``value / pot``, so a held position missing from the pot shrinks the
    denominator and inflates every other name's weight. With five equal
    holdings, one failed price fetch pushes the other four 5pp over target
    and fabricates four SELL orders against a portfolio that had not drifted
    at all. Since the true pot is unknowable in that state, this returns a
    no-op explaining why rather than trading on a guess — the same
    "inaction is the honest default" stance as the anti-churn band."""
    investable_cash = cash if investable_cash is None else min(investable_cash, cash)
    holdings_total = sum(v for v in holdings_value.values() if v and v > 0)
    pot = holdings_total + investable_cash
    plan = RebalancePlan(cash_before=cash, cash_after=cash, pot=pot)
    # Checked BEFORE the empty-pot guard: an unpriced holding is often the
    # very reason the pot looks empty, and "no holdings" would be a plainly
    # wrong thing to tell someone who is holding something.
    if unpriced_holdings:
        names = ", ".join(sorted(unpriced_holdings))
        plan.skipped = sorted(unpriced_holdings)
        plan.note = (
            f"Can't plan safely: no current price for {names}, which you "
            f"hold. Every weight is measured against the total portfolio, so "
            f"leaving a held position out of that total would inflate every "
            f"other name's weight and invent trades you don't need. Try "
            f"again when pricing recovers.")
        return plan
    if pot <= 0:
        # Guards the current_val / pot division below.
        plan.note = "Nothing to rebalance (no holdings and no investable cash)."
        return plan

    tickers = set(holdings_value) | set(target_weights)
    sells: list[RebalanceOrder] = []
    buys: list[tuple[float, RebalanceOrder]] = []   # (under-target pp, order)

    for t in sorted(tickers):
        target_pct = float(target_weights.get(t, 0.0))
        current_val = float(holdings_value.get(t, 0.0) or 0.0)
        current_pct = current_val / pot * 100.0
        drift_pp = current_pct - target_pct
        if abs(drift_pp) < band_pp:
            continue
        price = prices.get(t)
        if not price or price <= 0:
            plan.skipped.append(t)
            continue

        lot = max(1, int(lot_size_fn(t)))
        target_val = pot * target_pct / 100.0
        delta_val = target_val - current_val          # >0 buy, <0 sell
        lot_value = price * lot
        lots = int(round(abs(delta_val) / lot_value))
        if lots <= 0:
            continue
        shares = lots * lot
        value = shares * price

        if delta_val < 0:   # over target -> SELL
            # never sell more shares than actually held
            held_shares = int(round(current_val / price))
            shares = min(shares, (held_shares // lot) * lot)
            if shares <= 0:
                continue
            value = shares * price
            sells.append(RebalanceOrder(
                ticker=t, action="SELL", lots=shares // lot, shares=shares,
                price=price, value=value, drift_pp=drift_pp,
                reason=f"over target by {drift_pp:+.1f}pp"))
        else:               # under target -> BUY (subject to cash below)
            buys.append((drift_pp, RebalanceOrder(
                ticker=t, action="BUY", lots=lots, shares=shares,
                price=price, value=value, drift_pp=drift_pp,
                reason=f"under target by {drift_pp:+.1f}pp")))

    # Sells free up cash; execute them all (each already capped to holdings).
    available = investable_cash
    for o in sells:
        plan.orders.append(o)
        plan.total_sell_value += o.value
        available += o.value

    # Buys, most-under-target first, capped so we never exceed available cash.
    buys.sort(key=lambda kv: kv[0])   # most negative drift (most under) first
    for _, o in buys:
        lot = max(1, int(lot_size_fn(o.ticker)))
        lot_value = o.price * lot
        affordable_lots = int(available // lot_value)
        lots = min(o.lots, affordable_lots)
        if lots <= 0:
            continue
        shares = lots * lot
        value = shares * o.price
        placed = RebalanceOrder(ticker=o.ticker, action="BUY", lots=lots,
                                shares=shares, price=o.price, value=value,
                                drift_pp=o.drift_pp, reason=o.reason)
        plan.orders.append(placed)
        plan.total_buy_value += value
        available -= value

    plan.cash_after = cash - plan.total_buy_value + plan.total_sell_value
    if cost_model is not None:
        # Per-order estimate: the spread leg is price-aware (half_spread_at),
        # so a cheap tick-floored name is costed honestly, not with a flat
        # percentage. Buy leg pays commission+spread; sell leg pays fee+tax+spread.
        est = 0.0
        for o in plan.orders:
            hs = cost_model.half_spread_at(o.price)
            if o.action == "BUY":
                est += o.value * (cost_model.buy_commission + hs)
            else:
                est += o.value * (cost_model.sell_total + hs)
        plan.est_cost = est

    if plan.is_noop:
        plan.note = (f"No rebalancing needed — every holding is within "
                     f"{band_pp:.0f}pp of its target.")
    else:
        plan.note = (f"{len(plan.orders)} order(s) to move toward target "
                     f"(band {band_pp:.0f}pp).")
    return plan
