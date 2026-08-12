"""
Local HTML dashboard tests: render_dashboard_html is pure (no I/O, no
network) -- given plain dicts/positions, it must produce valid,
self-contained HTML (tabs + an interactive inline SVG chart, still zero
EXTERNAL references) and escape any untrusted-looking ticker/reason text.
"""

from kala.dashboard import render_dashboard_html
from kala.papertrade import PaperPosition
from kala.portfolio_analytics import PortfolioAnalysis, allocation_drift
from kala.twr import compute_time_weighted_return


def _summary(**overrides):
    base = {"equity": 11_000_000.0, "cash": 5_000_000.0, "return_pct": 10.0,
           "open_positions": 1, "closed_trades": 2, "win_rate_pct": 50.0}
    base.update(overrides)
    return base


def _recent(**overrides):
    base = {"window_days": 7, "n": 1, "wins": 1, "losses": 0, "win_rate_pct": 100.0,
           "net_profit_idr": 50_000.0,
           "trades": [{"ticker": "ANTM.JK", "pnl_pct": 5.0, "profit_idr": 50_000.0,
                       "reason": "target"}]}
    base.update(overrides)
    return base


def _positions():
    return {"ANTM.JK": PaperPosition(ticker="ANTM.JK", entry_price=1000.0, shares=100,
                                     entry_date="2026-07-01", peak_price=1050.0)}


def _log():
    return [{"date": "2026-07-10", "ticker": "ANTM.JK", "entry": 1000.0, "exit": 1050.0,
            "pnl_pct": 5.0, "shares": 100, "reason": "target"}]


def test_render_produces_valid_html_shell():
    out = render_dashboard_html(_summary(), _recent(), _positions(), _log(), "2026-07-21 10:00")
    assert out.strip().startswith("<!doctype html>")
    assert "</html>" in out


def test_render_has_no_external_references():
    """Inline <script> (tabs/chart interactivity) is expected and fine --
    what must NEVER appear is a network reference: no http(s) URLs, no
    <script src=...> pulling in an external file."""
    out = render_dashboard_html(_summary(), _recent(), _positions(), _log(), "2026-07-21 10:00")
    assert "http://" not in out
    assert "https://" not in out
    assert "<script src=" not in out
    assert "<script>" in out   # the inline tab/chart script IS expected


def test_render_shows_equity_and_return():
    out = render_dashboard_html(_summary(), _recent(), _positions(), _log(), "2026-07-21 10:00")
    assert "11,000,000" in out
    assert "+10.00%" in out


def test_render_shows_alpha_when_present():
    out = render_dashboard_html(_summary(alpha_pct=3.5), _recent(), _positions(), _log(),
                                "2026-07-21 10:00")
    assert "+3.50%" in out
    assert "vs IHSG" in out


def test_render_omits_alpha_when_absent():
    out = render_dashboard_html(_summary(), _recent(), _positions(), _log(), "2026-07-21 10:00")
    assert "vs IHSG" not in out


def test_render_shows_open_positions():
    out = render_dashboard_html(_summary(), _recent(), _positions(), _log(), "2026-07-21 10:00")
    assert "ANTM.JK" in out
    assert "2026-07-01" in out


def test_render_handles_no_positions():
    out = render_dashboard_html(_summary(open_positions=0), _recent(), {}, _log(),
                                "2026-07-21 10:00")
    assert "No open positions" in out


def test_render_handles_empty_log():
    out = render_dashboard_html(_summary(closed_trades=0), _recent(n=0, trades=[]),
                                _positions(), [], "2026-07-21 10:00")
    assert "No closed trades yet" in out


def test_render_respects_max_log_rows():
    log = [{"date": f"2026-07-{i:02d}", "ticker": "A.JK", "entry": 1000.0, "exit": 1010.0,
           "pnl_pct": 1.0, "shares": 100, "reason": "target"} for i in range(1, 21)]
    out = render_dashboard_html(_summary(), _recent(), {}, log, "2026-07-21 10:00", max_log_rows=5)
    assert out.count('<span class="pos">+1.0%</span>') == 5


def test_render_escapes_untrusted_looking_text():
    positions = {"<script>alert(1)</script>": PaperPosition(
        ticker="X", entry_price=1.0, shares=1, entry_date="2026-01-01", peak_price=1.0)}
    out = render_dashboard_html(_summary(), _recent(), positions, [], "2026-07-21 10:00")
    assert "<script>alert(1)</script>" not in out
    assert "&lt;script&gt;" in out


