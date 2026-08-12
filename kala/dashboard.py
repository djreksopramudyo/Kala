"""
Local HTML dashboard report generator — a static, self-contained HTML file
built from YOUR local trading-state files, not a hosted web page.

WHY LOCAL, NOT HOSTED
----------------------
A hosted dashboard (a web Artifact, a deployed page) can't read
paper_state.json off this machine, and shipping the state to a remote
renderer just to view it defeats the point of running everything locally.
This module instead RENDERS a single, dependency-free .html file (inline
CSS/JS only, no external CDN/fonts/analytics) that ``generate_dashboard.py``
writes to disk -- open it in any browser, no server needed. "Interactive"
here means vanilla inline JS (tab switching, a hover-tooltip SVG chart, a
privacy toggle) -- still zero network calls once the file is open.

This module is the pure, testable half: given already-loaded data
(PaperTrader summary/recent_performance dicts, positions, the trade log),
produce the HTML string. All I/O (loading state, fetching current prices)
lives in ``generate_dashboard.py`` at the repo root, same network/pure-
logic split as run_walkforward.py.
"""

from __future__ import annotations

import html
import json


def _esc(x) -> str:
    return html.escape(str(x))


def _drawdown_basis_note(twr_result) -> str:
    """Caption for the max-drawdown tile.

    On the realized-only fallback the figure counts only losses locked in by
    selling, so it sits near zero while a position is deep underwater. A
    drawdown number is exactly what someone checks before abandoning a plan,
    so it must never appear unqualified.
    """
    if not getattr(twr_result, "drawdown_is_real", False):
        return "realized only — excludes open positions, real figure is worse"
    if getattr(twr_result, "drawdown_is_complete", True):
        return "daily mark-to-market"
    # Partial: some lot had no price history and was held flat at cost, which
    # damps exactly the troughs this figure exists to show.
    return ("daily mark-to-market, but " + "; ".join(twr_result.drawdown_warnings)
            + " — those troughs are flattened, so the real figure is worse")


def _row(cells: list[str]) -> str:
    return "<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>"


def _fmt_pct_or_na(v) -> str:
    return f"{v:+.2f}%" if v is not None else "n/a"


def _step_onto_axis(series: list[tuple[str, float]],
                    axis: list[str]) -> list[float | None]:
    """Project a sparse, event-driven series onto a daily date ``axis`` by
    carrying each value forward until the next event.

    Forward-fill is the CORRECT projection here, not an approximation:
    realized P&L genuinely is a step function -- it changes only when a
    trade closes and is constant in between -- so holding the last value is
    what actually happened, unlike interpolating a straight line through
    days on which nothing was realized.

    Dates before the series' first event yield None so the renderer can
    start that line where it truly begins instead of inventing a value.
    """
    ordered = sorted((d, v) for d, v in series if d and d != "start")
    # A leading ("start", capital) sentinel carries the pre-first-trade
    # baseline; use it for every axis day before the first real event.
    baseline = next((v for d, v in series if d == "start"), None)

    out: list[float | None] = []
    i, current = 0, baseline
    for day in axis:
        while i < len(ordered) and ordered[i][0] <= day:
            current = ordered[i][1]
            i += 1
        out.append(current)
    return out


