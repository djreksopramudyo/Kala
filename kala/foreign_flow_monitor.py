"""
Foreign-accumulation MONITOR — a descriptive read on the broker-flow data
already paid for and backfilled into ``kala.broker_flow_archive``.

WHAT THIS IS, AND (IMPORTANT) WHAT IT IS NOT
--------------------------------------------
This ranks the watchlist by how strongly foreign money is CURRENTLY net-
buying each stock, relative to that stock's OWN recent norm (a rolling
z-score of cumulative foreign net flow). It answers "what is foreign
institutional money doing in these names right now" — a monitoring/context
input, the same way the news/sentiment archive is context.

It is NOT a validated buy signal. The identical z-score, tested as a trading
signal (``kala.strategy_foreign_flow`` run through the walk-forward harness
on this same data), came back INCONCLUSIVE — no demonstrated out-of-sample
edge after honest costs (see PROJECT_STATUS.md, "Bandarmology result"). So:
use this to SEE the flow, not to justify a trade as if the edge were proven.
A high z-score here means "foreigners are unusually active buyers of this
name," full stop — not "this will go up."

Deliberately reuses ``kala.strategy_foreign_flow.compute_features_foreign_flow``
so the number shown is EXACTLY the one the (unvalidated) signal would compute
— one source of truth, no second implementation to drift out of sync.
"""

from __future__ import annotations

import pandas as pd

from .strategy_foreign_flow import (
    FLOW_COLUMN,
    ZSCORE_WINDOW,
    compute_features_foreign_flow,
)

STALE_DAYS = 30         # a reading older than this many days vs. the reference date is stale
MATERIAL_FLOOR = 1e9    # |cumulative flow| below ~1bn IDR -> the z is dividing noise
HIGH_CONF_ABS_Z = 1.0   # a "credible" row needs at least this |z| (and fresh+material+not-thin)


def _bucket(z: float | None) -> str:
    """Plain-language label for a flow z-score. Descriptive only — these are
    'how unusual is the buying', never 'how good a trade'."""
    if z is None or pd.isna(z):
        return "no data"
    if z >= 2.0:
        return "strong accumulation"
    if z >= 1.0:
        return "accumulation"
    if z > -1.0:
        return "neutral"
    if z > -2.0:
        return "distribution"
    return "strong distribution"


def _row_flags(r, min_days: int, stale_days: int) -> str:
    """Data-quality caveats for one row, so a big z built on old or negligible
    flow isn't read as if it were solid. 'stale' = this reading is more than
    ``stale_days`` old vs. the reference date (an old backfill window showing
    flow that isn't current); 'thin' = too few observations behind the z;
    'faint' = the flow itself is tiny, so the z is normalizing rounding noise."""
    flags = []
    age = r.get("age_days")
    if age is not None and not pd.isna(age) and age > stale_days:
        flags.append(f"stale {int(age)}d")
    if r["n_days"] < min_days:
        flags.append(f"thin {int(r['n_days'])}d")
    if not r.get("material", True):
        flags.append("faint")
    return "  (" + ", ".join(flags) + ")" if flags else ""


def high_confidence(ranked: pd.DataFrame, min_days: int = ZSCORE_WINDOW,
                    stale_days: int = STALE_DAYS, min_abs_z: float = HIGH_CONF_ABS_Z) -> pd.DataFrame:
    """The subset actually worth looking at: fresh (not stale), material flow
    (not faint), enough history (not thin), and |z| >= ``min_abs_z``. This is
    what strips the illiquid-noise and stale-backfill rows out of the ranking
    so what's left is the handful of names where real foreign money is doing
    something unusual RIGHT NOW."""
    df = ranked
    z = pd.to_numeric(df["flow_z"], errors="coerce")   # object-dtype if any 'no data' rows
    keep = (
        z.notna()
        & (z.abs() >= min_abs_z)
        & (df["n_days"] >= min_days)
        & df.get("material", True)
        & ((df.get("age_days").isna()) | (df.get("age_days") <= stale_days)
           if "age_days" in df else True)
    )
    return df[keep].reset_index(drop=True)


def latest_flow_reading(flow_series: pd.DataFrame | pd.Series) -> dict | None:
    """Compute the most recent foreign-flow z-score from one ticker's stored
    flow. ``flow_series`` is a ``BrokerFlowArchive.read`` frame (needs the
    ``foreign_net_value`` column, DatetimeIndex) or that column as a Series.
    Returns {date, flow_z, flow_cum, last_net_value, n_days} for the last
    date that has a defined z-score, or None if there isn't enough coverage
    (fewer than the z-score window's worth of observations)."""
    if flow_series is None or len(flow_series) == 0:
        return None
    if isinstance(flow_series, pd.Series):
        df = flow_series.to_frame(FLOW_COLUMN)
    else:
        if FLOW_COLUMN not in flow_series.columns:
            return None
        df = flow_series[[FLOW_COLUMN]].copy()

    df = df[~df.index.duplicated(keep="last")].sort_index()
    feats = compute_features_foreign_flow(df)
    defined = feats["flow_z"].dropna()
    if defined.empty:
        return None
    last_date = defined.index[-1]
    return {
        "date": last_date.strftime("%Y-%m-%d") if hasattr(last_date, "strftime") else str(last_date)[:10],
        "flow_z": float(feats["flow_z"].loc[last_date]),
        "flow_cum": float(feats["flow_cum"].loc[last_date]),
        "last_net_value": float(df[FLOW_COLUMN].loc[last_date]),
        "n_days": int(df[FLOW_COLUMN].notna().sum()),
    }