# ---------------- tabs / interactivity chrome ------------------------------------

def test_render_has_all_four_tabs():
    out = render_dashboard_html(_summary(), _recent(), _positions(), _log(), "2026-07-21 10:00")
    for tab in ("overview", "performance", "portfolio", "history"):
        assert f'data-tab="{tab}"' in out
        assert f'id="tab-{tab}"' in out


def test_render_overview_tab_is_active_by_default():
    out = render_dashboard_html(_summary(), _recent(), _positions(), _log(), "2026-07-21 10:00")
    assert 'class="tab-btn active" data-tab="overview"' in out
    assert 'class="tab-panel active" id="tab-overview"' in out


def test_render_has_privacy_toggle():
    out = render_dashboard_html(_summary(), _recent(), _positions(), _log(), "2026-07-21 10:00")
    assert 'id="privacy-toggle"' in out
    assert "Hide numbers" in out


def test_render_headline_stats_are_maskable():
    out = render_dashboard_html(_summary(), _recent(), _positions(), _log(), "2026-07-21 10:00")
    assert 'class="value mask"' in out or 'class="value mask ' in out


def test_render_history_tab_holds_the_trade_log():
    out = render_dashboard_html(_summary(), _recent(), _positions(), _log(), "2026-07-21 10:00")
    history_start = out.index('id="tab-history"')
    assert "Trade Log" in out[history_start:]


# ---------------- position_comparisons (vs IHSG) --------------------------------

def _comparisons():
    return [
        {"ticker": "ANTM.JK", "shares": 100, "entry_price": 1000.0, "entry_date": "2026-07-01",
         "current_price": 1100.0, "return_pct": 10.0, "benchmark_return_pct": 3.0, "alpha_pct": 7.0},
        {"ticker": "BBRI.JK", "shares": 50, "entry_price": 4000.0, "entry_date": "2026-06-15",
         "current_price": 3800.0, "return_pct": -5.0, "benchmark_return_pct": 2.0, "alpha_pct": -7.0},
    ]


def test_render_shows_vs_ihsg_table_when_comparisons_given():
    out = render_dashboard_html(_summary(), _recent(), _positions(), _log(), "2026-07-21 10:00",
                                position_comparisons=_comparisons())
    assert "Open Positions vs IHSG" in out
    assert "IHSG (same window)" in out
    assert "+10.00%" in out or "+10.0%" in out
    assert "+7.00%" in out or "+7.0%" in out


def test_render_vs_ihsg_handles_missing_fields_gracefully():
    comparisons = [{"ticker": "X.JK", "shares": None, "entry_price": None, "entry_date": None,
                    "current_price": None, "return_pct": None, "benchmark_return_pct": None,
                    "alpha_pct": None}]
    out = render_dashboard_html(_summary(), _recent(), {}, [], "2026-07-21 10:00",
                                position_comparisons=comparisons)
    assert "n/a" in out


def test_render_falls_back_to_plain_position_table_without_comparisons():
    out = render_dashboard_html(_summary(), _recent(), _positions(), _log(), "2026-07-21 10:00")
    assert "Open Positions vs IHSG" not in out
    assert "<h2>Open Positions</h2>" in out


# ---------------- interactive equity chart (inline SVG) --------------------------

def test_render_embeds_interactive_svg_chart_when_given():
    points = [("start", 100.0), ("d1", 110.0), ("d2", 90.0)]
    out = render_dashboard_html(_summary(), _recent(), _positions(), _log(), "2026-07-21 10:00",
                                equity_points=points)
    assert "<svg" in out
    assert 'id="equity-chart-wrap"' in out
    assert "Equity Curve" in out
    assert "Hover the chart" in out


def test_render_omits_chart_section_when_no_points():
    out = render_dashboard_html(_summary(), _recent(), _positions(), _log(), "2026-07-21 10:00")
    assert "<svg" not in out
    assert "Equity Curve" not in out


def test_render_omits_chart_with_only_one_point():
    out = render_dashboard_html(_summary(), _recent(), _positions(), _log(), "2026-07-21 10:00",
                                equity_points=[("start", 100.0)])
    assert "<svg" not in out


