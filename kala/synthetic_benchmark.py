"""An equal-weighted benchmark built from the traded universe itself.

WHY THIS EXISTS
---------------
Every excess figure in this project is measured against IHSG. IHSG is
cap-weighted and includes conventional banks, insurers and other
interest-based names that a sharia-screened universe can NEVER hold. So
"excess vs IHSG" mixes two different things together:

    1. stock selection inside the sharia universe   <- the thing being tested
    2. sharia-screened stocks vs the whole market   <- a sector bet nobody chose

If the sharia screen alone outperformed over this sample, every strategy in
this system would show positive "alpha" regardless of what it picked — which
would explain how two strategies with near-disjoint selections (Jaccard 0.021)
still have excess returns correlating at +0.803.

The Jakarta Islamic Index (^JKII) fixes problem 2 but only holds the 30 most
liquid sharia names, cap-weighted, so a size-and-weighting gap remains against
an equal-weighted basket drawn from ~600. ISSI, which would match, is not on
yfinance.

This module builds the benchmark that matches exactly: an equal-weighted,
daily-rebalanced portfolio of the SAME tickers the strategy chooses from. The
question it answers is the one that actually matters:

    "Did picking these stocks beat buying all of them?"

CONSTRUCTION, AND WHY IT IS DONE THIS WAY
-----------------------------------------
Averaging each ticker's normalised PRICE LEVEL would be wrong. Tickers have
different history lengths, so a level average silently reweights toward the
names with the longest history — a survivorship tilt introduced by the
benchmark itself.

Instead this averages DAILY RETURNS across whatever tickers actually traded
that day, then compounds. That is a real, implementable portfolio: hold every
available name in equal weight, rebalance daily. A ticker joins the average
the day after it starts trading and leaves when it stops.
"""

from __future__ import annotations

import pandas as pd

# Below this many names a daily average is noise, not a market. Early dates in
# a universe often have a handful of tickers; letting those through would put
# a wild, meaningless benchmark in front of the earliest folds.
MIN_NAMES_DEFAULT = 20


def equal_weight_benchmark(dfs: dict[str, pd.DataFrame],
                           min_names: int = MIN_NAMES_DEFAULT,
                           price_col: str = "Close") -> pd.DataFrame:
    """Equal-weighted, daily-rebalanced index over ``dfs``.

    Returns a DataFrame with a ``Close`` column, shaped like the yfinance
    frames the rest of the pipeline expects, so it drops straight into
    ``walk_forward(benchmark=...)``.

    Raises ValueError rather than returning something empty or flat: a
    benchmark that silently degrades to nothing is the exact failure this
    project keeps finding, and excess measured against it would read as a
    result instead of as a broken measurement.
    """
    if not dfs:
        raise ValueError("equal_weight_benchmark: no tickers supplied")
    if min_names < 1:
        raise ValueError(f"equal_weight_benchmark: min_names must be >= 1, got {min_names}")

    cols = {}
    for ticker, df in dfs.items():
        if df is None or len(df) < 2 or price_col not in df:
            continue
        s = pd.to_numeric(df[price_col], errors="coerce")
        s = s[~s.index.duplicated(keep="last")].sort_index()
        # A non-positive price makes pct_change meaningless (and inf-prone).
        s = s.where(s > 0)
        if s.notna().sum() >= 2:
            cols[ticker] = s
    if not cols:
        raise ValueError(
            f"equal_weight_benchmark: none of the {len(dfs)} ticker(s) had two "
            f"usable '{price_col}' points")

    wide = pd.DataFrame(cols).sort_index()

    # Anchor on the first date with enough PRICES, not enough returns. That
    # date becomes the base bar — a base bar has no return, because there is
    # nothing before it in the series.
    #
    # Anchoring on returns instead produced a real bug: the series was cut at
    # the first date carrying a return, and the base level was then forced to
    # 1.0 after compounding had already begun. The second bar still held two
    # days compounded together, so the benchmark's first observed move was
    # DOUBLE the true one (+4.04% where every name moved +2%). It looked
    # perfectly plausible on a chart.
    n_prices = wide.notna().sum(axis=1)
    enough = n_prices >= min_names
    if not enough.any():
        raise ValueError(
            f"equal_weight_benchmark: no date had {min_names} tickers with a "
            f"price (most populated date had {int(n_prices.max())}). Lower "
            f"min_names or supply more tickers.")
    wide = wide.loc[enough.idxmax():]

    # pct_change per ticker, on each ticker's own consecutive observations. A
    # name that did not trade contributes nothing that day rather than a stale
    # 0% that would damp the average.
    rets = wide.pct_change()
    n_names = rets.notna().sum(axis=1)
    # The base bar's row is all-NaN and becomes 0.0 here, so the level starts
    # at exactly 1.0 by construction rather than by being overwritten.
    mean_ret = rets.mean(axis=1, skipna=True).fillna(0.0)

    # A day where fewer than min_names traded is an EXCHANGE HOLIDAY or a data
    # gap, not a thin market. Averaging the handful of names that carry a bar
    # on such a day puts pure noise into the index — and because the level
    # compounds, that noise is permanent for every date afterwards.
    #
    # Measured on the real universe: IDX Labour Day (2026-05-01) and
    # Independence Day (2026-08-17) both produced days with as few as TWO
    # contributing names out of 569, inside the most recent fold.
    #
    # A real equal-weighted portfolio does not move on a day it cannot trade.
    # So those days are carried at 0%, which is what holding through a closed
    # session actually does. The bar is kept rather than dropped so that every
    # trade's entry/exit window can still be matched against the benchmark —
    # removing dates would silently discard trades instead.
    mean_ret = mean_ret.where(n_names >= min_names, 0.0)

    level = (1.0 + mean_ret).cumprod()

    out = pd.DataFrame({"Close": level.astype(float)})
    out.index.name = wide.index.name
    # Carried for reporting; walk_forward only reads "Close".
    out.attrs["n_names"] = n_names
    out.attrs["min_names"] = min_names
    return out


def describe(bench: pd.DataFrame) -> str:
    """Provenance, so a run's log says what it was measured against.

    Breadth EXCLUDES the base bar. The base bar has no return by construction,
    so counting it makes every healthy benchmark report a minimum of 0 names —
    which is indistinguishable, at a glance, from a genuinely empty stretch.
    Thin days are counted separately and named, rather than being averaged into
    a range that hides them.
    """
    n = bench.attrs.get("n_names")
    min_names = bench.attrs.get("min_names", MIN_NAMES_DEFAULT)
    total = (float(bench["Close"].iloc[-1]) / float(bench["Close"].iloc[0]) - 1.0) * 100.0
    line = (f"EQUAL_WEIGHT synthetic benchmark: {len(bench)} bars "
            f"{bench.index[0].date()}..{bench.index[-1].date()}, "
            f"buy-and-hold {total:+.1f}%")
    if n is None or len(n) < 2:
        return line
    body = n.iloc[1:]                      # drop the base bar
    line += (f"\n    breadth: {int(body.min())}-{int(body.max())} names/day "
             f"(median {int(body.median())}), base bar excluded")
    thin = body[body < min_names]
    if len(thin):
        line += (f"\n    NOTE: {len(thin)} day(s) below {min_names} names, held FLAT "
                 f"(0%) as a closed session")
        line += f" — {thin.index[0].date()}"
        if len(thin) > 1:
            line += f" .. {thin.index[-1].date()}"
        line += ".\n    Exchange holidays and stale warehouse tails look like this. A"
        line += "\n    long run of them inside a fold means that fold's excess is"
        line += "\n    measured against a benchmark that was barely moving."
    return line