def rank_foreign_accumulation(archive, tickers: list[str],
                              source: str = "invezgo",
                              reference_date: str | None = None) -> pd.DataFrame:
    """Rank ``tickers`` by current foreign-flow z-score, strongest net buying
    first. ``archive`` is anything with ``read(ticker, source=...) ->
    DataFrame | None`` (i.e. ``BrokerFlowArchive``). Tickers with no stored
    flow, or too little history for a z-score, are still listed (bucket
    'no data') at the bottom rather than silently dropped — so a partially-
    backfilled archive reads honestly instead of looking like those names
    have no flow.

    ``age_days`` measures each reading against ``reference_date`` (default:
    today, WIB) — an ABSOLUTE age, so a reading from an old backfill window
    reads as stale even if it's the only ticker queried, not just when a
    fresher row exists to compare it to. Columns: ticker, date, flow_z,
    bucket, last_net_value, flow_cum, n_days, age_days, material."""
    rows = []
    for t in tickers:
        try:
            stored = archive.read(t, source=source)
        except Exception:
            stored = None
        reading = latest_flow_reading(stored) if stored is not None else None
        if reading is None:
            rows.append({"ticker": t, "date": None, "flow_z": None,
                         "bucket": "no data", "last_net_value": None,
                         "flow_cum": None, "n_days": 0})
        else:
            rows.append({"ticker": t, "bucket": _bucket(reading["flow_z"]), **reading})

    df = pd.DataFrame(rows, columns=["ticker", "date", "flow_z", "bucket",
                                     "last_net_value", "flow_cum", "n_days"])
    # Absolute age vs. a reference date (today by default): a reading from an
    # old backfill window is stale in real terms, not just relative to fresher
    # rows -- so a single old ticker is still correctly flagged.
    if reference_date is None:
        from .clock import today_str_wib
        reference_date = today_str_wib()
    ref = pd.to_datetime(reference_date)
    parsed = pd.to_datetime(df["date"], errors="coerce")
    df["age_days"] = (ref - parsed).dt.days
    # Is there enough absolute flow behind the z for it to mean anything, or is
    # it normalizing rounding noise on an illiquid, no-foreign-participation name?
    # (coerce first: an all-'no data' set leaves flow_cum object-dtype with None.)
    df["material"] = pd.to_numeric(df["flow_cum"], errors="coerce").abs() >= MATERIAL_FLOOR
    # strongest accumulation first; 'no data' (NaN z) sorts to the bottom.
    return df.sort_values("flow_z", ascending=False, na_position="last").reset_index(drop=True)


def format_report(ranked: pd.DataFrame, min_days: int = ZSCORE_WINDOW,
                  stale_days: int = STALE_DAYS) -> str:
    """Human-readable monitor. Leads with the CREDIBLE rows (fresh + material
    flow + enough history), then the full ranking with every low-quality row
    flagged — 'stale' (old backfill window), 'thin' (too few observations),
    'faint' (flow too small for the z to mean anything) — so a big number
    built on old or negligible data can't be mistaken for a live signal."""
    lines = [
        "FOREIGN-FLOW MONITOR (descriptive — NOT a validated buy signal)",
        "  z = how unusual today's net foreign buying is vs. this stock's own norm.",
        "  The same z-score tested as a trade signal was INCONCLUSIVE (PROJECT_STATUS.md).",
    ]

    credible = high_confidence(ranked, min_days=min_days, stale_days=stale_days)
    lines.append("")
    if len(credible):
        lines.append("  MOST CREDIBLE (fresh, material flow, enough history, |z| >= 1):")
        for _, r in credible.iterrows():
            net_bn = r["last_net_value"] / 1e9 if r["last_net_value"] is not None else float("nan")
            lines.append(f"    {r['ticker']:<10}{r['flow_z']:>7.2f}  {r['bucket']:<20}"
                         f"{str(r['date']):<12}{net_bn:>10,.1f} bn")
    else:
        lines.append("  MOST CREDIBLE: none — every row is stale, thin, faint, or near zero.")
        lines.append("  (Nothing here clears the bar for a live, material foreign-flow move.)")

    lines += [
        "",
        "  FULL RANKING (low-quality rows flagged):",
        f"  {'ticker':<12}{'z':>7}  {'bucket':<20}{'as of':<12}{'net (IDR bn)':>14}",
        "  " + "-" * 66,
    ]
    for _, r in ranked.iterrows():
        if r["flow_z"] is None or pd.isna(r["flow_z"]):
            lines.append(f"  {r['ticker']:<12}{'—':>7}  {'no data':<20}")
            continue
        net_bn = r["last_net_value"] / 1e9 if r["last_net_value"] is not None else float("nan")
        lines.append(f"  {r['ticker']:<12}{r['flow_z']:>7.2f}  {r['bucket']:<20}"
                     f"{str(r['date']):<12}{net_bn:>14,.1f}{_row_flags(r, min_days, stale_days)}")
    return "\n".join(lines)
