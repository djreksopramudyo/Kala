#!/usr/bin/env python3
"""Out-of-sample sweep over the EXIT ladder — stop, target, breakeven ratchet.

WHY THIS EXISTS
---------------
``diagnose_entry_param_sweep.py`` sweeps the BUY side and
``compare_exit_engines.py`` compares two exit engines on the full sample, but
nothing sweeps the exit ladder itself. That gap matters, because the ladder is
what decides the SHAPE of the return distribution:

  * ``hard_stop_pct``          how much a loser is allowed to cost
  * ``target_profit_pct``      where a winner is cashed
  * ``breakeven_trigger_pct``  the peak gain that moves the stop to entry, and
                               so converts pullbacks into ~0% scratches

A book can sit almost exactly on its break-even win rate purely because those
three numbers are mismatched to the universe's volatility — no entry-signal
change fixes that, and no amount of staring at a HOLD recommendation reveals it.

READ THE OUTPUT AS A SEARCH, NOT A DISCOVERY
--------------------------------------------
Every cell here is evaluated OUT OF SAMPLE: folds come from
``walkforward.make_folds``, and a variant is scored only on trades entered
inside a test window it never saw. That removes the crudest form of
self-deception, not the subtlest — picking the best of N cells is still a
multiple-comparison problem, which is what ``overfitting.deflated_sharpe``
exists to discount. The tool prints the grid size for exactly that reason.

A cell only deserves attention when it beats the configured baseline by a
margin that survives the fold-to-fold spread reported beside it. Two folds
agreeing is not a result.

USAGE
-----
    python diagnose_exit_param_sweep.py --max-tickers 40 --period 5y
    python diagnose_exit_param_sweep.py --tick-spread --stops -3 -4 -5 -6
"""

from __future__ import annotations

import argparse
import statistics as st
import sys
from dataclasses import replace

import pandas as pd

from kala.backtest_live_exits import backtest_ticker_live_exits
from kala.config import Config
from kala.logging_util import log_swallowed
from kala.universe import ALL_SHARIA_STOCKS
from kala.walkforward import (
    clustered_t_stat,
    excess_returns_by_date,
    make_folds,
)


def pooled_oos_trades(dfs: dict[str, pd.DataFrame], cfg: Config,
                      folds, benchmark=None, warmup_bars: int = 60) -> list:
    """Every trade ENTERED inside a test window, pooled across folds.

    The frame handed to the engine is the full prefix up to the test window's
    end, so indicators are warm; trades entered before ``test_start`` are then
    discarded. That keeps features point-in-time while ensuring a variant is
    only ever credited with trades it took out of sample.
    """
    out = []
    for fold in folds:
        for ticker, df in dfs.items():
            window = df.loc[:fold.test_end]
            if len(window) < warmup_bars + 5:
                continue
            try:
                res = backtest_ticker_live_exits(ticker, window,
                                                 benchmark=benchmark, cfg=cfg)
            except Exception as e:
                # Never silent: a swallowed engine error here is indistinguishable
                # from "this variant simply took no trades", which is how a wiring
                # fault can masquerade as a flat result across the whole grid.
                log_swallowed(f"exit_sweep({ticker}, fold {fold.fold_id})", e)
                continue
            # res.closed, NOT res.trades. Accessed directly on purpose: a
            # getattr() default would turn a renamed field back into a silent
            # empty grid instead of an AttributeError.
            for t in res.closed:
                entry = pd.Timestamp(t.entry_date)
                if fold.test_start <= entry <= fold.test_end:
                    out.append(t)
    return out


