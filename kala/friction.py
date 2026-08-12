"""
Transaction-cost (friction) tracker — how much has trading itself cost you,
in rupiah, and how much of your reported P&L is an accounting illusion.

WHY THIS MATTERS MORE THAN ANY SIGNAL WORK
--------------------------------------------
Sixteen hypotheses have been tested on this universe and none survived the
alpha check (PROJECT_STATUS.md). When expected return per trade is ~zero
BEFORE costs, every round trip is a guaranteed expected LOSS equal to its
friction. Under that condition the only lever that reliably moves the
outcome is trading less. So the total spent on friction stops being a
footnote and becomes the main number to watch.

THE ACCOUNTING GAP THIS EXISTS TO SURFACE
--------------------------------------------
``PaperTrader.manual_buy``/``manual_sell`` USED to record the RAW price you
typed in and add no synthetic commission, so paper P/L lined up with the
figure on your broker screen. That kept reconciliation easy -- but it meant
the paper state never deducted the commission, final tax and spread you
really paid, while automated fills DID embed them via the cost model. One
equity number then held two different accounting standards.

Since v3.9 manual fills charge costs too, so new trades are recorded the
same way automated ones always were. Trades booked BEFORE that change are
untouched -- rewriting them would falsify history -- which makes a real book
a MIXED one, and this module the thing that keeps the two straight.

For the raw-price trades, ``PaperTrader.summary()``'s return_pct remains
OPTIMISTIC by roughly the round-trip friction on each -- about 0.4-0.8% per
round trip on IDX, large relative to the few-percent moves this strategy
targets. For the costed ones it is already honest.

This module quantifies that gap. It does not change how trades are recorded;
it reports what those records leave out.

WHAT THE NUMBERS MEAN
---------------------
Friction is computed at the configured ``CostModel`` rates on the prices
actually recorded:

  buy leg   price * shares * (buy_commission + half_spread_at(price))
  sell leg  price * shares * (sell_total     + half_spread_at(price))

Records written since v3.9 say which world they belong to, so the split is
read per trade rather than assumed for the whole book:

  fill ledger    ``"costed": True`` on a fill whose price includes costs
  closed trade   ``"costed": True``            -- the SELL leg was net
                 ``"entry_costed_frac": 0..1`` -- share of the BUY leg's
                 cost basis that was booked with costs (a position opened by
                 hand before v3.9 and sold after it is genuinely partial)

``already_charged`` is the fallback for records with no marker -- i.e. every
trade booked before v3.9 -- and must still be set by the caller, because
those records do not say which path filled them:

  False (default, correct for an older manual book) -- the recorded prices
        are raw, friction was paid at the broker but never deducted here, so
        the reported P&L is overstated by this amount.
  True  -- fills already embedded costs; the figure is then "what you have
        already paid", NOT an additional deduction, and subtracting it again
        would double-count.

Friction on an already-costed record is computed from the cost-INCLUSIVE
price rather than the raw one, overstating that leg by the cost rate itself
(~0.3% of the leg, i.e. 0.001% of basis). It is reported as money already
spent, never deducted again, so the imprecision cannot move net P&L.
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import CostModel


@dataclass(frozen=True)
class FrictionReport:
    n_closed: int = 0
    n_open: int = 0
    closed_friction_idr: float = 0.0      # both legs, on closed trades
    open_friction_idr: float = 0.0        # buy leg only (sell not yet paid)
    total_friction_idr: float = 0.0
    # Split of total_friction_idr by accounting world. "charged" is already
    # embedded in the recorded prices (nothing further to deduct);
    # "uncharged" was paid at the broker but never taken out of paper P&L,
    # and is the only part net_pnl_idr subtracts.
    charged_friction_idr: float = 0.0
    uncharged_friction_idr: float = 0.0
    cost_basis_idr: float = 0.0
    friction_pct_of_basis: float = 0.0
    recorded_pnl_idr: float = 0.0         # realized P&L as the state records it
    net_pnl_idr: float = 0.0              # after deducting closed-trade friction
    friction_share_of_gross_pct: float = 0.0   # of gross PROFIT, when positive
    days_observed: int = 0
    round_trips_per_year: float = 0.0
    projected_annual_friction_idr: float = 0.0
    projected_annual_drag_pct: float = 0.0
    already_charged: bool = False
    note: str = ""


def _leg(price: float, shares: float, rate: float, costs: CostModel) -> float:
    """Friction on one leg: proportional rate plus the price-aware half
    spread. Guards junk input by contributing nothing rather than a NaN that
    would silently poison every total downstream."""
    if not price or price <= 0 or not shares or shares <= 0:
        return 0.0
    return price * shares * (rate + costs.half_spread_at(price))


def _frac(value, default: float) -> float:
    """A stored costed-fraction clamped to [0, 1], or ``default`` when the
    record predates the marker. Junk (None, a string, NaN) falls back to the
    default rather than poisoning the split with a nonsense weight."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    if f != f:                      # NaN
        return default
    return max(0.0, min(1.0, f))