def _svg_equity_chart(points: list[tuple[str, float]], width: int = 680, height: int = 220,
                      margin: int = 14,
                      secondary: list[float | None] | None = None,
                      primary_label: str = "", secondary_label: str = "") -> str:
    """An interactive inline SVG line+area chart (gradient fill, hover
    crosshair + tooltip via vanilla JS) -- no rasterized image, no
    external charting library. Returns "" if there aren't enough points
    to draw a line.

    ``secondary``: an optional second series of values ALREADY aligned
    index-for-index with ``points`` (use ``_step_onto_axis``). Drawn as a
    thin dashed line with no area fill, so the gap between the two lines
    reads as the unrealized portion. Passing None keeps the exact
    single-series output this function produced before.
    """
    if not points or len(points) < 2:
        return ""

    values = [v for _, v in points]
    # Both series share one y-scale -- drawing them on independent scales
    # would make the visual gap between them meaningless.
    scale_vals = list(values)
    if secondary:
        scale_vals += [v for v in secondary if v is not None]
    lo, hi = min(scale_vals), max(scale_vals)
    if lo == hi:
        lo, hi = lo - 1, hi + 1
    n = len(points)
    plot_w = width - 2 * margin
    plot_h = height - 2 * margin

    def x_for(i: int) -> float:
        return margin + (i / (n - 1)) * plot_w

    def y_for(v: float) -> float:
        return margin + plot_h - (v - lo) / (hi - lo) * plot_h

    coords = [(x_for(i), y_for(v)) for i, (_, v) in enumerate(points)]
    line_pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    area_pts = (f"{margin:.1f},{height - margin:.1f} " + line_pts
               + f" {width - margin:.1f},{height - margin:.1f}")
    up = values[-1] >= values[0]
    color = "#4caf50" if up else "#f44336"
    grad_id = "eqGradUp" if up else "eqGradDown"

    points_json = html.escape(json.dumps(points), quote=True)

    secondary_attr = ""
    secondary_svg = ""
    legend_html = ""
    if secondary:
        sec_coords = [(x_for(i), y_for(v)) for i, v in enumerate(secondary)
                      if v is not None]
        sec_pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in sec_coords)
        secondary_attr = (
            f' data-secondary="{html.escape(json.dumps(secondary), quote=True)}"')
        secondary_svg = (
            f'<polyline id="realized-line" points="{sec_pts}" fill="none" '
            f'stroke="#8a8e9c" stroke-width="1.5" stroke-dasharray="4 3" '
            f'stroke-linejoin="round" stroke-linecap="round"/>')
        legend_html = (
            f'<div class="chart-legend">'
            f'<span><i class="sw sw-primary"></i>{_esc(primary_label)}</span>'
            f'<span><i class="sw sw-secondary"></i>{_esc(secondary_label)}</span>'
            f'</div>')

    # Both gradients are always emitted (not just the trend that applies to the
    # full range) so the client-side date-range filter can redraw the line for
    # a SUBSET of points -- whose trend may differ from the full series' -- by
    # swapping which gradient the polygon references, without a server round trip.
    return f"""
<div class="chart-wrap" id="equity-chart-wrap" data-points="{points_json}"{secondary_attr}
     data-width="{width}" data-height="{height}" data-margin="{margin}">
  <svg id="equity-svg" viewBox="0 0 {width} {height}" preserveAspectRatio="none">
    <defs>
      <linearGradient id="eqGradUp" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="#4caf50" stop-opacity="0.35"/>
        <stop offset="100%" stop-color="#4caf50" stop-opacity="0"/>
      </linearGradient>
      <linearGradient id="eqGradDown" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="#f44336" stop-opacity="0.35"/>
        <stop offset="100%" stop-color="#f44336" stop-opacity="0"/>
      </linearGradient>
    </defs>
    <polygon id="equity-area" points="{area_pts}" fill="url(#{grad_id})"/>
    {secondary_svg}
    <polyline id="equity-line" points="{line_pts}" fill="none" stroke="{color}" stroke-width="2"
              stroke-linejoin="round" stroke-linecap="round"/>
    <line id="hover-line" x1="0" y1="{margin}" x2="0" y2="{height - margin}"
          stroke="#666" stroke-width="1" opacity="0"/>
    <circle id="hover-dot" r="4" fill="{color}" stroke="#0f1115" stroke-width="1.5" opacity="0"/>
  </svg>
  <div id="chart-tooltip" class="chart-tooltip"></div>
</div>
{legend_html}
"""


_RANGE_FILTER_HTML = """
<div class="range-filter" id="equity-range-filter">
  <button class="range-btn" data-range="7" type="button">1W</button>
  <button class="range-btn" data-range="30" type="button">1M</button>
  <button class="range-btn" data-range="ytd" type="button">YTD</button>
  <button class="range-btn" data-range="365" type="button">1Y</button>
  <button class="range-btn active" data-range="all" type="button">All</button>
  <button class="range-btn" data-range="custom" type="button">Custom</button>
  <span class="range-custom-inputs" id="range-custom-inputs" style="display:none">
    <input type="date" id="range-start" aria-label="Range start date">
    <input type="date" id="range-end" aria-label="Range end date">
    <button id="range-apply" type="button">Apply</button>
    <span class="range-hint" id="range-hint"></span>
  </span>
</div>
"""


