"""
Natural-language-ish log query tests: this is a keyword/pattern parser
(NOT real NLU -- see log_query.py's module docstring), tested against the
fixed vocabulary it actually recognizes.
"""

from datetime import date

from kala.log_query import LogQuery, answer, filter_trades, parse_query, summarize


def _log():
    return [
        {"date": "2026-06-01", "ticker": "BBCA.JK", "pnl_pct": 5.0, "reason": "target"},
        {"date": "2026-06-15", "ticker": "BBCA.JK", "pnl_pct": -3.0, "reason": "stop"},
        {"date": "2026-07-01", "ticker": "TLKM.JK", "pnl_pct": 8.0, "reason": "target"},
        {"date": "2026-07-10", "ticker": "TLKM.JK", "pnl_pct": -6.0, "reason": "stop"},
        {"date": "2026-07-15", "ticker": "ASII.JK", "pnl_pct": 1.5, "reason": "trailing"},
    ]


TODAY = date(2026, 7, 20)


# ---------------- parse_query --------------------------------------------------

def test_parse_extracts_ticker():
    q = parse_query("how did BBCA do", today=TODAY)
    assert q.ticker == "BBCA"


def test_parse_ticker_with_jk_suffix():
    q = parse_query("show me TLKM.JK trades", today=TODAY)
    assert q.ticker == "TLKM"


def test_parse_no_ticker_when_none_present():
    q = parse_query("how did I do this month", today=TODAY)
    assert q.ticker is None


def test_parse_outcome_loss():
    q = parse_query("show my losses", today=TODAY)
    assert q.outcome == "loss"


def test_parse_outcome_win():
    q = parse_query("show my winning trades", today=TODAY)
    assert q.outcome == "win"


def test_parse_last_n_days():
    q = parse_query("what happened in the last 14 days", today=TODAY)
    assert q.since == "2026-07-06"


def test_parse_this_month():
    q = parse_query("how did I do this month", today=TODAY)
    assert q.since == "2026-07-01"


def test_parse_last_month():
    q = parse_query("show trades from last month", today=TODAY)
    assert q.since == "2026-06-01"
    assert q.until == "2026-06-30"


def test_parse_today():
    q = parse_query("what did I trade today", today=TODAY)
    assert q.since == q.until == "2026-07-20"


def test_parse_best_n():
    q = parse_query("show me my best 2 trades", today=TODAY)
    assert q.sort == "best"
    assert q.limit == 2


def test_parse_worst_single():
    q = parse_query("what was my worst trade", today=TODAY)
    assert q.sort == "worst"
    assert q.limit == 1


def test_parse_defaults_to_recent_sort():
    q = parse_query("how did I do", today=TODAY)
    assert q.sort == "recent"
    assert q.limit is None


# ---------------- filter_trades ------------------------------------------------

def test_filter_by_ticker():
    matches = filter_trades(_log(), LogQuery(ticker="BBCA"))
    assert all(t["ticker"] == "BBCA.JK" for t in matches)
    assert len(matches) == 2


def test_filter_by_outcome_win():
    matches = filter_trades(_log(), LogQuery(outcome="win"))
    assert all(t["pnl_pct"] > 0 for t in matches)
    assert len(matches) == 3


def test_filter_by_outcome_loss():
    matches = filter_trades(_log(), LogQuery(outcome="loss"))
    assert all(t["pnl_pct"] <= 0 for t in matches)
    assert len(matches) == 2


def test_filter_by_date_range():
    matches = filter_trades(_log(), LogQuery(since="2026-07-01", until="2026-07-10"))
    assert {t["date"] for t in matches} == {"2026-07-01", "2026-07-10"}


def test_filter_sort_best():
    matches = filter_trades(_log(), LogQuery(sort="best", limit=1))
    assert matches[0]["pnl_pct"] == 8.0


def test_filter_sort_worst():
    matches = filter_trades(_log(), LogQuery(sort="worst", limit=1))
    assert matches[0]["pnl_pct"] == -6.0


def test_filter_sort_recent_is_default_ordering():
    matches = filter_trades(_log(), LogQuery())
    dates = [t["date"] for t in matches]
    assert dates == sorted(dates, reverse=True)


# ---------------- summarize -----------------------------------------------------

def test_summarize_empty():
    stats = summarize([])
    assert stats["n"] == 0
    assert stats["win_rate_pct"] == 0.0


def test_summarize_computes_win_rate_and_avg():
    stats = summarize(_log())
    assert stats["n"] == 5
    assert stats["n_wins"] == 3
    assert stats["win_rate_pct"] == 60.0
    assert stats["best"]["ticker"] == "TLKM.JK"
    assert stats["worst"]["ticker"] == "TLKM.JK"


# ---------------- answer (end-to-end) -------------------------------------------

def test_answer_no_matches():
    text = answer("how did BUMI do", _log(), today=TODAY)
    assert "No matching trades" in text


def test_answer_ticker_summary():
    text = answer("how did BBCA do", _log(), today=TODAY)
    assert "2 trade(s)" in text
    assert "50%" in text  # 1 win of 2 -> 50% win rate


def test_answer_best_n_lists_trades_not_summary():
    text = answer("show me my best 2 trades", _log(), today=TODAY)
    lines = text.splitlines()
    assert len(lines) == 2
    assert "TLKM" in lines[0]


def test_answer_worst_trade():
    text = answer("what was my worst trade", _log(), today=TODAY)
    assert "TLKM" in text
    assert "-6.0%" in text
