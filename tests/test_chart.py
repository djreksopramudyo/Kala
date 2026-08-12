"""
Dependency-free PNG encoder + equity-curve renderer tests. Since no image
library (PIL/matplotlib) is available in this environment, decoding for
verification is done with a small hand-rolled PNG parser (the exact
inverse of chart.py's encoder) rather than trusting an external tool.
"""

import struct
import zlib

from kala.chart import encode_png, equity_curve_points, render_equity_curve_png


def _decode_png(data: bytes):
    """Minimal PNG decoder for OUR encoder's specific subset (8-bit RGB,
    filter type 0 only, single IDAT). Returns (width, height, pixels)."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    pos = 8
    idat = b""
    width = height = None
    while pos < len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        ctype = data[pos + 4:pos + 8]
        cdata = data[pos + 8:pos + 8 + length]
        if ctype == b"IHDR":
            width, height, bitdepth, colortype, *_ = struct.unpack(">IIBBBBB", cdata)
            assert bitdepth == 8 and colortype == 2
        elif ctype == b"IDAT":
            idat += cdata
        pos += 8 + length + 4   # length + type + data + crc
    raw = zlib.decompress(idat)
    stride = width * 3
    pixels = bytearray(width * height * 3)
    for y in range(height):
        row_start = y * (stride + 1)
        filt = raw[row_start]
        assert filt == 0, "only filter type 0 supported by this test decoder"
        pixels[y * stride:(y + 1) * stride] = raw[row_start + 1:row_start + 1 + stride]
    return width, height, pixels


# ---------------- encode_png ---------------------------------------------------

def test_encode_png_has_valid_signature():
    pixels = bytearray([255, 0, 0] * (4 * 4))
    png = encode_png(4, 4, pixels)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_encode_png_round_trips_pixel_data():
    w, h = 5, 3
    pixels = bytearray()
    for y in range(h):
        for x in range(w):
            pixels.extend([x * 10 % 256, y * 20 % 256, 128])
    png = encode_png(w, h, pixels)
    dw, dh, decoded = _decode_png(png)
    assert (dw, dh) == (w, h)
    assert decoded == pixels


def test_encode_png_solid_color():
    w, h = 10, 10
    pixels = bytearray([1, 2, 3] * (w * h))
    png = encode_png(w, h, pixels)
    dw, dh, decoded = _decode_png(png)
    assert decoded == pixels


# ---------------- equity_curve_points -------------------------------------------

def test_equity_curve_points_starts_at_start_capital():
    points = equity_curve_points([], start_capital=10_000_000.0)
    assert points == [("start", 10_000_000.0)]


def test_equity_curve_points_accumulates_realized_pnl():
    log = [
        {"date": "2026-06-01", "entry": 1000.0, "exit": 1100.0, "shares": 100},   # +10,000
        {"date": "2026-06-15", "entry": 500.0, "exit": 450.0, "shares": 200},     # -10,000
    ]
    points = equity_curve_points(log, start_capital=10_000_000.0)
    assert points[0] == ("start", 10_000_000.0)
    assert points[1] == ("2026-06-01", 10_010_000.0)
    assert points[2] == ("2026-06-15", 10_000_000.0)


def test_equity_curve_points_no_capital_additions_is_unchanged():
    """Backward compatibility: omitting capital_additions must behave
    exactly as before the deposit-aware fix."""
    log = [{"date": "2026-06-01", "entry": 1000.0, "exit": 1100.0, "shares": 100}]
    assert (equity_curve_points(log, start_capital=10_000_000.0)
           == equity_curve_points(log, start_capital=10_000_000.0, capital_additions=[]))


def test_equity_curve_points_starts_at_original_capital_not_deposit_inflated():
    """The bug this fixes: start_capital passed in is ALREADY deposit-
    inflated (PaperTrader.add_capital bumps it), so the curve must
    subtract the deposit back out to find where the account actually
    began."""
    points = equity_curve_points(
        [], start_capital=15_000_000.0,   # 10M original + 5M deposit
        capital_additions=[{"date": "2026-06-10", "amount": 5_000_000.0}])
    assert points[0] == ("start", 10_000_000.0)


def test_equity_curve_points_places_deposit_at_its_own_date_not_day_one():
    # start_capital = original (10M) + deposit (5M) -- PaperTrader.start_capital
    # only ever moves for deposits, never for trade P&L.
    log = [{"date": "2026-06-01", "entry": 1000.0, "exit": 1100.0, "shares": 100}]  # +10,000, before deposit
    points = equity_curve_points(
        log, start_capital=15_000_000.0,
        capital_additions=[{"date": "2026-06-10", "amount": 5_000_000.0}])
    assert points[0] == ("start", 10_000_000.0)
    assert points[1] == ("2026-06-01", 10_010_000.0)     # trade P&L applied first
    assert points[2] == ("2026-06-10", 15_010_000.0)     # deposit lands on its own date


def test_equity_curve_points_deposit_after_a_later_trade_still_orders_correctly():
    log = [{"date": "2026-07-01", "entry": 1000.0, "exit": 900.0, "shares": 100}]   # -10,000, AFTER deposit
    points = equity_curve_points(
        log, start_capital=15_000_000.0,
        capital_additions=[{"date": "2026-06-10", "amount": 5_000_000.0}])
    dates = [d for d, _ in points]
    assert dates == ["start", "2026-06-10", "2026-07-01"]
    assert points[-1] == ("2026-07-01", 14_990_000.0)


def test_equity_curve_points_sorts_by_date_regardless_of_log_order():
    log = [
        {"date": "2026-06-15", "entry": 500.0, "exit": 450.0, "shares": 200},
        {"date": "2026-06-01", "entry": 1000.0, "exit": 1100.0, "shares": 100},
    ]
    points = equity_curve_points(log, start_capital=10_000_000.0)
    dates = [d for d, _ in points]
    assert dates == ["start", "2026-06-01", "2026-06-15"]


# ---------------- render_equity_curve_png ---------------------------------------

def test_render_returns_none_for_too_few_points():
    assert render_equity_curve_png([("start", 100.0)]) is None
    assert render_equity_curve_png([]) is None


def test_render_produces_valid_png():
    points = [("start", 100.0), ("d1", 110.0), ("d2", 95.0), ("d3", 130.0)]
    png = render_equity_curve_png(points, width=200, height=100)
    assert png is not None
    w, h, pixels = _decode_png(png)
    assert (w, h) == (200, 100)


def test_render_handles_flat_curve_without_crashing():
    points = [("start", 100.0), ("d1", 100.0), ("d2", 100.0)]
    png = render_equity_curve_png(points, width=100, height=60)
    assert png is not None
    w, h, _ = _decode_png(png)
    assert (w, h) == (100, 60)


def test_render_line_present_somewhere_in_image():
    """Not a pixel-perfect check (that's what the encode/decode tests are
    for) -- just proves SOMETHING other than pure background got drawn."""
    from kala.chart import BACKGROUND
    points = [("start", 100.0), ("d1", 200.0), ("d2", 150.0)]
    png = render_equity_curve_png(points, width=100, height=60)
    _, _, pixels = _decode_png(png)
    non_background = any(
        tuple(pixels[i:i + 3]) != BACKGROUND for i in range(0, len(pixels), 3))
    assert non_background