_TABS_AND_CHART_SCRIPT = """
<script>
(function () {
  document.querySelectorAll('.tab-btn').forEach(function (btn) {
    btn.addEventListener('click', function () {
      document.querySelectorAll('.tab-btn').forEach(function (b) { b.classList.remove('active'); });
      document.querySelectorAll('.tab-panel').forEach(function (p) { p.classList.remove('active'); });
      btn.classList.add('active');
      var panel = document.getElementById('tab-' + btn.dataset.tab);
      if (panel) panel.classList.add('active');
    });
  });

  var privacyBtn = document.getElementById('privacy-toggle');
  if (privacyBtn) {
    privacyBtn.addEventListener('click', function () {
      document.body.classList.toggle('privacy-mode');
      var hidden = document.body.classList.contains('privacy-mode');
      privacyBtn.textContent = hidden ? 'Show numbers' : 'Hide numbers';
    });
  }

  var wrap = document.getElementById('equity-chart-wrap');
  if (wrap) {
    var allPoints = JSON.parse(wrap.dataset.points);
    // Optional second series (realized P&L), already index-aligned with
    // allPoints server-side. Absent on a single-series chart.
    var allSecondary = wrap.dataset.secondary ? JSON.parse(wrap.dataset.secondary) : null;
    var svg = document.getElementById('equity-svg');
    var lineEl = document.getElementById('equity-line');
    var areaEl = document.getElementById('equity-area');
    var secondaryEl = document.getElementById('realized-line');
    var hoverLine = document.getElementById('hover-line');
    var hoverDot = document.getElementById('hover-dot');
    var tooltip = document.getElementById('chart-tooltip');
    var emptyNote = document.getElementById('range-empty-note');
    var W = parseFloat(wrap.dataset.width), H = parseFloat(wrap.dataset.height), M = parseFloat(wrap.dataset.margin);

    // points/secondary/lo/hi/range are reassigned by renderFiltered() below
    // when the range filter changes -- xFor/yFor and the hover handler close
    // over these vars, so they automatically track whichever range is shown.
    var points = allPoints;
    var secondary = allSecondary;
    var values = points.map(function (p) { return p[1]; });
    if (allSecondary) {
      allSecondary.forEach(function (v) { if (v !== null && v !== undefined) { values.push(v); } });
    }
    var lo = Math.min.apply(null, values), hi = Math.max.apply(null, values);
    var range = (hi === lo) ? 1 : (hi - lo);

    function xFor(i) { return M + (i / (points.length - 1)) * (W - 2 * M); }
    function yFor(v) { return M + (H - 2 * M) - ((v - lo) / range) * (H - 2 * M); }

    // Points from kala.chart.equity_curve_points aren't all real calendar
    // dates -- the very first is the literal string "start". Date.parse on
    // that (or any other unparseable string) yields NaN, mapped here to
    // -Infinity so it always qualifies as the range's fallback anchor
    // instead of being silently dropped.
    function dateOf(s) {
      var t = Date.parse(s);
      return isNaN(t) ? -Infinity : t;
    }

    function cutoffFor(key) {
      if (key === 'ytd') { return Date.UTC(new Date().getFullYear(), 0, 1); }
      return Date.now() - parseInt(key, 10) * 86400000;
    }

    // The window's start needs an ANCHOR: the latest point at/before the
    // cutoff, so a "1W" chart shows change from where the curve actually
    // was a week ago rather than starting the line mid-air. Falls back to
    // the very first point ("start") when nothing else qualifies.
    // Returns INDICES, not points, so the optional second series stays in
    // lockstep with the first: both are index-aligned by construction (see
    // _step_onto_axis), and slicing them with one shared index list is what
    // guarantees they can never drift apart as the range changes.
    function filterByCutoff(startCutoff, endCutoff) {
      endCutoff = (endCutoff === undefined) ? Infinity : endCutoff;
      var anchor = -1, within = [];
      for (var i = 0; i < allPoints.length; i++) {
        var d = dateOf(allPoints[i][0]);
        if (d <= startCutoff) {
          anchor = i;
        } else if (d <= endCutoff) {
          within.push(i);
        }
      }
      var result = (anchor >= 0) ? [anchor].concat(within) : within;
      if (result.length > 1 &&
          allPoints[result[0]][0] === allPoints[result[1]][0]) { result.shift(); }
      return result;
    }

    function allIndices() {
      var out = [];
      for (var i = 0; i < allPoints.length; i++) { out.push(i); }
      return out;
    }

    function renderFiltered(idx) {
      if (idx.length < 2) {
        if (emptyNote) { emptyNote.style.display = 'block'; }
        return;
      }
      if (emptyNote) { emptyNote.style.display = 'none'; }
      points = idx.map(function (i) { return allPoints[i]; });
      secondary = allSecondary ? idx.map(function (i) { return allSecondary[i]; }) : null;

      // One shared y-scale across both series -- independent scales would
      // make the visual gap between them meaningless.
      var vals = points.map(function (p) { return p[1]; });
      if (secondary) {
        secondary.forEach(function (v) { if (v !== null && v !== undefined) { vals.push(v); } });
      }
      lo = Math.min.apply(null, vals); hi = Math.max.apply(null, vals);
      range = (hi === lo) ? 1 : (hi - lo);

      var linePts = points.map(function (p, i) { return xFor(i).toFixed(1) + ',' + yFor(p[1]).toFixed(1); }).join(' ');
      var areaPts = M.toFixed(1) + ',' + (H - M).toFixed(1) + ' ' + linePts + ' ' + (W - M).toFixed(1) + ',' + (H - M).toFixed(1);
      var primaryVals = points.map(function (p) { return p[1]; });
      var up = primaryVals[primaryVals.length - 1] >= primaryVals[0];
      var color = up ? '#4caf50' : '#f44336';
      lineEl.setAttribute('points', linePts);
      lineEl.setAttribute('stroke', color);
      areaEl.setAttribute('points', areaPts);
      areaEl.setAttribute('fill', 'url(#' + (up ? 'eqGradUp' : 'eqGradDown') + ')');
      hoverDot.setAttribute('fill', color);

      if (secondaryEl && secondary) {
        var secPts = [];
        secondary.forEach(function (v, i) {
          if (v !== null && v !== undefined) {
            secPts.push(xFor(i).toFixed(1) + ',' + yFor(v).toFixed(1));
          }
        });
        secondaryEl.setAttribute('points', secPts.join(' '));
      }
    }

    wrap.addEventListener('mousemove', function (e) {
      var rect = svg.getBoundingClientRect();
      var relX = (e.clientX - rect.left) / rect.width * W;
      var idx = Math.round((relX - M) / (W - 2 * M) * (points.length - 1));
      idx = Math.max(0, Math.min(points.length - 1, idx));
      var x = xFor(idx), y = yFor(points[idx][1]);
      hoverLine.setAttribute('x1', x); hoverLine.setAttribute('x2', x); hoverLine.setAttribute('opacity', 1);
      hoverDot.setAttribute('cx', x); hoverDot.setAttribute('cy', y); hoverDot.setAttribute('opacity', 1);
      tooltip.style.display = 'block';

      // Content FIRST, then measure, then position -- the tooltip's width
      // depends on what's in it, so measuring before filling it would clamp
      // against a stale size.
      function money(v) { return v.toLocaleString(undefined, {maximumFractionDigits: 0}); }
      var lines = [points[idx][0]];
      if (secondary && secondary[idx] !== null && secondary[idx] !== undefined) {
        // Stacked, not one long line: the single-line version grew wide
        // enough to run off the page on the right-hand points. The gap IS
        // the unrealized P&L, which is why the second line is on the chart.
        var sec = secondary[idx], gap = points[idx][1] - sec;
        lines.push('Total ' + money(points[idx][1]));
        lines.push('Realized ' + money(sec));
        lines.push('Unrealized ' + (gap >= 0 ? '+' : '') + money(gap));
      } else {
        lines.push(money(points[idx][1]));
      }
      // '\\n' (escaped) so the newline survives Python's string literal and
      // reaches the browser as a JS escape, not a raw line break mid-string.
      tooltip.textContent = lines.join('\\n');

      // Edge-aware placement. The old code clamped against a HARDCODED 120px
      // assumed width; once the tooltip carried three figures it was far
      // wider than that and ran off the right edge of the page. Measure the
      // real box and flip to the cursor's left when it would overflow.
      var wrapRect = wrap.getBoundingClientRect();
      var tw = tooltip.offsetWidth, th = tooltip.offsetHeight;
      var cursorX = e.clientX - wrapRect.left;
      var left = cursorX + 12;
      if (left + tw > wrapRect.width) { left = cursorX - 12 - tw; }
      tooltip.style.left = Math.max(0, Math.min(left, wrapRect.width - tw)) + 'px';

      var top = (y / H) * wrapRect.height - th - 8;
      if (top < 0) { top = (y / H) * wrapRect.height + 12; }   // flip below
      tooltip.style.top = Math.max(0, Math.min(top, wrapRect.height - th)) + 'px';
    });
    wrap.addEventListener('mouseleave', function () {
      hoverLine.setAttribute('opacity', 0);
      hoverDot.setAttribute('opacity', 0);
      tooltip.style.display = 'none';
    });

    var filterBar = document.getElementById('equity-range-filter');
    if (filterBar) {
      var customBox = document.getElementById('range-custom-inputs');
      var rangeBtns = filterBar.querySelectorAll('.range-btn');
      rangeBtns.forEach(function (btn) {
        btn.addEventListener('click', function () {
          rangeBtns.forEach(function (b) { b.classList.remove('active'); });
          btn.classList.add('active');
          var key = btn.dataset.range;
          if (key === 'custom') {
            customBox.style.display = 'inline-flex';
            return;   // wait for Apply -- clicking "Custom" alone filters nothing yet
          }
          customBox.style.display = 'none';
          if (key === 'all') {
            renderFiltered(allIndices());
          } else {
            renderFiltered(filterByCutoff(cutoffFor(key)));
          }
        });
      });
      var applyBtn = document.getElementById('range-apply');
      var hint = document.getElementById('range-hint');
      if (applyBtn) {
        applyBtn.addEventListener('click', function () {
          if (hint) { hint.textContent = ''; }
          var s = document.getElementById('range-start').value;
          var e = document.getElementById('range-end').value;
          // Neither field filled: nothing to apply -- say so instead of a
          // silent no-op that looks like the button didn't register the click.
          if (!s && !e) {
            if (hint) { hint.textContent = 'Pick at least one date.'; }
            return;
          }
          // Blank start with an end date filled means "everything up to end".
          var startCutoff = s ? Date.parse(s) : -Infinity;
          var endCutoff = e ? (Date.parse(e) + 86399999) : Infinity;   // inclusive end-of-day
          if (isNaN(startCutoff) || isNaN(endCutoff)) {
            if (hint) { hint.textContent = 'That date could not be read.'; }
            return;
          }
          if (startCutoff > endCutoff) {
            if (hint) { hint.textContent = 'Start date must be before end date.'; }
            return;
          }
          renderFiltered(filterByCutoff(startCutoff, endCutoff));
        });
      }
    }
  }
})();
</script>
"""


