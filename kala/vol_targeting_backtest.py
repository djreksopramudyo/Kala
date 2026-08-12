"""
Volatility-targeting backtest — the last mechanically distinct lever: scale
TOTAL equity exposure up/down over time based on how volatile the market has
recently been, instead of staying 100% invested always.

WHY THIS IS DIFFERENT FROM EVERYTHING ELSE TESTED
---------------------------------------------------
Every one of the thirteen hypotheses in PROJECT_STATUS.md is CROSS-SECTIONAL:
they score WHICH stock to hold at a moment in time. The four weighting studies
are cross-sectional too (how much of each name). This is the orthogonal,
TIME-SERIES question: given a portfolio you've already chosen, how much TOTAL
exposure to it should you carry right now? Moreira & Muir (2017, "Volatility-
Managed Portfolios," Journal of Finance) found that scaling exposure DOWN when
recent realized volatility is high (and up when it's low) historically raised
risk-adjusted returns — because volatility is persistent (clusters) and
predictable in a way that RETURNS are not, and high-vol periods have not
historically been compensated with proportionally higher returns. It's the
one remaining lever that isn't stock selection, isn't cross-sectional
weighting, and isn't blocked on data this project doesn't have.

THE SHARIA CONSTRAINT CHANGES THE RESULT — STATED UP FRONT
------------------------------------------------------------
The textbook Moreira-Muir strategy LEVERS UP in calm periods (exposure > 1),
and a large share of its historical benefit comes from that leverage. Leverage
is riba — not permitted here — so the honest, sharia-compatible version can
only DE-RISK: cap exposure at 1.0 (100% invested), scaling DOWN into cash when
vol spikes but never borrowing to amplify calm periods. This backtest computes
BOTH:
  * ``targeted_capped``   — exposure clamped to [0, 1.0]; the sharia version
  * ``targeted_uncapped`` — exposure allowed above 1.0 (leverage); NOT sharia,
                            included ONLY as the upper-bound reference so you
                            can see how much of the textbook benefit the
                            no-leverage constraint costs you.
Expect the capped version to keep only part of the uncapped edge — possibly
most of the drawdown reduction (that comes from de-risking, which the cap
allows) but little of the return enhancement (that came from levering calm
periods, which the cap forbids).

HONEST PRIOR
------------
Like every other lever tested here, this is more likely a RISK tool than a
return booster — especially the sharia (capped) version, which can only reduce
exposure. It also faces the same two enemies as every timing idea in this
project: transaction costs (changing exposure trades, and this models that
friction on every exposure change) and the possibility that IDX's specific
vol/return dynamics differ from the US indices Moreira-Muir studied. Judge it
on ret/vol (risk-adjusted) and max drawdown, not raw CAGR, and don't expect
the capped version to "maximize returns" — expect it to smooth them.

POINT-IN-TIME DISCIPLINE
------------------------
The exposure applied to day t's return is decided from realized volatility
through day t-1 ONLY (``.shift(1)`` on the rolling vol). No exposure is ever
set using a return that hadn't happened yet — the same non-negotiable
no-look-ahead contract as the rest of the project.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

TRADING_DAYS = 252


@dataclass(frozen=True)
class VolTargetStats:
    total_return_pct: float
    cagr_pct: float
    ann_vol_pct: float
    max_drawdown_pct: float
    return_per_vol: float        # CAGR / annualized vol -- crude risk-adjusted return


@dataclass(frozen=True)
class VolTargetComparison:
    buy_hold: VolTargetStats
    targeted_capped: VolTargetStats        # sharia: exposure in [0, 1]
    targeted_uncapped: VolTargetStats      # non-sharia leverage reference
    target_vol_pct: float
    vol_window: int
    avg_exposure_capped: float
    avg_exposure_uncapped: float
    cost_pct_capped: float                 # friction as % of final equity
    cost_pct_uncapped: float
    n_days: int
    note: str = ""
    dropped_short_history: tuple = ()   # tickers excluded pre-join (see _align_close)


# Same fix as kala.weighting_backtest / kala.rebalance_backtest: a ticker
# whose own history is much shorter than the rest of the basket (recently
# listed, or a truncated Yahoo series) is dropped BEFORE the strict inner
# join, since a single such name can otherwise collapse a whole multi-name
# basket's overlap to a handful of days even when the rest have full history.
MIN_HISTORY_FRACTION = 0.5


def _align_close(prices: dict[str, pd.Series]) -> tuple[pd.DataFrame, list[str]]:
    """Inner-join Close series after dropping any name whose own history is
    too short to be a fair member of the join. Used to build one equal-weight
    portfolio return stream to apply the exposure overlay to. A single-name
    dict is fine (the overlay works on one asset too). Returns
    (aligned_df, dropped_tickers)."""
    frames = {t: s.dropna() for t, s in prices.items() if s is not None and len(s)}
    if not frames:
        return pd.DataFrame(), []
    max_len = max(len(s) for s in frames.values())
    floor = max_len * MIN_HISTORY_FRACTION
    kept = {t: s for t, s in frames.items() if len(s) >= floor}
    dropped = sorted(set(frames) - set(kept))
    if not kept:
        return pd.DataFrame(), dropped
    return pd.DataFrame(kept).dropna(how="any"), dropped


def _portfolio_returns(closes: pd.DataFrame) -> pd.Series:
    """Daily return of an equal-weight, daily-rebalanced portfolio of the
    columns — the base stream the exposure overlay scales. (Equal-weight here
    is just a neutral base; the point of the study is the exposure overlay, not
    the weighting, which the weighting study already covered.)"""
    rets = closes.pct_change()
    return rets.mean(axis=1)


def _stats(equity: pd.Series) -> VolTargetStats:
    equity = equity.dropna()
    if len(equity) < 2 or equity.iloc[0] <= 0:
        return VolTargetStats(0.0, 0.0, 0.0, 0.0, 0.0)
    total_return = equity.iloc[-1] / equity.iloc[0] - 1.0
    years = len(equity) / TRADING_DAYS
    cagr = (equity.iloc[-1] / equity.iloc[0]) ** (1.0 / years) - 1.0 if years > 0 else 0.0
    daily = equity.pct_change().dropna()
    ann_vol = float(daily.std() * np.sqrt(TRADING_DAYS)) if len(daily) else 0.0
    running_max = equity.cummax()
    max_dd = float((equity / running_max - 1.0).min())
    rpv = (cagr / ann_vol) if ann_vol > 0 else 0.0
    return VolTargetStats(total_return * 100, cagr * 100, ann_vol * 100, max_dd * 100, rpv)


def _simulate(returns: pd.Series, target_vol: float, vol_window: int,
              cap: float, cost_rate: float) -> tuple[pd.Series, float, float]:
    """Apply a vol-targeting exposure overlay. Exposure on day t = target_vol /
    (annualized realized vol through t-1), clamped to [0, cap]. Cash earns 0.
    Turnover cost is charged on each change in exposure. Returns (equity_series,
    avg_exposure, total_cost_fraction_of_final)."""
    realized = returns.rolling(vol_window).std() * np.sqrt(TRADING_DAYS)
    # decide today's exposure from vol through YESTERDAY -> shift(1). No look-ahead.
    exposure = (target_vol / realized.shift(1)).clip(lower=0.0, upper=cap)
    exposure = exposure.fillna(0.0)             # before enough history: flat/out
    strat_ret = exposure * returns
    turnover = exposure.diff().abs().fillna(exposure.abs())   # first day: 0 -> exposure
    cost = turnover * cost_rate
    net = strat_ret - cost
    equity = (1.0 + net).cumprod()
    avg_exp = float(exposure[exposure > 0].mean()) if (exposure > 0).any() else 0.0
    total_cost = float(cost.sum())
    return equity, avg_exp, total_cost


def compare_vol_targeting(prices: dict[str, pd.Series], target_vol: float = 0.20,
                          vol_window: int = 21, cost_rate: float = 0.003,
                          uncapped_max: float = 2.0) -> VolTargetComparison:
    """Compare always-invested buy-and-hold vs a vol-targeted overlay, in both
    a sharia (exposure capped at 1.0) and a non-sharia leverage-reference
    (capped at ``uncapped_max``) form. ``target_vol`` is the annualized vol the
    overlay aims for (default 0.20 = 20%/yr, a typical equity target).
    ``vol_window`` default 21 ≈ one month of realized vol. ``note`` explains a
    failed run. Any ticker with much shorter history than the rest of the
    basket is dropped BEFORE alignment rather than letting it collapse the
    whole join — see ``dropped_short_history`` on the result."""
    closes, dropped = _align_close(prices)
    if closes.empty or len(closes) < vol_window + 30:
        return VolTargetComparison(
            _stats(pd.Series(dtype=float)), _stats(pd.Series(dtype=float)),
            _stats(pd.Series(dtype=float)), target_vol * 100, vol_window,
            0.0, 0.0, 0.0, 0.0, len(closes),
            note=(f"Need more than {vol_window + 30} overlapping days to run a "
                  f"vol-window of {vol_window}."),
            dropped_short_history=tuple(dropped))

    port_ret = _portfolio_returns(closes)
    bh_equity = (1.0 + port_ret.fillna(0.0)).cumprod()
    cap_equity, cap_exp, cap_cost = _simulate(port_ret, target_vol, vol_window, 1.0, cost_rate)
    unc_equity, unc_exp, unc_cost = _simulate(port_ret, target_vol, vol_window,
                                              uncapped_max, cost_rate)

    return VolTargetComparison(
        buy_hold=_stats(bh_equity),
        targeted_capped=_stats(cap_equity),
        targeted_uncapped=_stats(unc_equity),
        target_vol_pct=target_vol * 100,
        vol_window=vol_window,
        avg_exposure_capped=cap_exp,
        avg_exposure_uncapped=unc_exp,
        cost_pct_capped=cap_cost / cap_equity.iloc[-1] * 100 if cap_equity.iloc[-1] else 0.0,
        cost_pct_uncapped=unc_cost / unc_equity.iloc[-1] * 100 if unc_equity.iloc[-1] else 0.0,
        n_days=len(closes),
        dropped_short_history=tuple(dropped))


def format_vol_targeting(cmp: VolTargetComparison, cost_rate: float) -> str:
    """Human-readable table + honest verdict, judged on ret/vol and drawdown,
    with the sharia cap's effect called out explicitly."""
    if cmp.note:
        msg = f"VOL-TARGETING STUDY — could not run: {cmp.note}"
        if cmp.dropped_short_history:
            msg += (f"\n  Dropped for short history before alignment: "
                    f"{', '.join(cmp.dropped_short_history)}")
        return msg

    bh, cap, unc = cmp.buy_hold, cmp.targeted_capped, cmp.targeted_uncapped
    lines = []
    if cmp.dropped_short_history:
        lines.append(f"  (dropped {len(cmp.dropped_short_history)} short-history "
                     f"ticker(s) before alignment: "
                     f"{', '.join(cmp.dropped_short_history)})")
    lines += [
        f"VOLATILITY-TARGETING STUDY — {cmp.n_days} trading days "
        f"(~{cmp.n_days / TRADING_DAYS:.1f}y)",
        f"  target {cmp.target_vol_pct:.0f}% ann vol | realized-vol window "
        f"{cmp.vol_window}d | cost {cost_rate * 100:.2f}%/exposure-change",
        "  Scales TOTAL exposure by recent vol (time-series), NOT stock selection.",
        "",
        f"  {'variant':<26}{'CAGR':>9}{'vol':>8}{'maxDD':>8}{'ret/vol':>9}{'avgExp':>8}",
        "  " + "-" * 68,
        f"  {'buy & hold (100% always)':<26}{bh.cagr_pct:>8.2f}%{bh.ann_vol_pct:>7.1f}%"
        f"{bh.max_drawdown_pct:>7.1f}%{bh.return_per_vol:>9.2f}{'1.00':>8}",
        f"  {'vol-target CAPPED (sharia)':<26}{cap.cagr_pct:>8.2f}%{cap.ann_vol_pct:>7.1f}%"
        f"{cap.max_drawdown_pct:>7.1f}%{cap.return_per_vol:>9.2f}{cmp.avg_exposure_capped:>8.2f}",
        f"  {'vol-target UNCAPPED (lev.)':<26}{unc.cagr_pct:>8.2f}%{unc.ann_vol_pct:>7.1f}%"
        f"{unc.max_drawdown_pct:>7.1f}%{unc.return_per_vol:>9.2f}{cmp.avg_exposure_uncapped:>8.2f}",
        "  " + "-" * 68,
        f"  UNCAPPED is NOT sharia (uses leverage, avg exp {cmp.avg_exposure_uncapped:.2f}) "
        f"— reference only.",
        "",
    ]

    # Verdict on the SHARIA (capped) version specifically, on ret/vol + drawdown.
    rv_delta = cap.return_per_vol - bh.return_per_vol
    dd_better = cap.max_drawdown_pct - bh.max_drawdown_pct   # both negative; >0 means shallower
    if rv_delta > 0.05 and dd_better > 2.0:
        verdict = (f"The sharia (capped) overlay improved BOTH risk-adjusted return "
                   f"(ret/vol {rv_delta:+.2f}) and max drawdown ({dd_better:+.1f}pp "
                   f"shallower). Notable — but confirm on another window before "
                   f"trusting it, and note avg exposure was {cmp.avg_exposure_capped:.2f} "
                   f"(it held cash a lot).")
    elif dd_better > 2.0:
        verdict = (f"Capped overlay's main effect is DRAWDOWN reduction "
                   f"({dd_better:+.1f}pp shallower) for a risk-adjusted return that's "
                   f"~flat ({rv_delta:+.2f} ret/vol). Risk control, not a return boost — "
                   f"the expected result. Whether it's worth the {cmp.cost_pct_capped:.1f}% "
                   f"friction and holding {1 - cmp.avg_exposure_capped:.0%} cash on average "
                   f"is the real question.")
    else:
        verdict = (f"Capped (sharia) overlay did NOT beat always-invested buy-and-hold "
                   f"on risk-adjusted return ({rv_delta:+.2f} ret/vol) or drawdown "
                   f"({dd_better:+.1f}pp). The no-leverage constraint strips most of the "
                   f"textbook benefit (see uncapped row for what leverage would have "
                   f"added — but that's riba, not available to you). Another lever that "
                   f"doesn't clear the bar once the sharia constraint and costs are paid.")
    lines.append(f"  READ: {verdict}")
    return "\n".join(lines)
