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
import json
import sys
from pathlib import Path

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
from kala.clock import today_str_wib
from kala.config import (
    BacktestConfig,
    Config,
    CostModel,
    EntryConfig,
    config_for_profile,
    us_equity_costs,
)
from kala.strategies import get_strategy, list_strategies, walk_forward_strategy
from kala.strategy_broker_concentration import SHARE_COLUMN
from kala.strategy_foreign_flow import FLOW_COLUMN, attach_foreign_flow
from kala.synthetic_benchmark import describe, equal_weight_benchmark
from kala.universe import ALL_SHARIA_STOCKS, US_SHARIA_STOCKS
from kala.walkforward import excess_ev

BROKER_FLOW_STRATEGIES = ("foreign_flow", "broker_concentration")

# The five filters --apply-entry-vetoes switches on together. Each already has
# its own EntryConfig flag; only the CLI lacked a way to separate them, so the
# measured -4.2 point cost of the vetoes could not be attributed to any one of
# them. Leave-one-out over this map is what attributes it.
VETO_FLAGS = {
    "rsi":         "veto_overbought",       # RSI >= 75
    "parabolic":   "veto_parabolic",        # +25% in 20 sessions
    "obv":         "veto_distribution",     # price up while OBV falls
    "thin_volume": "veto_thin_volume",      # surge unconfirmed by volume
    "bear":        "block_buys_in_bear",    # market regime BEARISH/MODERATE_BEAR
}

EQUAL_WEIGHT = "EQUAL_WEIGHT"   # sentinel: build the benchmark from the universe
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
         needs_dividends: bool = False,
         trust_short_cache: bool = False) -> dict[str, pd.DataFrame]:
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
            why = {"absent": 0, "too_short": 0, "stale_tail": 0}
            for t in tickers:
                covered = wh.covered_range(t)
                spans_start = bool(covered) and covered[0] <= start_iso
                tail_fresh = bool(covered) and covered[1] >= fresh_iso
                # A delisted or suspended ticker's newest bar is old forever, so
                # tail_fresh can never be satisfied and it was re-downloaded on
                # every single run. If we already asked TODAY and the source had
                # nothing newer, asking again cannot change the answer.
                #
                # Deliberately NOT extended to spans_start: a cache that is too
                # SHORT must still trigger a re-fetch, because the source may
                # hold more history than a previous call returned. See
                # test_warehouse_refetches_when_cached_history_is_too_short —
                # dropping such a ticker silently shrinks the universe.
                if spans_start and not tail_fresh and wh.is_as_fresh_as_it_gets(t, end_iso):
                    tail_fresh = True

                # A ticker listed AFTER the requested start can never satisfy
                # spans_start, so it is re-downloaded on every run forever. On a
                # 5y request over the IDX sharia list that is ~30% of the
                # universe — all of it "history too short", none of it stale.
                #
                # OFF by default: test_warehouse_refetches_when_cached_history_is
                # _too_short deliberately requires a short cache to trigger a
                # re-fetch, because a previous call may simply have been
                # truncated. That premise holds ACROSS days; within one day the
                # source returns the same history to the same request, so
                # trust_short_cache=True is safe for repeated sweeps and is what
                # makes parallel runs free.
                short_but_exhausted = (
                    trust_short_cache and not spans_start
                    and wh.is_as_fresh_as_it_gets(t, end_iso))

                if (spans_start and tail_fresh) or short_but_exhausted:
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
                    if not covered:
                        why["absent"] += 1
                    elif not spans_start:
                        why["too_short"] += 1
                    else:
                        why["stale_tail"] += 1
                    still_needed.append(t)
            if len(dfs) < len(tickers):
                # Break the re-fetch count down by CAUSE. A count that never
                # shrinks between runs is the visible symptom of a cache that
                # cannot answer a question it will be asked again tomorrow; the
                # breakdown says which question.
                print(f"  warehouse: {len(tickers) - len(still_needed)}/{len(tickers)} "
                     f"ticker(s) already covered, fetching {len(still_needed)} "
                     f"(never stored: {why['absent']}, history too short for "
                     f"{period}: {why['too_short']}, stale tail: {why['stale_tail']})")

    if still_needed:
        print(f"Downloading {len(still_needed)} ticker(s) ({period})...")
        raw = yf.download(still_needed, period=period, group_by="ticker",
                          auto_adjust=True, progress=False, threads=True)
        for t in still_needed:
            try:
                df = (raw[t].dropna(subset=["Close"]) if len(still_needed) > 1
                     else raw.dropna(subset=["Close"]))
            except KeyError:
                # The download returned nothing for this ticker. That is still an
                # ANSWER — record it, or the ticker is retried on every run.
                if wh is not None:
                    wh.record_fetch_attempt(
                        t, pd.Timestamp.today().strftime("%Y-%m-%d"), None)
                continue
            df = df[["Open", "High", "Low", "Close", "Volume"]]
            if wh is not None:
                wh.upsert(t, df)
                # Record the ATTEMPT, not just the data, so a ticker whose newest
                # bar is permanently old stops being re-fetched every run.
                newest = df.index[-1].strftime("%Y-%m-%d") if len(df) else None
                wh.record_fetch_attempt(t, pd.Timestamp.today().strftime("%Y-%m-%d"),
                                        newest)
            if _passes_filters(df, min_price):
                dfs[t] = df

    print(f"  usable: {len(dfs)} tickers")
    return dfs