def test_render_chart_points_embedded_as_escaped_json():
    points = [("start", 100.0), ("2026-07-01", 105.5)]
    out = render_dashboard_html(_summary(), _recent(), _positions(), _log(), "2026-07-21 10:00",
                                equity_points=points)
    assert "data-points=" in out
    assert "2026-07-01" in out


# ---------------- equity chart date-range filter ----------------------------------

def test_render_shows_range_filter_buttons_when_chart_present():
    points = [("start", 100.0), ("2026-07-01", 110.0), ("2026-07-15", 90.0)]
    out = render_dashboard_html(_summary(), _recent(), _positions(), _log(), "2026-07-21 10:00",
                                equity_points=points)
    assert 'id="equity-range-filter"' in out
    for key in ('data-range="7"', 'data-range="30"', 'data-range="ytd"',
               'data-range="365"', 'data-range="all"', 'data-range="custom"'):
        assert key in out
    assert '<input type="date" id="range-start"' in out
    assert '<input type="date" id="range-end"' in out
    assert 'class="range-btn active" data-range="all"' in out   # All is the default view


def test_render_omits_range_filter_when_no_chart():
    out = render_dashboard_html(_summary(), _recent(), _positions(), _log(), "2026-07-21 10:00")
    assert 'id="equity-range-filter"' not in out


def test_render_chart_has_stable_element_ids_for_client_side_redraw():
    """The range filter redraws the line client-side by id -- both must be
    present regardless of the full series' up/down trend."""
    points = [("start", 100.0), ("2026-07-01", 90.0)]   # down trend overall
    out = render_dashboard_html(_summary(), _recent(), _positions(), _log(), "2026-07-21 10:00",
                                equity_points=points)
    assert 'id="equity-line"' in out
    assert 'id="equity-area"' in out
    # both gradients must exist so a filtered SUBSET with the opposite trend
    # can still be colored correctly without a server round trip
    assert 'id="eqGradUp"' in out
    assert 'id="eqGradDown"' in out


def test_render_has_empty_range_note_hidden_by_default():
    points = [("start", 100.0), ("2026-07-01", 110.0)]
    out = render_dashboard_html(_summary(), _recent(), _positions(), _log(), "2026-07-21 10:00",
                                equity_points=points)
    assert 'id="range-empty-note" style="display:none"' in out


# ---------------- portfolio concentration panel ----------------------------------

def test_render_shows_portfolio_analysis_when_given():
    pa = PortfolioAnalysis(weights_pct={"ANTM.JK": 60.0, "BBRI.JK": 40.0}, hhi=0.52,
                           effective_n=1.9, high_corr_pairs=[("ANTM.JK", "BBRI.JK", 0.85)],
                           sector_weights_pct={})
    out = render_dashboard_html(_summary(), _recent(), _positions(), _log(), "2026-07-21 10:00",
                                portfolio_analysis=pa)
    assert "Portfolio Concentration" in out
    assert "0.520" in out
    assert "ANTM.JK <-> BBRI.JK" not in out   # rendered as separate cells, not this exact string
    assert "+0.85" in out


def test_render_omits_portfolio_section_when_empty():
    pa = PortfolioAnalysis()
    out = render_dashboard_html(_summary(), _recent(), _positions(), _log(), "2026-07-21 10:00",
                                portfolio_analysis=pa)
    assert "Portfolio Concentration" not in out


def test_render_portfolio_analysis_no_correlated_pairs_message():
    pa = PortfolioAnalysis(weights_pct={"ANTM.JK": 100.0}, hhi=1.0, effective_n=1.0)
    out = render_dashboard_html(_summary(), _recent(), _positions(), _log(), "2026-07-21 10:00",
                                portfolio_analysis=pa)
    assert "No highly correlated pairs" in out


# ---------------- TWR performance section ----------------------------------------

def test_render_shows_twr_section_when_given():
    twr = compute_time_weighted_return([], [], original_capital=10_000_000.0,
                                       current_equity=11_000_000.0,
                                       account_start_date="2026-01-01",
                                       today=None)
    out = render_dashboard_html(_summary(), _recent(), _positions(), _log(), "2026-07-21 10:00",
                                twr_result=twr)
    assert "Time-Weighted" in out
    assert "Time-weighted return" in out
    assert "Max drawdown" in out


