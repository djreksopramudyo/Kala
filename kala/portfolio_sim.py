"""
Portfolio-level simulator: the validated per-trade rules under real capital
constraints.

WHY THIS EXISTS
---------------
Everything validated so far (backtest.py, walkforward.py) measures PER-TRADE
EV: every signal that fires gets taken, in isolation, with no budget. A real
account can't do that — it has finite cash, a position cap (max_positions),
lot sizes, a liquidity cap, and days when 30 candidates fight for 2 free
slots. Compounded portfolio return depends on those constraints at least as
much as on per-trade EV, and no experiment so far has measured them. This
module does: same signals, same fills, same exits, plus the capital layer.

FIDELITY CONTRACT (tested, see tests/test_portfolio_sim.py)
------------------------------------------------------------
With ONE ticker, max_positions=1, effectively-unlimited capital and vetoes
off, the simulator must produce the IDENTICAL trade list (entry dates, exit
dates, net returns) to ``backtest_ticker``. The portfolio layer may only ever
REMOVE trades (no slot / no cash / too illiquid / vetoed), never invent or
alter them. Specifically it reuses, not reimplements:

  * signal:   composite_score >= score_entry_threshold at close t
              -> fill at open t+1 (no look-ahead)
  * vetoes:   entries.evaluate_entry on the data prefix up to t (cached per
              (ticker, date) — identical calls to what backtest.py makes)
  * exits:    backtest.py's validated set — target profit, governing_stop
              (with the ARB limit-down carry), death-cross EVENT, max holding
              period — deliberately NOT the wider live exits.py rule set,
              because the OOS-validated EV numbers were produced by this set.
  * costs:    CostModel on the correct legs, same multipliers as backtest.py.

THE CAPITAL LAYER (mirrors papertrade.py's semantics)
-----------------------------------------------------
  * max_positions slots; candidates ranked by score DESC (never list order).
  * sizing = min(risk budget, per-slot budget, cash) -> IDX lots of 100
    (papertrade.size_position semantics, with equity as the allocation base).
  * liquidity cap: an order may not exceed max_pct_of_adv % of the 20-day
    average daily traded value.
  * queued orders fill at the NEXT session's open; a BUY whose cash was
    consumed by a higher-ranked fill that morning is dropped, not forced.

WHAT THE SWEEP IS AND ISN'T
---------------------------
``run_grid`` evaluates a small pre-committed grid of max_positions values and
reports ALL of them, including a first-half/second-half split. It deliberately
does NOT auto-pick a winner: choosing the single best in-sample grid point is
the same selection trap as any other sweep. Read the table for a ROBUST
region (neighbouring values agree, both halves agree) rather than a peak.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from . import indicators as ind
from .backtest import _is_arb_locked
from .config import Config
from .entries import evaluate_entry
from .exits import governing_stop
from .regime import classify_market_regime, regime_at
from .scoring import composite_score, compute_features

LOT_SIZE = 100


@dataclass
class SimTrade:
    ticker: str
    entry_date: object
    exit_date: object
    entry_price: float      # cost-inclusive
    exit_price: float       # cost-inclusive
    shares: int
    net_return_pct: float
    exit_reason: str


@dataclass
class SimResult:
    max_positions: int
    start_capital: float
    equity_curve: pd.Series = None
    trades: list[SimTrade] = field(default_factory=list)
    n_signals: int = 0            # score cleared threshold (before any gate)
    n_vetoed: int = 0             # blocked by evaluate_entry
    n_no_slot: int = 0            # blocked by the position cap
    n_no_cash_or_size: int = 0    # blocked by sizing (cash / lots / ADV)

    @property
    def total_return_pct(self) -> float:
        eq = self.equity_curve
        return float((eq.iloc[-1] / eq.iloc[0] - 1.0) * 100.0)

    @property
    def max_drawdown_pct(self) -> float:
        eq = self.equity_curve
        dd = eq / eq.cummax() - 1.0
        return float(dd.min() * 100.0)

    @property
    def avg_exposure_pct(self) -> float:
        """Mean fraction of equity held in stock (not cash), in percent."""
        return float(self._exposure.mean() * 100.0)

    def half_split(self) -> tuple[float, float]:
        eq = self.equity_curve
        mid = len(eq) // 2
        first = (eq.iloc[mid] / eq.iloc[0] - 1.0) * 100.0
        second = (eq.iloc[-1] / eq.iloc[mid] - 1.0) * 100.0
        return float(first), float(second)


@dataclass
class _Position:
    ticker: str
    entry_raw: float        # raw fill open (stop/target math, same as backtest)
    entry_price: float      # cost-inclusive
    shares: int
    entry_atr: float
    peak: float
    entry_date: object
    bars_held: int = 0


@dataclass
class _Order:
    ticker: str
    side: str               # "BUY" | "SELL"
    shares: int
    reason: str = ""


def _precompute(dfs: dict[str, pd.DataFrame], cfg: Config) -> dict[str, dict]:
    """Per-ticker vectorised series the day loop reads. All point-in-time."""
    out = {}
    for t, df in dfs.items():
        feats = compute_features(df)
        out[t] = {
            "df": df,
            "score": composite_score(feats),
            "atr": feats["atr"],
            "death": ind.cross_below(feats["sma_fast"], feats["sma_slow"]),
            "adv": (df["Close"] * df["Volume"]).rolling(20).mean(),
        }
    return out


def simulate_portfolio(dfs: dict[str, pd.DataFrame],
                       benchmark: pd.DataFrame | None = None,
                       cfg: Config | None = None,
                       start_capital: float = 10_000_000,
                       max_positions: int = 5,
                       risk_pct: float = 2.0,
                       max_pct_of_adv: float = 5.0,
                       apply_entry_vetoes: bool = True,
                       warmup_bars: int = 0,
                       veto_cache: dict | None = None,
                       _pre: dict | None = None) -> SimResult:
    """Day-by-day portfolio replay. See module docstring for the contract.

    ``veto_cache``: optional dict shared across grid runs — the veto decision
    for a (ticker, date) doesn't depend on max_positions, so the grid reuses
    it instead of re-running evaluate_entry per grid point.

    ``warmup_bars`` defaults to 0 on purpose: composite_score is NaN until its
    own indicators are warm (and the signal check is NaN-guarded), so skipping
    days is unnecessary for correctness — and skipping any day backtest_ticker
    would have traded breaks the fidelity contract this module is tested on.
    """
    cfg = cfg or Config()
    rcfg, bcfg, costs = cfg.risk, cfg.backtest, cfg.costs
    veto_cache = {} if veto_cache is None else veto_cache

    regime = None
    if apply_entry_vetoes and benchmark is not None and len(benchmark) > 0:
        regime = classify_market_regime(benchmark)

    pre = _pre if _pre is not None else _precompute(dfs, cfg)
    master = pd.DatetimeIndex(sorted(set().union(*[set(df.index) for df in dfs.values()])))
    master = master[warmup_bars:]
    if len(master) == 0:
        raise ValueError("not enough history after warmup")

    res = SimResult(max_positions=max_positions, start_capital=start_capital)
    cash = float(start_capital)
    positions: dict[str, _Position] = {}
    orders: list[_Order] = []
    equity_vals, exposure_vals = [], []

    # integer row lookup per ticker (searchsorted on each day is O(log n))
    idx_of = {t: p["df"].index for t, p in pre.items()}

    for day in master:
        # ---- 1. fill yesterday's queued orders at TODAY'S OPEN -------------
        next_orders: list[_Order] = []
        # sells first: frees cash and slots before buys are attempted
        for o in sorted(orders, key=lambda o: o.side != "SELL"):
            p = pre.get(o.ticker)
            i = int(idx_of[o.ticker].searchsorted(day))
            has_bar = i < len(idx_of[o.ticker]) and idx_of[o.ticker][i] == day
            if not has_bar:
                next_orders.append(o)      # suspended today -> carry the order
                continue
            row_open = float(p["df"]["Open"].iloc[i])
            if o.side == "SELL":
                pos = positions.pop(o.ticker, None)
                if pos is None:
                    continue
                exit_price = row_open * costs.sell_multiplier(row_open)
                cash += exit_price * pos.shares
                res.trades.append(SimTrade(
                    ticker=o.ticker, entry_date=pos.entry_date, exit_date=day,
                    entry_price=pos.entry_price, exit_price=exit_price,
                    shares=pos.shares,
                    net_return_pct=(exit_price / pos.entry_price - 1.0) * 100.0,
                    exit_reason=o.reason))
            else:  # BUY
                if o.ticker in positions or len(positions) >= max_positions:
                    continue
                fill = row_open * costs.buy_multiplier(row_open)
                cost = fill * o.shares
                if cost > cash + 1e-6:
                    res.n_no_cash_or_size += 1
                    continue
                cash -= cost
                # The SIGNAL bar's ATR, not this fill bar's. This order was
                # queued on bar i-1 and fills at bar i's open, and Wilder's
                # ATR at bar i already contains bar i's own High and Low —
                # the fill day's realised range, unknowable at its open. It
                # feeds governing_stop() directly, so taking it from bar i
                # would size the stop with one bar of future volatility.
                # Mirrors backtest.backtest_ticker; test_portfolio_sim's
                # fidelity test pins the two together.
                atr_i = p["atr"].iloc[i - 1] if i > 0 else float("nan")
                positions[o.ticker] = _Position(
                    ticker=o.ticker, entry_raw=row_open, entry_price=fill,
                    shares=o.shares,
                    entry_atr=float(atr_i) if atr_i == atr_i else float("nan"),
                    peak=row_open, entry_date=day)
        orders = next_orders

        # ---- 2. manage holdings on today's close (backtest.py's exit set) --
        queued_sell = {o.ticker for o in orders if o.side == "SELL"}
        for t, pos in list(positions.items()):
            if t in queued_sell:
                continue
            p = pre[t]
            tidx = idx_of[t]
            i = int(tidx.searchsorted(day))
            if not (i < len(tidx) and tidx[i] == day):
                continue                     # no bar today: nothing to manage
            close_px = float(p["df"]["Close"].iloc[i])
            pos.peak = max(pos.peak, close_px)
            stop, _, _ = governing_stop(pos.entry_raw, pos.peak, pos.entry_atr, rcfg)
            target = pos.entry_raw * (1.0 + rcfg.target_profit_pct / 100.0)

            reason = None
            if close_px >= target:
                reason = "target profit"
            elif close_px <= stop:
                prev_close = float(p["df"]["Close"].iloc[i - 1]) if i > 0 else None
                if _is_arb_locked(p["df"].iloc[i], prev_close,
                                  bcfg.arb_limit_pct, bcfg.arb_lock_tol_pct):
                    pass                     # limit-down lock: carry, can't sell
                else:
                    reason = "stop"
            elif bool(p["death"].iloc[i]):
                reason = "death cross"
            elif pos.bars_held >= bcfg.holding_max_days:
                reason = "max holding period"
            # increment AFTER the checks: backtest_ticker's bars_held is
            # (i - entry_i), i.e. 0 on the fill bar — checking before the
            # increment keeps max-holding-period firing on the same bar.
            pos.bars_held += 1
            if reason is not None:
                orders.append(_Order(ticker=t, side="SELL", shares=pos.shares,
                                     reason=reason))

        # ---- 3. rank today's signals, queue buys into free slots -----------
        pending_buy = {o.ticker for o in orders if o.side == "BUY"}
        queued_sell = {o.ticker for o in orders if o.side == "SELL"}
        slots_left = max_positions - len(positions) - len(pending_buy)

        # mark-to-market equity (allocation base for sizing)
        mtm = cash
        for t, pos in positions.items():
            tidx = idx_of[t]
            i = min(int(tidx.searchsorted(day, side="right")) - 1, len(tidx) - 1)
            mtm += float(pre[t]["df"]["Close"].iloc[max(i, 0)]) * pos.shares
        equity_vals.append(mtm)
        exposure_vals.append((mtm - cash) / mtm if mtm > 0 else 0.0)

        candidates = []
        for t, p in pre.items():
            if t in positions or t in pending_buy or t in queued_sell:
                continue
            tidx = idx_of[t]
            i = int(tidx.searchsorted(day))
            if not (i < len(tidx) and tidx[i] == day) or i + 1 >= len(tidx):
                continue                     # no bar today / last bar: can't fill
            s = p["score"].iloc[i]
            if s == s and s >= bcfg.score_entry_threshold:
                candidates.append((float(s), t, i))
        res.n_signals += len(candidates)
        candidates.sort(reverse=True)        # score DESC, never list order

        for s, t, i in candidates:
            if slots_left <= 0:
                res.n_no_slot += 1
                continue
            p = pre[t]
            if apply_entry_vetoes:
                key = (t, day)
                allowed = veto_cache.get(key)
                if allowed is None:
                    status = regime_at(regime, day) if regime is not None else None
                    allowed = evaluate_entry(p["df"].iloc[: i + 1],
                                             market_status=status).allowed
                    veto_cache[key] = allowed
                if not allowed:
                    res.n_vetoed += 1
                    continue
            price = float(p["df"]["Close"].iloc[i])
            atr_i = p["atr"].iloc[i]
            atr_v = float(atr_i) if atr_i == atr_i else float("nan")
            stop, _, _ = governing_stop(price, price, atr_v, rcfg)
            risk_per_share = price - stop
            if risk_per_share <= 0:
                res.n_no_cash_or_size += 1
                continue
            by_risk = (mtm * risk_pct / 100.0) / risk_per_share
            by_slot = (mtm / max_positions) / price
            by_cash = cash / (price * costs.buy_multiplier(price))
            raw = min(by_risk, by_slot, by_cash)
            adv = p["adv"].iloc[i]
            if adv == adv and adv > 0:
                raw = min(raw, (float(adv) * max_pct_of_adv / 100.0) / price)
            shares = int(raw // LOT_SIZE) * LOT_SIZE
            if shares < LOT_SIZE:
                res.n_no_cash_or_size += 1
                continue
            orders.append(_Order(ticker=t, side="BUY", shares=shares))
            slots_left -= 1

    res.equity_curve = pd.Series(equity_vals, index=master)
    res._exposure = pd.Series(exposure_vals, index=master)
    return res


def run_grid(dfs: dict[str, pd.DataFrame], benchmark=None, cfg: Config | None = None,
             start_capital: float = 10_000_000,
             grid: tuple = (3, 5, 8, 10, 15),
             risk_pct: float = 2.0, apply_entry_vetoes: bool = True) -> list[SimResult]:
    """One shared precompute + veto cache; simulate every grid point."""
    cfg = cfg or Config()
    pre = _precompute(dfs, cfg)
    cache: dict = {}
    return [simulate_portfolio(dfs, benchmark, cfg, start_capital, m,
                               risk_pct=risk_pct,
                               apply_entry_vetoes=apply_entry_vetoes,
                               veto_cache=cache, _pre=pre)
            for m in grid]
