"""
Fundamental value screen — ported from the legacy kala_fundamental_only.py
prototype into small, pure, testable functions.

STATUS: SNAPSHOT SCREENING TOOL ONLY. NOT walk-forward validated, and it
cannot be, honestly, with the data this project has access to: yfinance's
``.info``/statements endpoints return the CURRENT fundamentals only, not
what a screener would have seen on any past date. Backtesting this against
historical prices while feeding it today's P/E, ROE, book value, etc. would
be a look-ahead bug — exactly the class of mistake this project already
caught and retracted once (see PROJECT_STATUS.md, "Retraction"). A real
validation would need a point-in-time historical-fundamentals data source
this project does not have.

UPDATE (2026-07-23): a real candidate for that missing data source was
found. Invezgo's ``/analysis/financial-statement/{code}`` (params:
``statement`` BS/IS/CF, ``type`` FY/Q/Q1-4, ``limit``) confirmed via real
probe calls to return GENUINE multiple historical periods, not a
snapshot -- an 8-quarter pull (Q1 2026 back through Q2 2023) and a 7-year
annual pull (FY2025 back through FY2019) both came back with real,
period-line-item values that actually differ quarter to quarter / year to
year (Indonesian-language line items, e.g. "Pendapatan bunga" = interest
income, "Beban bunga" = interest expense; each row is one line item, with
a ``values`` array of {year, period, amount} per period). See
``probe_financial_statement.py`` and ``results/invezgo_probe_financial_
statement_*.json`` for the raw samples this was confirmed against.

STILL UNKNOWN, and the actual blocker before trusting this for real:
POINT-IN-TIME INTEGRITY. Does querying "FY2020" today return exactly what
was reported back in 2020, or a since-restated figure (companies do
restate financials)? If restated, feeding "FY2020 as currently known" into
a 2020 backtest is the exact same look-ahead bug this file already warns
about, just with better-looking data.

UPDATE (2026-07-23, cont.): the raw response was inspected for the first of
the two proposed checks -- a revision/amendment indicator -- and it has
NONE. The complete field set is amount, col, columns, display_order, id,
is_abstract, level, name, parent_id, period, rows, values, year (see
tests/fixtures/invezgo_financial_statement_bbca_is_*.json). No revision
flag, and no filing/disclosure date either -- so a single pull can neither
distinguish an original figure from a restated one, nor tell you when a
figure became public. That leaves only the SECOND check -- compare the same
period pulled at two real dates -- which needs calendar time to pass and so
cannot be answered in one session. The infrastructure to answer it later is
now built: kala/fundamental_archive.py stores DATED snapshots (observed_date
in the primary key) and exposes diff_observations (restatement detector) and
as_of (never-read-from-the-future point-in-time read); archive_fundamentals.py
is the daily/monthly CLI that lays the snapshots down, same
archive-so-it's-eventually-backtestable pattern as kala/sentiment_archive.py.
Until diff_observations has been run across snapshots taken weeks/months
apart and comes back clean, this remains a CURRENT-snapshot screen only, not
a validated point-in-time signal.

So: use this to rank CURRENT candidates for the watchlist (kala.watchlist
already has the fair-value-alert machinery for that loop), not as a signal
fed into the paper trader or claimed as validated anywhere.

Formulas (Graham intrinsic value, simplified DCF, sector P/E, the 100-point
value score, the decision buckets) are carried over unchanged from the
legacy script — only the plumbing changed: pure functions taking a plain
``dict`` of fundamentals in, no yfinance import, no I/O, no emoji, easy to
unit test.
"""

from __future__ import annotations

from dataclasses import dataclass

_SECTOR_FAIR_PE = {
    "Financial Services": 12,
    "Basic Materials": 10,
    "Energy": 8,
    "Consumer Cyclical": 15,
    "Consumer Defensive": 18,
    "Healthcare": 20,
    "Technology": 25,
    "Communication Services": 14,
    "Industrials": 13,
    "Real Estate": 10,
    "Utilities": 12,
}
_DEFAULT_FAIR_PE = 12


def graham_intrinsic_value(fundamentals: dict) -> float | None:
    """IV = sqrt(22.5 * EPS * book value per share). None unless both
    inputs are positive numbers -- Graham's formula is undefined otherwise."""
    eps = fundamentals.get("trailing_eps")
    book_value = fundamentals.get("book_value")
    if eps and book_value and eps > 0 and book_value > 0:
        return (22.5 * eps * book_value) ** 0.5
    return None