def _fills(pos: dict) -> list[dict]:
    """Per-fill ledger for a stored position. Imported lazily so this module
    keeps its light dependency footprint (config only) at import time."""
    from .papertrade import position_fills
    return position_fills(pos)


def _days_between(a: str, b: str) -> int:
    """Whole days between two ISO dates, 0 if either is unparseable. ISO
    strings compare and subtract correctly via date(), and the state is
    written with date_str_today() so the format is consistent."""
    from datetime import date
    try:
        ya, ma, da = (int(x) for x in a[:10].split("-"))
        yb, mb, db = (int(x) for x in b[:10].split("-"))
        return abs((date(yb, mb, db) - date(ya, ma, da)).days)
    except (ValueError, AttributeError, TypeError):
        return 0


def friction_report(state: dict, costs: CostModel | None = None,
                    already_charged: bool = False,
                    today: str | None = None) -> FrictionReport:
    """Total friction implied by a PaperTrader state.

    ``state``            the loaded paper_state.json dict
    ``costs``            CostModel to price the legs (default: IDX defaults)
    ``already_charged``  see the module docstring -- False for a manual book
    ``today``            ISO date closing the annualization window. PASS THE
                         REAL DATE for an honest pace: the default closes the
                         window at the last recorded trade, which measures the
                         rate DURING an active burst and overstates the
                         long-run pace for anyone who then stopped trading for
                         a while. The default exists so the function stays
                         deterministic for tests and reproducible reports; the
                         CLI passes the actual date.
    """
    costs = costs or CostModel()
    positions = state.get("positions", {}) or {}
    log = state.get("log", []) or []

    default_frac = 1.0 if already_charged else 0.0

    closed_friction = 0.0
    closed_charged = 0.0     # already embedded in recorded prices
    closed_uncharged = 0.0   # paid at the broker, never deducted from paper P&L
    open_charged = 0.0
    open_uncharged = 0.0
    recorded_pnl = 0.0
    closed_basis = 0.0
    dates: list[str] = []

    for t in log:
        entry = float(t.get("entry") or 0.0)
        exit_px = float(t.get("exit") or 0.0)
        shares = float(t.get("shares") or 0.0)
        if entry <= 0 or shares <= 0:
            continue
        buy_leg = _leg(entry, shares, costs.buy_total, costs)
        sell_leg = _leg(exit_px, shares, costs.sell_total, costs)
        # The two legs are classified independently: a position opened by
        # hand before costs were charged and closed after can have a raw buy
        # and a net sell inside the same round trip.
        buy_frac = _frac(t.get("entry_costed_frac"), default_frac)
        sell_costed = bool(t["costed"]) if "costed" in t else already_charged
        closed_charged += buy_leg * buy_frac + (sell_leg if sell_costed else 0.0)
        closed_uncharged += (buy_leg * (1.0 - buy_frac)
                             + (0.0 if sell_costed else sell_leg))
        closed_friction += buy_leg + sell_leg
        recorded_pnl += (exit_px - entry) * shares
        closed_basis += entry * shares
        for key in ("entry_date", "date"):
            if t.get(key):
                dates.append(str(t[key]))

    open_friction = 0.0
    open_basis = 0.0
    for p in positions.values():
        entry = float(p.get("entry_price") or 0.0)
        shares = float(p.get("shares") or 0.0)
        if entry <= 0 or shares <= 0:
            continue
        # Priced per FILL, not off the blended average, because one position
        # can hold raw legacy shares alongside costed ones added later.
        # Only the buy leg has been paid; the sell leg is a future cost and is
        # deliberately NOT counted, so this never overstates money spent.
        for f in _fills(p):
            leg = _leg(f["price"], f["shares"], costs.buy_total, costs)
            open_friction += leg
            if f.get("costed", already_charged):
                open_charged += leg
            else:
                open_uncharged += leg
        open_basis += entry * shares
        if p.get("entry_date"):
            dates.append(str(p["entry_date"]))

    total_friction = closed_friction + open_friction
    cost_basis = closed_basis + open_basis

    span_end = today or (max(dates) if dates else "")
    span_start = min(dates) if dates else ""
    days = _days_between(span_start, span_end) if (span_start and span_end) else 0

    n_closed = sum(1 for t in log
                   if float(t.get("entry") or 0) > 0 and float(t.get("shares") or 0) > 0)
    per_year = (n_closed / days * 365.0) if days > 0 else 0.0
    avg_friction_per_rt = (closed_friction / n_closed) if n_closed else 0.0
    projected_annual = per_year * avg_friction_per_rt
    projected_drag = (projected_annual / cost_basis * 100.0) if cost_basis > 0 else 0.0

    charged = closed_charged + open_charged
    uncharged = closed_uncharged + open_uncharged

    # Only friction the records never took out is deducted. Subtracting the
    # charged part too would double-count it: it is already inside the
    # recorded entry/exit prices, and so already inside recorded_pnl. Open
    # positions are excluded either way -- this line is about REALIZED P&L.
    net_pnl = recorded_pnl - closed_uncharged
    gross_share = (closed_uncharged / recorded_pnl * 100.0) if recorded_pnl > 0 else 0.0

    if uncharged > 0 and charged > 0:
        note = ("Mixed book: trades booked before costs were charged carry raw "
                "prices (that friction was paid but never deducted from paper "
                "P&L), while newer ones already include it. Only the raw part "
                "is subtracted below.")
    elif uncharged > 0:
        note = ("Recorded prices are raw: this friction was paid at your broker "
                "but never deducted from paper P&L, so reported returns are "
                "overstated by this much.")
    else:
        note = ("Costs were already embedded in the recorded fills: this is what "
                "you have ALREADY paid, not a further deduction.")

    return FrictionReport(
        n_closed=n_closed, n_open=len(positions),
        closed_friction_idr=closed_friction, open_friction_idr=open_friction,
        total_friction_idr=total_friction,
        charged_friction_idr=charged, uncharged_friction_idr=uncharged,
        cost_basis_idr=cost_basis,
        friction_pct_of_basis=(total_friction / cost_basis * 100.0) if cost_basis > 0 else 0.0,
        recorded_pnl_idr=recorded_pnl, net_pnl_idr=net_pnl,
        friction_share_of_gross_pct=gross_share,
        days_observed=days, round_trips_per_year=per_year,
        projected_annual_friction_idr=projected_annual,
        projected_annual_drag_pct=projected_drag,
        already_charged=already_charged, note=note)


