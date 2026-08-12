"""
Paper trader — full automation, zero rupiah at risk.

Runs the complete decision loop the way real automation would: takes the
scanner's BUY signals, sizes positions from YOUR allocated capital, queues
orders, fills them at the NEXT session's open with the honest cost model,
manages exits through the tested exit engine, and persists everything to JSON.

Mechanics mirror the backtest exactly (signal at close t -> fill at open t+1),
so its live track record is directly comparable to backtested numbers. IDX
reality is respected: shares trade in LOTS of 100, fills pay commission + tax +
spread, and one ticker can hold at most one position.

State file schema (JSON): {"cash": float, "start_capital": float,
"positions": {...}, "pending": [...], "log": [...], "undo_stack": [...],
"redo_stack": [...]}
"""

from __future__ import annotations

import json
import math
import os
import shutil
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from .backtest import _is_arb_locked
from .config import Config
from .exits import governing_stop
from .intraday import arb_lower_limit_pct
from .live import evaluate_position


def date_str_today() -> str:
    # WIB, not server-local — a trade logged in the evening (WIB) on a UTC
    # host must still carry today's Jakarta date, not yesterday's UTC one.
    from .clock import today_str_wib
    return today_str_wib()

LOT_SIZE = 100  # IDX trades in lots of 100 shares
MAX_UNDO_DEPTH = 5  # fat-finger safety net, not a full audit log

# Corporate-action guard band: the stored entry price is compared against
# what today's (dividend/split-adjusted) history says that same fill should
# have cost. Ordinary dividend adjustments move adjusted history a few
# percent; a stock split moves it 2x+. Outside this band we assume a
# corporate action and refuse to auto-evaluate exits on distorted numbers.
_CA_RATIO_LO, _CA_RATIO_HI = 0.75, 1.33


def _corporate_action_ratio(pos, history, costs) -> tuple[float, float] | None:
    """(ratio, expected_entry) if ``pos``'s stored entry price is
    inconsistent with the current adjusted history at its entry date — the
    signature of a split/large corporate action since purchase. None if
    consistent, or if the entry date isn't inside this history window
    (nothing to compare).

    Why this exists: yfinance returns ADJUSTED prices, so after a 2:1 split
    the whole chart halves — but the entry price stored in paper_state.json
    was recorded pre-split and does NOT halve with it. profit_pct would then
    read ~-50% and the exit engine would scream a false URGENT stop. Selling
    on that is acting on a data artifact, not a price move.
    """
    try:
        key = pd.Timestamp(pos.entry_date)
        idx = history.index
        if getattr(idx, "tz", None) is not None:
            key = key.tz_localize(idx.tz)
        mask = idx.normalize() == key.normalize()
        if not mask.any():
            return None                      # window doesn't reach entry date
        open_then = float(history.loc[mask, "Open"].iloc[0])
        if open_then <= 0 or pos.entry_price <= 0:
            return None
        expected_entry = open_then * costs.buy_multiplier(open_then)
        ratio = expected_entry / pos.entry_price
    except Exception:
        return None                          # never let the guard itself break a run
    if _CA_RATIO_LO <= ratio <= _CA_RATIO_HI:
        return None
    return ratio, expected_entry


def apply_corporate_action_adjustment(pos, ratio: float) -> str:
    """Rescale a position IN PLACE for a detected split/reverse-split so
    exit evaluation can resume immediately instead of staying stuck until
    someone manually edits paper_state.json. Mirrors what actually happens
    to a real brokerage holding: total position VALUE is preserved,
    price-per-share and share count move inversely.

    Shares are rounded to the nearest lot (100) — IDX only trades in
    lots, so a split ratio rarely divides the old share count exactly;
    the resulting few-share rounding drift is negligible next to the
    alternative (a permanently unmanaged position). Returns a one-line
    description of what changed, for the caller to surface to the user.
    """
    old_entry, old_shares, old_peak = pos.entry_price, pos.shares, pos.peak_price
    pos.entry_price = old_entry * ratio
    pos.peak_price = old_peak * ratio
    if pos.entry_atr is not None:
        pos.entry_atr = pos.entry_atr * ratio
    new_shares = int(round((old_shares / ratio) / LOT_SIZE)) * LOT_SIZE
    pos.shares = max(new_shares, LOT_SIZE) if old_shares > 0 else old_shares
    # Rescale the fill ledger the same way, or its share total stops matching
    # pos.shares and position_fills() would (correctly, but silently) discard
    # the whole ledger as out-of-sync on the next read. Prices move by the
    # ratio, share counts inversely, exactly as above.
    #
    # The lot-rounding drift is spread across ALL fills proportionally rather
    # than dumped on the last one. Dumping it there can drive a small final
    # fill negative — position_fills() then drops that entry, the total stops
    # matching pos.shares, and the ledger this block exists to preserve is
    # discarded anyway (taking its per-fill dates and "costed" markers with
    # it). Proportional scaling lands on pos.shares exactly and cannot zero a
    # fill, since every share count is multiplied by the same positive factor.
    existing = getattr(pos, "fills", None)
    if existing:
        scaled = [{**f, "price": f["price"] * ratio, "shares": f["shares"] / ratio}
                  for f in existing]
        total = sum(f["shares"] for f in scaled)
        if total > 0:
            k = pos.shares / total
            for f in scaled:
                f["shares"] *= k
        pos.fills = [f for f in scaled if f["shares"] > 0]
    return (f"auto-adjusted for suspected x{ratio:.2f} corporate action: "
           f"entry {old_entry:,.0f} -> {pos.entry_price:,.0f}, "
           f"shares {old_shares} -> {pos.shares} — verify against your "
           f"broker statement")


