"""
Regime-conditional performance breakdown — bull/bear/crash-quarter slicing
of walk-forward OOS trades.

WHY THIS EXISTS
---------------
PROJECT_STATUS.md's "fold-level diagnosis" finding (the original positive
result was concentrated in 2 of 14 folds coinciding with the two biggest
IHSG rallies) was done by eyeballing individual fold results. This module
makes that check a first-class, repeatable report: pool every OOS trade
from a walk-forward run, tag each one by the market regime
(``kala.regime.classify_market_regime``) in effect on its ENTRY date,
and report EV/trade + t-stat PER REGIME BUCKET — so "is the edge
everywhere, or only in bull markets" is a table, not an anecdote.

Reuses the exact walk-forward machinery (folds, threshold selection on
train data only, the configured baseline threshold) via
``kala.walkforward``'s public helpers -- this module only adds the
regime tag and the per-bucket aggregation.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .config import Config
from .regime import STATUSES, classify_market_regime, regime_at
from .walkforward import evaluate_window, make_folds, trade_stats


@dataclass
class RegimeBreakdownResult:
    by_regime: dict = field(default_factory=dict)   # {status: trade_stats dict}
    n_trades_total: int = 0
    # Trades carrying NO usable regime tag. Two different things land here and
    # both are untaggable, but only the first used to be counted:
    #   * entry predates the benchmark's first bar -> regime_at returns None
    #   * entry falls inside the benchmark's SMA50 warm-up -> the string
    #     'UNKNOWN' (see regime.classify_market_regime)
    # Both are bucketed under 'UNKNOWN', so counting only one made the footer
    # disagree with the table's own UNKNOWN row and understated how much of the
    # run could not be attributed to a regime at all.
    n_untagged: int = 0
    n_before_benchmark: int = 0   # entry predates the benchmark's first bar
    n_in_warmup: int = 0          # entry inside the benchmark's SMA50 warm-up

    def summary_text(self) -> str:
        lines = ["REGIME-CONDITIONAL OOS PERFORMANCE", "=" * 56,
                f"{'regime':<16}{'trades':>9}{'EV/trade':>11}{'win%':>7}{'t-stat':>9}"]
        for status in (*STATUSES, "UNKNOWN"):
            s = self.by_regime.get(status)
            if s is None or s.get("n", 0) == 0:
                continue
            lines.append(f"{status:<16}{s['n']:>9}{s['ev_pct']:>+10.2f}%"
                         f"{s['win_rate_pct']:>6.0f}%{s['t_stat']:>9.2f}")
        lines.append("-" * 56)
        pct = (self.n_untagged / self.n_trades_total * 100.0) if self.n_trades_total else 0.0
        lines.append(f"total trades: {self.n_trades_total}  "
                     f"(no regime tag: {self.n_untagged} = {pct:.0f}% — "
                     f"{self.n_before_benchmark} before the benchmark starts, "
                     f"{self.n_in_warmup} inside its SMA50 warm-up)")
        if pct >= 20.0:
            lines.append(f"WARNING: {pct:.0f}% of trades could not be attributed to a "
                         "regime — extend the benchmark's history before reading "
                         "the per-regime rows as a verdict.")
        return "\n".join(lines)


def regime_conditional_breakdown(dfs: dict[str, pd.DataFrame],
                                 benchmark: pd.DataFrame,
                                 cfg: Config | None = None,
                                 train_bars: int = 252, test_bars: int = 63,
                                 warmup_bars: int = 60,
                                 strategy=None) -> RegimeBreakdownResult:
    """Pool walk-forward OOS trades at the configured BASELINE threshold
    (the number PROJECT_STATUS.md's verdict is about) and bucket them by
    the benchmark regime at each trade's entry date. No threshold sweep is
    needed here -- the baseline is fixed by ``cfg``, not chosen per fold --
    so this only replays the SAME fold windows walk_forward uses and
    evaluates that one threshold on each.

    ``benchmark`` is required (unlike walk_forward, where it's optional) --
    there is nothing to slice by without it.
    """
    if benchmark is None or len(benchmark) < 50:
        raise ValueError("regime_conditional_breakdown needs a benchmark "
                         "(e.g. ^JKSE) with enough history to warm up SMA50")

    cfg = cfg or Config()
    baseline = cfg.backtest.score_entry_threshold
    regime_series = classify_market_regime(benchmark)

    master = pd.DatetimeIndex(sorted(set().union(*[set(df.index) for df in dfs.values()])))
    folds = make_folds(master, train_bars, test_bars, warmup_bars)

    returns_by_regime: dict[str, list[float]] = {s: [] for s in (*STATUSES, "UNKNOWN")}
    n_before_benchmark = 0
    n_in_warmup = 0
    n_total = 0

    for fold in folds:
        trades_b: list = []
        for ticker, df in dfs.items():
            trades_b.extend(evaluate_window(ticker, df, fold.test_start, fold.test_end,
                                            baseline, cfg, warmup_bars, benchmark=benchmark,
                                            return_trades=True, strategy=strategy))

        for t in trades_b:
            n_total += 1
            status = regime_at(regime_series, pd.Timestamp(t.entry_date))
            bucket = status if status is not None else "UNKNOWN"
            if bucket not in returns_by_regime:
                returns_by_regime[bucket] = []
            # Both untaggable routes land in the same bucket; count them the
            # same way so the footer agrees with the table's UNKNOWN row.
            if status is None:
                n_before_benchmark += 1
            elif status == "UNKNOWN":
                n_in_warmup += 1
            returns_by_regime[bucket].append(t.net_return_pct)

    by_regime = {status: trade_stats(rets) for status, rets in returns_by_regime.items()}
    return RegimeBreakdownResult(by_regime=by_regime, n_trades_total=n_total,
                                 n_untagged=n_before_benchmark + n_in_warmup,
                                 n_before_benchmark=n_before_benchmark,
                                 n_in_warmup=n_in_warmup)