def test_render_omits_twr_section_when_none():
    out = render_dashboard_html(_summary(), _recent(), _positions(), _log(), "2026-07-21 10:00")
    assert "Time-Weighted" not in out


def test_render_twr_shows_na_cagr_when_unavailable():
    twr = compute_time_weighted_return([], [], 10_000_000.0, 11_000_000.0)   # no account_start_date
    out = render_dashboard_html(_summary(), _recent(), _positions(), _log(), "2026-07-21 10:00",
                                twr_result=twr)
    assert ">n/a<" in out


def test_render_twr_includes_the_honesty_note():
    twr = compute_time_weighted_return([], [], 10_000_000.0, 11_000_000.0)
    out = render_dashboard_html(_summary(), _recent(), _positions(), _log(), "2026-07-21 10:00",
                                twr_result=twr)
    assert "chain-linked around deposit dates" in out


def test_render_twr_lives_in_performance_tab():
    twr = compute_time_weighted_return([], [], 10_000_000.0, 11_000_000.0)
    out = render_dashboard_html(_summary(), _recent(), _positions(), _log(), "2026-07-21 10:00",
                                twr_result=twr)
    perf_start = out.index('id="tab-performance"')
    perf_end = out.index('id="tab-portfolio"')
    assert "Time-Weighted" in out[perf_start:perf_end]


# ---------------- allocation drift section ---------------------------------------

def test_render_shows_drift_table_when_given():
    rows = allocation_drift({"ANTM.JK": 45.0}, {"ANTM.JK": 30.0}, threshold_pp=5.0)
    out = render_dashboard_html(_summary(), _recent(), _positions(), _log(), "2026-07-21 10:00",
                                allocation_drift_rows=rows)
    assert "Allocation vs Target" in out
    assert "OVER" in out
    assert "+15.0pp" in out


def test_render_omits_drift_table_when_empty():
    out = render_dashboard_html(_summary(), _recent(), _positions(), _log(), "2026-07-21 10:00",
                                allocation_drift_rows=[])
    assert "Allocation vs Target" not in out


def test_render_drift_not_a_rebalancing_instruction_disclaimer():
    rows = allocation_drift({"ANTM.JK": 30.0}, {"ANTM.JK": 30.0})
    out = render_dashboard_html(_summary(), _recent(), _positions(), _log(), "2026-07-21 10:00",
                                allocation_drift_rows=rows)
    assert "not a rebalancing instruction" in out


def test_render_drift_lives_in_portfolio_tab():
    rows = allocation_drift({"ANTM.JK": 30.0}, {"ANTM.JK": 30.0})
    out = render_dashboard_html(_summary(), _recent(), _positions(), _log(), "2026-07-21 10:00",
                                allocation_drift_rows=rows)
    portfolio_start = out.index('id="tab-portfolio"')
    portfolio_end = out.index('id="tab-history"')
    assert "Allocation vs Target" in out[portfolio_start:portfolio_end]


# ---------------- mark-to-market second series ------------------------------------
# The realized-only curve is flat whenever nothing has been SOLD, which is
# what prompted this: a book that bought seven names today and sold none
# showed a dead-flat line. MTM becomes the primary series; realized stays as
# a dashed reference so the gap between them reads as unrealized P&L.

def _mtm():
    return [("2026-07-01", 1_000_000.0), ("2026-07-02", 1_020_000.0),
            ("2026-07-03", 1_010_000.0), ("2026-07-06", 1_050_000.0)]


def test_mtm_becomes_primary_and_realized_becomes_secondary():
    out = render_dashboard_html(_summary(), _recent(), _positions(), _log(), "2026-07-21 10:00",
                                equity_points=[("start", 1_000_000.0),
                                               ("2026-07-03", 1_005_000.0)],
                                mtm_points=_mtm())
    assert 'id="equity-line"' in out          # primary
    assert 'id="realized-line"' in out        # dashed secondary
    assert "data-secondary=" in out
    assert "Total equity (mark-to-market)" in out
    assert "Realized only" in out


def test_chart_falls_back_to_single_series_without_mtm():
    """Existing behavior must be untouched when no MTM data is supplied."""
    out = render_dashboard_html(_summary(), _recent(), _positions(), _log(), "2026-07-21 10:00",
                                equity_points=[("start", 100.0), ("d1", 110.0)])
    assert 'id="equity-line"' in out
    assert 'id="realized-line"' not in out
    assert "data-secondary=" not in out
    assert "Equity Curve (realized P&amp;L)" in out


