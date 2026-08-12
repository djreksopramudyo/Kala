"""
Tax-reporting SKELETON — a raw transaction export, deliberately NOT a tax
calculator.

READ THIS BEFORE USING ANYTHING IN THIS MODULE
------------------------------------------------
This module does NOT compute tax owed, does NOT apply Indonesian capital-
gains or final-tax rules, and is NOT tax advice. It exists to do exactly
one thing: format your closed-trade log into a plain, chronological
transaction list you (or a licensed Indonesian tax professional / your
broker) can use as a starting point. Nothing here should be treated as a
completed tax filing input.

Why so little logic, on purpose:
  * Indonesian securities tax treatment (PPh final on transactions, capital
    gains treatment, any personal-income-tax interaction) is a specialized
    legal area this project's author is not qualified to encode into
    software, and shipping a plausible-looking wrong number here is worse
    than shipping nothing — someone could file on it.
  * ``PaperTrader.log`` entries (see papertrade.py) store COST-INCLUSIVE
    fill prices (commission + spread + the 0.10% PPh final transaction tax
    already blended into ``entry``/``exit``), not gross price vs. fees
    broken out separately. That is the right model for trading P&L, but it
    is NOT the same shape a tax filing needs, and this module does not
    attempt to reverse-engineer the split.
  * This bot is a PAPER-trading system (see PROJECT_STATUS.md — no
    validated live edge). If you ever trade for real, your broker's
    official annual transaction statement is the authoritative source for
    any real filing, not this bot's records.

If you need this to be genuinely useful for a real filing, the honest next
step is a conversation with an accountant/tax preparer licensed in
Indonesia, not a bigger version of this module.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass

TAX_DISCLAIMER = (
    "NOT TAX ADVICE. This is a raw transaction export from PAPER-TRADING "
    "records, not a tax calculation -- it does not apply any Indonesian "
    "tax rule. If you trade for real, use your broker's official annual "
    "statement for filing; consult a licensed Indonesian tax professional "
    "for anything beyond organizing records."
)


@dataclass(frozen=True)
class TransactionRow:
    exit_date: str
    ticker: str
    shares: float
    entry_price: float     # cost-inclusive fill (see module docstring)
    exit_price: float      # cost-inclusive fill
    proceeds: float        # exit_price * shares
    cost_basis: float      # entry_price * shares
    realized_pnl: float    # proceeds - cost_basis


def build_transaction_report(log: list[dict], year: int | None = None) -> list[TransactionRow]:
    """Every closed trade, optionally filtered to those that EXITED in
    ``year``, sorted chronologically by exit date. ``year`` filters on the
    trade's exit date (when the gain/loss was realized), not entry date --
    the conventional basis for "which tax year does this belong to", though
    whether that convention is even the right one for your situation is
    exactly the kind of question a real tax professional answers, not this
    function."""
    rows = []
    for t in log:
        date_str = str(t.get("date", ""))
        if year is not None:
            try:
                if int(date_str[:4]) != year:
                    continue
            except ValueError:
                continue
        shares = t.get("shares", 0.0)
        entry = t.get("entry", 0.0)
        exit_ = t.get("exit", 0.0)
        rows.append(TransactionRow(
            exit_date=date_str, ticker=t.get("ticker", ""), shares=shares,
            entry_price=entry, exit_price=exit_,
            proceeds=exit_ * shares, cost_basis=entry * shares,
            realized_pnl=(exit_ - entry) * shares,
        ))
    rows.sort(key=lambda r: r.exit_date)
    return rows


def report_to_csv_text(rows: list[TransactionRow]) -> str:
    """CSV text (disclaimer as a leading comment line) — hand this to
    whoever is organizing your records, not to a filing directly."""
    buf = io.StringIO()
    buf.write(f"# {TAX_DISCLAIMER}\n")
    writer = csv.writer(buf)
    writer.writerow(["exit_date", "ticker", "shares", "entry_price", "exit_price",
                     "proceeds", "cost_basis", "realized_pnl"])
    for r in rows:
        writer.writerow([r.exit_date, r.ticker, r.shares, r.entry_price, r.exit_price,
                         r.proceeds, r.cost_basis, r.realized_pnl])
    return buf.getvalue()


def summary_text(rows: list[TransactionRow], year: int | None = None) -> str:
    """Short human-readable total, for a Telegram reply -- count and net
    realized P&L only, with the disclaimer attached every time this is
    shown, not just once at the top of a file that might get separated
    from it."""
    label = f" for {year}" if year is not None else ""
    if not rows:
        return f"{TAX_DISCLAIMER}\n\nNo closed trades{label}."
    total_pnl = sum(r.realized_pnl for r in rows)
    total_proceeds = sum(r.proceeds for r in rows)
    return (f"{TAX_DISCLAIMER}\n\n"
           f"{len(rows)} closed transaction(s){label}: "
           f"total proceeds {total_proceeds:,.0f}, "
           f"total realized P&L {total_pnl:+,.0f}")
