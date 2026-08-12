"""
Walk-forward validation runner.

Fetches history for a sample of the universe, runs the walk-forward harness,
and prints the out-of-sample report. This is the script that answers:
"does THIS signal have a real edge, or did we fit the past?" -- for whichever
signal you point it at with --strategy (default: the original composite
momentum score, already found to have no edge -- see PROJECT_STATUS.md).
Other strategies in the zoo (e.g. mean_reversion) are UNTESTED until you
actually run this against them; nothing about them is assumed to work.

Usage:
    python run_walkforward.py                          # 60-ticker sample, 3y, momentum
    python run_walkforward.py --strategy mean_reversion --period 5y
    python run_walkforward.py --max-tickers 150 --period 5y
    python run_walkforward.py --tickers ANTM.JK BRIS.JK TLKM.JK
    python run_walkforward.py --train-bars 252 --test-bars 63
    python run_walkforward.py --period 5y --apply-entry-vetoes   # gate entries
                                                                  # through entries.py
                                                                  # (RSI/parabolic/OBV/
                                                                  # thin-volume/bear-regime),
                                                                  # same as the live bot
    python run_walkforward.py --period 5y --apply-entry-vetoes --tick-spread \
        --veto-ranging-stock   # regime-conditional momentum: also block entries into
                                # this TICKER's own choppy/ranging price action (ADX,
                                # see kala/regime_filter.py + entries.py). Requires
                                # --apply-entry-vetoes (this veto lives in evaluate_entry,
                                # which only runs when that flag is set). UNVALIDATED —
                                # run once without this flag and once with it, same other
                                # settings, and compare the VERDICT lines.

Network access happens ONLY here — kala.walkforward is pure logic.
"""

from __future__ import annotations

import argparse
import sys

import pandas as pd
import yfinance as yf

import kala.strategy_broker_concentration  # noqa: F401  (registers "broker_concentration")
import kala.strategy_calendar_effects  # noqa: F401  (registers "turn_of_month" in the zoo)
import kala.strategy_dividend_yield  # noqa: F401  (registers "dividend_yield" in the zoo)
import kala.strategy_foreign_flow  # noqa: F401  (registers "foreign_flow" in the zoo)
import kala.strategy_high_proximity  # noqa: F401  (registers "high_proximity" in the zoo)
import kala.strategy_longhorizon_momentum  # noqa: F401  (registers "long_momentum" in the zoo)
import kala.strategy_low_volatility  # noqa: F401  (registers "low_volatility" in the zoo)
import kala.strategy_mean_reversion  # noqa: F401  (registers "mean_reversion" in the zoo)
import kala.strategy_multihorizon_trend  # noqa: F401  (registers "multihorizon_trend")
import kala.strategy_ramadan_effect  # noqa: F401  (registers "ramadan_effect" in the zoo)
import kala.strategy_support_resistance  # noqa: F401  (registers "support_resistance")
from kala.config import BacktestConfig, Config, CostModel, EntryConfig, us_equity_costs
from kala.strategies import get_strategy, list_strategies, walk_forward_strategy
from kala.strategy_broker_concentration import SHARE_COLUMN
from kala.strategy_foreign_flow import FLOW_COLUMN, attach_foreign_flow
from kala.universe import ALL_SHARIA_STOCKS, US_SHARIA_STOCKS

BROKER_FLOW_STRATEGIES = ("foreign_flow", "broker_concentration")

BENCHMARK = "^JKSE"      # IHSG -- default, overridable via --benchmark (see its help text
                         # for why this default is arguably the WRONG choice for this
                         # project's sharia-only universe)
MIN_BARS = 400          # a ticker must have enough history to span >= 1 fold
MIN_PRICE = 50.0        # skip gocap/near-dead names whose "returns" are tick noise


def _passes_filters(df: pd.DataFrame, min_price: float) -> bool:
    if df is None or len(df) < MIN_BARS:
        return False
    if float(df["Close"].iloc[-1]) < min_price:
        return False
    if (df["Volume"].tail(60) == 0).mean() > 0.5:   # mostly untraded -> skip
        return False
    return True


def _period_to_start_iso(period: str, end: pd.Timestamp) -> str | None:
    """'3y' -> ISO date 3 years before ``end``. None for anything not a
    plain 'Ny' string (ytd/max/etc.) — the warehouse cache is skipped for
    those rather than guessing a start date."""
    import re
    m = re.fullmatch(r"(\d+)y", period.strip())
    if not m:
        return None
    return (end - pd.DateOffset(years=int(m.group(1)))).strftime("%Y-%m-%d")