def rotate_state_backup(state_path, backup_dir, keep: int = 7):
    """Copy paper_state.json into ``backup_dir`` as
    paper_state_YYYYMMDD.json (one per calendar day; a same-day re-run just
    overwrites that day's copy), then prune to the newest ``keep`` files.
    Returns the backup path, or None if there is no state file yet.

    Why: save() being atomic protects against a crash MID-write, but not
    against the file being damaged some other way (disk fault, accidental
    edit, a future bug writing valid-but-wrong JSON). A rotating daily
    snapshot caps the worst case at losing one day of history instead of
    all of it. Called by daily_run before anything mutates state."""
    state_path = Path(state_path)
    if not state_path.exists():
        return None
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    from .clock import today_wib
    dest = backup_dir / f"paper_state_{today_wib().strftime('%Y%m%d')}.json"
    shutil.copy2(state_path, dest)
    backups = sorted(backup_dir.glob("paper_state_*.json"))
    for old in backups[:-keep] if keep > 0 else []:
        old.unlink()
    return dest


def _bars_held(entry_date: str, history) -> int | None:
    """Trading bars since the entry fill (fill day = 0), or None if the entry
    date isn't inside this history window. Same convention as backtest.py's
    ``bars_held = i - entry_i`` — needed for the max-holding-period exit,
    which is a VALIDATED rule the live path historically never applied."""
    try:
        key = pd.Timestamp(entry_date)
        idx = history.index
        if getattr(idx, "tz", None) is not None:
            key = key.tz_localize(idx.tz)
        mask = idx.normalize() == key.normalize()
        if not mask.any():
            return None
        return int(len(idx) - 1 - mask.argmax())
    except Exception:
        return None


@dataclass
class PaperPosition:
    ticker: str
    entry_price: float          # cost-inclusive per share -- BLENDED average
    shares: int
    entry_date: str             # FIRST purchase (unchanged by later adds)
    peak_price: float
    entry_atr: float | None = None
    # Per-fill ledger: [{"date", "shares", "price"}] in purchase order.
    #
    # WHY: entry_price/entry_date describe the position as a single blended
    # lot bought on day one. Buying more of a name you already hold updates
    # the average but keeps the ORIGINAL date, so the state could not say
    # when the added shares actually arrived -- and anything reconstructing
    # history (kala.chart.mark_to_market_points) had to value the whole
    # blended position from the first purchase date, overstating early
    # equity. Every one of this book's 15 positions is averaged-in, so that
    # was not an edge case.
    #
    # entry_price/entry_date are deliberately NOT removed: every existing
    # caller reads them, and they stay exactly correct as the blended
    # summary. ``fills`` is additive detail, not a replacement.
    #
    # None means a LEGACY position recorded before this existed. Read it
    # through ``position_fills()``, which synthesizes the single-lot view
    # for those -- i.e. exactly the old behavior, never a crash.
    #
    # INVARIANT: sum(f["shares"]) == shares. A partial sell reduces fills
    # pro-rata, which preserves the blended average exactly and keeps this
    # consistent with the average-cost accounting the rest of the class uses.
    #
    # A fill may also carry ``"costed": True``, meaning its recorded price
    # already includes commission and spread. Fills booked before manual
    # trades charged costs have no such marker, so one position can hold
    # both kinds; kala.friction reads this per fill to avoid charging the
    # new ones twice. Absent = not costed.
    fills: list | None = None


def position_fills(pos) -> list[dict]:
    """The per-fill ledger for a position, ALWAYS as a usable list.

    Reads a PaperPosition or a raw state dict. When ``fills`` is missing or
    empty -- a position recorded before the ledger existed -- this
    synthesizes the single-lot view ``(entry_date, shares, entry_price)``,
    which is precisely how such a position was treated before. Callers can
    therefore assume fills exist and never branch on legacy-ness.

    Falls back the same way if a stored ledger has drifted out of sync with
    ``shares`` (its share total not matching): a half-trusted ledger would
    silently mis-value the position, while the blended single lot is at
    worst imprecise about DATES and always right about size and cost.
    """
    is_dict = isinstance(pos, dict)
    shares = float((pos.get("shares") if is_dict else pos.shares) or 0.0)
    entry_price = float((pos.get("entry_price") if is_dict else pos.entry_price) or 0.0)
    entry_date = str((pos.get("entry_date") if is_dict else pos.entry_date) or "")
    stored = (pos.get("fills") if is_dict else pos.fills) or []

    clean = [f for f in stored
             if isinstance(f, dict) and float(f.get("shares") or 0) > 0]
    if clean and abs(sum(float(f["shares"]) for f in clean) - shares) < 1e-6:
        # "costed" is carried through rather than rebuilt: it records whether
        # THAT fill's price already had transaction costs applied, and a
        # position can legitimately mix (legacy shares bought before costs
        # were charged, plus shares added after). Dropping it here would
        # silently reclassify old fills as costed on the next add or sell.
        return [{"date": str(f.get("date") or entry_date),
                 "shares": float(f["shares"]),
                 "price": float(f.get("price") or entry_price),
                 **({"costed": True} if f.get("costed") else {})}
                for f in clean]

    # Synthesized legacy lot: no "costed" marker, because a position recorded
    # before the ledger existed predates cost charging too.
    return [{"date": entry_date, "shares": shares, "price": entry_price}]


def _costed_basis_fraction(pos) -> float:
    """Share of a position's COST BASIS whose price already includes
    transaction costs, in [0, 1].

    A position can mix: shares bought before manual trades charged costs
    carry no ``costed`` marker, shares added afterwards do. Weighting by
    basis (shares x price) rather than share count is what makes the
    friction split proportional to the money actually at stake in each fill.

    Returns 0.0 for a fully legacy position and 1.0 for a fully costed one.
    """
    fills = position_fills(pos)
    total = sum(f["shares"] * f["price"] for f in fills)
    if total <= 0:
        return 0.0
    costed = sum(f["shares"] * f["price"] for f in fills if f.get("costed"))
    return max(0.0, min(1.0, costed / total))


@dataclass
class PendingOrder:
    ticker: str
    side: str                   # "BUY" | "SELL"
    shares: int
    reason: str
    queued: str                 # date the order was decided
    limit_hint: float = 0.0     # last close when decided (info for the ticket)
    stop_hint: float = 0.0      # initial stop (info for the ticket)