def render_dashboard_html(summary: dict, recent: dict,
                          positions: dict, log: list[dict],
                          generated_at: str, max_log_rows: int = 200,
                          position_comparisons: list[dict] | None = None,
                          equity_points: list[tuple[str, float]] | None = None,
                          mtm_points: list[tuple[str, float]] | None = None,
                          mtm_warnings: list[str] | None = None,
                          portfolio_analysis=None,
                          twr_result=None,
                          allocation_drift_rows: list[dict] | None = None) -> str:
    """``summary``: PaperTrader.summary() output. ``recent``:
    PaperTrader.recent_performance() output. ``positions``: {ticker:
    PaperPosition}. ``log``: PaperTrader.log (full closed-trade history,
    most recent ``max_log_rows`` shown, in the History tab).

    Optional, each gracefully omitted from the page if not supplied:
    ``position_comparisons`` (kala.portfolio_analytics.
    positions_vs_benchmark output — per-holding return vs IHSG over the
    same window), ``equity_points`` (kala.chart.equity_curve_points
    output, rendered as an interactive inline SVG chart, not a static
    image), ``portfolio_analysis`` (kala.portfolio_analytics.
    PortfolioAnalysis — concentration/correlation), ``twr_result``
    (kala.twr.TWRResult — deposit-neutral time-weighted return,
    CAGR, max drawdown), ``allocation_drift_rows`` (kala.
    portfolio_analytics.allocation_drift output — actual vs target
    weight per ticker, flagged not advised).
    """

    return_pct = summary.get("return_pct", 0.0)
    return_class = "pos" if return_pct >= 0 else "neg"
    alpha_line = ""
    if "alpha_pct" in summary:
        a = summary["alpha_pct"]
        alpha_class = "pos" if a >= 0 else "neg"
        alpha_line = (f'<div class="stat"><span class="label">vs IHSG (alpha)</span>'
                      f'<span class="value mask {alpha_class}">{a:+.2f}%</span></div>')

    if position_comparisons:
        position_rows = "".join(
            _row([
                _esc(r["ticker"]),
                f"{r['shares']:,.0f}" if r.get("shares") is not None else "n/a",
                f"{r['entry_price']:,.0f}" if r.get("entry_price") is not None else "n/a",
                f"{r['current_price']:,.0f}" if r.get("current_price") is not None else "n/a",
                (f'<span class="{"pos" if r["return_pct"] >= 0 else "neg"}">'
                 f'{r["return_pct"]:+.2f}%</span>') if r.get("return_pct") is not None else "n/a",
                _fmt_pct_or_na(r.get("benchmark_return_pct")),
                (f'<span class="{"pos" if r["alpha_pct"] >= 0 else "neg"}">'
                 f'{r["alpha_pct"]:+.2f}%</span>') if r.get("alpha_pct") is not None else "n/a",
            ])
            for r in position_comparisons
        ) or '<tr><td colspan="7" class="empty">No open positions</td></tr>'
        position_header = ("<tr><th>Ticker</th><th>Shares</th><th>Entry</th><th>Current</th>"
                           "<th>Return</th><th>IHSG (same window)</th><th>Alpha</th></tr>")
    else:
        position_rows = "".join(
            _row([_esc(t), f"{p.shares:,.0f}", f"{p.entry_price:,.0f}", f"{p.peak_price:,.0f}",
                 _esc(p.entry_date)])
            for t, p in sorted(positions.items())
        ) or '<tr><td colspan="5" class="empty">No open positions</td></tr>'
        position_header = "<tr><th>Ticker</th><th>Shares</th><th>Entry</th><th>Peak</th><th>Entry date</th></tr>"

    # Mark-to-market is the PRIMARY series when available: it answers "what is
    # the account worth today", which is what a reader assumes an equity curve
    # shows. Realized P&L is kept as a dashed secondary line rather than
    # dropped -- it is the only one of the two that is fully banked, and the
    # gap between them is exactly the unrealized (still reversible) portion.
    # Without mtm_points this falls back to the previous single-series chart.
    chart_title = "Equity Curve (realized P&amp;L)"
    chart_note = ("Cumulative REALIZED P&amp;L from closed trades only — excludes "
                  "unrealized P&amp;L on open positions, steps only on days a trade "
                  "closed. Hover the chart for a value at any point.")
    if mtm_points and len(mtm_points) >= 2:
        axis = [d for d, _ in mtm_points]
        secondary = _step_onto_axis(equity_points or [], axis)
        chart_html = _svg_equity_chart(
            mtm_points, secondary=secondary,
            primary_label="Total equity (mark-to-market)",
            secondary_label="Realized only")
        chart_title = "Equity Curve"
        chart_note = ("Solid line: TOTAL account value each day — cash plus open "
                      "positions valued at that day's close, so it moves with the "
                      "market even on days you didn't trade. Dashed line: REALIZED "
                      "P&amp;L only, which steps just on days a trade closed. The gap "
                      "between them is unrealized profit/loss — real, but not banked "
                      "until you sell. Hover for both figures.")
    else:
        chart_html = _svg_equity_chart(equity_points) if equity_points else ""

    warn_html = ""
    for w in (mtm_warnings or []):
        warn_html += f'<div class="chart-note">⚠️ {_esc(w)}</div>'

    chart_section = ""
    if chart_html:
        chart_section = f"""
<h2>{chart_title}</h2>
{_RANGE_FILTER_HTML}
{chart_html}
<div class="chart-note" id="range-empty-note" style="display:none">Not enough data points
in this range to draw a curve — the previous range is still shown. Try a wider window.</div>
<div class="chart-note">{chart_note}</div>
{warn_html}
"""

    portfolio_section = ""
    if portfolio_analysis is not None and portfolio_analysis.weights_pct:
        pa = portfolio_analysis
        weight_rows = "".join(
            _row([_esc(t), f"{w:.1f}%"])
            for t, w in sorted(pa.weights_pct.items(), key=lambda kv: kv[1], reverse=True)
        )
        corr_rows = "".join(
            _row([_esc(a), _esc(b), f"{c:+.2f}"]) for a, b, c in pa.high_corr_pairs
        ) or '<tr><td colspan="3" class="empty">No highly correlated pairs</td></tr>'
        portfolio_section = f"""
<h2>Portfolio Concentration</h2>
<div class="stats">
  <div class="stat"><span class="label">Herfindahl index</span><span class="value">{pa.hhi:.3f}</span></div>
  <div class="stat"><span class="label">Effective N</span><span class="value">{pa.effective_n:.1f}</span>
       <span class="sub">of {len(pa.weights_pct)} nominal position(s)</span></div>
</div>
<table>
  <tr><th>Ticker</th><th>Weight</th></tr>
  {weight_rows}
</table>
<h3>Highly Correlated Pairs</h3>
<table>
  <tr><th>Ticker</th><th>Ticker</th><th>Correlation</th></tr>
  {corr_rows}
</table>
"""

    twr_section = ""
    if twr_result is not None:
        twr_class = "pos" if twr_result.twr_pct >= 0 else "neg"
        cagr_html = (f'<span class="{"pos" if twr_result.cagr_pct >= 0 else "neg"}">'
                    f'{twr_result.cagr_pct:+.2f}%</span>') if twr_result.cagr_pct is not None else "n/a"
        twr_section = f"""
<h2>Performance (Time-Weighted)</h2>
<div class="stats">
  <div class="stat"><span class="label">Time-weighted return</span>
       <span class="value mask {twr_class}">{twr_result.twr_pct:+.2f}%</span>
       <span class="sub">{twr_result.n_sub_periods} sub-period(s)</span></div>
  <div class="stat"><span class="label">CAGR</span><span class="value mask">{cagr_html}</span></div>
  <div class="stat"><span class="label">Max drawdown</span>
       <span class="value mask neg">{twr_result.max_drawdown_pct:.2f}%</span>
       <span class="sub">{_esc(_drawdown_basis_note(twr_result))}</span></div>
</div>
<div class="chart-note">{_esc(twr_result.note)}</div>
"""

    drift_section = ""
    if allocation_drift_rows:
        flag_class = {"OVER": "flag-over", "UNDER": "flag-under", "ON TARGET": "flag-ontarget"}
        drift_rows_html = "".join(
            _row([_esc(r["ticker"]), f"{r['actual_pct']:.1f}%", f"{r['target_pct']:.1f}%",
                 f"{r['drift_pp']:+.1f}pp",
                 f'<span class="badge {flag_class.get(r["flag"], "")}">{_esc(r["flag"])}</span>'])
            for r in allocation_drift_rows
        )
        drift_section = f"""
<h2>Allocation vs Target</h2>
<div class="chart-note">Flags only, not a rebalancing instruction — see whichever
target this run used (config's target_allocation, or an equal-weight default).</div>
<table>
  <tr><th>Ticker</th><th>Actual</th><th>Target</th><th>Drift</th><th>Flag</th></tr>
  {drift_rows_html}
</table>
"""

    log_sorted = sorted(log, key=lambda t: str(t.get("date", "")), reverse=True)[:max_log_rows]
    log_rows = "".join(
        _row([_esc(t.get("date", "")), _esc(t.get("ticker", "")),
             f"{t.get('entry', 0):,.0f}", f"{t.get('exit', 0):,.0f}",
             f'<span class="{"pos" if t.get("pnl_pct", 0) > 0 else "neg"}">'
             f'{t.get("pnl_pct", 0):+.1f}%</span>',
             _esc(t.get("reason", ""))])
        for t in log_sorted
    ) or '<tr><td colspan="6" class="empty">No closed trades yet</td></tr>'

    recent_rows = "".join(
        _row([_esc(t.get("ticker", "")),
             f'<span class="{"pos" if t.get("pnl_pct", 0) > 0 else "neg"}">'
             f'{t.get("pnl_pct", 0):+.1f}%</span>',
             f"{t.get('profit_idr', 0):+,.0f}", _esc(t.get("reason", ""))])
        for t in recent.get("trades", [])
    ) or f'<tr><td colspan="4" class="empty">No closed trades in the last {recent.get("window_days", 7)} days</td></tr>'

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kala — Paper Trading Dashboard</title>
<style>
  :root {{ --accent: #7c6cf7; --bg: #0b0d12; --card: #161922; --border: #262b36; }}
  * {{ box-sizing: border-box; }}
  body {{ font-family: -apple-system, Segoe UI, Roboto, sans-serif; margin: 0;
         background: var(--bg); color: #e8e8ec; }}
  .page {{ max-width: 980px; margin: 0 auto; padding: 1.5rem 1.5rem 3rem; }}
  header {{ display: flex; align-items: center; justify-content: space-between;
           flex-wrap: wrap; gap: 0.8rem; margin-bottom: 0.3rem; }}
  h1 {{ font-size: 1.35rem; margin: 0; font-weight: 700; }}
  .generated {{ color: #7d8190; font-size: 0.82rem; margin-bottom: 1.2rem; }}
  .privacy-btn {{ background: var(--card); border: 1px solid var(--border); color: #ccc;
                 border-radius: 8px; padding: 0.5rem 0.9rem; font-size: 0.82rem;
                 cursor: pointer; transition: background 0.15s, border-color 0.15s; }}
  .privacy-btn:hover {{ background: #1e2230; border-color: var(--accent); }}
  nav.tabs {{ display: flex; gap: 0.3rem; margin: 1.2rem 0 1.6rem; border-bottom: 1px solid var(--border);
             overflow-x: auto; }}
  .tab-btn {{ background: none; border: none; color: #8a8e9c; font-size: 0.92rem; font-weight: 500;
             padding: 0.65rem 1rem; cursor: pointer; border-bottom: 2px solid transparent;
             white-space: nowrap; transition: color 0.15s, border-color 0.15s; }}
  .tab-btn:hover {{ color: #d0d2da; }}
  .tab-btn.active {{ color: #fff; border-bottom-color: var(--accent); }}
  .tab-panel {{ display: none; animation: fadein 0.15s ease-in; }}
  .tab-panel.active {{ display: block; }}
  @keyframes fadein {{ from {{ opacity: 0; }} to {{ opacity: 1; }} }}
  .stats {{ display: flex; flex-wrap: wrap; gap: 0.9rem; margin-bottom: 1.6rem; }}
  .stat {{ background: var(--card); border: 1px solid var(--border); border-radius: 10px;
          padding: 1rem 1.3rem; min-width: 155px; flex: 1 1 155px;
          transition: border-color 0.15s, transform 0.15s; }}
  .stat:hover {{ border-color: #3a3f4f; transform: translateY(-1px); }}
  .stat .label {{ display: block; font-size: 0.76rem; color: #8a8e9c; margin-bottom: 0.35rem;
                 text-transform: uppercase; letter-spacing: 0.03em; }}
  .stat .value {{ display: block; font-size: 1.4rem; font-weight: 700; }}
  .pos {{ color: #4caf50; }}
  .neg {{ color: #f44336; }}
  h2 {{ font-size: 1.05rem; margin: 1.8rem 0 0; font-weight: 600; color: #f0f0f3; }}
  h3 {{ font-size: 0.92rem; margin-top: 1.3rem; color: #b8bcc8; }}
  table {{ border-collapse: collapse; width: 100%; margin-top: 0.7rem; font-size: 0.88rem; }}
  th, td {{ text-align: left; padding: 0.55rem 0.6rem; border-bottom: 1px solid var(--border); }}
  th {{ color: #8a8e9c; font-weight: 500; font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.02em; }}
  tbody tr {{ transition: background 0.12s; }}
  tbody tr:hover {{ background: #14171f; }}
  .empty {{ color: #666; font-style: italic; }}
  .sub {{ display: block; font-size: 0.74rem; color: #7d8190; margin-top: 0.15rem; }}
  .chart-wrap {{ position: relative; margin-top: 0.7rem; background: var(--card);
                border: 1px solid var(--border); border-radius: 10px; padding: 0.6rem; }}
  .chart-wrap svg {{ width: 100%; height: auto; display: block; cursor: crosshair; }}
  /* pre-line (not nowrap) so the stacked multi-figure tooltip renders on
     separate lines -- one long line grew wide enough to run off the page
     at the right-hand end of the curve. */
  .chart-tooltip {{ position: absolute; display: none; background: #23273a; border: 1px solid var(--accent);
                    color: #fff; font-size: 0.78rem; padding: 0.35rem 0.6rem; border-radius: 6px;
                    pointer-events: none; white-space: pre-line; line-height: 1.35;
                    max-width: 220px; z-index: 5; }}
  .chart-note {{ color: #7d8190; font-size: 0.8rem; margin-top: 0.5rem; }}
  .chart-legend {{ display: flex; gap: 1rem; margin-top: 0.45rem; font-size: 0.78rem;
                  color: #9298a6; flex-wrap: wrap; }}
  .chart-legend span {{ display: inline-flex; align-items: center; gap: 0.35rem; }}
  .chart-legend .sw {{ width: 14px; height: 0; border-top: 2px solid currentColor;
                      display: inline-block; }}
  .chart-legend .sw-primary {{ color: #4caf50; }}
  .chart-legend .sw-secondary {{ color: #8a8e9c; border-top-style: dashed; }}
  .range-filter {{ display: flex; align-items: center; gap: 0.4rem; margin: 0.7rem 0 -0.2rem; flex-wrap: wrap; }}
  .range-btn {{ background: var(--card); border: 1px solid var(--border); color: #9298a6;
               border-radius: 7px; padding: 0.35rem 0.7rem; font-size: 0.78rem; cursor: pointer;
               transition: background 0.15s, border-color 0.15s, color 0.15s; }}
  .range-btn:hover {{ border-color: var(--accent); color: #d0d2da; }}
  .range-btn.active {{ background: var(--accent); border-color: var(--accent); color: #fff; }}
  .range-custom-inputs {{ display: inline-flex; align-items: center; gap: 0.35rem; }}
  .range-custom-inputs input[type=date] {{ background: var(--card); border: 1px solid var(--border);
               color: #e8e8ec; border-radius: 6px; padding: 0.3rem 0.4rem; font-size: 0.78rem; }}
  .range-custom-inputs button {{ background: var(--accent); border: none; color: #fff; border-radius: 6px;
               padding: 0.32rem 0.6rem; font-size: 0.78rem; cursor: pointer; }}
  .range-hint {{ color: #f44336; font-size: 0.78rem; }}
  .badge {{ display: inline-block; padding: 0.15rem 0.55rem; border-radius: 999px; font-size: 0.76rem;
           font-weight: 600; }}
  .flag-over {{ background: rgba(255, 167, 38, 0.15); color: #ffa726; }}
  .flag-under {{ background: rgba(66, 165, 245, 0.15); color: #42a5f5; }}
  .flag-ontarget {{ background: rgba(76, 175, 80, 0.15); color: #4caf50; }}
  .disclaimer {{ margin-top: 2.2rem; padding: 1rem 1.2rem; background: var(--card);
                border: 1px solid var(--border); border-radius: 10px; font-size: 0.82rem; color: #9a9ea8; }}
  body.privacy-mode .mask {{ filter: blur(7px); user-select: none; }}
  @media (max-width: 560px) {{ .page {{ padding: 1rem; }} .stat {{ min-width: 130px; }} }}
</style>
</head>
<body>
<div class="page">
<header>
  <h1>Kala Dashboard</h1>
  <button id="privacy-toggle" class="privacy-btn" type="button">Hide numbers</button>
</header>
<div class="generated">Generated {_esc(generated_at)} — updated data as of this run, reopen after re-running to refresh</div>

<nav class="tabs">
  <button class="tab-btn active" data-tab="overview" type="button">Overview</button>
  <button class="tab-btn" data-tab="performance" type="button">Performance</button>
  <button class="tab-btn" data-tab="portfolio" type="button">Portfolio</button>
  <button class="tab-btn" data-tab="history" type="button">History</button>
</nav>

<section class="tab-panel active" id="tab-overview">
<div class="stats">
  <div class="stat"><span class="label">Equity</span><span class="value mask">{summary.get('equity', 0):,.0f}</span></div>
  <div class="stat"><span class="label">Return</span><span class="value mask {return_class}">{return_pct:+.2f}%</span></div>
  <div class="stat"><span class="label">Cash</span><span class="value mask">{summary.get('cash', 0):,.0f}</span></div>
  <div class="stat"><span class="label">Open positions</span><span class="value">{summary.get('open_positions', 0)}</span></div>
  <div class="stat"><span class="label">Closed trades</span><span class="value">{summary.get('closed_trades', 0)}</span></div>
  <div class="stat"><span class="label">Win rate</span><span class="value">{summary.get('win_rate_pct', 0):.0f}%</span></div>
  {alpha_line}
</div>
{chart_section}
<h2>Open Positions{" vs IHSG" if position_comparisons else ""}</h2>
<table>
  {position_header}
  {position_rows}
</table>
</section>

<section class="tab-panel" id="tab-performance">
{twr_section or '<p class="empty">No time-weighted return data yet.</p>'}
<h2>Last {recent.get('window_days', 7)} Days ({recent.get('n', 0)} trades, {recent.get('win_rate_pct', 0):.0f}% win rate, net {recent.get('net_profit_idr', 0):+,.0f})</h2>
<table>
  <tr><th>Ticker</th><th>P&amp;L</th><th>Net IDR</th><th>Reason</th></tr>
  {recent_rows}
</table>
</section>

<section class="tab-panel" id="tab-portfolio">
{portfolio_section or '<p class="empty">No open positions to analyze.</p>'}
{drift_section}
</section>

<section class="tab-panel" id="tab-history">
<h2>Trade Log</h2>
<table>
  <tr><th>Date</th><th>Ticker</th><th>Entry</th><th>Exit</th><th>P&amp;L</th><th>Reason</th></tr>
  {log_rows}
</table>
</section>

<div class="disclaimer">
This is a PAPER-TRADING record, not investment advice. See PROJECT_STATUS.md
in the repository for this project's validated (negative) out-of-sample
edge finding before drawing any conclusion from the numbers above.
</div>
</div>
{_TABS_AND_CHART_SCRIPT}
</body>
</html>
"""
