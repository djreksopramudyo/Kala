"""
Equity-curve chart rendering — a dependency-free PNG encoder + line-chart
renderer, so /chart can send an actual image to Telegram without pulling
in matplotlib/Pillow (neither is available in every deployment target this
project runs on, and a stdlib-only image is one less thing that can fail
to install on a cheap VPS).

HONESTY NOTE ON WHAT THE CURVE ACTUALLY SHOWS: there is no stored daily
equity snapshot anywhere in this codebase (papertrade.py only tracks
CURRENT cash/positions, not a history of past equity marks). The curve
here is CUMULATIVE REALIZED P&L from closed trades only — it does not
include unrealized P&L on currently open positions, and it steps only on
days a trade closed, not every calendar day. Labelled as such wherever
it's surfaced; treat it as a rough shape of "am I compounding or bleeding
over time", not a precise mark-to-market equity curve.

No text/font rendering (no font rasterizer in the stdlib) — axis labels
and summary numbers belong in the caption the caller sends alongside the
image, not burned into the pixels.
"""

from __future__ import annotations

import struct
import zlib

BACKGROUND = (15, 17, 21)
GRID = (42, 45, 52)
AXIS = (90, 94, 102)
GREEN = (76, 175, 80)
RED = (244, 67, 54)


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + chunk_type + data
           + struct.pack(">I", zlib.crc32(chunk_type + data) & 0xFFFFFFFF))


def encode_png(width: int, height: int, pixels: bytearray) -> bytes:
    """``pixels``: flat RGB bytes, row-major top-to-bottom, length ==
    width*height*3. Filter type 0 (None) per scanline, 8-bit truecolor —
    simplest valid PNG, no compression tricks beyond zlib's own."""
    raw = bytearray()
    stride = width * 3
    for y in range(height):
        raw.append(0)   # filter type: None
        raw.extend(pixels[y * stride:(y + 1) * stride])

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    idat = zlib.compress(bytes(raw), level=6)
    return (b"\x89PNG\r\n\x1a\n"
           + _png_chunk(b"IHDR", ihdr)
           + _png_chunk(b"IDAT", idat)
           + _png_chunk(b"IEND", b""))


def _set_px(pixels: bytearray, width: int, height: int, x: int, y: int, color: tuple[int, int, int]) -> None:
    if 0 <= x < width and 0 <= y < height:
        i = (y * width + x) * 3
        pixels[i:i + 3] = bytes(color)