def build_run_config(exit_profile: str, costs, apply_entry_vetoes: bool,
                     veto_ranging_stock: bool, holding_days: int | None = None,
                     disabled_vetoes: tuple | None = None,
                     baseline_threshold: float | None = None):
    """Compose the Config a walk-forward run validates through.

    Extracted from main() so the wiring itself is testable. Checking that the
    profile FUNCTION returns the right settings proves nothing about whether
    the flag reaches the harness — that gap is how a run labelled "exits off"
    can quietly execute the ordinary ladder and return an ordinary negative.

    ``baseline_threshold`` is the "fixed baseline" arm of the walk-forward —
    the control that does NOT get to pick a threshold per fold, and the arm
    the printed VERDICT is computed from. It must be on the SCALE OF THE
    SIGNAL BEING TESTED.

    That last sentence is here because the profile got it wrong. Passing a
    cfg to walk_forward_strategy overrides the strategy's own
    ``default_threshold``, and ``forward_test`` carries 80 — a number from
    the composite-score work. Applied to support_resistance (own grid tops
    out at 60) or dividend_yield (tops out at 70), the baseline arm sat
    ABOVE the strategy's entire grid, traded almost nothing, and the verdict
    printed from it meant nothing. Default None now means "use the
    strategy's own", which is what walk_forward_strategy does when no cfg
    overrides it.
    """
    profile = config_for_profile(exit_profile)
    hold = holding_days or profile.backtest.holding_max_days
    thr = (profile.backtest.score_entry_threshold if baseline_threshold is None
           else float(baseline_threshold))
    return Config(
        risk=profile.risk,
        backtest=BacktestConfig(
            apply_entry_vetoes=apply_entry_vetoes,
            score_entry_threshold=thr,
            holding_max_days=hold,
        ),
        costs=costs,
        entries=EntryConfig(veto_ranging_stock=veto_ranging_stock,
                            **{VETO_FLAGS[name]: False
                               for name in (disabled_vetoes or ())}))


# Baseline-arm reporting is pure so it can be tested by CALLING it. An earlier
# version of these tests asserted on the source text of main(), which passed
# happily when the whole block was made unreachable — a test that reads the
# source cannot tell live code from dead code.

THIN_ARM_FRACTION = 0.2