def _idr(x: float) -> str:
    return f"Rp{x:,.0f}"


def format_friction(r: FrictionReport) -> str:
    """Plain-text report. Leads with the rupiah total, because a percentage
    is easy to wave away and a rupiah figure is not."""
    if not r.n_closed and not r.n_open:
        return "FRICTION — no trades recorded."

    lines = [
        "TRANSACTION-COST (FRICTION) REPORT",
        f"  {r.n_closed} closed round trip(s), {r.n_open} open position(s), "
        f"cost basis {_idr(r.cost_basis_idr)}",
        "",
        f"  Friction on closed round trips : {_idr(r.closed_friction_idr)}",
        f"  Friction on open buys so far   : {_idr(r.open_friction_idr)}"
        f"   (sell leg not yet paid)",
        f"  TOTAL PAID TO TRADE            : {_idr(r.total_friction_idr)}"
        f"  ({r.friction_pct_of_basis:.2f}% of basis)",
        "",
    ]

    if r.charged_friction_idr > 0 and r.uncharged_friction_idr > 0:
        lines += [
            "  OF WHICH",
            f"    already in your recorded prices : {_idr(r.charged_friction_idr)}",
            f"    never deducted (raw-price era)  : {_idr(r.uncharged_friction_idr)}",
            "",
        ]

    if r.recorded_pnl_idr != r.net_pnl_idr:
        lines += [
            "  REPORTED vs REAL (closed trades)",
            f"    P&L as recorded : {_idr(r.recorded_pnl_idr)}",
            f"    less friction   : {_idr(r.net_pnl_idr - r.recorded_pnl_idr)}",
            f"    P&L in reality  : {_idr(r.net_pnl_idr)}",
        ]
        if r.recorded_pnl_idr > 0:
            lines.append(
                f"    -> friction ate {r.friction_share_of_gross_pct:.0f}% of the "
                f"gross profit you think you made.")
        elif r.recorded_pnl_idr < 0:
            lines.append("    -> already negative before costs; friction deepens it.")
        lines.append("")

    if r.days_observed > 0 and r.round_trips_per_year > 0:
        lines += [
            f"  PACE ({r.days_observed} days observed)",
            f"    ~{r.round_trips_per_year:.0f} round trips/year at this rate",
            f"    projected friction: {_idr(r.projected_annual_friction_idr)}/year "
            f"= {r.projected_annual_drag_pct:.1f}% of basis",
            "",
            "    Small sample: a few weeks of trading extrapolated to a year is a "
            "rough indication of pace, not a forecast.",
            "",
        ]

    lines.append(f"  NOTE: {r.note}")
    lines.append(
        "  With no measured edge (16 hypotheses, all null), expected return per "
        "trade is ~0 BEFORE costs — which makes each round trip an expected loss "
        "of roughly its friction. Trading less is the only lever that reliably "
        "improves this number.")
    return "\n".join(lines)