def _draw_line(pixels: bytearray, width: int, height: int, x0: int, y0: int,
               x1: int, y1: int, color: tuple[int, int, int], thickness: int = 1) -> None:
    """Bresenham, with an optional vertical thickening for visibility at
    typical chat-bubble image sizes."""
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx + dy
    x, y = x0, y0
    while True:
        for t in range(-(thickness // 2), thickness // 2 + 1):
            _set_px(pixels, width, height, x, y + t, color)
        if x == x1 and y == y1:
            break
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x += sx
        if e2 <= dx:
            err += dx
            y += sy


def equity_curve_points(log: list[dict], start_capital: float,
                        capital_additions: list[dict] | None = None) -> list[tuple[str, float]]:
    """Cumulative realized equity in chronological order: begins at
    ORIGINAL capital (``start_capital`` minus any deposits) and steps
    through every closed trade AND every dated deposit in date order, so
    a mid-period deposit shows up exactly where it happened instead of
    being folded into day one.

    ``capital_additions``: ``PaperTrader.capital_additions`` (list of
    ``{"date", "amount"}``). None (default) treats ``start_capital`` as
    the base with no deposits to place -- correct when there haven't been
    any, and the prior (pre-fix) behavior for callers not yet updated to
    pass it. Without this, a deposit made mid-period would make the curve
    START at the post-deposit total, misrepresenting how much capital was
    actually at risk before that date -- the same distortion
    ``kala.twr`` exists to correct for the return NUMBER, applied
    here to the curve's SHAPE.
    """
    capital_additions = capital_additions or []
    original_capital = start_capital - sum(d.get("amount", 0.0) for d in capital_additions)

    events = [
        {"date": str(t.get("date", "")),
         "amount": (t.get("exit", 0.0) - t.get("entry", 0.0)) * t.get("shares", 0)}
        for t in log
    ] + [
        {"date": str(d.get("date", "")), "amount": float(d.get("amount", 0.0))}
        for d in capital_additions
    ]
    events.sort(key=lambda e: e["date"])

    points: list[tuple[str, float]] = [("start", original_capital)]
    running = original_capital
    for e in events:
        running += e["amount"]
        points.append((e["date"], running))
    return points


def _lot_shares(pos) -> float:
    """shares off a PaperPosition OR a raw state dict -- callers pass either
    (generate_dashboard has objects, a JSON reader has dicts)."""
    if isinstance(pos, dict):
        return float(pos.get("shares") or 0.0)
    return float(getattr(pos, "shares", 0) or 0.0)


def _lot_attr(pos, name: str, default=None):
    if isinstance(pos, dict):
        return pos.get(name, default)
    return getattr(pos, name, default)


def held_lots(log: list[dict], positions: dict) -> list[dict]:
    """Every position ever opened, as independent LOTS.

    Lot-level (not per-ticker) accounting is required, not fussiness: this
    project's own state contains a same-day re-entry -- SRTG sold 1,400 sh
    on 2026-07-24 (bought 07-17) and 1,000 fresh shares bought 07-24 -- so a
    ticker can be simultaneously present in the closed log and the open book
    with different cost bases. Collapsing by ticker would double-count the
    overlap or lose one leg entirely. Partial sells produce the same shape.

    Returns dicts with ``exit_date=None`` for still-open lots.
    """
    lots: list[dict] = []
    for t in log or []:
        ticker = str(t.get("ticker") or "")
        shares = float(t.get("shares") or 0.0)
        entry_date = str(t.get("entry_date") or t.get("date") or "")
        if not ticker or shares <= 0 or not entry_date:
            continue
        lots.append({
            "ticker": ticker, "shares": shares, "entry_date": entry_date,
            "exit_date": str(t.get("date") or "") or None,
            "entry_price": float(t.get("entry") or 0.0),
            "exit_price": float(t.get("exit") or 0.0),
        })
    from .papertrade import position_fills
    for ticker, p in (positions or {}).items():
        if _lot_shares(p) <= 0:
            continue
        # One lot PER FILL, so shares bought later are only valued from the
        # day they were actually bought. A position that was added to used to
        # be valued in full from its FIRST purchase date, overstating early
        # equity. position_fills() collapses to the old single-lot view for
        # positions recorded before the ledger existed, so legacy state
        # behaves exactly as before rather than breaking.
        for f in position_fills(p):
            if f["shares"] <= 0 or not f["date"]:
                continue
            lots.append({
                "ticker": str(ticker), "shares": f["shares"],
                "entry_date": f["date"], "exit_date": None,
                "entry_price": f["price"], "exit_price": 0.0,
            })
    return lots


def mark_to_market_points(log: list[dict], positions: dict,
                          price_histories: dict, start_capital: float,
                          capital_additions: list[dict] | None = None,
                          dividends: list[dict] | None = None,
                          today: str | None = None) -> tuple[list, list[str]]:
    """Daily TOTAL equity (cash + market value of open positions), rebuilt
    day by day from the trade log and historical closes.

    WHY THIS IS RECONSTRUCTED RATHER THAN READ
    -------------------------------------------
    Nothing in this project stores a daily equity snapshot -- ``papertrade``
    tracks only CURRENT cash/positions. ``equity_curve_points`` sidesteps
    that by plotting realized P&L, which needs no prices but only moves when
    a trade CLOSES: a book that bought seven names today and sold nothing
    shows a flat line, which is what prompted this function. Here the whole
    series is rebuilt instead, so the curve moves with the market every day
    a position is held.

    ``price_histories``: ``{ticker: Close Series}`` covering the period.
    Needed for CLOSED tickers too, not just currently-held ones -- a closed
    lot still has to be valued on the days it was held. Missing history is
    handled (see below) rather than silently producing a hole.

    Returns ``(points, warnings)``. ``points`` is ``[(iso_date, equity)]``,
    the same shape ``equity_curve_points`` returns so both feed the same
    renderer. ``warnings`` names any ticker valued at a fallback price, so
    a degraded curve announces itself instead of looking authoritative.

    HONEST LIMITATION -- AVERAGED-IN POSITIONS
    -------------------------------------------
    ``manual_buy`` on an already-held ticker blends the cost basis and keeps
    the ORIGINAL ``entry_date`` (see its docstring). The state therefore does
    not record WHEN the added shares arrived, so this function values the
    full blended lot from the first purchase date onward. For a position
    that was added to later, early-period equity is overstated by the
    not-yet-purchased shares. Nothing here can fix that without a per-fill
    ledger; it is stated rather than hidden.
    """
    import pandas as pd

    capital_additions = capital_additions or []
    dividends = dividends or []
    original_capital = start_capital - sum(d.get("amount", 0.0) for d in capital_additions)
    lots = held_lots(log, positions)

    if not lots and not capital_additions:
        return [], []

    # --- the day axis: union of every ticker's trading days -----------------
    index = None
    for s in (price_histories or {}).values():
        if s is None or not len(s):
            continue
        idx = pd.DatetimeIndex(s.index).normalize()
        index = idx if index is None else index.union(idx)
    if index is None or not len(index):
        return [], ["no price history at all -- cannot mark to market"]

    first_activity = min([lot["entry_date"] for lot in lots]
                         + [str(d.get("date", "")) for d in capital_additions if d.get("date")]
                         or [""])
    if first_activity:
        index = index[index >= pd.Timestamp(first_activity)]
    if today:
        index = index[index <= pd.Timestamp(today)]
    if not len(index):
        return [], []

    # --- prices: align every ticker onto the day axis, carry last close ----
    # ffill is the honest handling of a non-trading day or a suspension: the
    # position is still worth its last traded price, not zero and not NaN.
    warnings: list[str] = []
    aligned: dict[str, "pd.Series"] = {}
    for lot in lots:
        t = lot["ticker"]
        if t in aligned:
            continue
        s = (price_histories or {}).get(t)
        if s is None or not len(s):
            continue
        s = pd.Series(s.values, index=pd.DatetimeIndex(s.index).normalize())
        s = s[~s.index.duplicated(keep="last")]
        aligned[t] = s.reindex(index).ffill()

    # --- cash: exact for a manual book -------------------------------------
    # Replaying entry_price*shares and exit_price*shares reproduces the stored
    # cash balance exactly. This holds whether or not manual fills charge
    # costs: since v3.9 manual_buy debits the COST-INCLUSIVE fill and stores
    # that same figure as entry_price (manual_sell likewise credits and stores
    # the net proceeds), so the recorded price is always the amount that
    # actually moved. Do NOT add a cost adjustment here — it would be charged
    # twice.
    def _on_or_before(d, iso):
        return str(d.get("date", "")) and str(d.get("date", "")) <= iso

    points: list[tuple[str, float]] = []
    missing: set[str] = set()

    for ts in index:
        iso = ts.strftime("%Y-%m-%d")
        cash = original_capital
        cash += sum(float(d.get("amount", 0.0)) for d in capital_additions if _on_or_before(d, iso))
        cash += sum(float(d.get("amount", 0.0)) for d in dividends if _on_or_before(d, iso))

        holdings = 0.0
        for lot in lots:
            if lot["entry_date"] > iso:
                continue                      # not bought yet
            cash -= lot["entry_price"] * lot["shares"]
            if lot["exit_date"] is not None and lot["exit_date"] <= iso:
                cash += lot["exit_price"] * lot["shares"]
                continue                      # already sold -> no market value
            s = aligned.get(lot["ticker"])
            px = None
            if s is not None:
                v = s.get(ts)
                if v is not None and pd.notna(v):
                    px = float(v)
            if px is None:
                # No usable close (ticker never fetched, or the day precedes
                # its history). Hold it at cost: wrong, but bounded and
                # reported -- dropping it would silently shrink equity.
                px = lot["entry_price"]
                missing.add(lot["ticker"])
            holdings += px * lot["shares"]

        points.append((iso, cash + holdings))

    if missing:
        warnings.append("valued at cost (no price history): " + ", ".join(sorted(missing)))
    return points, warnings


def render_equity_curve_png(points: list[tuple[str, float]], width: int = 640,
                            height: int = 360, margin: int = 24) -> bytes | None:
    """A single-line equity chart, colored green if the curve ends at/above
    its starting value and red otherwise. Returns None if there aren't
    enough points to draw a line (nothing meaningful to chart)."""
    if len(points) < 2:
        return None

    values = [v for _, v in points]
    lo, hi = min(values), max(values)
    if lo == hi:
        lo, hi = lo - 1, hi + 1   # avoid a zero-height division on a flat curve

    pixels = bytearray(BACKGROUND * (width * height))

    plot_w = width - 2 * margin
    plot_h = height - 2 * margin

    # gridlines: baseline (start value) + top/bottom border
    def y_for(v: float) -> int:
        frac = (v - lo) / (hi - lo)
        return int(margin + plot_h - frac * plot_h)

    baseline_y = y_for(values[0])
    for x in range(margin, width - margin):
        _set_px(pixels, width, height, x, baseline_y, GRID)
    for y in (margin, height - margin):
        for x in range(margin, width - margin):
            _set_px(pixels, width, height, x, y, AXIS)

    n = len(points)
    color = GREEN if values[-1] >= values[0] else RED
    xs = [margin + int(i / (n - 1) * plot_w) for i in range(n)]
    ys = [y_for(v) for v in values]
    for i in range(n - 1):
        _draw_line(pixels, width, height, xs[i], ys[i], xs[i + 1], ys[i + 1], color, thickness=2)

    return encode_png(width, height, pixels)