def baseline_provenance_lines(threshold: float, default_threshold: float,
                              grid=None) -> list[str]:
    """Lines describing where the fixed-baseline threshold came from.

    The verdict is computed from the fixed-baseline arm, not from the per-fold
    chosen thresholds, so a reader has to be able to see whether that baseline
    is this strategy's own number or one carried in from another signal's
    scale. `--exit-profile forward_test` supplies 80, which comes from the
    composite score's work; applied to mean_reversion or support_resistance it
    is a number from a different scale entirely.
    """
    head = f"fixed-baseline threshold: {threshold:.0f} (strategy default {default_threshold:.0f}"
    if grid:
        head += f", grid {min(grid):.0f}-{max(grid):.0f}"
    lines = [
        head + ")",
        "  ^ the VERDICT below is computed from this arm, not from the per-fold",
        "    chosen thresholds — which is why the baseline's provenance is printed",
        ("    beside it: the strategy's own default, and the grid it searches."
         if grid else
         "    beside it: the strategy's own default. It declares no grid."),
    ]
    if grid and not (min(grid) <= threshold <= max(grid)):
        # Outside the SEARCH grid is not the same as invalid. These scores are
        # 0-100, so a baseline above the grid is a tighter-than-searched
        # threshold that may still trade plenty. Whether it does is a
        # measurement taken after the run, not a guess made from the grid.
        lines += [
            f"  NOTE: baseline {threshold:.0f} sits outside the search grid "
            f"({min(grid):.0f}-{max(grid):.0f}).",
            "    That is allowed. The grid is the range the per-fold selection",
            "    searches, not the range of valid scores. Momentum's own headline",
            "    run had a baseline of 80 against a 50-75 grid and traded 5,241",
            "    times. What settles it is the arm's trade count, measured below.",
        ]
    return lines


def thin_baseline_arm_warning(n_baseline: int, n_chosen: int) -> str | None:
    """The check the pre-run grid comparison cannot make.

    Returns None when the baseline arm traded enough to carry a verdict.

    A run where NOTHING traded needs no guard of its own: with n_chosen at 0
    the threshold is 0 too, so any count clears it and no warning is emitted.
    That is the right answer — a run with no trades at all is not a thin-arm
    story, and saying "the baseline arm is thin" would point the reader at the
    baseline when the problem is upstream of it.
    """
    if n_baseline >= THIN_ARM_FRACTION * n_chosen:
        return None
    return (f"\nWARNING: the fixed-baseline arm traded {n_baseline} vs "
            f"{n_chosen} in the walk-forward arm — under a fifth. The VERDICT "
            f"above comes from that thin arm; treat it as unreliable and read "
            f"the walk-forward numbers instead.")


def run_provenance(args, strategy, cfg, n_tickers: int, *, measured_at: str) -> dict:
    """The metadata half of a saved fold table: WHAT the run was.

    Pure, and separate from the fold rows, so a test can call it. The fields
    it carries were added once before as an inline dict edit that silently
    matched nothing — the claim "the saved JSON records the veto arm" sat in
    CHANGES.md while fifteen real runs were written without those keys, and
    the only thing telling a no-veto table from an all-veto one was its
    filename. A source-text assertion would not have caught that either; only
    calling this does.

    ``measured_at`` is a required keyword, not a ``datetime.now()`` inside the
    body, so this stays pure and a test can pin the stamp. Required rather than
    defaulted because the daily run's staleness check reads it: a table that
    silently omits the date is one the live path can only call "age unknown"
    forever.
    """
    grid = getattr(strategy, "default_thresholds_grid", None)
    return {
        "strategy": strategy.name,
        "exit_profile": args.exit_profile,
        "baseline_threshold": cfg.backtest.score_entry_threshold,
        "holding_max_days": cfg.backtest.holding_max_days,
        "benchmark": args.benchmark,
        # Which veto arm produced this table.
        "apply_entry_vetoes": bool(args.apply_entry_vetoes),
        "disabled_vetoes": sorted(args.disable_veto),
        "n_tickers": n_tickers,
        # Which spread model this measurement charged. The live book charges
        # whatever runner_config.json says (default flat), and flat is 0.23
        # points per trade cheaper than tick_floor on this account's own
        # holdings — always in the direction that flatters the live result.
        # A measurement taken under one model does not describe a book kept
        # under the other.
        "spread_mode": cfg.costs.spread_mode,
        "measured_at": measured_at,
        # How many thresholds the deflated Sharpe was deflating for. Without
        # it a reader — or the live path — cannot tell a DSR that discounts a
        # 6-value grid from one discounting a 60-value grid, and the verdict
        # cannot apply its deflation clause at all.
        "threshold_grid_size": len(grid) if grid else 0,
    }