def summarise(trades, benchmark=None) -> dict:
    """Raw geometry, plus the benchmark-excess side when a benchmark is given.

    The excess figures are not decoration. A long-only book held for weeks in a
    market that rose will show positive RAW expectancy from market exposure
    alone; the project's bar is |t| >= 2 on raw AND on excess precisely so beta
    cannot be reported as skill.
    """
    r = [t.net_return_pct for t in trades]
    if not r:
        return {"n": 0}
    # Trades opened the same day across different tickers share that day's
    # market move, so the plain t below treats correlated draws as independent
    # and over-rejects — badly, once the universe is wide. See
    # walkforward.clustered_t_stat for the measured false-positive rates.
    try:
        ct = clustered_t_stat(r, [str(t.entry_date) for t in trades])
    except Exception:
        ct = float("nan")
    wins = [x for x in r if x > 0]
    losses = [x for x in r if x <= 0]
    W = st.mean(wins) if wins else 0.0
    L = abs(st.mean(losses)) if losses else 0.0
    gl = -sum(losses)
    mean = st.mean(r)
    # Without a t, a table of EVs invites reading a thin positive as a result.
    sd = st.stdev(r) if len(r) > 1 else 0.0
    t = (mean / (sd / (len(r) ** 0.5))) if sd > 0 else 0.0
    ex_ev = ex_t = ex_ct = float("nan")
    ex_n = 0
    if benchmark is not None:
        ex_vals, ex_dates = excess_returns_by_date(trades, benchmark)
        if len(ex_vals) > 1:
            ex_n = len(ex_vals)
            ex_ev = st.mean(ex_vals)
            ex_sd = st.stdev(ex_vals)
            ex_t = (ex_ev / (ex_sd / (ex_n ** 0.5))) if ex_sd > 0 else 0.0
            try:
                ex_ct = clustered_t_stat(ex_vals, [str(d) for d in ex_dates])
            except Exception:
                ex_ct = float("nan")

    return {
        "n": len(r),
        "ev": mean,
        "ex_n": ex_n,
        "ex_ev": ex_ev,
        "ex_t": ex_t,
        "ex_ct": ex_ct,
        "median": st.median(r),
        "std": sd,
        "t": t,
        "ct": ct,
        "win_pct": len(wins) / len(r) * 100.0,
        "avg_win": W,
        "avg_loss": L,
        "payoff": (W / L) if L > 0 else float("inf"),
        "pf": (sum(wins) / gl) if gl > 0 else float("inf"),
        # the break-even win rate this geometry demands; compare with win_pct
        "be_win_pct": (L / (W + L) * 100.0) if (W + L) > 0 else float("nan"),
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tickers", nargs="*", default=None)
    ap.add_argument("--max-tickers", type=int, default=40)
    ap.add_argument("--period", default="5y")
    ap.add_argument("--train-bars", type=int, default=252)
    ap.add_argument("--test-bars", type=int, default=63)
    ap.add_argument("--warmup-bars", type=int, default=60)
    ap.add_argument("--min-price", type=float, default=50.0)
    ap.add_argument("--warehouse", default=None,
                    help="price warehouse path, so repeated sweeps stop re-downloading")
    ap.add_argument("--tick-spread", action="store_true",
                    help="floor the half-spread at half an IDX tick (honest for cheap stocks)")
    ap.add_argument("--stops", type=float, nargs="*", default=[-3.0, -4.0, -5.0, -6.0],
                    help="hard_stop_pct values to try")
    ap.add_argument("--targets", type=float, nargs="*", default=[6.0, 8.0, 10.0, 12.0],
                    help="target_profit_pct values to try")
    ap.add_argument("--breakevens", type=float, nargs="*", default=[4.0, 6.0],
                    help="breakeven_trigger_pct values to try (the scratch-maker)")
    ap.add_argument("--benchmark", default="^JKSE",
                    help="index for the ALPHA check. Raw expectancy on a long-only "
                         "book is not skill until it survives subtracting this.")
    ap.add_argument("--split-liquidity", action="store_true",
                    help="SURVIVORSHIP DISCRIMINATOR. Split the universe into "
                         "liquid and illiquid halves by median daily turnover and "
                         "run the threshold sweep on each. Large, liquid names "
                         "rarely delist, so their survivorship exposure is low; "
                         "thin names carry most of it. Alpha that lives only in "
                         "the illiquid half implicates the bias, alpha present in "
                         "both does not.")
    ap.add_argument("--trust-short-cache", action="store_true",
                    help="do not re-download tickers whose history is simply too "
                         "short for --period. On a 5y IDX sharia run that is ~30%% "
                         "of the universe re-fetched every time; the source cannot "
                         "supply bars from before a stock listed. Safe for repeated "
                         "sweeps on the same day, which is what makes parallel runs "
                         "free.")
    ap.add_argument("--sweep-threshold", type=float, nargs="*", default=None,
                    help="sweep score_entry_threshold with exits OFF — the "
                         "signal-contribution control. If expectancy is flat from "
                         "0 to 80, the entry score selects nothing and the result "
                         "is universe drift, not stock picking. Combine with "
                         "--hold-days to fix the holding period.")
    ap.add_argument("--hold-days", type=int, default=60,
                    help="holding_max_days used by --sweep-threshold (default 60)")
    ap.add_argument("--sweep-holding", type=int, nargs="*", default=None,
                    help="sweep holding_max_days with ALL exit rules OFF instead of "
                         "sweeping the ladder. Use this once the control line beats "
                         "every managed cell: if managing the exit subtracts value, "
                         "the only remaining exit decision is how long to hold.")
    args = ap.parse_args()

    from run_walkforward import fetch, us_equity_costs  # noqa: F401  (shared fetch path)

    tickers = args.tickers or ALL_SHARIA_STOCKS[:: max(1, len(ALL_SHARIA_STOCKS) // args.max_tickers)]
    dfs = fetch(tickers, args.period, min_price=args.min_price,
                warehouse_path=args.warehouse,
                trust_short_cache=args.trust_short_cache)
    if not dfs:
        print("No usable price data — check network / period.", file=sys.stderr)
        return 1

    # run_walkforward.fetch()'s min-price filter tests each ticker's LATEST
    # close, not the price at trade time. That is a hindsight filter: today's
    # price partly records which stocks went UP, so screening on it retroactively
    # selects winners. It is the exact mechanism behind this project's one
    # retracted result (see kala/edge.py). Say so every time it is active.
    if args.min_price > 0:
        print(f"WARNING: --min-price {args.min_price:g} screens on each ticker's "
              "LATEST close, not the\n         price at trade time — a look-ahead "
              "filter, and the one that caused\n         this project's earlier "
              "retraction. Re-run with --min-price 0 before\n         believing any "
              "positive result below.\n", file=sys.stderr)

    master = pd.DatetimeIndex(sorted(set().union(*[set(d.index) for d in dfs.values()])))
    folds = make_folds(master, args.train_bars, args.test_bars, args.warmup_bars)
    if not folds:
        print(f"Not enough history for one fold at train={args.train_bars} "
              f"test={args.test_bars}. Shorten them or lengthen --period.", file=sys.stderr)
        return 1

    import yfinance as yf
    bench = yf.download(args.benchmark, period=args.period, auto_adjust=True,
                        progress=False)
    if bench is None or len(bench) < 2:
        print(f"WARNING: no benchmark data for {args.benchmark} — the alpha check "
              "cannot run,\n         so every raw figure below may be market "
              "exposure rather than skill.\n", file=sys.stderr)
        bench = None
    elif isinstance(bench.columns, pd.MultiIndex):
        bench.columns = bench.columns.get_level_values(0)

    base = Config()
    if args.tick_spread:
        base = replace(base, costs=replace(base.costs, spread_mode="tick_floor"))

    # Exits fully inert: only holding_max_days can close a position.
    unmanaged = replace(base.risk, trailing_enabled=False, hard_stop_pct=-99.0,
                        target_profit_pct=999.0, breakeven_trigger_pct=999.0)

    if args.split_liquidity:
        if not args.sweep_threshold:
            print("--split-liquidity needs --sweep-threshold to compare against.",
                  file=sys.stderr)
            return 1
        # Median daily turnover over the whole sample, as a stand-in for how
        # exposed a name is to being delisted or dropped from the index. Median
        # rather than mean so one frantic week cannot promote a thin stock.
        turnover = {}
        for tk, d in dfs.items():
            try:
                turnover[tk] = float((d["Close"] * d["Volume"]).median())
            except Exception:
                turnover[tk] = 0.0
        ranked = sorted(turnover, key=turnover.get, reverse=True)
        half = len(ranked) // 2
        halves = [("LIQUID   (top half by turnover)", ranked[:half]),
                  ("ILLIQUID (bottom half)", ranked[half:])]

        for label, names in halves:
            sub = {k: dfs[k] for k in names if k in dfs}
            print(f"\n=== {label} — {len(sub)} tickers ===")
            h = (f"{'thresh':>8}{'n':>7}{'EV%':>9}{'win%':>7}{'payoff':>8}"
                 f"{'PF':>7}{'exEV%':>9}{'ex_clt':>8}")
            print(h); print("-" * len(h))
            for thr in args.sweep_threshold:
                cfg = replace(base, risk=unmanaged,
                              backtest=replace(base.backtest,
                                               holding_max_days=args.hold_days,
                                               score_entry_threshold=thr))
                sm = summarise(pooled_oos_trades(sub, cfg, folds,
                                                 warmup_bars=args.warmup_bars), bench)
                if not sm.get("n"):
                    print(f"{thr:>8.0f}{0:>7}   (no OOS trades)")
                    continue
                print(f"{thr:>8.0f}{sm['n']:>7}{sm['ev']:>+9.3f}{sm['win_pct']:>7.1f}"
                      f"{sm['payoff']:>8.2f}{sm['pf']:>7.2f}"
                      f"{sm['ex_ev']:>+9.3f}{sm['ex_ct']:>+8.2f}")

        print("\nRead it this way: survivorship bias is concentrated in names that "
              "COULD have\nbeen delisted or dropped — the thin end. If excess return "
              "appears in both\nhalves, the bias is not what is producing it. If it "
              "lives only in the\nilliquid half, the result is most likely an "
              "artefact of who survived to be\nin today's index.")
        return 0

    if args.sweep_threshold:
        print(f"tickers={len(dfs)}  folds={len(folds)}  "
              f"thresholds={len(args.sweep_threshold)}  ({args.period})")
        print(f"ALL exit rules OFF, holding {args.hold_days}d fixed. Sweeping the "
              "ENTRY score.\n")
        h = (f"{'thresh':>8}{'n':>7}{'EV%':>9}{'med%':>8}{'win%':>7}"
             f"{'payoff':>8}{'PF':>7}{'clust_t':>9}{'exEV%':>9}{'ex_clt':>8}")
        print(h); print("-" * len(h))
        rows_th = []
        for thr in args.sweep_threshold:
            cfg = replace(base, risk=unmanaged,
                          backtest=replace(base.backtest,
                                           holding_max_days=args.hold_days,
                                           score_entry_threshold=thr))
            sm = summarise(pooled_oos_trades(dfs, cfg, folds,
                                             warmup_bars=args.warmup_bars), bench)
            if not sm.get("n"):
                print(f"{thr:>8.0f}{0:>7}   (no OOS trades)")
                continue
            rows_th.append((thr, sm))
            print(f"{thr:>8.0f}{sm['n']:>7}{sm['ev']:>+9.3f}{sm['median']:>+8.2f}"
                  f"{sm['win_pct']:>7.1f}{sm['payoff']:>8.2f}{sm['pf']:>7.2f}"
                  f"{sm['ct']:>+9.2f}{sm['ex_ev']:>+9.3f}{sm['ex_ct']:>+8.2f}")
        if len(rows_th) < 2:
            print("\nNeed at least two thresholds to compare.", file=sys.stderr)
            return 1
        lo_ex = rows_th[0][1]["ex_ev"]
        hi_ex = rows_th[-1][1]["ex_ev"]
        spread = max(r["ex_ev"] for _, r in rows_th) - min(r["ex_ev"] for _, r in rows_th)
        print(f"\nexcess EV at the loosest threshold ({rows_th[0][0]:.0f}): "
              f"{lo_ex:+.3f}%")
        print(f"excess EV at the tightest threshold ({rows_th[-1][0]:.0f}): "
              f"{hi_ex:+.3f}%")
        print(f"spread across the sweep: {spread:.3f} pts")
        print("\nRead it this way: a threshold of 0 enters almost every bar, so its "
              "row is\nwhat the UNIVERSE did over these windows. If the tighter "
              "thresholds do not\nbeat it, the composite score is selecting nothing "
              "and the holding-period\nresult is drift rather than stock picking — "
              "the alpha check cannot catch\nthat, because it subtracts the INDEX, "
              "not this universe.")
        return 0

    if args.sweep_holding:
        print(f"tickers={len(dfs)}  folds={len(folds)}  "
              f"holding periods={len(args.sweep_holding)}  ({args.period})")
        print("ALL exit rules OFF — the only thing closing a position is the "
              "holding limit.\n")
        h = (f"{'hold_d':>8}{'n':>7}{'EV%':>9}{'med%':>8}{'win%':>7}"
             f"{'be-win%':>9}{'payoff':>8}{'PF':>7}{'t':>7}{'clust_t':>9}"
             f"{'exEV%':>9}{'ex_clt':>8}")
        print(h); print("-" * len(h))
        best_h, best_s = None, None
        ev_by_hold = []
        stats_by_hold = []
        for days in args.sweep_holding:
            cfg = replace(base, risk=unmanaged,
                          backtest=replace(base.backtest, holding_max_days=days))
            s = summarise(pooled_oos_trades(dfs, cfg, folds,
                                            warmup_bars=args.warmup_bars), bench)
            if not s.get("n"):
                print(f"{days:>8}{0:>7}   (no OOS trades)")
                ev_by_hold.append(None)
                stats_by_hold.append(None)
                continue
            ev_by_hold.append(s["ev"])
            stats_by_hold.append(s)
            print(f"{days:>8}{s['n']:>7}{s['ev']:>+9.3f}{s['median']:>+8.2f}"
                  f"{s['win_pct']:>7.1f}{s['be_win_pct']:>9.1f}{s['payoff']:>8.2f}"
                  f"{s['pf']:>7.2f}{s['t']:>+7.2f}{s['ct']:>+9.2f}"
                  f"{s['ex_ev']:>+9.3f}{s['ex_ct']:>+8.2f}")
            if best_s is None or s["ev"] > best_s["ev"]:
                best_h, best_s = days, s
        if best_s is None:
            print("\nNo holding period produced a trade.", file=sys.stderr)
            return 1
        print(f"\nbest: hold {best_h} days -> EV {best_s['ev']:+.3f}%/trade "
              f"(n={best_s['n']}, plain t={best_s['t']:+.2f}, "
              f"CLUSTERED t={best_s['ct']:+.2f})")
        print("  The clustered figure governs: same-day trades across tickers share "
              "that day's\n  move, so the plain t treats correlated draws as "
              "independent and over-rejects.")

        # "Not significant" is not actionable on its own — the useful question is
        # how far away significance is. If the shortfall is a few hundred trades
        # it is worth collecting; if it is an order of magnitude it is a
        # statement about the universe, not a to-do.
        if best_s["std"] > 0 and best_s["ev"] > 0:
            need = (2.0 * best_s["std"] / best_s["ev"]) ** 2
            print(f"  per-trade std {best_s['std']:.1f}% -> reaching |t|=2 at this EV "
                  f"needs n≈{need:,.0f},\n  about {need / best_s['n']:.1f}x the "
                  f"{best_s['n']} trades this sweep produced.")

        # universe.py exposes no point-in-time flag (CHANGES.md claims one was
        # added; it was not), and the list IS current membership, so state this
        # unconditionally rather than gating it on a symbol that may not exist.
        if True:
            print("\nSURVIVORSHIP: the universe is CURRENT index membership, so every "
                  "ticker here\n  survived to today. Names delisted or dropped from the "
                  "index — usually after\n  falling — are absent from all of history. "
                  "That inflates a long-hold result\n  specifically, because the "
                  "expectancy sits in a right tail made of survivors.\n  It cannot be "
                  "removed without point-in-time constituents; it can only be\n  "
                  "stated. A positive result here is an UPPER bound.")

        evs = [e for e in ev_by_hold if e is not None]
        # With fewer than three points there is no shape to read: a one-row
        # sweep makes `all(...)` vacuously true, which printed "the column never
        # turns over — widen the range" after a run that swept a single value.
        if len(evs) < 3:
            print("\nOnly %d holding period(s) swept — too few to say anything "
                  "about the\nshape of the curve. Sweep at least three to judge "
                  "whether it turns over." % len(evs))
        elif all(b >= a for a, b in zip(evs, evs[1:])):
            print("\nThe EV column never turns over, so the best holding period is "
                  "outside\nthe range you swept — widen it before reading the top row "
                  "as an optimum.")
        else:
            # A dip does not mean noise on its own. Judge it against the spread
            # of the strong rows: a shallow wobble across cells that all clear
            # the significance bar is a PLATEAU — which is the friendlier shape,
            # because it means the result does not depend on hitting one setting.
            strong = [e for e, s_ in zip(evs, [r for r in stats_by_hold if r])
                      if s_ and abs(s_.get("ct", 0)) >= 2.0]
            top = sorted(evs, reverse=True)[:3]
            wobble = (max(top) - min(top)) if len(top) > 1 else 0.0
            if len(strong) >= 3 and wobble < 0.5 * max(top):
                print(f"\nThe EV column is not monotone, but the top rows sit within "
                      f"{wobble:.2f} pts of\neach other and several clear the "
                      "significance bar — that is a PLATEAU, not noise.\nA plateau is "
                      "the better shape: the result does not hinge on picking one\n"
                      "exact setting. Do not read the top row as an optimum; read the "
                      "range as one.")
            else:
                print("\nThe EV column is NOT monotone and the rows are not uniformly "
                      "strong. On a\nreal effect this surface would be smooth; rises "
                      "and dips of this size are\nthe shape of noise, and a second "
                      "reason not to read the best row as a setting.")
        return 0

    grid = [(s, t, b) for s in args.stops for t in args.targets for b in args.breakevens]
    print(f"tickers={len(dfs)}  folds={len(folds)}  grid={len(grid)} cells "
          f"({args.period}, train={args.train_bars}/test={args.test_bars})")
    print(f"baseline: stop {base.risk.hard_stop_pct:+.1f}%  "
          f"target +{base.risk.target_profit_pct:.1f}%  "
          f"breakeven +{base.risk.breakeven_trigger_pct:.1f}%\n")

    hdr = (f"{'stop':>6}{'target':>8}{'brkeven':>9}{'n':>6}{'EV%':>8}{'med%':>8}"
           f"{'win%':>7}{'be-win%':>9}{'payoff':>8}{'PF':>7}{'t':>7}{'clust_t':>9}")

    # CONTROL: same entries, same folds, exits effectively switched off, so the
    # only thing closing a position is BacktestConfig.holding_max_days. Without
    # this line the grid answers "which ladder is least bad" and quietly ducks
    # the prior question — whether managing the exit beats not managing it. If
    # no cell beats the control, the ladder is subtracting value and no amount
    # of tuning inside the grid fixes that.
    ctrl_cfg = replace(base, risk=unmanaged)
    control = summarise(pooled_oos_trades(dfs, ctrl_cfg, folds,
                                          warmup_bars=args.warmup_bars), bench)
    print(hdr); print("-" * len(hdr))
    if control.get("n"):
        print(f"{'HOLD':>6}{'--':>8}{'--':>9}{control['n']:>6}{control['ev']:>+8.3f}"
              f"{control['median']:>+8.2f}{control['win_pct']:>7.1f}"
              f"{control['be_win_pct']:>9.1f}{control['payoff']:>8.2f}{control['pf']:>7.2f}"
              f"{control['t']:>+7.2f}{control['ct']:>+9.2f}   <- control: no stop/target/trail")
        print("-" * len(hdr))

    rows = []
    for i, (stop, target, brk) in enumerate(grid):
        cfg = replace(base, risk=replace(base.risk, hard_stop_pct=stop,
                                         target_profit_pct=target,
                                         breakeven_trigger_pct=brk))
        s = summarise(pooled_oos_trades(dfs, cfg, folds, warmup_bars=args.warmup_bars), bench)
        # A whole grid of zeros is a wiring fault, not a finding — and it is the
        # single most misleading thing this tool could print, because it looks
        # like a tidy negative result. Stop on the first cell instead of filling
        # the screen with zeros.
        if i == 0 and not s.get("n"):
            print(f"\nERROR: the baseline cell produced no out-of-sample trades at "
                  f"all.\n       With {len(dfs)} tickers over {len(folds)} folds that "
                  "is a wiring fault,\n       not a property of the exit ladder. Check "
                  "results/kala.log for\n       swallowed engine errors before "
                  "trusting any row below.", file=sys.stderr)
            return 1
        if not s.get("n"):
            print(f"{stop:>6.1f}{target:>8.1f}{brk:>9.1f}{0:>6}   (no OOS trades)")
            continue
        rows.append(((stop, target, brk), s))
        print(f"{stop:>6.1f}{target:>8.1f}{brk:>9.1f}{s['n']:>6}{s['ev']:>+8.3f}"
              f"{s['median']:>+8.2f}{s['win_pct']:>7.1f}{s['be_win_pct']:>9.1f}"
              f"{s['payoff']:>8.2f}{s['pf']:>7.2f}{s['t']:>+7.2f}{s['ct']:>+9.2f}")

    if not rows:
        print("\nNo cell produced an out-of-sample trade.")
        return 1

    rows.sort(key=lambda kv: kv[1]["ev"], reverse=True)
    (bs, bt, bb), best = rows[0]
    print("\n" + "-" * len(hdr))
    print(f"best EV cell: stop {bs:+.1f}%  target +{bt:.1f}%  breakeven +{bb:.1f}%  "
          f"-> EV {best['ev']:+.3f}%/trade on n={best['n']}")
    print(f"  win rate {best['win_pct']:.1f}% vs break-even {best['be_win_pct']:.1f}% "
          f"— margin {best['win_pct'] - best['be_win_pct']:+.1f} pts")

    if control.get("n"):
        print(f"  vs control (no exit management): EV {control['ev']:+.3f}%/trade "
              f"-> ladder adds {best['ev'] - control['ev']:+.3f} pts")

    # The direction of the verdict decides how the grid size cuts. Picking the
    # best of N biases the winner UP, so an all-negative grid is a conservative
    # negative — deflation cannot rescue it, and does not need to.
    if best["ev"] <= 0:
        print(f"\nEVERY one of the {len(rows)} cells is negative. Note which way the "
              f"multiple-comparison\nbias runs here: taking the best of {len(rows)} "
              "inflates the winner, and the winner is\nSTILL negative — so this is a "
              "conservative reading, not an optimistic one.\nNo setting inside this "
              "grid makes the strategy profitable; the exit ladder is\nnot the binding "
              "constraint. Look upstream at the entry signal.")
    else:
        print(f"\nThis is the best of {len(rows)} cells. Treat it as a hypothesis, not "
              f"a setting:\n  * a margin under ~3 points is inside the noise of a sample "
              f"this size;\n  * re-run with a different --period before believing any "
              f"cell;\n  * feed the winner through overfitting.deflated_sharpe with "
              f"n_trials={len(rows)}\n    before it earns a place in config.py.")

    # A monotone gradient that never turns over means the optimum is outside the
    # box, so the "best" cell is an artefact of where the grid was cut.
    edges = []
    if bt == max(args.targets):
        edges.append(f"target sits at the grid edge (+{bt:.0f}%)")
    if bb == max(args.breakevens):
        edges.append(f"breakeven sits at the grid edge (+{bb:.0f}%)")
    if bs in (min(args.stops), max(args.stops)):
        edges.append(f"stop sits at the grid edge ({bs:+.0f}%)")
    if edges:
        print("\nGrid-boundary warning: " + "; ".join(edges) + ".")
        print("  The surface has not turned over, so the best cell is where the box "
              "ends,\n  not where the optimum is. Widen those axes before reading the "
              "winner as one.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