def _freshness_target_iso(end: pd.Timestamp, slack_bdays: int = 1) -> str:
    """The newest bar a cache can REASONABLY be expected to hold, as ISO date.

    Not simply ``end``: markets are closed on weekends and holidays, so on a
    Saturday the newest bar that can exist is Friday's. Requiring the cache to
    reach "today" therefore made the coverage check IMPOSSIBLE to satisfy every
    weekend and holiday — the warehouse silently missed and re-downloaded the
    whole universe, burning yfinance rate limit precisely when nothing had
    changed (and this project has already been throttled by Yahoo mid-study).

    ``slack_bdays`` additionally tolerates "today's bar hasn't been published
    yet" during or shortly after a session, and exchange holidays this code has
    no calendar for. One business day is deliberately small: enough to stop
    spurious misses, not so much that genuinely stale data is served as fresh
    (a tail that's staler than this still triggers a re-fetch)."""
    last_bday = end if end.weekday() < 5 else end - pd.tseries.offsets.BDay(1)
    target = last_bday - pd.tseries.offsets.BDay(slack_bdays)
    return target.strftime("%Y-%m-%d")


def fetch(tickers: list[str], period: str, min_price: float = MIN_PRICE,
         warehouse_path: str | None = None,
         needs_dividends: bool = False) -> dict[str, pd.DataFrame]:
    """Batch-download OHLCV and keep only clean, sufficiently long histories.

    ``min_price`` filters on the LATEST close only (a listing-quality floor,
    not point-in-time) — it decides which tickers enter the study at all,
    same spirit as MIN_PRICE's original "skip near-dead names" purpose. Use
    it to isolate whether a cheap price TIER is dragging the pooled edge
    down: e.g. --min-price 500 vs the default 50 under --tick-spread tells
    you whether honest costs sink the whole universe or just the low tier.

    ``warehouse_path`` (optional, e.g. "results/warehouse.db"): cache OHLCV
    in a local SQLite store (kala.warehouse) so re-running this script
    with an overlapping period/ticker set doesn't re-download history
    yfinance already gave you. Only kicks in for plain 'Ny' periods (e.g.
    '3y', '5y') — 'ytd'/'max' skip the cache since their start date isn't
    fixed. Default (None) is the original behavior, unchanged.

    ``needs_dividends`` (set from ``Strategy.needs_dividends``): fetch with
    ``actions=True`` and keep a ``Dividends`` column alongside OHLCV, instead
    of the default 5-column frame. This path deliberately BYPASSES the
    warehouse cache entirely rather than risk two different on-disk schemas
    under the same store — a strategy that needs dividends is rare enough
    that always re-fetching is the simpler, safer choice over migrating the
    cache format.
    """
    if needs_dividends:
        print(f"Downloading {len(tickers)} ticker(s) ({period}, with dividends)...")
        raw = yf.download(tickers, period=period, group_by="ticker",
                          auto_adjust=True, actions=True, progress=False, threads=True)
        dfs: dict[str, pd.DataFrame] = {}
        for t in tickers:
            try:
                df = (raw[t].dropna(subset=["Close"]) if len(tickers) > 1
                     else raw.dropna(subset=["Close"]))
            except KeyError:
                continue
            cols = ["Open", "High", "Low", "Close", "Volume"]
            # Dividends is present whenever actions=True was honored; fall back
            # to an all-zero column rather than crash if a vendor quirk omits it
            # for a particular ticker (e.g. no corporate-action history at all).
            df = df.copy()
            if "Dividends" not in df.columns:
                df["Dividends"] = 0.0
            cols.append("Dividends")
            df = df[cols]
            if _passes_filters(df, min_price):
                dfs[t] = df
        return dfs

    wh = None
    still_needed = list(tickers)
    dfs = {}

    if warehouse_path:
        from kala.warehouse import Warehouse
        wh = Warehouse(warehouse_path)
        end = pd.Timestamp.today().normalize()
        start_iso = _period_to_start_iso(period, end)
        if start_iso is not None:
            end_iso = end.strftime("%Y-%m-%d")
            # Freshness is judged against the last bar that can plausibly EXIST
            # (see _freshness_target_iso), not the raw calendar date -- comparing
            # against "today" made every weekend and holiday an automatic miss.
            fresh_iso = _freshness_target_iso(end)
            still_needed = []
            for t in tickers:
                covered = wh.covered_range(t)
                spans_start = bool(covered) and covered[0] <= start_iso
                tail_fresh = bool(covered) and covered[1] >= fresh_iso
                if spans_start and tail_fresh:
                    cached = wh.read(t, start_iso, end_iso)
                    if cached is not None and _passes_filters(cached, min_price):
                        dfs[t] = cached
                    # cached but filtered out (e.g. below min_price): intentionally
                    # excluded from the study, NOT a re-fetch candidate.
                else:
                    # missing, too SHORT to cover the requested start, or stale
                    # tail. The too-short case previously matched neither branch
                    # and made the ticker vanish from the study entirely -- worse
                    # than re-fetching, since it silently shrank the universe.
                    still_needed.append(t)
            if len(dfs) < len(tickers):
                print(f"  warehouse: {len(tickers) - len(still_needed)}/{len(tickers)} "
                     f"ticker(s) already covered, fetching {len(still_needed)}")

    if still_needed:
        print(f"Downloading {len(still_needed)} ticker(s) ({period})...")
        raw = yf.download(still_needed, period=period, group_by="ticker",
                          auto_adjust=True, progress=False, threads=True)
        for t in still_needed:
            try:
                df = (raw[t].dropna(subset=["Close"]) if len(still_needed) > 1
                     else raw.dropna(subset=["Close"]))
            except KeyError:
                continue
            df = df[["Open", "High", "Low", "Close", "Volume"]]
            if wh is not None:
                wh.upsert(t, df)
            if _passes_filters(df, min_price):
                dfs[t] = df

    print(f"  usable: {len(dfs)} tickers")
    return dfs