def test_note_explains_the_gap_is_unrealized():
    out = render_dashboard_html(_summary(), _recent(), _positions(), _log(), "2026-07-21 10:00",
                                equity_points=[("start", 1_000_000.0)],
                                mtm_points=_mtm())
    assert "unrealized" in out.lower()
    assert "not banked" in out.lower()


def test_mtm_warnings_are_surfaced_not_swallowed():
    out = render_dashboard_html(_summary(), _recent(), _positions(), _log(), "2026-07-21 10:00",
                                equity_points=[("start", 1.0)], mtm_points=_mtm(),
                                mtm_warnings=["valued at cost (no price history): GHOST.JK"])
    assert "GHOST.JK" in out
    assert "⚠️" in out


def test_too_short_mtm_series_falls_back_instead_of_breaking():
    out = render_dashboard_html(_summary(), _recent(), _positions(), _log(), "2026-07-21 10:00",
                                equity_points=[("start", 100.0), ("d1", 110.0)],
                                mtm_points=[("2026-07-01", 100.0)])   # only 1 point
    assert 'id="realized-line"' not in out
    assert 'id="equity-line"' in out


# ---------------- _step_onto_axis -------------------------------------------------

def test_step_onto_axis_carries_values_forward():
    """Realized P&L is genuinely a step function -- holding the last value is
    what actually happened, not an approximation."""
    from kala.dashboard import _step_onto_axis
    series = [("start", 100.0), ("2026-07-02", 150.0), ("2026-07-05", 120.0)]
    axis = ["2026-07-01", "2026-07-02", "2026-07-03", "2026-07-05", "2026-07-06"]
    assert _step_onto_axis(series, axis) == [100.0, 150.0, 150.0, 120.0, 120.0]


def test_step_onto_axis_uses_start_sentinel_before_the_first_event():
    from kala.dashboard import _step_onto_axis
    series = [("start", 500.0), ("2026-07-10", 600.0)]
    assert _step_onto_axis(series, ["2026-07-01", "2026-07-10"]) == [500.0, 600.0]


def test_step_onto_axis_yields_none_before_a_series_with_no_baseline():
    """No 'start' sentinel means the line genuinely has no value yet; None
    lets the renderer begin it where it really begins."""
    from kala.dashboard import _step_onto_axis
    out = _step_onto_axis([("2026-07-05", 42.0)], ["2026-07-01", "2026-07-05"])
    assert out == [None, 42.0]


def test_step_onto_axis_handles_empty_series():
    from kala.dashboard import _step_onto_axis
    assert _step_onto_axis([], ["2026-07-01", "2026-07-02"]) == [None, None]


def test_tooltip_is_multiline_not_one_wide_line():
    """Regression: the single-line tooltip grew wide enough (date + total +
    realized + unrealized) to run off the right edge of the page. Stacked
    lines keep it narrow; the JS must emit a newline join, and the CSS must
    render it (nowrap would collapse it back to one line)."""
    out = render_dashboard_html(_summary(), _recent(), _positions(), _log(), "2026-07-21 10:00",
                                equity_points=[("start", 1_000_000.0)], mtm_points=_mtm())
    assert "white-space: pre-line" in out
    assert "white-space: nowrap" not in out.split(".chart-tooltip")[1][:400]
    # the newline must survive Python's string literal as a JS escape
    assert r"lines.join('\n')" in out


def test_tooltip_positioning_measures_the_real_width():
    """The old code clamped against a HARDCODED 120px assumed width, which is
    what let the wider tooltip overflow. It must measure offsetWidth instead."""
    out = render_dashboard_html(_summary(), _recent(), _positions(), _log(), "2026-07-21 10:00",
                                equity_points=[("start", 1_000_000.0)], mtm_points=_mtm())
    assert "tooltip.offsetWidth" in out
    assert "wrapRect.width - 120" not in out      # the old hardcoded clamp


def test_tooltip_flips_to_the_left_near_the_right_edge():
    out = render_dashboard_html(_summary(), _recent(), _positions(), _log(), "2026-07-21 10:00",
                                equity_points=[("start", 1_000_000.0)], mtm_points=_mtm())
    assert "left = cursorX - 12 - tw" in out
