"""
Tax-reporting skeleton tests: this is a raw transaction FORMATTER, not a
tax calculator (see tax_report.py's module docstring) -- tests only check
the export mechanics and that the disclaimer is never dropped, not that
any number here is tax-correct (there is no such claim to test).
"""

from kala.tax_report import (
    TAX_DISCLAIMER,
    TransactionRow,
    build_transaction_report,
    report_to_csv_text,
    summary_text,
)


def _log():
    return [
        {"date": "2025-12-20", "ticker": "ANTM.JK", "entry": 1000.0, "exit": 1100.0, "shares": 100},
        {"date": "2026-01-15", "ticker": "TLKM.JK", "entry": 3000.0, "exit": 2800.0, "shares": 50},
        {"date": "2026-06-01", "ticker": "BBRI.JK", "entry": 4000.0, "exit": 4400.0, "shares": 200},
    ]


# ---------------- build_transaction_report --------------------------------------

def test_build_report_includes_all_trades_when_no_year_filter():
    rows = build_transaction_report(_log())
    assert len(rows) == 3
    assert all(isinstance(r, TransactionRow) for r in rows)


def test_build_report_filters_by_exit_year():
    rows = build_transaction_report(_log(), year=2026)
    assert {r.ticker for r in rows} == {"TLKM.JK", "BBRI.JK"}


def test_build_report_sorted_chronologically():
    rows = build_transaction_report(_log())
    dates = [r.exit_date for r in rows]
    assert dates == sorted(dates)


def test_build_report_computes_proceeds_and_pnl():
    rows = build_transaction_report(_log(), year=2025)
    r = rows[0]
    assert r.proceeds == 1100.0 * 100
    assert r.cost_basis == 1000.0 * 100
    assert r.realized_pnl == 10_000.0


def test_build_report_ignores_malformed_dates():
    log = [{"date": "not-a-date", "ticker": "X.JK", "entry": 1.0, "exit": 1.0, "shares": 1}]
    rows = build_transaction_report(log, year=2026)
    assert rows == []


def test_build_report_empty_log():
    assert build_transaction_report([]) == []


# ---------------- report_to_csv_text ---------------------------------------------

def test_csv_text_includes_disclaimer_as_comment():
    rows = build_transaction_report(_log())
    csv_text = report_to_csv_text(rows)
    assert csv_text.startswith("# NOT TAX ADVICE")


def test_csv_text_has_header_and_all_rows():
    rows = build_transaction_report(_log())
    csv_text = report_to_csv_text(rows)
    lines = csv_text.strip().splitlines()
    assert "exit_date" in lines[1]
    assert len(lines) == 2 + len(rows)   # disclaimer + header + one per row


def test_csv_text_empty_report_still_has_header():
    csv_text = report_to_csv_text([])
    assert "exit_date" in csv_text


# ---------------- summary_text ---------------------------------------------------

def test_summary_text_always_includes_disclaimer():
    assert TAX_DISCLAIMER in summary_text([])
    rows = build_transaction_report(_log())
    assert TAX_DISCLAIMER in summary_text(rows)


def test_summary_text_no_trades():
    text = summary_text([], year=2027)
    assert "No closed trades" in text
    assert "2027" in text


def test_summary_text_totals_are_correct():
    rows = build_transaction_report(_log())
    text = summary_text(rows)
    expected_total = sum(r.realized_pnl for r in rows)
    assert f"{expected_total:+,.0f}" in text
    assert "3 closed transaction(s)" in text