def dcf_simplified(fundamentals: dict) -> float | None:
    """5-year simplified DCF: growth capped at 15%, 12% discount rate
    (Indonesia risk-adjusted), 3% terminal growth."""
    fcf = fundamentals.get("free_cash_flow")
    shares = fundamentals.get("shares_outstanding")
    growth = fundamentals.get("earnings_growth")
    if not fcf or not shares or fcf <= 0 or shares <= 0:
        return None

    growth_rate = min(growth, 0.15) if growth and growth > 0 else 0.05
    discount_rate = 0.12
    terminal_growth = 0.03

    pv_sum = sum(
        fcf * ((1 + growth_rate) ** year) / ((1 + discount_rate) ** year)
        for year in range(1, 6)
    )
    terminal_fcf = fcf * ((1 + growth_rate) ** 5) * (1 + terminal_growth)
    terminal_value = terminal_fcf / (discount_rate - terminal_growth)
    pv_terminal = terminal_value / ((1 + discount_rate) ** 5)

    return (pv_sum + pv_terminal) / shares


def pe_based_value(fundamentals: dict) -> float | None:
    """Fair value = EPS x sector-typical P/E (default 12x if sector unknown)."""
    eps = fundamentals.get("trailing_eps")
    if not eps or eps <= 0:
        return None
    sector = fundamentals.get("sector", "")
    fair_pe = _SECTOR_FAIR_PE.get(sector, _DEFAULT_FAIR_PE)
    return eps * fair_pe


def composite_intrinsic_value(fundamentals: dict) -> float | None:
    """Weighted blend of the three methods above (Graham 40% / DCF 30% /
    P/E 30%), renormalized over whichever methods actually produced a
    value -- None only if all three are undefined."""
    candidates = [
        (graham_intrinsic_value(fundamentals), 0.4),
        (dcf_simplified(fundamentals), 0.3),
        (pe_based_value(fundamentals), 0.3),
    ]
    values = [(v, w) for v, w in candidates if v]
    if not values:
        return None
    total_weight = sum(w for _, w in values)
    return sum(v * w / total_weight for v, w in values)


def margin_of_safety_pct(current_price: float, intrinsic_value: float) -> float:
    """Positive = trading BELOW intrinsic value (a discount, i.e. margin of
    safety); negative = overvalued."""
    return (intrinsic_value - current_price) / current_price * 100.0


def value_score(fundamentals: dict, intrinsic_value: float | None) -> tuple[float, list[str]]:
    """0-100: margin of safety (30) + profitability quality (25) +
    financial health (20) + growth potential (15) + dividend yield (10)."""
    score = 0.0
    notes: list[str] = []
    current_price = fundamentals.get("current_price")

    if current_price and intrinsic_value:
        mos = margin_of_safety_pct(current_price, intrinsic_value)
        if mos > 40:
            score += 30
            notes.append("huge margin of safety (>40%)")
        elif mos > 30:
            score += 25
            notes.append("strong margin (30-40%)")
        elif mos > 15:
            score += 20
            notes.append("good margin (15-30%)")
        elif mos > 0:
            score += 10
            notes.append("slight margin (0-15%)")
        elif mos > -15:
            score += 5
            notes.append("near fair value")
        else:
            notes.append("overvalued (MoS < -15%)")
    else:
        notes.append("cannot calc margin")

    roe = fundamentals.get("roe")
    if roe and roe > 0:
        if roe > 0.20:
            score += 15
            notes.append(f"excellent ROE ({roe * 100:.1f}%)")
        elif roe > 0.15:
            score += 12
            notes.append(f"strong ROE ({roe * 100:.1f}%)")
        elif roe > 0.10:
            score += 8
            notes.append(f"good ROE ({roe * 100:.1f}%)")
        else:
            notes.append(f"weak ROE ({roe * 100:.1f}%)")

    profit_margin = fundamentals.get("profit_margin")
    if profit_margin and profit_margin > 0:
        if profit_margin > 0.15:
            score += 10
            notes.append(f"high margin ({profit_margin * 100:.1f}%)")
        elif profit_margin > 0.05:
            score += 5
            notes.append(f"good margin ({profit_margin * 100:.1f}%)")
        else:
            notes.append(f"low margin ({profit_margin * 100:.1f}%)")

    debt_equity = fundamentals.get("debt_equity")
    if debt_equity is not None:
        if debt_equity < 50:
            score += 10
            notes.append(f"low debt ({debt_equity:.1f}%)")
        elif debt_equity < 100:
            score += 5
            notes.append(f"moderate debt ({debt_equity:.1f}%)")
        else:
            notes.append(f"high debt ({debt_equity:.1f}%)")

    current_ratio = fundamentals.get("current_ratio")
    if current_ratio:
        if current_ratio > 1.5:
            score += 10
            notes.append(f"strong liquidity ({current_ratio:.2f})")
        elif current_ratio > 1.0:
            score += 5
            notes.append(f"adequate liquidity ({current_ratio:.2f})")
        else:
            notes.append(f"liquidity concern ({current_ratio:.2f})")

    earnings_growth = fundamentals.get("earnings_growth")
    if earnings_growth and earnings_growth > 0:
        if earnings_growth > 0.15:
            score += 10
            notes.append(f"strong growth ({earnings_growth * 100:.1f}%)")
        elif earnings_growth > 0.05:
            score += 5
            notes.append(f"moderate growth ({earnings_growth * 100:.1f}%)")
        else:
            notes.append(f"slow growth ({earnings_growth * 100:.1f}%)")
    elif earnings_growth and earnings_growth < -0.10:
        notes.append(f"value-trap warning: earnings declining ({earnings_growth * 100:.1f}%)")

    revenue_growth = fundamentals.get("revenue_growth")
    if revenue_growth and revenue_growth > 0.05:
        score += 5
        notes.append(f"revenue growing ({revenue_growth * 100:.1f}%)")

    div_yield = fundamentals.get("dividend_yield")
    if div_yield and div_yield > 0:
        if div_yield > 0.05:
            score += 10
            notes.append(f"high dividend ({div_yield * 100:.2f}%)")
        elif div_yield > 0.03:
            score += 5
            notes.append(f"good dividend ({div_yield * 100:.2f}%)")
        else:
            notes.append(f"low dividend ({div_yield * 100:.2f}%)")

    return score, notes


