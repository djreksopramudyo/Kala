"""
Time-weighted return (TWR) — the "one honest number" that deposits and
withdrawals can't distort.

WHY THIS EXISTS
---------------
``PaperTrader.summary()``'s ``return_pct`` is a SIMPLE return: current
equity vs. ``start_capital``. ``PaperTrader.add_capital`` already bumps
``start_capital`` by the deposit amount so a single deposit doesn't read
as an instant "gain" -- a reasonable one-deposit fix. But with MULTIPLE
deposits at different times, a single adjusted base can't correctly
weight a deposit made right before a rally against one made right before
a drawdown -- the money wasn't at risk for the same stretch of time or the
same market conditions. Chain-linking sub-period returns around each
deposit (the standard TWR method professional funds report) fixes that:
performance in each sub-period is measured on ITS OWN base, then the
sub-period returns compound together.

SCOPE / HONEST LIMITATION
--------------------------
This project has no daily mark-to-market equity history (see
``chart.py``'s module docstring for the same limitation on the equity
curve) -- only REALIZED trade P&L (``PaperTrader.log``) and dated deposits
(``PaperTrader.capital_additions``). So each INTERMEDIATE sub-period
boundary (i.e. every boundary except the most recent one) uses realized
P&L as of that date as a proxy for portfolio value -- unrealized P&L on a
position that happened to be open exactly at a deposit date gets folded
into the NEXT sub-period instead of split precisely at the deposit. The
FINAL (most recent) sub-period uses the caller-supplied CURRENT equity
(mark-to-market, from live prices), so today's number is accurate; only
past deposit boundaries carry this approximation. Flagged in
``TWRResult.note`` so it's visible wherever this is displayed, not just
here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class TWRResult:
    twr_pct: float
    n_sub_periods: int
    cagr_pct: float | None
    max_drawdown_pct: float
    equity_curve: list[tuple[str, float]] = field(default_factory=list)
    # Which series max_drawdown_pct was measured on:
    #   "mark-to-market"          daily market values throughout — the real figure
    #   "mark-to-market-partial"  as above, but some lot had no price history and
    #                             was held flat at cost, so troughs are damped
    #   "realized-only"           only losses locked in by selling are visible
    # The latter two understate, always in the flattering direction. Never
    # display the number without the corresponding qualifier.
    drawdown_basis: str = "realized-only"
    # Ticker-level detail behind a "-partial" basis, straight from
    # kala.chart.mark_to_market_points.
    drawdown_warnings: list[str] = field(default_factory=list)
    note: str = (
        "Time-weighted return: chain-linked around deposit dates so cash "
        "additions don't distort performance. Intermediate boundaries use "
        "REALIZED P&L as of that date (no historical mark-to-market "
        "snapshot exists); the final period uses today's actual equity."
    )

    @property
    def drawdown_is_real(self) -> bool:
        """True when the figure came from market values rather than the
        realized-only fallback. A "-partial" curve still qualifies — it is
        mark-to-market for everything that could be priced — but callers
        must surface ``drawdown_warnings`` alongside it."""
        return self.drawdown_basis.startswith("mark-to-market")

    @property
    def drawdown_is_complete(self) -> bool:
        return self.drawdown_basis == "mark-to-market"


def _merged_events(log: list[dict], capital_additions: list[dict]) -> list[dict]:
    events = [
        {"date": str(t.get("date", "")), "kind": "trade",
         "amount": (t.get("exit", 0.0) - t.get("entry", 0.0)) * t.get("shares", 0)}
        for t in log
    ]
    events += [
        {"date": str(d.get("date", "")), "kind": "deposit", "amount": float(d.get("amount", 0.0))}
        for d in capital_additions
    ]
    events.sort(key=lambda e: e["date"])
    return events


def compute_time_weighted_return(log: list[dict], capital_additions: list[dict],
                                 original_capital: float, current_equity: float,
                                 account_start_date: str | None = None,
                                 today: date | None = None,
                                 equity_points: list | None = None,
                                 equity_points_warnings: list | None = None) -> TWRResult:
    """``original_capital``: starting capital BEFORE any deposits (i.e.
    ``PaperTrader.start_capital`` minus the sum of ``capital_additions``).
    ``current_equity``: TODAY's real mark-to-market equity (e.g.
    ``PaperTrader.summary()['equity']``), used as the final period's end
    value so unrealized P&L on open positions is captured for the most
    recent stretch.

    ``equity_points``: optional ``[(iso_date, equity)]`` daily mark-to-market
    series, from ``kala.chart.mark_to_market_points``. **Supply this whenever
    you have it.** Without it the drawdown is measured on the realized-only
    curve, which steps solely when a trade CLOSES — so a position that fell
    45% while held and was then closed flat reports a 0% drawdown. That
    understatement is always in the flattering direction, and the result is
    tagged ``drawdown_basis="realized-only"`` so callers can say so rather
    than presenting it as the real figure.

    ``equity_points_warnings``: the second half of
    ``mark_to_market_points``'s return value. A lot with no price history is
    held flat at cost there, which damps the very troughs a drawdown is meant
    to expose — so a curve carrying warnings is tagged
    ``"mark-to-market-partial"`` rather than being passed off as complete.
    """
    events = _merged_events(log, capital_additions)

    sub_returns: list[float] = []
    equity_curve: list[tuple[str, float]] = [("start", original_capital)]
    period_start_value = original_capital
    running = original_capital

    for e in events:
        if e["kind"] == "deposit":
            if period_start_value > 0:
                sub_returns.append(running / period_start_value - 1.0)
            running += e["amount"]
            period_start_value = running
            equity_curve.append((e["date"], running))
        else:
            running += e["amount"]
            equity_curve.append((e["date"], running))

    if period_start_value > 0:
        sub_returns.append(current_equity / period_start_value - 1.0)
    equity_curve.append((str(today or "today"), current_equity))

    twr = 1.0
    for r in sub_returns:
        twr *= (1.0 + r)
    twr -= 1.0

    # Drawdown wants the daily mark-to-market series when one exists. The
    # chain-linked TWR above is unaffected either way — only this figure is.
    dd_series = [v for _, v in (equity_points or [])]
    dd_warnings = list(equity_points_warnings or []) if dd_series else []
    if not dd_series:
        basis = "realized-only"
        dd_series = [v for _, v in equity_curve]
    else:
        basis = "mark-to-market-partial" if dd_warnings else "mark-to-market"

    peak = -float("inf")
    max_dd = 0.0
    for v in dd_series:
        peak = max(peak, v)
        if peak > 0:
            max_dd = min(max_dd, (v - peak) / peak)

    cagr_pct = None
    if account_start_date:
        try:
            start_d = date.fromisoformat(account_start_date)
            end_d = today or date.today()
            days = (end_d - start_d).days
            if days > 0 and (1.0 + twr) > 0:
                cagr_pct = ((1.0 + twr) ** (365.0 / days) - 1.0) * 100.0
        except ValueError:
            pass

    return TWRResult(twr_pct=twr * 100.0, n_sub_periods=len(sub_returns),
                     cagr_pct=cagr_pct, max_drawdown_pct=max_dd * 100.0,
                     equity_curve=equity_curve, drawdown_basis=basis,
                     drawdown_warnings=dd_warnings)