def main() -> int:
    ap = argparse.ArgumentParser(description="Walk-forward OOS validation of the composite-score edge")
    ap.add_argument("--tickers", nargs="*", default=None,
                    help="explicit ticker list; default = evenly spaced sample of the universe")
    ap.add_argument("--max-tickers", type=int, default=60,
                    help="sample size when --tickers not given (default 60)")
    ap.add_argument("--period", default="3y", help="yfinance period (default 3y)")
    ap.add_argument("--train-bars", type=int, default=252)
    ap.add_argument("--test-bars", type=int, default=63)
    ap.add_argument("--min-train-trades", type=int, default=30)
    ap.add_argument("--apply-entry-vetoes", action="store_true",
                    help="gate entries through entries.evaluate_entry (RSI overbought, "
                         "parabolic ROC20, OBV distribution, thin volume, bear-regime "
                         "block) — same guardrails the live bot already applies, off by "
                         "default to match prior backtest numbers")
    ap.add_argument("--tick-spread", action="store_true",
                    help="floor the half-spread at half of one IDX tick at the fill "
                         "price instead of the flat 0.10%% assumption. Cheap stocks "
                         "cannot trade tighter than their tick (a 67-rupiah stock's "
                         "1-rupiah tick is a ~1.5%% spread), so this measures how much "
                         "of the edge survives honest spread costs. Run once WITHOUT "
                         "and once WITH this flag and compare the VERDICT lines.")
    ap.add_argument("--veto-ranging-stock", action="store_true",
                    help="also reject entries when THIS TICKER's own ADX says it's "
                         "range-bound/choppy (kala/regime_filter.py's signal, "
                         "distinct from the benchmark-level bear-regime block) — "
                         "regime-conditional momentum. Requires --apply-entry-vetoes. "
                         "UNVALIDATED: off by default so it doesn't change prior "
                         "backtest numbers; run once without and once with, same other "
                         "settings, and compare VERDICT lines.")
    ap.add_argument("--min-price", type=float, default=MIN_PRICE,
                    help=f"exclude tickers priced below this (latest close) BEFORE "
                         f"the study runs (default {MIN_PRICE:.0f}, a listing-quality "
                         f"floor only -- that default is in IDR; pass something like "
                         f"5 for --universe us, which prices in USD). Raise it under "
                         f"--tick-spread (e.g. 500 or 1000) to test whether a cheap "
                         f"PRICE TIER is dragging the pooled edge down, vs the whole "
                         f"universe being negative.")
    ap.add_argument("--universe", default="idx", choices=["idx", "us"],
                    help="which built-in sharia universe backs the default ticker "
                         "sample when --tickers is not given (default idx: "
                         "kala.universe.ALL_SHARIA_STOCKS, IDX). 'us': "
                         "kala.universe.US_SHARIA_STOCKS -- a hand-curated STARTER "
                         "list, see that module's docstring for its provenance "
                         "caveat before trusting individual names. Pair with "
                         "--cost-preset us_equity and --benchmark SPUS.")
    ap.add_argument("--cost-preset", default="idx", choices=["idx", "us_equity"],
                    help="which CostModel to backtest with (default idx: the "
                         "original asymmetric IDX fee/tax model). 'us_equity': "
                         "kala.config.us_equity_costs() -- zero commission, tiny "
                         "SEC fee, tight flat spread, no tick_floor (IDX-tick tiers "
                         "are meaningless for USD-priced names). --tick-spread is "
                         "ignored under this preset.")
    ap.add_argument("--warehouse", nargs="?", const="results/warehouse.db", default=None,
                    help="cache OHLCV in a local SQLite store so re-running with an "
                         "overlapping period/ticker set skips re-downloading history "
                         "(path optional, defaults to results/warehouse.db). Only "
                         "applies to plain 'Ny' --period values.")
    ap.add_argument("--strategy", default="momentum",
                    help=f"strategy from the zoo to validate (default: momentum -- "
                         f"already found to have no edge, see PROJECT_STATUS.md). "
                         f"Available: {', '.join(list_strategies())}. Anything other "
                         f"than momentum is UNTESTED until this run produces a verdict.")
    ap.add_argument("--broker-flow-db", nargs="?", const="results/broker_flow.db", default=None,
                    help="path to a BrokerFlowArchive SQLite file (default when the "
                         "flag is given but no path: results/broker_flow.db). REQUIRED "
                         "for --strategy foreign_flow -- the foreign_net_value column "
                         "is merged onto each ticker's OHLCV frame from here before the "
                         "backtest. Backfill it first with the Invezgo adapter (see "
                         "BROKER_FLOW_DATA_SPEC.md); tickers absent from it simply never "
                         "trade rather than erroring.")
    ap.add_argument("--benchmark", default=BENCHMARK,
                    help=f"yfinance ticker for the alpha-vs-beta comparison (default "
                         f"{BENCHMARK}, IHSG -- the full IDX composite). ARGUABLY WRONG "
                         f"for this project: the tradeable universe is sharia-screened "
                         f"only (kala.universe.ALL_SHARIA_STOCKS), and IHSG includes "
                         f"conventional banks/insurers/interest-based names this project "
                         f"can never hold. If IHSG rallies on a move with no sharia "
                         f"counterpart, 'beating IHSG' or 'trailing it' says nothing "
                         f"about stock-picking skill within the universe actually "
                         f"traded -- ISSI (the sharia-only composite) is the correct "
                         f"comparison, if it has a working yfinance ticker (untried as "
                         f"of 2026-07 -- try '^JKSII' or fall back to JII, the narrower "
                         f"30-stock sharia index, likely '^JKII'; verify with "
                         f"yf.Ticker(...).history() before trusting either). ALL prior "
                         f"verdicts in PROJECT_STATUS.md used the IHSG default -- rerun "
                         f"with the correct ticker once confirmed rather than assuming "
                         f"the old numbers transfer.")
    args = ap.parse_args()

    if args.veto_ranging_stock and not args.apply_entry_vetoes:
        print("--veto-ranging-stock has no effect without --apply-entry-vetoes "
             "(the veto lives in entries.evaluate_entry, which only runs when "
             "that flag is set) — add --apply-entry-vetoes too.", file=sys.stderr)
        return 1

    if args.strategy in BROKER_FLOW_STRATEGIES and not args.broker_flow_db:
        print(f"--strategy {args.strategy} needs --broker-flow-db pointing at a "
             "backfilled BrokerFlowArchive. See BROKER_FLOW_DATA_SPEC.md.", file=sys.stderr)
        return 1

    try:
        strategy = get_strategy(args.strategy)
    except KeyError as e:
        print(e, file=sys.stderr)
        return 1

    base_universe = US_SHARIA_STOCKS if args.universe == "us" else ALL_SHARIA_STOCKS
    if args.tickers:
        tickers = args.tickers
    else:
        # evenly spaced sample -> no alphabetical sector clustering
        step = max(1, len(base_universe) // args.max_tickers)
        tickers = base_universe[::step][:args.max_tickers]

    if args.cost_preset == "us_equity":
        if args.tick_spread:
            print("  NOTE: --tick-spread is ignored under --cost-preset us_equity "
                 "(IDX tick tiers don't apply to USD-priced names).", file=sys.stderr)
        print(f"min price: ${args.min_price:.2f} | spread: flat "
             f"{us_equity_costs().half_spread * 2 * 100:.2f}% (us_equity preset)")
    else:
        print(f"min price: IDR {args.min_price:.0f} | spread: "
             f"{'tick-floored' if args.tick_spread else 'flat 0.10%'}")
    dfs = fetch(tickers, args.period, min_price=args.min_price, warehouse_path=args.warehouse,
               needs_dividends=strategy.needs_dividends)
    if not dfs:
        print("No usable data — check network / period.", file=sys.stderr)
        return 1

    if args.broker_flow_db:
        from pathlib import Path as _Path

        from kala.broker_flow_archive import BrokerFlowArchive
        archive = BrokerFlowArchive(args.broker_flow_db)
        resolved = _Path(args.broker_flow_db).resolve()

        # sqlite happily creates an empty database at a path that does not
        # exist, and an empty archive merges onto 0 tickers, produces 0 trades,
        # and used to print "VERDICT: INCONCLUSIVE — too few OOS trades to
        # judge the edge". That reads as a finding about the strategy when it
        # is really a missing file. Refuse to run instead.
        if archive.created_empty:
            print(f"\nERROR: no broker-flow archive at {resolved}\n"
                  "       (sqlite created an empty one there — that is not data).\n"
                  "       Put the backfilled broker_flow.db at that path, or pass\n"
                  "       --broker-flow-db <path> pointing at it.", file=sys.stderr)
            return 1

        n_rows = archive.row_count()
        if n_rows == 0:
            print(f"\nERROR: broker-flow archive at {resolved} exists but is EMPTY "
                  "(0 rows).\n       Backfill it before running "
                  f"--strategy {args.strategy}.", file=sys.stderr)
            return 1

        dfs = attach_foreign_flow(dfs, archive, source="invezgo", column=FLOW_COLUMN)
        dfs = attach_foreign_flow(dfs, archive, source="invezgo", column=SHARE_COLUMN)
        covered = sum(1 for d in dfs.values() if FLOW_COLUMN in d.columns)
        print(f"broker-flow: merged {FLOW_COLUMN}/{SHARE_COLUMN} onto "
             f"{covered}/{len(dfs)} ticker(s) from {resolved} ({n_rows:,} rows)")
        if covered == 0:
            stored = archive.tickers()
            print(f"\nERROR: the archive holds {n_rows:,} row(s) for {len(stored)} "
                  "ticker(s), but NONE of them\n       match the tickers requested "
                  "— so this run would measure nothing.\n"
                  f"       archive has: {', '.join(stored[:8])}"
                  f"{' ...' if len(stored) > 8 else ''}\n"
                  "       Pass --tickers from that list.", file=sys.stderr)
            return 1

    print(f"benchmark: {args.benchmark}"
         + ("  (default IHSG -- see --help for why ISSI may be more correct here)"
            if args.benchmark == BENCHMARK else ""))
    bench = yf.download(args.benchmark, period=args.period, auto_adjust=True, progress=False)
    if isinstance(bench.columns, pd.MultiIndex):
        bench.columns = bench.columns.get_level_values(0)
    bench = bench.dropna(subset=["Close"]) if len(bench) else None
    if bench is None or bench.empty:
        print(f"  WARNING: no data for benchmark '{args.benchmark}' -- check the ticker "
             "is valid on yfinance before trusting the alpha/excess numbers below "
             "(they'll be meaningless without a real benchmark).", file=sys.stderr)

    costs = (us_equity_costs() if args.cost_preset == "us_equity"
            else CostModel(spread_mode="tick_floor" if args.tick_spread else "flat"))
    cfg = Config(backtest=BacktestConfig(apply_entry_vetoes=args.apply_entry_vetoes),
                 costs=costs,
                 entries=EntryConfig(veto_ranging_stock=args.veto_ranging_stock))
    print(f"strategy: {strategy.name}"
         + ("" if strategy.name == "momentum" else "  (UNTESTED until this run completes)"))
    report = walk_forward_strategy(
        strategy,
        dfs,
        cfg=cfg,
        benchmark=bench,
        train_bars=args.train_bars,
        test_bars=args.test_bars,
        min_train_trades=args.min_train_trades,
    )
    print()
    print(report.summary_text())
    return 0


if __name__ == "__main__":
    sys.exit(main())
