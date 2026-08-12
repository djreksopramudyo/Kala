"""
Generate the local HTML paper-trading dashboard (kala.dashboard).

Loads paper_state.json, best-effort fetches current prices/history for open
positions and the IHSG benchmark (so equity/return/the vs-IHSG comparison
reflect TODAY, not the last time the bot ran), and writes a static,
self-contained results/dashboard.html — open it in any browser, no server
needed. "Live" would need a running server; re-running this script is the
"updated data on demand" version of that.

Usage:
    python generate_dashboard.py
    python generate_dashboard.py --out results/dashboard.html --days 14
"""

from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from pathlib import Path

import yfinance as yf

from kala.chart import equity_curve_points, mark_to_market_points
from kala.clock import now_wib
from kala.dashboard import render_dashboard_html
from kala.papertrade import PaperTrader
from kala.portfolio_analytics import (
    allocation_drift,
    analyze_portfolio,
    positions_vs_benchmark,
)
from kala.twr import compute_time_weighted_return

STATE_PATH = "paper_state.json"
CONFIG_PATH = "runner_config.json"
BENCHMARK = "^JKSE"
HISTORY_PERIOD = "6mo"     # covers typical swing-trade holding periods for
                           # both the correlation panel and vs-IHSG lookups


def _load_config(path: str) -> dict:
    try:
        return json.loads(Path(path).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _account_start_date(log: list[dict], capital_additions: list[dict]) -> str | None:
    """Earliest known activity date (first trade or first deposit) -- used
    as a proxy 'account start' for CAGR annualization since PaperTrader
    doesn't store an explicit account-creation date."""
    dates = [str(t.get("date", "")) for t in log if t.get("date")]
    dates += [str(d.get("date", "")) for d in capital_additions if d.get("date")]
    return min(dates) if dates else None


def _target_weights(cfg: dict, held_tickers: list[str]) -> dict[str, float]:
    """``runner_config.json``'s optional ``target_allocation`` (a
    {ticker: weight%} dict you set by hand), or -- if not configured -- a
    naive equal-weight default across the PLANNED slot count
    (``max_positions``), matching the per-slot sizing cap
    (``budget / max_positions``) this project already uses elsewhere. Not
    a recommendation, just a default worth having something to compare
    against rather than nothing."""
    configured = cfg.get("target_allocation")
    if configured:
        return {t: float(w) for t, w in configured.items()}
    max_positions = int(cfg.get("max_positions", 5))
    if max_positions <= 0 or not held_tickers:
        return {}
    return {t: 100.0 / max_positions for t in held_tickers}


def _fetch_position_histories(tickers: list[str], period: str = HISTORY_PERIOD) -> dict:
    """Best-effort OHLCV history per open position -- feeds both the
    current-price fallback chain and the correlation panel. A fetch
    failure for any one ticker just drops it from the dict; callers
    degrade gracefully (peak_price fallback for price, skipped from
    correlation) rather than crashing the whole report."""
    histories: dict = {}
    if not tickers:
        return histories
    try:
        raw = yf.download(tickers, period=period, group_by="ticker",
                          auto_adjust=True, progress=False, threads=True)
        for t in tickers:
            try:
                df = raw[t] if len(tickers) > 1 else raw
                df = df.dropna(subset=["Close"])
                if len(df):
                    histories[t] = df
            except (KeyError, IndexError):
                continue
    except Exception:
        pass
    return histories


def _fetch_benchmark_close(period: str = HISTORY_PERIOD):
    """IHSG Close history (a pandas Series), or None on failure. The full
    series (not just the latest price) is what lets positions_vs_benchmark
    look up 'what was the index at when I entered this position'."""
    try:
        b = yf.download(BENCHMARK, period=period, auto_adjust=True, progress=False)
        if hasattr(b.columns, "get_level_values"):
            b.columns = b.columns.get_level_values(0)
        closes = b["Close"].dropna()
        return closes if len(closes) else None
    except Exception:
        return None


def build_dashboard(state_path: str = STATE_PATH, config_path: str = CONFIG_PATH,
                    days: int = 7) -> dict:
    """The reusable core of this script: load real state, best-effort fetch
    live prices/benchmark, compute TWR + allocation drift, render the HTML.
    Extracted out of ``main()`` so callers OTHER than this CLI (e.g.
    ``telegram_bot.py``'s ``/report``) can produce the exact same real
    dashboard on demand without shelling out to a subprocess. Returns
    {'html': str, 'summary': dict, 'twr_result': TWRResult, 'drift_rows':
    list[dict], 'n_positions': int} -- the non-html fields are just what
    ``main()`` already had in hand, exposed for a caller that wants a short
    caption instead of (or alongside) the full document."""
    cfg = _load_config(config_path)
    pt = PaperTrader.load(state_path, start_capital=cfg.get("start_capital_idr", 10_000_000))

    # Fetch CLOSED tickers too, not just currently-held ones: the
    # mark-to-market curve has to value a sold lot on the days it was still
    # held, and those tickers are otherwise never downloaded. Held names come
    # first so a partial/throttled fetch still serves the live panels.
    closed_tickers = {str(t.get("ticker")) for t in pt.log if t.get("ticker")}
    all_tickers = list(pt.positions) + sorted(closed_tickers - set(pt.positions))
    histories = _fetch_position_histories(all_tickers)
    last_prices = {t: float(df["Close"].iloc[-1]) for t, df in histories.items()}
    # Fall back to COST, not peak. peak_price is by definition the highest
    # price the position ever saw, so using it to stand in for "today"
    # inflates equity by the entire run-up: a name bought at 1000 that
    # peaked at 1500 and now trades at 800 was being valued at 1500. Cost is
    # wrong too, but bounded and not systematically flattering — the same
    # call chart.mark_to_market_points already makes ("hold it at cost:
    # wrong, but bounded and reported"). Reported, not silent: refusing a
    # stale cache makes an unpriced holding more common, not less.
    price_fallbacks = []
    for t, pos in pt.positions.items():
        if t not in last_prices:
            last_prices[t] = pos.entry_price
            price_fallbacks.append(t)

    benchmark_close = _fetch_benchmark_close()
    benchmark_price = float(benchmark_close.iloc[-1]) if benchmark_close is not None else None

    summary = pt.summary(last_prices, benchmark_price=benchmark_price)
    recent = pt.recent_performance(days=days)

    position_comparisons = None
    if benchmark_close is not None and pt.positions:
        position_comparisons = positions_vs_benchmark(pt.positions, last_prices, benchmark_close)

    portfolio_analysis = None
    if pt.positions:
        shares_by_ticker = {t: p.shares for t, p in pt.positions.items()}
        close_histories = {t: df["Close"] for t, df in histories.items()}
        portfolio_analysis = analyze_portfolio(shares_by_ticker, last_prices,
                                               price_histories=close_histories)

    equity_points = equity_curve_points(pt.log, pt.start_capital, pt.capital_additions)

    # Mark-to-market: total equity (cash + holdings at market) day by day.
    # The realized curve above only steps when a trade CLOSES, so a book that
    # bought today and sold nothing shows a flat line; this one moves with
    # the market. Best-effort -- a failure here must not sink the report.
    mtm_points, mtm_warnings = [], []
    try:
        mtm_points, mtm_warnings = mark_to_market_points(
            pt.log, pt.positions,
            {t: df["Close"] for t, df in histories.items()},
            pt.start_capital, pt.capital_additions, pt.dividends,
            today=now_wib().strftime("%Y-%m-%d"))
    except Exception as e:
        from kala.logging_util import log_swallowed
        log_swallowed("mark_to_market_points", e)
        mtm_warnings = [f"mark-to-market unavailable: {e}"]

    original_capital = pt.start_capital - sum(d.get("amount", 0.0) for d in pt.capital_additions)
    # mtm_points feeds the drawdown: the realized-only curve steps only when a
    # trade closes, so a position that fell hard while held and closed flat
    # would report no drawdown at all. Empty (fetch failed) falls back and the
    # result says so via drawdown_basis.
    twr_result = compute_time_weighted_return(
        pt.log, pt.capital_additions, original_capital, summary["equity"],
        account_start_date=_account_start_date(pt.log, pt.capital_additions),
        today=now_wib().date(), equity_points=mtm_points,
        equity_points_warnings=mtm_warnings)

    actual_weights = portfolio_analysis.weights_pct if portfolio_analysis is not None else {}
    target_weights = _target_weights(cfg, list(pt.positions))
    drift_rows = allocation_drift(actual_weights, target_weights) if (
        actual_weights or target_weights) else []

    html = render_dashboard_html(summary, recent, pt.positions, pt.log,
                                 generated_at=now_wib().strftime("%Y-%m-%d %H:%M WIB"),
                                 position_comparisons=position_comparisons,
                                 equity_points=equity_points,
                                 mtm_points=mtm_points,
                                 mtm_warnings=mtm_warnings,
                                 portfolio_analysis=portfolio_analysis,
                                 twr_result=twr_result,
                                 allocation_drift_rows=drift_rows)

    return {"html": html, "summary": summary, "twr_result": twr_result,
           "drift_rows": drift_rows, "n_positions": len(pt.positions),
           "total_dividends": sum(d["amount"] for d in pt.dividends),
           # Held names valued at cost because no price could be fetched.
           # Every figure derived from them — equity, weights, drift — is a
           # placeholder, and the caller has to be able to say so.
           "price_fallbacks": price_fallbacks}


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate the local paper-trading HTML dashboard")
    ap.add_argument("--state", default=STATE_PATH)
    ap.add_argument("--config", default=CONFIG_PATH)
    ap.add_argument("--out", default="results/dashboard.html")
    ap.add_argument("--days", type=int, default=7, help="recent-performance window (default 7)")
    ap.add_argument("--open", action="store_true", help="open the file in a browser when done")
    args = ap.parse_args()

    result = build_dashboard(args.state, args.config, args.days)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(result["html"], encoding="utf-8")
    print(f"Dashboard written to {out_path}")

    if args.open:
        webbrowser.open(out_path.resolve().as_uri())
    return 0


if __name__ == "__main__":
    sys.exit(main())
