"""
Walk-forward, out-of-sample validation of the composite-score edge.

WHY THIS EXISTS
---------------
The backtest engine (``kala.backtest``) is honest about *execution* —
next-open fills, ARB carry, asymmetric costs — but every number it produces is
still IN-SAMPLE: the score weights and the entry threshold were shaped while
looking at the same history the backtest runs on. That means the reported
returns measure "how well the rules fit the past", not "does the edge exist".

This module answers the second question the only way it can be answered:

  1. Slice history into rolling folds:  [train window][test window] ->
     shift -> [train window][test window] -> ...
  2. On each TRAIN window, sweep the entry threshold and record the pooled
     per-trade expected value (EV) across the whole universe.
  3. Pick the best threshold *using train data only* (subject to a minimum
     trade count so one lucky trade can't win the sweep).
  4. Evaluate that choice on the TEST window — data the choice never saw —
     and, side by side, evaluate the configured baseline threshold on the
     same test window.
  5. Pool the out-of-sample trades across all folds and report EV/trade,
     win rate, profit factor and a t-statistic on "is mean net return > 0".

THE PRIMARY METRIC IS EV PER TRADE, NOT WIN RATE. A 45%-win system with fat
winners beats a 60%-win system with fat losers; win rate is reported only as
context. (See the coin-toss argument: P(win)*avg_win + P(loss)*avg_loss is
the number that compounds.)

DESIGN CONSTRAINTS honoured here:
  * Zero changes to ``backtest.py``. We re-use ``backtest_ticker`` verbatim
    and confine entries to a window by filtering closed trades on
    ``entry_date``. Exits are allowed to complete past the window edge (a
    small grace tail) so a trade entered on the last test day still gets its
    *real* exit instead of being dropped or force-marked.
  * Point-in-time discipline is inherited: features are computed on the
    slice we feed in, warm-up bars are prepended so the first in-window bar
    already has valid SMA-50/RSI/ATR, and the threshold used on test data is
    frozen before the test data is touched.
  * No network access. Callers supply ``{ticker: OHLCV DataFrame}``; the CLI
    wrapper (``run_walkforward.py``) does the yfinance fetching.

Typical use::

    from kala.walkforward import walk_forward
    report = walk_forward(dfs, benchmark=ihsg_df)
    print(report.summary_text())
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

import pandas as pd

from .backtest import backtest_ticker
from .config import Config

# Sweep grid. Deliberately coarse: a fine grid on a noisy objective is just
# another way to overfit. 5-point steps around the configured default.
DEFAULT_THRESHOLDS = (50.0, 55.0, 60.0, 65.0, 70.0, 75.0)


# ---------------------------------------------------------------------------
# Per-trade statistics — EV first, win rate as context
# ---------------------------------------------------------------------------

def excess_ev(stats: dict | None) -> float | None:
    """The excess EV of a fold, or None when no excess was COMPUTED.

    Never 0.0 for the not-measured case. ``trade_stats([])`` returns a fully
    populated dict whose ev_pct is 0.0, and a populated dict is truthy — so the
    obvious guards (``if stats:`` / ``stats or {}``) both sail straight past an
    empty result and hand back a zero.

    That zero then rendered as "+0.00" in the fold table and was written as
    ``0.0`` into --save-folds JSON: a run with no benchmark reported "measured,
    exactly no alpha, in all fourteen folds" instead of "not measured". The
    saved file is the worse half, because it outlives the terminal and gets
    correlated later.

    A run of identical zeros also has zero variance, so a correlation against
    it comes back NaN — which looks like the tooling correctly refusing to
    answer, when in fact it was fed fabricated data.
    """
    if not stats or stats.get("n", 0) <= 0:
        return None
    return stats.get("ev_pct")


def trade_stats(returns: list[float]) -> dict:
    """Pooled statistics for a list of NET per-trade returns (percent).

    ``ev_pct`` (the arithmetic mean) is the headline number: it is the
    expected value of putting on one trade under these rules. ``t_stat`` is
    mean / (std/sqrt(n)) — a crude but honest check on whether that EV is
    distinguishable from zero, or just noise. Rule of thumb: |t| >= 2 with a
    healthy n before believing the edge.
    """
    n = len(returns)
    if n == 0:
        return {"n": 0, "ev_pct": 0.0, "median_pct": 0.0, "win_rate_pct": 0.0,
                "profit_factor": 0.0, "std_pct": 0.0, "t_stat": 0.0,
                "total_compounded_pct": 0.0}

    mean = sum(returns) / n
    srt = sorted(returns)
    mid = n // 2
    median = srt[mid] if n % 2 else (srt[mid - 1] + srt[mid]) / 2.0

    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r <= 0]
    gross_win = sum(wins)
    gross_loss = -sum(losses)
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else float("inf")

    var = sum((r - mean) ** 2 for r in returns) / (n - 1) if n > 1 else 0.0
    std = math.sqrt(var)
    t_stat = (mean / (std / math.sqrt(n))) if (n > 1 and std > 0) else 0.0

    equity = 1.0
    for r in returns:
        equity *= (1.0 + r / 100.0)

    return {
        "n": n,
        "ev_pct": mean,                       # <- THE number
        "median_pct": median,
        "win_rate_pct": len(wins) / n * 100.0,
        "profit_factor": profit_factor,
        "std_pct": std,
        "t_stat": t_stat,
        "total_compounded_pct": (equity - 1.0) * 100.0,
    }


# ---------------------------------------------------------------------------
# Fold generation on a master calendar
# ---------------------------------------------------------------------------

def clustered_t_stat(returns: list[float], cluster_keys: list) -> float:
    """t-stat of the mean using a CLUSTER-ROBUST standard error.

    ``trade_stats``'s plain t divides by std/sqrt(n), which assumes the n
    trades are independent draws. They are not: trades opened on the same
    day, across different tickers, share whatever the market did that day.
    Subtracting the benchmark (see ``excess_returns``) removes the index
    component, but sector and style moves survive it.

    Measured cost of ignoring that, by simulation on trades with a TRUE edge
    of exactly zero — how often |t| >= 2 says "significant":

        share of variance shared within a day  |  false positives
                                            0% |   4.4%   (correct)
                                           10% |  13.1%
                                           20% |  20.8%
                                           40% |  31.5%

    So the plain t over-rejects, sometimes several-fold. Two consequences,
    pulling in opposite directions:

      * A NULL result gets STRONGER. A test biased toward finding an edge
        that still found none is more damning, not less.
      * Any POSITIVE t deserves discounting before it is believed.

    This clusters by ``cluster_keys`` (use the entry date) and returns the
    corrected t. With one trade per cluster it reduces to the plain t.
    """
    n = len(returns)
    if n < 2 or len(cluster_keys) != n:
        return 0.0
    mean = sum(returns) / n
    groups: dict = {}
    for r, k in zip(returns, cluster_keys):
        groups.setdefault(k, []).append(r - mean)
    # CRVE for a sample mean: sum the squared WITHIN-CLUSTER sums of the
    # demeaned values, rather than the squared values themselves. Identical
    # to the usual formula when every cluster holds one observation.
    meat = sum(sum(g) ** 2 for g in groups.values())
    if meat <= 0 or len(groups) < 2:
        return 0.0
    se = math.sqrt(meat) / n
    return mean / se if se > 0 else 0.0


def _dsr_fields(returns: list[float], n_trials: int) -> dict:
    """Deflated Sharpe on the pooled excess returns, as report fields.

    The walk-forward picks the best of ``n_trials`` entry thresholds, so the
    winning number is a maximum over trials and is biased upward by
    selection alone. That is precisely what the Deflated Sharpe corrects
    for, and precisely the failure this project already suffered once (the
    retracted >= IDR 1,000 "edge", t=3.38). Wired in here so it runs on
    every study instead of being a module nobody calls.

    trial_variance is left at the textbook 1/n default — the honest
    alternative needs each threshold's own Sharpe, which the pooled view
    does not carry.
    """
    n = len(returns)
    if n < 3 or n_trials < 1:
        return {"pooled_excess_dsr": 0.0, "dsr_n_trials": max(0, n_trials)}
    mean = sum(returns) / n
    var = sum((r - mean) ** 2 for r in returns) / (n - 1)
    std = math.sqrt(var)
    if std <= 0:
        return {"pooled_excess_dsr": 0.0, "dsr_n_trials": n_trials}
    try:
        from .overfitting import deflated_sharpe_ratio
        res = deflated_sharpe_ratio(mean / std, n_trials=n_trials,
                                    n_observations=n)
        return {"pooled_excess_dsr": float(res.dsr), "dsr_n_trials": n_trials}
    except Exception:
        # A diagnostic must never take down the study it is diagnosing.
        return {"pooled_excess_dsr": 0.0, "dsr_n_trials": n_trials}


def excess_returns_by_date(trades: list, benchmark: pd.DataFrame | None):
    """``excess_returns`` paired with each trade's entry date, so the caller
    can cluster by date. Same skipping rules, same order."""
    if benchmark is None or len(benchmark) < 2:
        return [], []
    bclose = benchmark["Close"]
    values, dates = [], []
    for t in trades:
        try:
            entry_ts, exit_ts = pd.Timestamp(t.entry_date), pd.Timestamp(t.exit_date)
            b_entry = bclose.asof(entry_ts)
            b_exit = bclose.asof(exit_ts)
            if pd.isna(b_entry) or pd.isna(b_exit) or b_entry <= 0:
                continue
            bench_pct = (float(b_exit) / float(b_entry) - 1.0) * 100.0
            values.append(t.net_return_pct - bench_pct)
            dates.append(entry_ts.normalize())
        except Exception:
            continue
    return values, dates


@dataclass(frozen=True)
class Fold:
    fold_id: int
    train_start: pd.Timestamp
    train_end: pd.Timestamp     # inclusive
    test_start: pd.Timestamp
    test_end: pd.Timestamp      # inclusive


def make_folds(master_index: pd.DatetimeIndex, train_bars: int, test_bars: int,
               warmup_bars: int = 60) -> list[Fold]:
    """Rolling, non-overlapping-test folds on a shared calendar.

    ``master_index`` is the union of all tickers' trading days, so fold
    boundaries are dates, not per-ticker bar counts — every ticker is judged
    on the same calendar window. The first ``warmup_bars`` days are reserved
    so even the first train window starts with warm indicators.
    """
    idx = master_index.sort_values().unique()
    folds: list[Fold] = []
    start = warmup_bars
    fid = 0
    while start + train_bars + test_bars <= len(idx):
        tr0 = idx[start]
        tr1 = idx[start + train_bars - 1]
        te0 = idx[start + train_bars]
        te1 = idx[start + train_bars + test_bars - 1]
        folds.append(Fold(fid, tr0, tr1, te0, te1))
        start += test_bars           # step by the test length: OOS windows tile
        fid += 1
    return folds


# ---------------------------------------------------------------------------
# Window evaluation: entries confined, exits allowed to finish
# ---------------------------------------------------------------------------

def _with_threshold(cfg: Config, threshold: float) -> Config:
    """Immutable clone of cfg with a different entry threshold."""
    return replace(cfg, backtest=replace(cfg.backtest, score_entry_threshold=threshold))


def evaluate_window(ticker: str, df: pd.DataFrame,
                    entry_start: pd.Timestamp, entry_end: pd.Timestamp,
                    threshold: float, cfg: Config,
                    warmup_bars: int = 60,
                    exit_grace_bars: int | None = None,
                    benchmark: pd.DataFrame | None = None,
                    return_trades: bool = False,
                    strategy=None):
    """Net per-trade returns for trades ENTERED inside [entry_start, entry_end].
    Returns ``list[float]`` (default) or ``list[Trade]`` when
    ``return_trades=True`` — the latter carries entry_date/exit_date, needed
    to measure a trade's return AGAINST the benchmark over its own holding
    window (see ``excess_returns``), not just in isolation.

    ``strategy``: an ``kala.strategies.Strategy`` (or any duck-typed
    object with ``.compute_features``/``.score``) to test INSTEAD of the
    default composite score. Its score is computed fresh on THIS SAME
    sliced window, mirroring exactly what backtest_ticker does internally
    for the default score — computing it once on full history and slicing
    would NOT be equivalent for EMA-based features (MACD has exponentially-
    decaying memory, so where the calculation starts changes the value).
    None (default) uses composite_score, unchanged behavior.

    The slice fed to ``backtest_ticker`` runs from ``warmup_bars`` before the
    window to ``exit_grace_bars`` after it. Warm-up gives the first in-window
    bar valid indicators; the grace tail lets trades opened late in the window
    reach their real exit. Trades whose entry date falls outside the window —
    including grace-tail entries and positions carried in from before — are
    discarded, so no fold's stats contain another fold's information.
    """
    if exit_grace_bars is None:
        exit_grace_bars = cfg.backtest.holding_max_days + 5

    idx = df.index
    lo = max(0, int(idx.searchsorted(entry_start)) - warmup_bars)
    hi = min(len(idx), int(idx.searchsorted(entry_end, side="right")) + exit_grace_bars)
    window = df.iloc[lo:hi]
    if len(window) < warmup_bars // 2:      # too little history to say anything
        return []

    score_override = strategy.score(strategy.compute_features(window)) if strategy is not None else None
    res = backtest_ticker(ticker, window, benchmark=benchmark, cfg=_with_threshold(cfg, threshold),
                          score_override=score_override)
    trades = [t for t in res.closed
             if entry_start <= pd.Timestamp(t.entry_date) <= entry_end]
    return trades if return_trades else [t.net_return_pct for t in trades]


def excess_returns(trades: list, benchmark: pd.DataFrame | None) -> list[float]:
    """Per-trade return MINUS what the benchmark did over that SAME
    [entry_date, exit_date] window — 'would this stock have beaten just
    holding the index over the days you actually held it, or did it merely
    ride the index up?'. This is the alpha-vs-beta test: a positive raw EV
    that collapses here was market exposure dressed as stock selection.

    Trades whose window can't be matched in the benchmark (missing data,
    or benchmark not supplied) are skipped, not zero-filled — a silent
    zero would understate the drag exactly like an unmeasured trade would."""
    if benchmark is None or len(benchmark) < 2:
        return []
    bclose = benchmark["Close"]
    out = []
    for t in trades:
        try:
            entry_ts, exit_ts = pd.Timestamp(t.entry_date), pd.Timestamp(t.exit_date)
            b_entry = bclose.asof(entry_ts)
            b_exit = bclose.asof(exit_ts)
            if pd.isna(b_entry) or pd.isna(b_exit) or b_entry <= 0:
                continue
            bench_pct = (float(b_exit) / float(b_entry) - 1.0) * 100.0
            out.append(t.net_return_pct - bench_pct)
        except Exception:
            continue
    return out


def sweep_thresholds(dfs: dict[str, pd.DataFrame],
                     entry_start: pd.Timestamp, entry_end: pd.Timestamp,
                     thresholds, cfg: Config, warmup_bars: int = 60,
                     benchmark: pd.DataFrame | None = None,
                     strategy=None) -> dict[float, dict]:
    """Pooled trade stats per threshold, across the whole universe, one window.

    ``strategy``: an ``kala.strategies.Strategy`` to test instead of the
    default composite score. None uses composite_score."""
    out: dict[float, dict] = {}
    for thr in thresholds:
        pooled: list[float] = []
        for ticker, df in dfs.items():
            pooled.extend(evaluate_window(ticker, df, entry_start, entry_end,
                                          thr, cfg, warmup_bars, benchmark=benchmark,
                                          strategy=strategy))
        out[thr] = trade_stats(pooled)
    return out


def pick_threshold(sweep: dict[float, dict], baseline: float,
                   min_trades: int = 30) -> float:
    """Highest-EV threshold among those with enough trades to be believed.

    ``min_trades`` is the anti-overfit guard: a threshold that produced 4
    trades at +6% each must not beat one that produced 80 at +1.2%. If no
    threshold clears the bar, fall back to the configured baseline — 'not
    enough evidence to deviate' is the correct conservative answer.
    """
    eligible = {t: s for t, s in sweep.items() if s["n"] >= min_trades}
    if not eligible:
        return baseline
    return max(eligible.items(), key=lambda kv: kv[1]["ev_pct"])[0]


# ---------------------------------------------------------------------------
# The walk itself
# ---------------------------------------------------------------------------

DSR_CONFIDENT = 0.95      # the report's own stated bar for the deflated Sharpe
T_CONFIDENT = 2.0         # the report's own stated bar for the t-statistic


def _edge_verdict(stats: dict, clustered_t: float | None = None,
                  dsr: float | None = None, n_trials: int = 0) -> str:
    """Shared verdict wording for a pooled trade_stats dict — used for both
    the raw-return check and the alpha (excess-over-benchmark) check, so the
    two read as the same kind of judgment, not two different vocabularies.

    ``clustered_t`` and ``dsr`` MUST be the ones computed for the same arm as
    ``stats``. Passing the walk-forward arm's clustered t alongside the
    fixed-baseline arm's stats would judge one arm by another's evidence.

    WHY THESE ARGUMENTS EXIST
    -------------------------
    This function used to read only ``stats["t_stat"]`` — the PLAIN t. The
    report printed the clustered t and the deflated Sharpe directly above the
    verdict, told the reader in as many words to trust them, and then rendered
    a verdict that ignored both.

    That went live. A run against an equal-weighted benchmark printed:

        clustered t (by entry date) = 1.60  vs plain t = 1.74
        deflated Sharpe = 0.670 ...
        Below ~0.95, the winning threshold is not distinguishable from the
        best of that many coin flips.
        ALPHA VERDICT: ALPHA CHECK: EDGE CONFIRMED OOS

    Both corrections said no. The headline said yes, off a plain t of 2.05 that
    the surrounding text had just finished explaining was too generous. A
    reader who trusts the bold line — which is what a bold line is for — gets
    the opposite of what the evidence supports.
    """
    ev = stats.get("ev_pct", 0.0)
    if stats.get("n", 0) < 30:
        return "INCONCLUSIVE — too few OOS trades to judge the edge."
    if ev <= 0:
        return ("NO OOS EDGE — the in-sample numbers were fit, not found. "
                "Do not size up on backtest returns.")

    # Same-day trades share that day's move, so the plain t over-rejects.
    # Where the clustered t exists it is the honest one and it governs.
    if clustered_t:
        t_used, t_label = clustered_t, "clustered t"
    else:
        t_used, t_label = stats.get("t_stat", 0.0), "t"

    if t_used < T_CONFIDENT:
        return (f"EV positive but WEAK ({t_label} {t_used:.2f} < {T_CONFIDENT:g}): "
                f"could be noise. More history or a stronger filter needed "
                f"before trusting it.")

    # Surviving the t is not enough when the threshold was the best of N.
    if n_trials and dsr is not None and dsr < DSR_CONFIDENT:
        return (f"EV positive and {t_label} {t_used:.2f} clears {T_CONFIDENT:g}, "
                f"but the DEFLATED SHARPE is {dsr:.3f} (< {DSR_CONFIDENT}) after "
                f"deflating for {n_trials} thresholds tried — NOT distinguishable "
                f"from the best of that many coin flips. Do not size up on it.")

    return "EDGE CONFIRMED OOS — positive EV, statistically distinguishable from 0."


# Public alias. The live path judges a saved measurement with the SAME words
# this report uses, deliberately: a third vocabulary for the same question is
# how a screen ends up saying "EDGE CONFIRMED" while the report that produced
# the file says the opposite.
edge_verdict = _edge_verdict


@dataclass
class FoldResult:
    fold: Fold
    chosen_threshold: float
    train_stats: dict                 # stats of the chosen threshold, in-sample
    oos_chosen: dict                  # chosen threshold, out-of-sample
    oos_baseline: dict                # configured baseline, same OOS window
    oos_returns_chosen: list[float] = field(default_factory=list)
    oos_returns_baseline: list[float] = field(default_factory=list)
    benchmark_return_pct: float | None = None   # IHSG buy&hold over the test window
    # Alpha-vs-beta diagnostic (empty/zero unless a benchmark was supplied):
    # each trade's return minus what the benchmark did over that SAME
    # entry->exit window. A raw edge that vanishes here was market exposure
    # during a rally, not stock-picking skill — see excess_returns().
    oos_excess_chosen: dict = field(default_factory=dict)
    oos_excess_baseline: dict = field(default_factory=dict)


@dataclass
class WalkForwardReport:
    folds: list[FoldResult]
    baseline_threshold: float
    pooled_chosen: dict = field(default_factory=dict)
    pooled_baseline: dict = field(default_factory=dict)
    pooled_excess_chosen: dict = field(default_factory=dict)
    pooled_excess_baseline: dict = field(default_factory=dict)
    # Same pooled excess returns, but with a standard error that allows for
    # trades opened on the SAME DAY sharing that day's move. The plain t in
    # pooled_excess_chosen assumes independence and over-rejects; see
    # clustered_t_stat for the measured size of that.
    pooled_excess_clustered_t: float = 0.0
    # Probability the TRUE per-trade Sharpe is > 0 once deflated for having
    # picked the best of N thresholds. kala/overfitting.py existed to
    # quantify exactly this and had ZERO callers — CASE_STUDY.md told a
    # reader the check was in place while nothing ran it. Now every
    # walk-forward computes it.
    pooled_excess_dsr: float = 0.0
    dsr_n_trials: int = 0
    # The SAME two corrections, computed for the fixed-baseline arm. The ALPHA
    # VERDICT is rendered from that arm, so judging it on the chosen arm's
    # clustered t would apply one arm's statistic to another arm's conclusion.
    pooled_excess_baseline_clustered_t: float = 0.0
    pooled_excess_baseline_dsr: float = 0.0

    def summary_text(self) -> str:
        """Human-readable report (fits in a Telegram message for small runs)."""
        lines = []
        lines.append("WALK-FORWARD VALIDATION — out-of-sample per-trade EV")
        lines.append("=" * 73)
        lines.append(f"{'fold':<5}{'test window':<26}{'thr':>5}"
                     f"{'trades':>8}{'EV/trade':>10}{'win%':>7}{'IHSG%':>8}"
                     f"{'excess%':>9}")
        for fr in self.folds:
            win = f"{fr.fold.test_start.date()}..{fr.fold.test_end.date()}"
            bench = f"{fr.benchmark_return_pct:+.1f}" if fr.benchmark_return_pct is not None else "  n/a"
            # Per-fold EXCESS, not just raw. Two long-only baskets in the same
            # market have strongly correlated RAW fold returns by construction,
            # so comparing strategies on the raw column measures the market and
            # invites exactly the wrong conclusion. The excess column is the one
            # that can say whether two signals share something beyond beta.
            ex = excess_ev(fr.oos_excess_chosen)
            ex_s = f"{ex:+.2f}" if ex is not None else "  n/a"
            lines.append(f"{fr.fold.fold_id:<5}{win:<26}{fr.chosen_threshold:>5.0f}"
                         f"{fr.oos_chosen['n']:>8}{fr.oos_chosen['ev_pct']:>+9.2f}%"
                         f"{fr.oos_chosen['win_rate_pct']:>6.0f}%{bench:>8}{ex_s:>9}")
        lines.append("-" * 73)

        for label, s in (("POOLED OOS (walk-forward threshold)", self.pooled_chosen),
                         (f"POOLED OOS (fixed baseline {self.baseline_threshold:.0f})", self.pooled_baseline)):
            lines.append(label)
            lines.append(f"  trades={s['n']}  EV/trade={s['ev_pct']:+.2f}%  "
                         f"median={s['median_pct']:+.2f}%  win={s['win_rate_pct']:.0f}%  "
                         f"PF={s['profit_factor']:.2f}  t={s['t_stat']:.2f}")
        lines.append("-" * 64)
        # Labelled RAW because that is what it is: measured against cash, not
        # against the market. Unlabelled, it reads as the last word on the
        # strategy — and when the alpha check below does not run, it becomes
        # the last word, which is how a beta result gets recorded as an edge.
        lines.append("VERDICT (raw, vs cash): " + _edge_verdict(self.pooled_baseline))

        if self.pooled_excess_baseline.get("n", 0) > 0:
            lines.append("-" * 64)
            lines.append("ALPHA CHECK — same trades, return measured AGAINST the "
                         "benchmark over each trade's own holding window (not in "
                         "isolation). Tests whether the raw edge above is stock-picking "
                         "skill or just market exposure during a rally.")
            for label, s in (("EXCESS OOS (walk-forward threshold)", self.pooled_excess_chosen),
                             (f"EXCESS OOS (fixed baseline {self.baseline_threshold:.0f})",
                              self.pooled_excess_baseline)):
                lines.append(label)
                lines.append(f"  trades={s['n']}  EV/trade={s['ev_pct']:+.2f}%  "
                             f"median={s['median_pct']:+.2f}%  win={s['win_rate_pct']:.0f}%  "
                             f"PF={s['profit_factor']:.2f}  t={s['t_stat']:.2f}")
            if self.pooled_excess_clustered_t:
                plain = self.pooled_excess_chosen.get("t_stat", 0.0)
                lines.append(
                    f"  clustered t (by entry date) = "
                    f"{self.pooled_excess_clustered_t:.2f}  vs plain t = {plain:.2f}")
                # The verdict is rendered from the BASELINE arm, so that arm's
                # own corrections have to be on the page. Printing only the
                # chosen arm's left the verdict's actual basis invisible.
                if self.pooled_excess_baseline_clustered_t:
                    plain_b = self.pooled_excess_baseline.get("t_stat", 0.0)
                    lines.append(
                        f"  fixed-baseline arm: clustered t = "
                        f"{self.pooled_excess_baseline_clustered_t:.2f}  vs plain t = "
                        f"{plain_b:.2f}   <- the ALPHA VERDICT is judged on THIS")
                lines.append(
                    "  The plain t assumes trades are independent; same-day "
                    "trades share that day's move, so it over-rejects. Trust "
                    "the clustered figure — a null gets stronger under it, a "
                    "positive gets weaker.")
            if self.dsr_n_trials:
                lines.append(
                    f"  deflated Sharpe = {self.pooled_excess_dsr:.3f}  "
                    f"(P[true Sharpe > 0] after deflating for "
                    f"{self.dsr_n_trials} thresholds tried)")
                if self.pooled_excess_baseline_dsr:
                    lines.append(
                        f"  fixed-baseline arm: deflated Sharpe = "
                        f"{self.pooled_excess_baseline_dsr:.3f}"
                        f"   <- and on THIS")
                lines.append(
                    "  Below ~0.95, the winning threshold is not "
                    "distinguishable from the best of that many coin flips.")
            lines.append("-" * 64)
            raw_ev = self.pooled_baseline.get("ev_pct", 0.0)
            exc_ev = self.pooled_excess_baseline.get("ev_pct", 0.0)
            if raw_ev > 0 and exc_ev <= 0:
                alpha_verdict = ("RAW EDGE IS BETA, NOT ALPHA — positive vs cash but flat/"
                                 "negative vs the benchmark held over the same days. This "
                                 "looks like market exposure during favorable windows, not "
                                 "stock selection.")
            else:
                alpha_verdict = "ALPHA CHECK: " + _edge_verdict(
                    self.pooled_excess_baseline,
                    clustered_t=self.pooled_excess_baseline_clustered_t,
                    dsr=self.pooled_excess_baseline_dsr,
                    n_trials=self.dsr_n_trials)
            lines.append("ALPHA VERDICT: " + alpha_verdict)
        else:
            # The absence of this section used to be silent, on the reasoning
            # that the alpha check was additive and opt-in. It is not additive
            # any more: it is the measurement that overturned the exit-ladder
            # result, and every conclusion drawn from this harness rests on it.
            #
            # A run with a mistyped --benchmark prints its warning on stderr,
            # then produces a report whose only difference is a MISSING
            # section. Redirect stdout to a log and the warning is gone, and
            # what is saved reads as a clean confirmed edge. A missing section
            # is far harder to notice than a wrong number, so it is named here.
            lines.append("-" * 64)
            lines.append("ALPHA CHECK: NOT RUN — no benchmark returns were available for "
                         "these trades.")
            lines.append("  The verdict above is measured against CASH, not against the "
                         "market. It")
            lines.append("  cannot distinguish stock-picking from having been long during "
                         "a rally,")
            lines.append("  which is the distinction this harness exists to make.")
            lines.append("  Usual cause: --benchmark names a ticker yfinance does not "
                         "resolve (it")
            lines.append("  accepts any string), or the benchmark history does not overlap "
                         "the test")
            lines.append("  windows. Re-run with a benchmark that resolves before treating "
                         "this as")
            lines.append("  an edge.")
        return "\n".join(lines)


def walk_forward(dfs: dict[str, pd.DataFrame],
                 cfg: Config | None = None,
                 benchmark: pd.DataFrame | None = None,
                 train_bars: int = 252, test_bars: int = 63,
                 thresholds=DEFAULT_THRESHOLDS,
                 warmup_bars: int = 60,
                 min_train_trades: int = 30,
                 strategy=None) -> WalkForwardReport:
    """Run the full walk-forward across the universe.

    Defaults: 1 trading year of train, 1 quarter of test, quarterly steps —
    each calendar day appears in exactly one test window, so pooled OOS stats
    never double-count.

    ``strategy``: an ``kala.strategies.Strategy`` to validate a
    DIFFERENT hypothesis through this exact harness (prefer calling
    ``kala.strategies.walk_forward_strategy`` instead of passing this
    directly — it also sets a sane baseline threshold for you). None
    (default) uses composite_score, identical to every existing call.
    """
    cfg = cfg or Config()
    baseline = cfg.backtest.score_entry_threshold

    master = pd.DatetimeIndex(sorted(set().union(*[set(df.index) for df in dfs.values()])))
    folds = make_folds(master, train_bars, test_bars, warmup_bars)

    results: list[FoldResult] = []
    pooled_c: list[float] = []
    pooled_b: list[float] = []
    pooled_exc_c: list[float] = []
    pooled_exc_c_dates: list = []
    pooled_exc_b: list[float] = []
    pooled_exc_b_dates: list = []

    for fold in folds:
        # 1) choose on TRAIN only
        sweep = sweep_thresholds(dfs, fold.train_start, fold.train_end,
                                 thresholds, cfg, warmup_bars, benchmark=benchmark,
                                 strategy=strategy)
        chosen = pick_threshold(sweep, baseline, min_train_trades)

        # 2) evaluate frozen choices on TEST — trade objects once per
        # ticker/threshold (not floats), so the SAME trades feed both the
        # raw-return stats and the benchmark-relative (alpha) stats without
        # re-running backtest_ticker a second time.
        trades_c: list = []
        trades_b: list = []
        for ticker, df in dfs.items():
            trades_c.extend(evaluate_window(ticker, df, fold.test_start, fold.test_end,
                                            chosen, cfg, warmup_bars, benchmark=benchmark,
                                            return_trades=True, strategy=strategy))
            if chosen != baseline:
                trades_b.extend(evaluate_window(ticker, df, fold.test_start, fold.test_end,
                                                baseline, cfg, warmup_bars, benchmark=benchmark,
                                                return_trades=True, strategy=strategy))
        if chosen == baseline:
            trades_b = list(trades_c)

        oos_c = [t.net_return_pct for t in trades_c]
        oos_b = [t.net_return_pct for t in trades_b]
        exc_c, exc_c_dates = excess_returns_by_date(trades_c, benchmark)
        exc_b, exc_b_dates = excess_returns_by_date(trades_b, benchmark)

        bench_ret = None
        if benchmark is not None and len(benchmark) >= 2:
            b = benchmark["Close"]
            b = b.loc[(b.index >= fold.test_start) & (b.index <= fold.test_end)]
            if len(b) >= 2:
                bench_ret = float((b.iloc[-1] / b.iloc[0] - 1.0) * 100.0)

        results.append(FoldResult(
            fold=fold,
            chosen_threshold=chosen,
            train_stats=sweep[chosen],
            oos_chosen=trade_stats(oos_c),
            oos_baseline=trade_stats(oos_b),
            oos_returns_chosen=oos_c,
            oos_returns_baseline=oos_b,
            benchmark_return_pct=bench_ret,
            oos_excess_chosen=trade_stats(exc_c),
            oos_excess_baseline=trade_stats(exc_b),
        ))
        pooled_c.extend(oos_c)
        pooled_b.extend(oos_b)
        pooled_exc_c.extend(exc_c)
        pooled_exc_c_dates.extend(exc_c_dates)
        pooled_exc_b.extend(exc_b)
        pooled_exc_b_dates.extend(exc_b_dates)

    return WalkForwardReport(
        folds=results,
        baseline_threshold=baseline,
        pooled_chosen=trade_stats(pooled_c),
        pooled_baseline=trade_stats(pooled_b),
        pooled_excess_chosen=trade_stats(pooled_exc_c),
        pooled_excess_baseline=trade_stats(pooled_exc_b),
        pooled_excess_clustered_t=clustered_t_stat(pooled_exc_c, pooled_exc_c_dates),
        pooled_excess_baseline_clustered_t=clustered_t_stat(pooled_exc_b,
                                                            pooled_exc_b_dates),
        pooled_excess_baseline_dsr=_dsr_fields(
            pooled_exc_b, len(list(thresholds)))["pooled_excess_dsr"],
        **_dsr_fields(pooled_exc_c, len(list(thresholds))),
    )