def fold_row(fr) -> dict:
    """One saved fold. Split out so ``saved_table`` can be called in a test.

    Carries BOTH arms' per-fold excess. ``excess_pct`` is the walk-forward
    chosen arm, as it always was; ``excess_baseline_pct`` is the fixed-baseline
    arm and is new.

    It is new because the table could not previously support its own
    decomposition. Every headline this project quotes — +1.71%/trade, the
    clustered t, the deflated Sharpe, the VERDICT — comes from the BASELINE
    arm, while the only per-fold excess on file was the CHOSEN arm's. Anything
    computing "the pooled figure minus its biggest fold" was therefore
    subtracting one arm's fold from another arm's total. The two arms pooled to
    +1.71% and +1.27% over different trade counts, so the result was not a
    decomposition of either.
    """
    return {
        "fold": fr.fold.fold_id,
        "start": str(fr.fold.test_start.date()),
        "end": str(fr.fold.test_end.date()),
        "threshold": fr.chosen_threshold,
        "n": fr.oos_chosen["n"],
        "ev_pct": fr.oos_chosen["ev_pct"],
        "win_rate_pct": fr.oos_chosen["win_rate_pct"],
        "benchmark_pct": fr.benchmark_return_pct,
        "excess_pct": excess_ev(fr.oos_excess_chosen),
        "n_baseline": (fr.oos_excess_baseline or {}).get("n", 0),
        "excess_baseline_pct": excess_ev(fr.oos_excess_baseline),
    }


def saved_table(provenance: dict, report) -> dict:
    """The exact dict written to --save-folds.

    Extracted from ``main`` because the tie between ``run_provenance`` and the
    file on disk used to be asserted by grepping this module's source for the
    call — and a source-text assertion is not a test. The same claim went
    unverified once already: a patch that was supposed to add the veto fields
    matched nothing, the source-grep still passed on the OLD line it anchored
    to, and fifteen runs were written without them. Calling this is the only
    way to know what the file will contain.

    ``report`` is duck-typed on purpose so a test can pass a stand-in instead
    of running a walk-forward.
    """
    return {
        **provenance,
        "folds": [fold_row(fr) for fr in report.folds],
        "pooled_excess_baseline": report.pooled_excess_baseline,
        # The chosen arm's pooled excess was never saved — only its clustered t
        # and DSR were, which is a correction with nothing to correct.
        "pooled_excess_chosen": report.pooled_excess_chosen,
        "pooled_excess_clustered_t": report.pooled_excess_clustered_t,
        "pooled_excess_dsr": report.pooled_excess_dsr,
        # The ALPHA VERDICT is judged on the BASELINE arm, so a saved table
        # without these cannot reproduce the verdict it was printed with —
        # only the chosen arm's figures were being kept.
        "pooled_excess_baseline_clustered_t":
            report.pooled_excess_baseline_clustered_t,
        "pooled_excess_baseline_dsr": report.pooled_excess_baseline_dsr,
    }


