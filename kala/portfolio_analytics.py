"""
Portfolio analytics — concentration and correlation across CURRENT open
positions.

WHY THIS EXISTS
---------------
Every guardrail in this project (entries.py's vetoes, risk-based sizing)
looks at ONE candidate at a time. Nothing looks at the portfolio as a
whole: five "different" momentum names that are all banks, or five names
that move in near-lockstep, is one concentrated bet wearing five tickers,
not five independent ones. This module answers "how diversified is what I
actually hold right now" -- position-weight concentration (Herfindahl
index) and pairwise return correlation among held names.

Not a signal, not a veto -- a read-only report. Wire its output into
/performance or a pre-buy check yourself if you want it to gate anything;
nothing here changes existing behavior.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


def position_weights(shares_by_ticker: dict[str, float],
                     current_prices: dict[str, float]) -> dict[str, float]:
    """Market-value weight (0-100) of each ticker within the portfolio of
    tickers actually priced. Tickers missing a current price are skipped
    (not zero-weighted -- an unpriced position isn't "0% of the book", it's
    unknown, and silently including it as zero would understate real
    concentration in whatever DOES have a price)."""
    values = {t: shares * current_prices[t] for t, shares in shares_by_ticker.items()
             if t in current_prices and current_prices[t] > 0}
    total = sum(values.values())
    if total <= 0:
        return {}
    return {t: v / total * 100.0 for t, v in values.items()}


def herfindahl_index(weights_pct: dict[str, float]) -> float:
    """Sum of squared weight fractions (0-1 fraction, not percent) -- the
    standard concentration measure. 1/N for N equal-weighted positions
    (e.g. 0.20 for 5 equal names); 1.0 for a single-name portfolio. Higher
    = more concentrated."""
    if not weights_pct:
        return 0.0
    return sum((w / 100.0) ** 2 for w in weights_pct.values())


def effective_n_positions(weights_pct: dict[str, float]) -> float:
    """1 / HHI -- 'how many EQUALLY-weighted positions would give this same
    concentration'. A 5-position book skewed 60/10/10/10/10 has an
    effective_n well below 5, even though it nominally holds 5 names."""
    hhi = herfindahl_index(weights_pct)
    return (1.0 / hhi) if hhi > 0 else 0.0


def correlation_matrix(price_histories: dict[str, pd.Series], lookback: int = 60) -> pd.DataFrame:
    """Pairwise Pearson correlation of daily returns over the trailing
    ``lookback`` bars, aligned on overlapping dates only. Tickers with too
    little overlapping history to compute a meaningful correlation are
    dropped from the matrix rather than filled with a fake value."""
    returns = {}
    for ticker, closes in price_histories.items():
        r = closes.pct_change().dropna()
        if len(r) >= 10:
            returns[ticker] = r.tail(lookback)
    if len(returns) < 2:
        return pd.DataFrame()
    aligned = pd.DataFrame(returns).dropna(how="any")
    if len(aligned) < 10:
        return pd.DataFrame()
    return aligned.corr()


def high_correlation_pairs(corr: pd.DataFrame, threshold: float = 0.7) -> list[tuple[str, str, float]]:
    """Ticker pairs whose return correlation clears ``threshold`` --
    candidates that are functionally the same bet. Sorted highest-
    correlation first."""
    if corr.empty:
        return []
    pairs = []
    tickers = list(corr.columns)
    for i, a in enumerate(tickers):
        for b in tickers[i + 1:]:
            c = corr.loc[a, b]
            if pd.notna(c) and abs(c) >= threshold:
                pairs.append((a, b, float(c)))
    pairs.sort(key=lambda p: abs(p[2]), reverse=True)
    return pairs


def positions_vs_benchmark(positions: dict, current_prices: dict[str, float],
                           benchmark: pd.Series) -> list[dict]:
    """Per-holding return since entry vs. what the benchmark (e.g. IHSG)
    did over that SAME entry-to-today window -- 'is this position actually
    beating the index, or just riding it up?', the same alpha-vs-beta
    question ``walkforward.excess_returns`` asks of closed backtest
    trades, applied here to currently OPEN positions instead.

    ``positions``: {ticker: obj} where obj has ``.entry_price``,
    ``.entry_date``, ``.shares``, ``.peak_price`` (duck-typed --
    PaperPosition satisfies this without this module needing to import
    papertrade.py). ``benchmark``: a Close-price Series indexed by date
    (e.g. IHSG), covering at least back to the earliest entry_date.

    A position missing a current price, or whose entry_date can't be
    matched in the benchmark (index predates the fetched history), still
    gets a row -- with ``benchmark_return_pct``/``alpha_pct`` as None
    rather than being silently dropped, since "we don't know" and "beat
    the index" are different facts.
    """
    rows = []
    bench_now = float(benchmark.iloc[-1]) if len(benchmark) else None
    for ticker, pos in positions.items():
        price = current_prices.get(ticker)
        entry_price = getattr(pos, "entry_price", None)
        return_pct = None
        if price is not None and price > 0 and entry_price and entry_price > 0:
            return_pct = (price / entry_price - 1.0) * 100.0

        bench_return_pct = None
        if bench_now is not None:
            try:
                b_entry = benchmark.asof(pd.Timestamp(getattr(pos, "entry_date", None)))
                if pd.notna(b_entry) and float(b_entry) > 0:
                    bench_return_pct = (bench_now / float(b_entry) - 1.0) * 100.0
            except (TypeError, ValueError):
                pass

        alpha_pct = (return_pct - bench_return_pct) if (
            return_pct is not None and bench_return_pct is not None) else None

        rows.append({
            "ticker": ticker, "shares": getattr(pos, "shares", None),
            "entry_price": entry_price, "entry_date": getattr(pos, "entry_date", None),
            "current_price": price, "return_pct": return_pct,
            "benchmark_return_pct": bench_return_pct, "alpha_pct": alpha_pct,
        })
    rows.sort(key=lambda r: r["ticker"])
    return rows


def allocation_drift(actual_weights: dict[str, float], target_weights: dict[str, float],
                     threshold_pp: float = 5.0) -> list[dict]:
    """Per-ticker drift (percentage points) between what you actually hold
    and a target mix -- the union of tickers in either. A ticker held but
    with no target drifts toward its full actual weight (target reads as
    0); a ticker targeted but not currently held reads as fully
    under-target. Sorted biggest-drift-first, the one most worth a look.

    NOT a rebalancing instruction, same "flag, don't act" stance as every
    other read-only diagnostic in this module (mirrors Folio's own framing:
    "non-advisory rebalancing nudges" -- it tells you where you've
    drifted, never what to trade).
    """
    tickers = set(actual_weights) | set(target_weights)
    rows = []
    for t in tickers:
        actual = actual_weights.get(t, 0.0)
        target = target_weights.get(t, 0.0)
        drift = actual - target
        if drift > threshold_pp:
            flag = "OVER"
        elif drift < -threshold_pp:
            flag = "UNDER"
        else:
            flag = "ON TARGET"
        rows.append({"ticker": t, "actual_pct": actual, "target_pct": target,
                    "drift_pp": drift, "flag": flag})
    rows.sort(key=lambda r: abs(r["drift_pp"]), reverse=True)
    return rows


def sector_weights(weights_pct: dict[str, float], sector_map: dict[str, str]) -> dict[str, float]:
    """Roll position weights up to sector weights. Tickers absent from
    ``sector_map`` are grouped under 'UNKNOWN' rather than dropped -- an
    unclassified position still counts toward real concentration."""
    out: dict[str, float] = {}
    for ticker, w in weights_pct.items():
        sector = sector_map.get(ticker, "UNKNOWN")
        out[sector] = out.get(sector, 0.0) + w
    return out


@dataclass
class PortfolioAnalysis:
    weights_pct: dict = field(default_factory=dict)
    hhi: float = 0.0
    effective_n: float = 0.0
    high_corr_pairs: list = field(default_factory=list)
    sector_weights_pct: dict = field(default_factory=dict)

    def summary_text(self) -> str:
        lines = ["PORTFOLIO CONCENTRATION & CORRELATION", "=" * 48]
        if not self.weights_pct:
            lines.append("No priced open positions.")
            return "\n".join(lines)

        lines.append(f"{'ticker':<12}{'weight':>9}")
        for ticker, w in sorted(self.weights_pct.items(), key=lambda kv: kv[1], reverse=True):
            lines.append(f"{ticker:<12}{w:>8.1f}%")
        lines.append("-" * 48)
        lines.append(f"HHI: {self.hhi:.3f}   effective N: {self.effective_n:.1f}  "
                     f"(of {len(self.weights_pct)} nominal positions)")

        if self.sector_weights_pct:
            lines.append("")
            lines.append("By sector:")
            for sector, w in sorted(self.sector_weights_pct.items(), key=lambda kv: kv[1], reverse=True):
                lines.append(f"  {sector:<20}{w:>6.1f}%")

        lines.append("")
        if self.high_corr_pairs:
            lines.append("Highly correlated pairs (|corr| >= threshold):")
            for a, b, c in self.high_corr_pairs:
                lines.append(f"  {a} <-> {b}: {c:+.2f}")
        else:
            lines.append("No highly correlated pairs found.")
        return "\n".join(lines)


def analyze_portfolio(shares_by_ticker: dict[str, float],
                      current_prices: dict[str, float],
                      price_histories: dict[str, pd.Series] | None = None,
                      sector_map: dict[str, str] | None = None,
                      corr_threshold: float = 0.7,
                      corr_lookback: int = 60) -> PortfolioAnalysis:
    """The one-call entry point: weights, concentration, correlation, and
    sector rollup, bundled into a single report."""
    weights = position_weights(shares_by_ticker, current_prices)
    hhi = herfindahl_index(weights)
    eff_n = effective_n_positions(weights)

    high_corr: list = []
    if price_histories:
        held_histories = {t: s for t, s in price_histories.items() if t in weights}
        corr = correlation_matrix(held_histories, lookback=corr_lookback)
        high_corr = high_correlation_pairs(corr, threshold=corr_threshold)

    sectors = sector_weights(weights, sector_map) if sector_map else {}

    return PortfolioAnalysis(weights_pct=weights, hhi=hhi, effective_n=eff_n,
                             high_corr_pairs=high_corr, sector_weights_pct=sectors)