def investment_decision(value_score_: float, margin_of_safety: float | None,
                        fundamentals: dict) -> tuple[str, str]:
    """(decision, confidence). Value-trap check (earnings falling >10%)
    overrides the score/MoS buckets -- cheap-and-declining is a trap, not
    a bargain."""
    earnings_growth = fundamentals.get("earnings_growth")
    if earnings_growth and earnings_growth < -0.10:
        return "VALUE TRAP", "caution - cheap but declining business"

    mos = margin_of_safety if margin_of_safety is not None else 0.0
    if value_score_ >= 75 and mos > 30:
        return "STRONG BUY", "high confidence - excellent opportunity"
    if value_score_ >= 60 and mos > 15:
        return "BUY", "good confidence - undervalued"
    if value_score_ >= 50 or -15 < mos < 15:
        return "HOLD", "neutral - fair value"
    return "AVOID", "low confidence - overvalued or poor quality"


@dataclass(frozen=True)
class ScreenResult:
    ticker: str
    intrinsic_value: float | None
    margin_of_safety: float | None
    score: float
    decision: str
    confidence: str
    notes: tuple[str, ...]


def screen_stock(ticker: str, fundamentals: dict) -> ScreenResult:
    """Screen one ticker's CURRENT fundamentals snapshot. ``fundamentals``
    keys used: current_price, trailing_eps, book_value, free_cash_flow,
    shares_outstanding, earnings_growth, revenue_growth, sector, roe,
    profit_margin, debt_equity, current_ratio, dividend_yield -- all
    optional, missing ones just skip that component."""
    iv = composite_intrinsic_value(fundamentals)
    current_price = fundamentals.get("current_price")
    mos = margin_of_safety_pct(current_price, iv) if (current_price and iv) else None
    score, notes = value_score(fundamentals, iv)
    decision, confidence = investment_decision(score, mos, fundamentals)
    return ScreenResult(ticker=ticker, intrinsic_value=iv, margin_of_safety=mos,
                        score=score, decision=decision, confidence=confidence,
                        notes=tuple(notes))


def screen_universe(fundamentals_by_ticker: dict[str, dict]) -> list[ScreenResult]:
    """Screen every ticker, ranked best-score-first (ties broken by wider
    margin of safety)."""
    results = [screen_stock(t, f) for t, f in fundamentals_by_ticker.items()]
    results.sort(key=lambda r: (r.score, r.margin_of_safety or -1e9), reverse=True)
    return results