def build_parser() -> argparse.ArgumentParser:
    """The CLI, split out of ``main`` so it can be parsed without running.

    Extracted so the daily run's "to measure THIS configuration" command can be
    round-tripped in a test: generate it, parse it HERE, build the provenance,
    and assert the expectation block accepts the result. That instruction used
    to be a fixed string which — followed literally against a tick-floored book
    — produced a table the block then refused.
    """
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
    ap.add_argument("--trust-short-cache", action="store_true",
                    help="do not re-download tickers whose history is simply too "
                         "short for --period. The source cannot supply bars from "
                         "before a stock listed, so re-asking never helps; on a 5y "
                         "IDX run that is ~30%% of the universe re-fetched every "
                         "time. Safe for repeated runs on the same day.")
    ap.add_argument("--exit-profile", default="legacy",
                    choices=("legacy", "forward_test"),
                    help="which exit geometry to VALIDATE THROUGH. 'legacy' is the "
                         "stop/target/trailing ladder every historical number in "
                         "PROJECT_STATUS was computed under. 'forward_test' turns "
                         "every price-based exit off, leaving holding_max_days as "
                         "the only close. Use it to ask whether a standing "
                         "'unvalidated' verdict describes the SIGNAL or the exits "
                         "it was measured through — the ladder was later found to "
                         "subtract ~1.6 points per trade.")
    ap.add_argument("--save-folds", default=None, metavar="PATH",
                    help="write this run's per-fold table to JSON. Ten runs have "
                         "now been compared by pasting terminal output and "
                         "reading columns by eye; one transcription slip in that "
                         "loop is invisible. Saved runs can be compared "
                         "mechanically with compare_folds.py.")
    ap.add_argument("--baseline-threshold", type=float, default=None,
                    help="entry threshold for the FIXED BASELINE arm — the "
                         "control the printed VERDICT is computed from. Default: "
                         "the strategy's own default_threshold for any strategy "
                         "other than momentum. Set this only if you know the "
                         "signal's scale; a value outside the strategy's grid "
                         "makes the baseline arm trade nothing and its verdict "
                         "meaningless.")
    ap.add_argument("--holding-days", type=int, default=None,
                    help="override holding_max_days (default: the profile's)")
    ap.add_argument("--disable-veto", nargs="*", default=[], choices=sorted(VETO_FLAGS),
                    metavar="NAME",
                    help="switch OFF individual entry vetoes that "
                         "--apply-entry-vetoes would otherwise enable: "
                         + ", ".join(sorted(VETO_FLAGS)) + ". Measured: the "
                         "vetoes as a group cost -4.2 points of excess "
                         "(+1.71%% -> -2.52%%, clustered t -3.10), but the group "
                         "is five filters and the cost has never been "
                         "attributed to any one. Leave-one-out does that: run "
                         "--apply-entry-vetoes once per name with that name "
                         "disabled, and whichever removal recovers the most is "
                         "the culprit. No effect without --apply-entry-vetoes.")
    ap.add_argument("--benchmark", default=BENCHMARK,
                    help=f"yfinance ticker, or the literal EQUAL_WEIGHT to build an "
                         f"equal-weighted, daily-rebalanced index from the traded "
                         f"universe itself (no index-composition mismatch: it answers "
                         f"'did picking these beat buying all of them?'). "
                         f"^JKII is the Jakarta Islamic Index, sharia-screened but only "
                         f"the 30 largest, cap-weighted. Default "
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
    return ap


def main() -> int:
    args = build_parser().parse_args()

    if args.veto_ranging_stock and not args.apply_entry_vetoes:
        print("--veto-ranging-stock has no effect without --apply-entry-vetoes "
             "(the veto lives in entries.evaluate_entry, which only runs when "
             "that flag is set) — add --apply-entry-vetoes too.", file=sys.stderr)
        return 1

    # Same shape as the guard above: without --apply-entry-vetoes no veto runs
    # at all, so "disable one of them" is a no-op that would produce a run
    # indistinguishable from the plain no-veto arm — and get filed under a name
    # implying it measured something about that veto.
    if args.disable_veto and not args.apply_entry_vetoes:
        print(f"--disable-veto {' '.join(args.disable_veto)} has no effect without "
             "--apply-entry-vetoes: with that flag absent NO veto runs, so this "
             "would silently reproduce the plain no-veto arm under a misleading "
             "filename. Add --apply-entry-vetoes.", file=sys.stderr)
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
               needs_dividends=strategy.needs_dividends,
               trust_short_cache=args.trust_short_cache)
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
    if args.benchmark == EQUAL_WEIGHT:
        # Built from the SAME tickers the strategy chooses from, so the
        # comparison is "did picking these beat buying all of them?" — with no
        # index-composition mismatch to launder into apparent alpha.
        bench = equal_weight_benchmark(dfs)
        print("  " + describe(bench))
    else:
        bench = yf.download(args.benchmark, period=args.period, auto_adjust=True,
                            progress=False)
        if isinstance(bench.columns, pd.MultiIndex):
            bench.columns = bench.columns.get_level_values(0)
        bench = bench.dropna(subset=["Close"]) if len(bench) else None
    if bench is None or bench.empty:
        print(f"  WARNING: no data for benchmark '{args.benchmark}' -- check the ticker "
             "is valid on yfinance before trusting the alpha/excess numbers below "
             "(they'll be meaningless without a real benchmark).", file=sys.stderr)

    costs = (us_equity_costs() if args.cost_preset == "us_equity"
            else CostModel(spread_mode="tick_floor" if args.tick_spread else "flat"))
    # Start from the chosen exit profile, then layer this run's CLI overrides
    # on top of it — so --exit-profile decides the exit geometry while the
    # veto/cost flags keep behaving exactly as before.
    # The baseline arm must sit on the tested signal's own scale. An explicit
    # --baseline-threshold wins; otherwise a non-momentum strategy uses its own
    # default rather than inheriting the profile's composite-score number.
    baseline = args.baseline_threshold
    if baseline is None and strategy.name != "momentum":
        baseline = strategy.default_threshold
    cfg = build_run_config(args.exit_profile, costs, args.apply_entry_vetoes,
                           args.veto_ranging_stock, args.holding_days,
                           disabled_vetoes=tuple(args.disable_veto),
                           baseline_threshold=baseline)
    holding = cfg.backtest.holding_max_days
    if args.exit_profile == "forward_test":
        print(f"exit profile: FORWARD_TEST — no stop/target/trailing, "
              f"hold {holding}d, entry score >= "
              f"{cfg.backtest.score_entry_threshold:.0f}. NOT comparable with the "
              "historical numbers in PROJECT_STATUS, which were all computed "
              "through the ladder.")
    else:
        print(f"exit profile: legacy (stop/target/trailing active, hold {holding}d)")
    if args.apply_entry_vetoes:
        off = sorted(args.disable_veto)
        on = [n for n in sorted(VETO_FLAGS) if n not in off]
        print(f"entry vetoes: ON  {', '.join(on) if on else '(none)'}"
              + (f"   |  OFF {', '.join(off)}" if off else ""))
        if not on:
            print("  ^ every veto disabled — this is the NO-VETO arm with extra steps.")
    print(f"strategy: {strategy.name}"
         + ("" if strategy.name == "momentum" else "  (UNTESTED until this run completes)"))
    for line in baseline_provenance_lines(
            cfg.backtest.score_entry_threshold,
            strategy.default_threshold,
            getattr(strategy, "default_thresholds_grid", None)):
        print(line)
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

    # Whether the baseline arm actually traded enough to carry a verdict is a
    # measurement, available only now. A grid check before the run cannot say it.
    warn = thin_baseline_arm_warning((report.pooled_baseline or {}).get("n", 0),
                                     (report.pooled_chosen or {}).get("n", 0))
    if warn:
        print(warn)

    if args.save_folds:
        # Everything needed to recompute the comparisons by hand, including
        # what the run WAS: a fold table without its strategy, profile and
        # baseline is a table of numbers nobody can place later.
        out = saved_table(
            run_provenance(args, strategy, cfg, len(dfs),
                           measured_at=today_str_wib()),
            report)
        path = Path(args.save_folds)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(out, indent=2), encoding="utf-8")
        print(f"\nfold table saved to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