class PaperTrader:
    def __init__(self, path, cfg: Config | None = None,
                 charge_manual_costs: bool = True):
        self.path = Path(path)
        self.cfg = cfg or Config()
        # Manual fills (the bot's /buy and /sell) apply the same cost model as
        # automated ones, so a hand-kept book and an automated one mean the
        # same thing. Set False to record raw broker prices instead -- the
        # pre-v3.9 behavior, kept as an escape hatch for anyone reconciling
        # against a statement line by line.
        self.charge_manual_costs = bool(charge_manual_costs)
        self.cash: float = 0.0
        self.start_capital: float = 0.0
        self.positions: dict[str, PaperPosition] = {}
        self.pending: list[PendingOrder] = []
        self.log: list[dict] = []
        self.benchmark_start: float | None = None  # IHSG on day 1 -> alpha
        self.capital_additions: list[dict] = []    # audit trail for add_capital
        self.dividends: list[dict] = []            # audit trail for record_dividend
        self.undo_stack: list[dict] = []           # manual actions only, see _push_undo
        self.redo_stack: list[dict] = []

    # ---------------- persistence ----------------
    @classmethod
    def load(cls, path, start_capital: float = 10_000_000, cfg: Config | None = None,
             charge_manual_costs: bool = True):
        pt = cls(path, cfg, charge_manual_costs=charge_manual_costs)
        p = Path(path)
        if p.exists():
            raw = json.loads(p.read_text())
            pt.cash = raw["cash"]
            pt.start_capital = raw["start_capital"]
            pt.positions = {t: PaperPosition(**r) for t, r in raw["positions"].items()}
            pt.pending = [PendingOrder(**r) for r in raw["pending"]]
            pt.log = raw.get("log", [])
            pt.benchmark_start = raw.get("benchmark_start")
            pt.capital_additions = raw.get("capital_additions", [])
            pt.dividends = raw.get("dividends", [])
            pt.undo_stack = raw.get("undo_stack", [])
            pt.redo_stack = raw.get("redo_stack", [])
        else:
            pt.cash = float(start_capital)
            pt.start_capital = float(start_capital)
        return pt

    def save(self):
        """Atomic write: serialize to a temp file next to the target, then
        os.replace() it over paper_state.json. A crash/power-cut mid-write
        can therefore never leave a half-written (corrupt) state file — the
        old file survives intact until the new one is fully on disk.
        os.replace is atomic on both POSIX and Windows. This file holds the
        entire trading history, undo stacks, and everything /edge measures;
        it must not be corruptible by bad timing."""
        payload = json.dumps({
            "cash": self.cash,
            "start_capital": self.start_capital,
            "positions": {t: asdict(p) for t, p in self.positions.items()},
            "pending": [asdict(o) for o in self.pending],
            "log": self.log,
            "benchmark_start": self.benchmark_start,
            "capital_additions": self.capital_additions,
            "dividends": self.dividends,
            "undo_stack": self.undo_stack,
            "redo_stack": self.redo_stack,
        }, indent=2)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(payload)
        os.replace(tmp, self.path)

    # ---------------- undo / redo (manual actions only) ----------------
    # Scoped to manual_buy / manual_sell / add_capital — the three places a
    # fat-fingered number does real (if paper) damage. The automated daily
    # step() is a batch action, not a typo, and isn't covered on purpose.

    def _snapshot(self) -> dict:
        return {
            "cash": self.cash,
            "start_capital": self.start_capital,
            "positions": {t: asdict(p) for t, p in self.positions.items()},
            "pending": [asdict(o) for o in self.pending],
            "log": list(self.log),
            "benchmark_start": self.benchmark_start,
            "capital_additions": list(self.capital_additions),
            "dividends": list(self.dividends),
        }

    def _restore(self, snap: dict) -> None:
        self.cash = snap["cash"]
        self.start_capital = snap["start_capital"]
        self.positions = {t: PaperPosition(**r) for t, r in snap["positions"].items()}
        self.pending = [PendingOrder(**r) for r in snap["pending"]]
        self.log = list(snap["log"])
        self.benchmark_start = snap["benchmark_start"]
        self.capital_additions = list(snap["capital_additions"])
        # .get(): undo-stack entries snapshotted before this field existed
        # (an already-running install upgrading mid-session) won't have it —
        # restoring them must degrade to "no dividends known yet", not KeyError.
        self.dividends = list(snap.get("dividends", []))

    def _push_undo(self, label: str, kind: str | None = None,
                   amount: float | None = None, meta: dict | None = None) -> None:
        """Snapshot state BEFORE a manual mutation. `kind`/`amount`/`meta`
        let a caller (the bot) react to what KIND of action this was — e.g.
        a deposit also syncs runner_config.json outside this class, and
        that side effect needs to be undone/redone in step; `meta` is an
        opaque bag the caller can stuff whatever it needs into (e.g. the
        exact pre-deposit budget, so the reversal restores a known value
        instead of doing relative arithmetic on whatever the config
        currently holds). A fresh manual action clears the redo stack —
        same convention as any editor: redo only makes sense immediately
        after an undo, not after you've since done something else."""
        self.undo_stack.append({"label": label, "kind": kind, "amount": amount,
                                "meta": meta, "state": self._snapshot()})
        if len(self.undo_stack) > MAX_UNDO_DEPTH:
            self.undo_stack.pop(0)
        self.redo_stack.clear()

    def undo(self) -> dict:
        """Revert the last manual_buy/manual_sell/add_capital. Returns
        {"label": str, "kind": str|None, "amount": float|None,
        "meta": dict|None} describing what was reverted. Raises ValueError
        if there's nothing to undo."""
        if not self.undo_stack:
            raise ValueError("nothing to undo")
        entry = self.undo_stack.pop()
        self.redo_stack.append({**entry, "state": self._snapshot()})
        if len(self.redo_stack) > MAX_UNDO_DEPTH:
            self.redo_stack.pop(0)
        self._restore(entry["state"])
        self.save()
        return {"label": entry["label"], "kind": entry["kind"],
                "amount": entry["amount"], "meta": entry.get("meta")}

    def redo(self) -> dict:
        """Re-apply the action just undone. Same return shape as undo().
        Raises ValueError if there's nothing to redo."""
        if not self.redo_stack:
            raise ValueError("nothing to redo")
        entry = self.redo_stack.pop()
        self.undo_stack.append({**entry, "state": self._snapshot()})
        if len(self.undo_stack) > MAX_UNDO_DEPTH:
            self.undo_stack.pop(0)
        self._restore(entry["state"])
        self.save()
        return {"label": entry["label"], "kind": entry["kind"],
                "amount": entry["amount"], "meta": entry.get("meta")}

    def add_capital(self, amount: float, date: str | None = None,
                    meta: dict | None = None) -> None:
        """Record fresh money deposited into the trading account mid-cycle
        (e.g. you topped up your broker account today). Increases BOTH cash
        AND start_capital by the same amount — a deposit is new principal,
        not trading profit, so it must never be allowed to inflate
        return_pct in summary(). Without bumping start_capital too, a
        deposit would show up as an instant "gain" that has nothing to do
        with the strategy's performance. `meta` is passed straight to the
        undo entry (see _push_undo) — the bot uses it to carry the exact
        pre-deposit daily_capital_idr for a precise undo/redo."""
        if amount <= 0:
            raise ValueError("amount must be positive")
        self._push_undo(f"DEPOSIT IDR {amount:,.0f}", kind="deposit",
                        amount=float(amount), meta=meta)
        self.cash += amount
        self.start_capital += amount
        self.capital_additions.append({"date": date or date_str_today(), "amount": float(amount)})
        self.save()

    def record_dividend(self, ticker: str, amount: float, date: str | None = None) -> None:
        """Record dividend income received on ``ticker``. The DELIBERATE
        opposite of add_capital: this increases cash but does NOT touch
        start_capital, because a dividend is real investment RETURN, not
        external principal you added. Get this backwards (e.g. by using
        /deposit to log a dividend, which this method exists to stop
        someone doing) and TWR/return_pct silently UNDERSTATE your real
        performance — the dividend cash would sit in the account looking
        like unexplained principal instead of counting as a gain.

        Not required that you still hold ``ticker`` -- a dividend can be
        paid after you've since sold, and recording it late/backdated is
        still more honest than not recording it at all."""
        ticker = ticker.upper()
        if amount <= 0:
            raise ValueError("amount must be positive")
        self._push_undo(f"DIVIDEND {ticker} IDR {amount:,.0f}", kind="dividend",
                        amount=float(amount))
        self.cash += amount
        self.dividends.append({"date": date or date_str_today(), "ticker": ticker,
                               "amount": float(amount)})
        self.save()

    def note_benchmark(self, price) -> None:
        """Record the benchmark (IHSG) level the first time we see one, so
        every later summary can report alpha vs holding the index instead."""
        if price and price > 0 and self.benchmark_start is None:
            self.benchmark_start = float(price)
            self.save()

    # ---------------- manual trade recording ----------------
    # These let you tell the system about trades YOU actually made in your real
    # broker, so /review manages them with the same trailing-stop + cut-loss
    # engine it uses for auto positions. Entry/exit prices are the real prices
    # you enter — no synthetic commission is added, so P/L matches your broker.

    def manual_fill_price(self, price: float, side: str) -> float:
        """The price a manual fill is BOOKED at, given the raw price you were
        filled at on your broker screen.

        With ``charge_manual_costs`` on (default) this applies exactly the
        cost model the automated path uses in ``step()`` -- buy prices go UP
        by commission + half spread, sell proceeds come DOWN by commission +
        final tax + half spread. That makes ``entry_price`` genuinely
        cost-inclusive, as PaperPosition has always documented it to be, and
        stops a manual book from reporting a return it never earned.

        With the switch off it returns the raw price unchanged.
        """
        raw = float(price)
        if not self.charge_manual_costs:
            return raw
        c = self.cfg.costs
        mult = c.buy_multiplier(raw) if side.upper() == "BUY" else c.sell_multiplier(raw)
        return raw * mult

    def manual_buy(self, ticker: str, shares: int, price: float,
                   date: str | None = None, atr: float | None = None) -> float:
        """Record a buy you executed. ``price`` is the RAW price your broker
        filled you at; commission and half the spread are added on top, so
        the booked ``entry_price`` is what the shares actually cost you.
        Returns that cost-inclusive fill price.

        If you already hold this ticker, this
        ADDS to the position instead of rejecting: shares combine and
        entry_price becomes the size-weighted average cost basis — the
        classic "pyramid into strength" move /review's "could add" note
        points at. peak_price and entry_date are preserved (it's still the
        SAME open position, opened on the original date; the trailing stop
        must keep judging profit against the true historical peak, not
        reset it to today's price). entry_atr is refreshed if a new one is
        given, since ATR-based stop sizing is more accurate with the
        current volatility reading. Raises ValueError on bad input so the
        caller (the bot) can show a clear message.

        Note: the corporate-action guard (_corporate_action_ratio)
        compares entry_price against adjusted history at entry_date — after
        an add, entry_price is a blend but entry_date is still the FIRST
        purchase, so that check is slightly less precise for averaged-in
        positions. It still catches genuine splits; it isn't tuned for this
        edge case specifically.
        """
        ticker = ticker.upper()
        if shares <= 0:
            raise ValueError("shares must be positive")
        if price <= 0:
            raise ValueError("price must be positive")
        fill = self.manual_fill_price(price, "BUY")
        cost = fill * shares
        if cost > self.cash + 1e-6:
            raise ValueError(
                f"not enough cash: need IDR {cost:,.0f}, have IDR {self.cash:,.0f}. "
                f"Raise it with /deposit.")
        self._push_undo(f"BUY {ticker} {shares:,} sh @ IDR {price:,.0f}", kind="buy")
        self.cash -= cost

        existing = self.positions.get(ticker)
        fill_date = date or date_str_today()
        # peak_price tracks the MARKET price, not the cost-inclusive one: the
        # trailing stop compares it against later closes, and seeding it above
        # any price the market actually printed would arm the stop early.
        new_fill = {"date": fill_date, "shares": float(shares), "price": fill}
        if self.charge_manual_costs:
            new_fill["costed"] = True
        if existing is None:
            self.positions[ticker] = PaperPosition(
                ticker=ticker, entry_price=fill, shares=int(shares),
                entry_date=fill_date, peak_price=float(price),
                entry_atr=atr, fills=[new_fill])
        else:
            total_shares = existing.shares + int(shares)
            # Snapshot the ledger BEFORE touching entry_price or shares. For a
            # legacy position position_fills() synthesizes its single lot FROM
            # those two fields, so blending first would back-date the new
            # average onto the original shares and lose their real cost.
            prior_fills = position_fills(existing)
            existing.entry_price = (existing.entry_price * existing.shares
                                    + fill * shares) / total_shares
            existing.fills = prior_fills + [new_fill]
            existing.shares = total_shares
            existing.peak_price = max(existing.peak_price, float(price))
            if atr is not None:
                existing.entry_atr = atr
        self.save()
        return fill

    def manual_sell(self, ticker: str, price: float, shares: int | None = None,
                    date: str | None = None, reason: str = "manual sell") -> float:
        """Record a sell you executed. ``price`` is the RAW price your broker
        filled you at; commission, the final transaction tax and half the
        spread are deducted from it, so the booked exit and the cash credited
        are the proceeds you actually keep.

        `shares=None` (default) sells the
        WHOLE position, same as before. Passing `shares` less than the full
        position size takes PARTIAL profit: that many shares are sold at
        `price`, the rest stay open UNCHANGED — same entry_price, peak_price
        and entry_date, since the cost basis of shares you didn't sell never
        moves. Returns realised P/L % on the shares actually sold, net of
        costs on both legs."""
        ticker = ticker.upper()
        pos = self.positions.get(ticker)
        if pos is None:
            raise ValueError(f"you are not holding {ticker}")
        if price <= 0:
            raise ValueError("price must be positive")
        sell_shares = pos.shares if shares is None else int(shares)
        if sell_shares <= 0:
            raise ValueError("shares must be positive")
        if sell_shares > pos.shares:
            raise ValueError(f"you only hold {pos.shares:,} sh of {ticker}, "
                            f"can't sell {sell_shares:,}")
        # A sell dated before its own entry produces a negative hold time
        # that the /edge tracker would silently average in (ISO date
        # strings compare correctly as plain strings, so no parsing needed).
        if date is not None and date < pos.entry_date:
            raise ValueError(f"sell date {date} is before {ticker}'s entry date "
                            f"{pos.entry_date} — check the @date")
        partial = sell_shares < pos.shares
        label = (f"SELL {ticker} {sell_shares:,} sh @ IDR {price:,.0f}"
                + (" (partial)" if partial else ""))
        self._push_undo(label, kind="sell")
        # Capture how much of the cost basis was booked WITH costs before the
        # position (and its fill ledger) is popped. Once closed, the log entry
        # is the only surviving record, and a position opened before manual
        # trades charged costs must not be reported as though it had.
        entry_costed_frac = _costed_basis_fraction(pos)
        net = self.manual_fill_price(price, "SELL")
        proceeds = net * sell_shares
        self.cash += proceeds
        pnl_pct = (net / pos.entry_price - 1) * 100.0
        entry = {"date": date or date_str_today(), "ticker": ticker,
                 "entry": pos.entry_price, "exit": net,
                 "entry_date": pos.entry_date,
                 "shares": sell_shares, "pnl_pct": pnl_pct, "reason": reason}
        if self.charge_manual_costs:
            entry["costed"] = True          # the SELL leg is net of costs
        if entry_costed_frac > 0:
            entry["entry_costed_frac"] = entry_costed_frac   # the BUY leg
        self.log.append(entry)
        if partial:
            remaining = pos.shares - sell_shares
            # Shrink the ledger PRO-RATA rather than consuming fills FIFO.
            # Pro-rata leaves the blended average untouched, which is what
            # the rest of this class assumes (entry_price deliberately does
            # not move on a partial sell); FIFO would silently switch the
            # position to a different cost-basis convention mid-life.
            scale = remaining / pos.shares
            pos.fills = [{**f, "shares": f["shares"] * scale}
                         for f in position_fills(pos)]
            pos.shares = remaining
        else:
            self.positions.pop(ticker)
        self.save()
        return pnl_pct

    def edit_entry_price(self, ticker: str, new_price: float,
                         reconcile_cash: bool = True) -> float:
        """Correct a WRONG entry price already on the books -- e.g. you
        mistyped the price in /buy, or your broker confirmation shows a
        different fill than what you logged. Only ``entry_price`` changes;
        ``shares`` and ``entry_date`` are untouched. Returns the OLD price.

        This exists because /undo only reaches the MOST RECENT manual
        action -- a typo from three trades ago can't be fixed without also
        undoing everything since. Editing the position directly targets
        exactly the field that was wrong.

        ``reconcile_cash`` (default True): entry_price is COST-INCLUSIVE
        (see PaperPosition's docstring), so cash was debited based on the
        WRONG price when the position was opened. This adjusts cash by the
        difference so it reflects what was actually paid -- silently
        changing entry_price without this would leave cash and equity
        internally inconsistent, effectively fabricating or destroying
        money. Pass False only if you've already reconciled cash yourself
        by some other means.

        ``peak_price`` is raised to at least ``new_price`` if the
        correction is an INCREASE: peak_price must never sit below
        entry_price, or the trailing-stop logic in kala.live computes a
        stop below the position's own cost basis, which defeats the point
        of having one.
        """
        ticker = ticker.upper()
        pos = self.positions.get(ticker)
        if pos is None:
            raise ValueError(f"you are not holding {ticker}")
        if new_price <= 0:
            raise ValueError("price must be positive")
        old_price = pos.entry_price
        if new_price == old_price:
            raise ValueError(
                f"{ticker}'s entry price is already {new_price:,.0f} — nothing to change")

        delta_cost = (new_price - old_price) * pos.shares
        if reconcile_cash and delta_cost > self.cash + 1e-6:
            raise ValueError(
                f"correcting to IDR {new_price:,.0f} implies you spent IDR "
                f"{delta_cost:,.0f} more than currently recorded, but you only "
                f"have IDR {self.cash:,.0f} cash. Double-check the price.")

        label = f"EDIT ENTRY {ticker}: IDR {old_price:,.0f} -> IDR {new_price:,.0f}"
        self._push_undo(label, kind="edit_entry",
                        meta={"ticker": ticker, "old_price": old_price,
                              "new_price": float(new_price)})
        if reconcile_cash:
            self.cash -= delta_cost
        # Rescale every fill by the same factor the blended price moved, so
        # the ledger keeps summing to entry_price. Correcting a mistyped
        # price says nothing about which fill was wrong, and this is the only
        # adjustment that leaves the average exactly where the caller asked.
        factor = float(new_price) / old_price if old_price else 1.0
        pos.fills = [{**f, "price": f["price"] * factor}
                     for f in position_fills(pos)]
        pos.entry_price = float(new_price)
        pos.peak_price = max(pos.peak_price, pos.entry_price)
        self.save()
        return old_price

    # ---------------- sizing ----------------
    def size_position(self, price: float, stop_price: float, allocation: float,
                      risk_pct: float = 2.0, max_positions: int = 5,
                      cash_override: float | None = None) -> int:
        """Risk-based sizing, respecting IDX lots and the user's allocation.

        Risk `risk_pct` of the allocation per trade, spread across at most
        `max_positions` concurrent names; never spend more than the per-slot
        cap or available cash. Returns SHARES (a multiple of 100), or 0.

        ``cash_override``: use this instead of ``self.cash`` for the
        affordability check. Exists so a caller ranking MULTIPLE candidates
        in one pass (e.g. /scan's new-buy list) can pass a running remaining-
        cash total that shrinks as earlier, higher-ranked candidates are
        hypothetically bought — without it, every candidate in the list
        would be sized against the SAME full cash balance independently,
        recommending more in total than the account could actually afford."""
        if price <= 0 or stop_price >= price or allocation <= 0:
            return 0
        cash = self.cash if cash_override is None else cash_override
        risk_per_share = price - stop_price
        risk_budget = allocation * (risk_pct / 100.0)
        by_risk = risk_budget / risk_per_share
        by_slot = (allocation / max_positions) / price
        by_cash = cash / (price * self.cfg.costs.buy_multiplier(price))
        raw = min(by_risk, by_slot, by_cash)
        lots = int(raw // LOT_SIZE)
        return lots * LOT_SIZE

    # ---------------- one daily step ----------------
    def step(self, histories: dict, signals: list[dict] | None = None,
             market_status: str | None = None, allocation: float | None = None,
             today: str | None = None, risk_pct: float = 2.0,
             max_positions: int = 5, max_pct_of_adv: float = 5.0,
             auto_buy: bool = True) -> dict:
        """Run one end-of-day cycle.

        histories: {ticker: OHLCV DataFrame whose LAST row is today}
        signals:   scanner output (dicts with 'ticker','signal', price, 'atr',
                   'stop_loss', optional 'entry_vetoes')
        allocation: max IDR the trader may deploy in NEW buys queued today
                    (defaults to available cash)
        auto_buy:  if True (default — unchanged historical behavior), stage 3
                   QUEUES real BUY orders that fill automatically next session,
                   same as a fully autonomous paper-trading benchmark. If
                   False, stage 3 becomes RECOMMENDATION-ONLY: the same
                   ranking/sizing/veto/liquidity logic runs to produce
                   realistic tickets, but nothing is queued, no cash moves,
                   and no position appears until the user calls manual_buy
                   (the bot's /buy). Stages 1-2 (fills, exits) are unaffected
                   either way — they only ever act on orders/positions that
                   already exist, auto or manual.

        Order of operations (mirrors the backtest):
          1. Fill yesterday's pending orders at TODAY'S OPEN (with costs).
          2. Update peaks; evaluate exits on holdings -> queue SELLs for
             tomorrow's open.
          3. Size new BUYs from today's signals within `allocation` ->
             queue (auto_buy=True) or report as ideas only (auto_buy=False).
        Returns a report dict incl. human-ready `tickets` for tomorrow."""
        today = today or date_str_today()
        allocation = self.cash if allocation is None else min(allocation, self.cash)
        costs = self.cfg.costs
        report = {"date": today, "fills": [], "exits_queued": [],
                  "buys_queued": [], "skipped": [], "tickets": [],
                  # Holdings whose exit rules could not be evaluated at all
                  # today. Kept separate from "skipped" (which is truncated
                  # for display) because an unchecked stop is not a footnote.
                  "unevaluated": []}

        # -- 1. fill pending at today's open --------------------------------
        still_pending = []
        for o in self.pending:
            h = histories.get(o.ticker)
            if h is None or not len(h):
                still_pending.append(o)   # no bar today (suspended?) -> carry
                continue
            open_px = float(h["Open"].iloc[-1])
            # yfinance hands back NaN for an unposted or illiquid latest bar,
            # and NaN loses every comparison silently: `cost > self.cash` is
            # False when cost is NaN, so the affordability check below WAVES
            # THROUGH an unaffordable order, sets self.cash to NaN, and books
            # a position at a NaN entry price. That state is then saved, so
            # equity, TWR and every report read "nan" from then on and do not
            # heal on the next run. Carry the order instead — the same
            # treatment a missing bar already gets a few lines above.
            if not math.isfinite(open_px) or open_px <= 0:
                still_pending.append(o)
                report["skipped"].append(
                    f"{o.side} {o.ticker} carried — no usable open price today "
                    f"(got {open_px})")
                continue
            if o.side == "BUY":
                fill = open_px * costs.buy_multiplier(open_px)
                cost = fill * o.shares
                if o.ticker in self.positions or cost > self.cash + 1e-6:
                    report["skipped"].append(f"BUY {o.ticker} skipped (held or cash short)")
                    continue
                self.cash -= cost
                atr_val = None
                if "atr" in getattr(h, "columns", []):
                    a = h["atr"].iloc[-1]
                    atr_val = None if a != a else float(a)
                self.positions[o.ticker] = PaperPosition(
                    ticker=o.ticker, entry_price=fill, shares=o.shares,
                    entry_date=today, peak_price=open_px, entry_atr=atr_val,
                    fills=[{"date": today, "shares": float(o.shares),
                            "price": fill, "costed": True}])
                report["fills"].append(f"BOUGHT {o.ticker} {o.shares} @ {fill:,.0f} (open {open_px:,.0f})")
            else:  # SELL
                pos = self.positions.get(o.ticker)
                if pos is None:
                    continue
                # Limit-down ("ARB") carry — same realism rule as the backtest:
                # a bar pinned at the lower auto-rejection band has no bids, so
                # the sell cannot fill. Carry the order to the next session.
                prev_close = float(h["Close"].iloc[-2]) if len(h) >= 2 else None
                if prev_close and _is_arb_locked(h.iloc[-1], prev_close,
                                                 arb_lower_limit_pct(prev_close)):
                    still_pending.append(o)
                    report["skipped"].append(
                        f"SELL {o.ticker} carried — limit down, no bids (ARB)")
                    continue
                entry_costed_frac = _costed_basis_fraction(pos)
                self.positions.pop(o.ticker)
                fill = open_px * costs.sell_multiplier(open_px)
                proceeds = fill * pos.shares
                self.cash += proceeds
                pnl_pct = (fill / pos.entry_price - 1) * 100
                # An automated sell is always net of costs; the buy leg may
                # not be, if this position was opened by hand beforehand.
                closed = {"date": today, "ticker": o.ticker,
                          "entry": pos.entry_price, "exit": fill,
                          "entry_date": pos.entry_date,
                          "shares": pos.shares, "pnl_pct": pnl_pct,
                          "reason": o.reason, "costed": True}
                if entry_costed_frac > 0:
                    closed["entry_costed_frac"] = entry_costed_frac
                self.log.append(closed)
                report["fills"].append(
                    f"SOLD {o.ticker} {pos.shares} @ {fill:,.0f} ({pnl_pct:+.1f}%, {o.reason})")
        self.pending = still_pending

        # -- 2. exits on current holdings ------------------------------------
        pending_tickers = {o.ticker for o in self.pending}
        for t, pos in list(self.positions.items()):
            if t in pending_tickers:
                continue
            h = histories.get(t)
            if h is None or len(h) < 60:
                # No usable history: the stop, the trailing stop and the
                # max-holding rule all go UNCHECKED for this position today.
                # Staying silent here is what made that dangerous — the daily
                # message simply omitted the ticker, which reads as "no exit
                # signal" when the truth is "never looked".
                report["unevaluated"].append(
                    f"{t}: no price data today — stop/exit rules NOT checked"
                    if h is None else
                    f"{t}: only {len(h)} bars of history (need 60) — "
                    f"stop/exit rules NOT checked")
                continue
            ca_detected = _corporate_action_ratio(pos, h, costs)
            if ca_detected is not None:
                ratio, _expected_entry = ca_detected
                note = apply_corporate_action_adjustment(pos, ratio)
                report["skipped"].append(f"{t}: {note}")
                report["tickets"].append(f"⚠️ {t} — {note}")
                # fall through: the position is now consistent with today's
                # adjusted history, so exit evaluation below can run on it
                # THIS SAME CYCLE instead of staying stuck until tomorrow.
            close_px = float(h["Close"].iloc[-1])
            pos.peak_price = max(pos.peak_price, close_px)
            r = evaluate_position(ticker=t, entry_price=pos.entry_price,
                                  history=h, peak_price=pos.peak_price,
                                  market_status=market_status, cfg=self.cfg.risk)
            queue_reason = None
            if r["exit_signal"] and r["urgency"] in ("URGENT", "CONSIDER"):
                queue_reason = "; ".join(r["reasons"])[:200]
                headline = f"{r['urgency']} — {r['reasons'][0]}"
            else:
                # Max holding period — a VALIDATED exit rule (backtest.py)
                # that the live path never applied until v3.3. Fill day = 0,
                # same bar convention as the backtest.
                held = _bars_held(pos.entry_date, h)
                max_days = self.cfg.backtest.holding_max_days
                if held is not None and held >= max_days:
                    queue_reason = f"[CONSIDER] max holding period ({held} bars >= {max_days})"
                    headline = queue_reason
            if queue_reason is not None:
                self.pending.append(PendingOrder(
                    ticker=t, side="SELL", shares=pos.shares,
                    reason=queue_reason, queued=today,
                    limit_hint=close_px))
                report["exits_queued"].append(f"{t}: {headline}")
                report["tickets"].append(
                    f"SELL {t} — {pos.shares:,} shares at open "
                    f"(~IDR {close_px:,.0f}) | {headline}")

        # -- 3. new entries from today's signals -----------------------------
        # Rank BUY candidates by conviction (technical_score, STRONG BUY ahead
        # of BUY on ties) BEFORE spending the day's allocation. The scanner
        # emits signals in WATCHLIST (alphabetical) order; walking that order
        # blindly would fill the alphabetically-first BUYs, not the strongest
        # ones the dashboard ranks at the top. Sorting here makes the paper
        # trader buy the SAME top names the dashboard highlights, regardless of
        # the order the scanner happened to return them in. Python's sort is
        # stable, so signals without a score keep their original order.
        _signal_rank = {"STRONG BUY": 1, "BUY": 0}
        candidates = [s for s in (signals or [])
                      if str(s.get("signal", "")).upper() in ("BUY", "STRONG BUY")]
        candidates.sort(
            key=lambda s: (float(s.get("technical_score", 0) or 0),
                           _signal_rank.get(str(s.get("signal", "")).upper(), 0)),
            reverse=True)

        # Portfolio cap: only open enough NEW names to reach max_positions,
        # counting what we already hold plus buys already queued today. This
        # makes "top N" literal instead of relying on the allocation running dry.
        already = set(self.positions) | {o.ticker for o in self.pending if o.side == "BUY"}
        slots_left = max(0, max_positions - len(already))

        for i, s in enumerate(candidates):
            if slots_left <= 0:
                remaining = [c["ticker"] for c in candidates[i:]
                             if c["ticker"] not in self.positions]
                if remaining:
                    shown = ", ".join(remaining[:5]) + ("…" if len(remaining) > 5 else "")
                    report["skipped"].append(
                        f"portfolio full ({max_positions} names) — passed over "
                        f"{len(remaining)} lower-ranked BUY(s): {shown}")
                break
            if s.get("entry_vetoes"):
                report["skipped"].append(f"{s['ticker']}: vetoed ({s['entry_vetoes'][0]})")
                continue
            t = s["ticker"]
            if t in self.positions or t in pending_tickers:
                continue
            price = float(s.get("price") or s.get("close") or 0)
            if price <= 0:
                continue
            atr_val = s.get("atr")
            stop, _, _ = governing_stop(price, price, atr_val, self.cfg.risk)
            shares = self.size_position(price, stop, allocation,
                                        risk_pct=risk_pct, max_positions=max_positions)
            if shares < LOT_SIZE:
                report["skipped"].append(f"{t}: allocation too small for 1 lot")
                continue
            # Liquidity cap: never be more than `max_pct_of_adv`% of the
            # stock's 20-day average daily traded VALUE. A paper fill bigger
            # than that is fantasy — a real order would move the price.
            h = histories.get(t)
            if h is not None and "Volume" in h.columns and len(h) >= 20:
                adv = float((h["Close"] * h["Volume"]).tail(20).mean())
                if adv > 0:
                    cap_shares = int((adv * max_pct_of_adv / 100.0) / price
                                     // LOT_SIZE) * LOT_SIZE
                    if cap_shares < LOT_SIZE:
                        report["skipped"].append(
                            f"{t}: too illiquid (ADV IDR {adv:,.0f} — "
                            f"even 1 lot exceeds {max_pct_of_adv:.0f}% of it)")
                        continue
                    if cap_shares < shares:
                        report["skipped"].append(
                            f"{t}: shrunk {shares}->{cap_shares} sh (liquidity cap "
                            f"{max_pct_of_adv:.0f}% of ADV)")
                        shares = cap_shares
            target = price * (1 + self.cfg.risk.target_profit_pct / 100.0)
            est = price * shares

            if auto_buy:
                self.pending.append(PendingOrder(
                    ticker=t, side="BUY", shares=shares, reason="scanner BUY",
                    queued=today, limit_hint=price, stop_hint=stop))
                pending_tickers.add(t)
                report["buys_queued"].append(f"{t}: {shares} sh ≈ IDR {est:,.0f}")
                report["tickets"].append(
                    f"BUY {t} — {shares:,} shares ≈ IDR {est:,.0f} "
                    f"(last {price:,.0f}, stop-loss {stop:,.0f}, "
                    f"take-profit {target:,.0f} / +{self.cfg.risk.target_profit_pct:.0f}%)")
                allocation -= est
            else:
                # Recommendation only — nothing queued, no cash/position
                # touched. Sizing/vetoes/liquidity still ran for real so the
                # numbers shown are what you'd actually be able to fill.
                report["tickets"].append(
                    f"💡 IDEA {t} — {shares:,} shares ≈ IDR {est:,.0f} "
                    f"(last {price:,.0f}, stop-loss {stop:,.0f}, "
                    f"take-profit {target:,.0f} / +{self.cfg.risk.target_profit_pct:.0f}%) "
                    f"— reply /buy {t.split('.')[0]} {shares} {price:,.0f} if you actually buy it")
            slots_left -= 1

        self.save()
        return report

    # ---------------- reporting ----------------
    def equity(self, last_prices: dict[str, float]) -> float:
        eq = self.cash
        for t, p in self.positions.items():
            eq += p.shares * last_prices.get(t, p.entry_price)
        return eq

    def summary(self, last_prices: dict[str, float],
                benchmark_price: float | None = None) -> dict:
        eq = self.equity(last_prices)
        closed = self.log
        wins = [x for x in closed if x["pnl_pct"] > 0]
        out = {
            "equity": eq,
            "cash": self.cash,
            "return_pct": (eq / self.start_capital - 1) * 100 if self.start_capital else 0.0,
            "open_positions": len(self.positions),
            "closed_trades": len(closed),
            "win_rate_pct": (len(wins) / len(closed) * 100) if closed else 0.0,
        }
        # Alpha vs buy-and-hold IHSG since the account started: the honest
        # question is not "am I up?" but "did I beat doing nothing?".
        if benchmark_price and benchmark_price > 0 and self.benchmark_start:
            bench_ret = (benchmark_price / self.benchmark_start - 1) * 100
            out["benchmark_return_pct"] = bench_ret
            out["alpha_pct"] = out["return_pct"] - bench_ret
        return out

    def recent_performance(self, days: int = 7, today: date | None = None) -> dict:
        """A 'live performance this week' slice of the closed-trade log — the
        same kind of number a signal-service ad leads with (win rate, W/L
        this week), computed honestly from YOUR real fills: every closed
        trade in the window counts, wins and losses alike, nothing held back
        as 'watchlist'. Net P&L is in rupiah (exit-entry)*shares, matching
        what a real position actually made or lost, not a bare percentage.

        Returns {"window_days", "n", "wins", "losses", "win_rate_pct",
        "net_profit_idr", "trades": [{"ticker","pnl_pct","profit_idr",
        "reason"}]} — trades sorted most-recent-first.
        """
        from .clock import today_wib
        ref = today or today_wib()
        window: list[dict] = []
        for t in self.log:
            try:
                d = date.fromisoformat(str(t["date"]))
            except (KeyError, TypeError, ValueError):
                continue
            if 0 <= (ref - d).days < days:
                window.append(t)
        window.sort(key=lambda t: t["date"], reverse=True)

        wins = [t for t in window if t["pnl_pct"] > 0]
        losses = [t for t in window if t["pnl_pct"] <= 0]
        net_profit_idr = sum((t["exit"] - t["entry"]) * t["shares"] for t in window)

        return {
            "window_days": days,
            "n": len(window),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate_pct": (len(wins) / len(window) * 100.0) if window else 0.0,
            "net_profit_idr": net_profit_idr,
            "trades": [{"ticker": t["ticker"], "pnl_pct": t["pnl_pct"],
                       "profit_idr": (t["exit"] - t["entry"]) * t["shares"],
                       "reason": t.get("reason", "")} for t in window],
        }
