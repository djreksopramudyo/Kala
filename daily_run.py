"""
DAILY RUN — the one script the scheduler calls.
===============================================

Runs the whole Kala loop after market close, on the right cadence:

  DAILY     scan for BUY signals -> paper-trade them within YOUR allocation,
            check exits on paper positions, check watchlist dips,
            send ONE Telegram message with tomorrow's order tickets.
  WEEKLY    (Saturday) fundamental value screen -> refreshes watchlist.json.
  QUARTERLY (1st weekday run of Jan/Apr/Jul/Oct) out-of-sample walk-forward
            validation on a universe sample — the edge-decay alarm. This
            REPLACED the old monthly per-ticker backtest, which measured the
            strategy in-sample on 3 mega-caps: flattering, and unable to say
            whether the edge still exists. The walk-forward answers exactly
            that, with the same engine that validated the strategy.

Configure in runner_config.json (created with defaults on first run):
  daily_capital_idr  — max IDR of NEW buys the paper trader may queue per day.
                       Change it any evening; tomorrow uses the new number.
  telegram_token / telegram_chat_id — from @BotFather (see kala/notify.py).
  risk_pct_per_trade, max_positions — sizing knobs.

Each stage is isolated: one failure is reported, the rest still run.
Everything here is PAPER trading + notifications. No real orders are placed.
"""

import json
import sys
import traceback
from pathlib import Path

from kala import regime
from kala.circuit_breaker import (
    BreakerConfig,
    evaluate_breaker,
    format_breaker,
    load_breaker_state,
    save_breaker_state,
)
from kala.clock import today_wib  # WIB, not server-local (see kala/clock.py)

ROOT = Path(__file__).parent
CONFIG_PATH = ROOT / "runner_config.json"
STATE_PATH = ROOT / "paper_state.json"
LOG_PATH = ROOT / "results" / "daily_run.log"
# Sidecar, deliberately NOT inside paper_state.json — see kala/circuit_breaker.py
BREAKER_PATH = ROOT / "results" / "breaker_state.json"

DEFAULT_CONFIG = {
    "daily_capital_idr": 5_000_000,
    "start_capital_idr": 10_000_000,
    "risk_pct_per_trade": 2.0,
    "max_positions": 5,
    "max_pct_of_adv": 5.0,   # order size cap: % of 20-day avg daily traded value
    # False (default): /run and the scheduler only RECOMMEND buys — nothing
    # is queued/filled, no cash moves, /positions stays empty until you
    # /buy. True: the old fully-autonomous behavior — BUY signals queue and
    # fill on their own, so /positions can show stocks you never told the
    # bot you bought. Flip to True only if you actually want a hands-off
    # simulated benchmark book, separate from your real trading.
    "auto_paper_trade": False,
    "telegram_token": "",
    "telegram_chat_id": "",
    "watchlist_min_discount_pct": 15.0,
    "weekly_fundamental_weekday": 5,   # 0=Mon ... 5=Sat
    # quarterly walk-forward validation (the edge-decay alarm):
    "walkforward_max_tickers": 60,     # universe sample size for the quarterly check
    "walkforward_period": "3y",        # history window (3y ~= 8 OOS folds)
    # advisory news/sentiment on today's tickets + holdings (display only —
    # sentiment is unbacktestable and must never feed the signal):
    "news_check_enabled": True,
    "news_max_tickers": 6,             # scraping is slow; cap the daily check
    # Drawdown circuit breaker — OFF by default because it changes how real
    # money behaves and must be switched on deliberately, never inherited
    # silently by upgrading. When enabled and tripped it stops NEW buys only;
    # existing positions keep their normal stops/exits and nothing is ever
    # force-sold. Drawdown is measured net of deposits/withdrawals.
    # See kala/circuit_breaker.py.
    "breaker_enabled": False,
    "breaker_halt_drawdown_pct": 15.0,     # halt new buys at this drawdown
    "breaker_resume_drawdown_pct": 10.0,   # resume once recovered to this (hysteresis)
    # Weekly friction reminder appended to the daily message. 0=Mon ... 4=Fri.
    "friction_report_weekday": 4,
    # Weekly live scorecard — real trades vs simply holding the benchmark.
    # Defaults to Friday like the friction report rather than its own quieter
    # day: a timer installed Mon-Fri would never fire on Sat/Sun, and the
    # report would then silently never arrive. Move it if your timer covers
    # more days and you'd rather read the two separately.
    "scorecard_report_enabled": True,
    "scorecard_report_weekday": 4,
    "scorecard_benchmark": "XIJI.JK",   # what you'd otherwise just have held
}


def quarterly_walkforward_due(today, results_dir: Path):
    """Return (marker_path, quarter_label) when the quarterly walk-forward
    should run today, else (None, None).

    Due on the first weekday window (day <= 5, Mon-Fri) of each quarter's
    first month (Jan/Apr/Jul/Oct), at most once per quarter (marker file).
    Pure calendar logic — kept separate from main() so it's testable offline.
    """
    if today.month not in (1, 4, 7, 10) or today.day > 5 or today.weekday() >= 5:
        return None, None
    label = f"{today.year}Q{(today.month - 1) // 3 + 1}"
    marker = results_dir / f".walkforward_done_{label}"
    if marker.exists():
        return None, None
    return marker, label


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(json.dumps(DEFAULT_CONFIG, indent=2))
        print(f"Created {CONFIG_PATH.name} with defaults — edit it (capital, Telegram) any time.")
    cfg = {**DEFAULT_CONFIG, **json.loads(CONFIG_PATH.read_text())}
    return cfg


def log(msg: str):
    print(msg)
    try:
        LOG_PATH.parent.mkdir(exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{today_wib().isoformat()}] {msg}\n")
    except Exception:
        pass


def degraded_scan_warning(coverage: dict | None, min_pct: float = 50.0) -> str | None:
    """Warn when a scan saw too little of the watchlist to be informative.

    A partly-failed scan still returns a tidy, short BUY list, so "no buys
    today" reads as a statement about the market when it is really a
    statement about the data feed. Total failure raises into ``errors``;
    this covers the partial case, which is the more deceptive of the two
    because the output still looks plausible.

    Pure calendar-free logic, kept out of main() so it is testable offline —
    same reasoning as quarterly_walkforward_due.
    """
    if not coverage:
        return None
    pct = coverage.get("coverage_pct")
    if pct is None or pct >= min_pct:
        return None
    return (f"⚠️ DEGRADED SCAN — only {coverage.get('analysed', 0)}/"
            f"{coverage.get('attempted', 0)} tickers had usable data "
            f"({pct:.0f}%). Today's BUY list covers a fraction of the "
            f"market, so an empty one is not evidence that nothing "
            f"qualified.")


def stage(name, fn, errors):
    try:
        return fn()
    except Exception as e:
        errors.append(f"{name}: {e}")
        log(f"STAGE FAILED — {name}: {e}\n{traceback.format_exc(limit=3)}")
        return None


def main():
    cfg = load_config()
    # CLI override: python daily_run.py --capital 3000000
    if "--capital" in sys.argv:
        cfg["daily_capital_idr"] = float(sys.argv[sys.argv.index("--capital") + 1])
        log(f"Capital override for this run: IDR {cfg['daily_capital_idr']:,.0f}")

    errors: list[str] = []
    today = today_wib()

    # Imports that need the venv / network live inside main so config errors
    # surface cleanly.
    from kala.notify import format_daily_message, resolve_telegram_credentials, send_telegram
    from kala.papertrade import PaperTrader, rotate_state_backup
    from kala.watchlist import WatchlistStore

    tg_token, tg_chat_id = resolve_telegram_credentials(cfg)
    import kala_daily_trader as dt

    # ---- daily state snapshot BEFORE anything mutates it ------------------
    # save() is crash-atomic, but this caps every OTHER corruption scenario
    # (disk fault, bad edit, future bug) at losing one day, not the whole
    # trading history the /edge tracker depends on. Keeps the last 7 days.
    stage("state_backup",
          lambda: rotate_state_backup(STATE_PATH, ROOT / "results" / "state_backups"),
          errors)

    # ---- market health + BUY scan (network-heavy) -------------------------
    mkt = stage("market_health", dt.check_market_health, errors) or {}
    # If the whole stage blew up we have no regime at all — that is a failure to
    # read the tape, so default to the fail-closed sentinel rather than the
    # warm-up 'UNKNOWN' that entry/exit guards deliberately let through.
    market_status = mkt.get("status", regime.UNAVAILABLE)

    signals = stage("buy_scan", dt.live_trading_dashboard, errors) or []
    buys = [s for s in signals
            if str(s.get("signal", "")).upper() in ("BUY", "STRONG BUY")]
    log(f"Scan complete: {len(signals)} analyzed, {len(buys)} BUY (post-guardrail).")

    # A scan that saw only a fraction of the watchlist still returns a tidy
    # (short) BUY list, and "no buys today" then reads as a statement about
    # the market rather than about the data feed. Total failure now raises
    # into `errors`; this covers the partial case, which is the more
    # deceptive one because the output still looks plausible.
    scan_warning = degraded_scan_warning(
        getattr(dt, "LAST_SCAN_COVERAGE", None),
        getattr(dt, "MIN_SCAN_COVERAGE_PCT", 50.0))
    if scan_warning:
        log(scan_warning)

    # ---- histories for paper positions + buy candidates -------------------
    def fetch_histories():
        tickers = {s["ticker"] for s in buys}
        pt_peek = PaperTrader.load(STATE_PATH, cfg["start_capital_idr"])
        tickers |= set(pt_peek.positions.keys())
        tickers |= {o.ticker for o in pt_peek.pending}
        out = {}
        for t in tickers:
            try:
                d = dt.download_stock_data(t, dt.START_DATE, dt.END_DATE)
                if d is not None and len(d):
                    out[t] = d
            except Exception as e:
                from kala.logging_util import log_swallowed
                log_swallowed(f"fetch_histories({t})", e)
        return out
    histories = stage("price_histories", fetch_histories, errors) or {}

    # ---- paper trading step ------------------------------------------------
    def run_paper():
        pt = PaperTrader.load(STATE_PATH, cfg["start_capital_idr"])
        jci = mkt.get("jci_price")
        pt.note_benchmark(jci)  # locks in the IHSG baseline on first run
        last = {t: float(h["Close"].iloc[-1]) for t, h in histories.items()}

        # Drawdown circuit breaker (OFF unless enabled in runner_config.json).
        # When tripped it only zeroes the day's BUY allocation — size_position
        # returns 0 for a non-positive allocation, so no new order can be
        # sized, while stage 1 (fill pending) and stage 2 (exits) still run
        # untouched. Nothing is ever force-sold; see kala/circuit_breaker.py.
        breaker_cfg = BreakerConfig(
            enabled=bool(cfg.get("breaker_enabled", False)),
            halt_drawdown_pct=float(cfg.get("breaker_halt_drawdown_pct", 15.0)),
            resume_drawdown_pct=float(cfg.get("breaker_resume_drawdown_pct", 10.0)))
        allocation = cfg["daily_capital_idr"]
        breaker = None
        if breaker_cfg.enabled:
            stored_peak, was_halted = load_breaker_state(BREAKER_PATH)
            breaker = evaluate_breaker(
                equity=pt.equity(last),
                net_contributions=sum(d.get("amount", 0.0)
                                      for d in pt.capital_additions),
                stored_peak=stored_peak, was_halted=was_halted, cfg=breaker_cfg)
            save_breaker_state(BREAKER_PATH, breaker)
            if breaker.halted:
                allocation = 0.0

        report = pt.step(histories, buys, market_status=market_status,
                         allocation=allocation,
                         today=today.isoformat(),
                         risk_pct=cfg["risk_pct_per_trade"],
                         max_positions=cfg["max_positions"],
                         max_pct_of_adv=cfg.get("max_pct_of_adv", 5.0),
                         auto_buy=cfg.get("auto_paper_trade", False))
        if breaker is not None and (breaker.halted or breaker.changed):
            report.setdefault("tickets", []).insert(
                0, format_breaker(breaker, breaker_cfg))
        return report, pt.summary(last, benchmark_price=jci)
    paper = stage("paper_trader", run_paper, errors)
    report, summary = paper if paper else ({"date": today.isoformat(), "tickets": []}, None)

    # ---- watchlist dip alerts ----------------------------------------------
    def run_watchlist():
        wl = WatchlistStore.load(ROOT / "watchlist.json")
        if len(wl) == 0:
            return []
        import yfinance as yf
        prices = {}
        for item in wl:
            try:
                h = yf.Ticker(item.ticker).history(period="5d")
                if len(h):
                    prices[item.ticker] = float(h["Close"].iloc[-1])
            except Exception:
                pass
        return wl.alerts(prices, cfg["watchlist_min_discount_pct"])
    alerts = stage("watchlist", run_watchlist, errors) or []

    # ---- advisory news check on tickets + holdings (display only) ----------
    # Same engine as kala_engine.py's dashboard and the bot's /news command.
    # Deliberately NOT part of the signal: news sentiment has no historical
    # archive, so it can never pass the walk-forward validation every other
    # signal input had to pass. It informs the human, not the engine.
    news_lines: list[str] = []
    if cfg.get("news_check_enabled", True):
        def run_news():
            from kala.news import news_brief
            pt_peek = PaperTrader.load(STATE_PATH, cfg["start_capital_idr"])
            tickers = list(dict.fromkeys(
                [o.ticker for o in pt_peek.pending if o.side == "BUY"]
                + list(pt_peek.positions.keys())))
            return news_brief(tickers, max_tickers=int(cfg.get("news_max_tickers", 6)))
        news_lines = stage("news_check", run_news, errors) or []

    # ---- weekly: fundamental screen (refreshes the watchlist) --------------
    if today.weekday() == cfg["weekly_fundamental_weekday"]:
        def run_fundamental():
            import kala_fundamental_only as fo
            from kala.universe import ALL_SHARIA_STOCKS
            fo.run_value_screening(ALL_SHARIA_STOCKS)
        stage("weekly_fundamental", run_fundamental, errors)

    # ---- quarterly: out-of-sample walk-forward (edge-decay alarm) -----------
    # Replaces the old monthly in-sample backtest on 3 mega-caps. Sends its own
    # Telegram message: the report's VERDICT line is the alarm — if it degrades
    # from quarter to quarter, the edge is decaying and sizing up would be wrong.
    wf_marker, wf_label = quarterly_walkforward_due(today, ROOT / "results")
    if wf_marker is not None:
        def run_quarterly_walkforward():
            import pandas as pd
            import yfinance as yf

            from kala.config import BacktestConfig, Config
            from kala.universe import ALL_SHARIA_STOCKS
            from kala.walkforward import walk_forward
            from run_walkforward import BENCHMARK, fetch

            n = int(cfg["walkforward_max_tickers"])
            step_n = max(1, len(ALL_SHARIA_STOCKS) // n)
            tickers = ALL_SHARIA_STOCKS[::step_n][:n]
            dfs = fetch(tickers, cfg["walkforward_period"])
            if not dfs:
                raise RuntimeError("walk-forward fetch returned no usable data")
            bench = yf.download(BENCHMARK, period=cfg["walkforward_period"],
                                auto_adjust=True, progress=False)
            if isinstance(bench.columns, pd.MultiIndex):
                bench.columns = bench.columns.get_level_values(0)
            bench = bench.dropna(subset=["Close"]) if len(bench) else None

            wf_report = walk_forward(
                dfs, cfg=Config(backtest=BacktestConfig(apply_entry_vetoes=True)),
                benchmark=bench)
            text = wf_report.summary_text()
            out = ROOT / "results" / f"walkforward_{wf_label}.txt"
            out.parent.mkdir(exist_ok=True)
            out.write_text(text, encoding="utf-8")
            send_telegram(tg_token, tg_chat_id,
                          f"📊 QUARTERLY WALK-FORWARD ({wf_label}) — edge-decay check\n{text}")
            wf_marker.touch()
            log(f"Quarterly walk-forward {wf_label} done -> {out.name}")
        stage("quarterly_walkforward", run_quarterly_walkforward, errors)

    # ---- one message with everything ----------------------------------------
    msg = format_daily_message(report, summary, market_status, alerts)
    from kala.edge import entry_signal_warning
    entry_warning = entry_signal_warning(cfg)
    has_buy_ticket = any(t.startswith("BUY ") or "IDEA" in t for t in report.get("tickets", []))
    if entry_warning and has_buy_ticket:
        msg = entry_warning + "\n\n" + msg
    if news_lines:
        msg += ("\n\n📰 NEWS (advisory only — never changes the signal)\n"
                + "\n".join(news_lines))
    from kala.universe import staleness_warning
    stale = staleness_warning()
    if stale:
        msg += "\n\n" + stale

    if scan_warning:
        msg += "\n\n" + scan_warning

    # Weekly friction reminder. Appended to the existing daily message rather
    # than sent separately — an extra notification gets muted, a line in the
    # message you already read does not. Once a week, not daily: the figure
    # moves slowly and daily repetition would train you to skip it.
    if today.weekday() == cfg.get("friction_report_weekday", 4):   # 4 = Friday
        def run_friction():
            from kala.config import CostModel
            from kala.friction import format_friction, friction_report
            raw = json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {}
            if not raw.get("positions") and not raw.get("log"):
                return None
            return format_friction(friction_report(
                raw, costs=CostModel(spread_mode="tick_floor"),
                already_charged=False, today=today.isoformat()))
        friction_text = stage("friction_report", run_friction, errors)
        if friction_text:
            msg += "\n\n" + friction_text

    # Weekly live scorecard: did the trades actually placed beat simply holding
    # the benchmark over each trade's OWN holding window? This is the only
    # out-of-sample test still running — every backtest in this project is
    # finished and null — so it is worth a weekly line even though a live book
    # this small has no statistical power yet. format_scorecard() prints that
    # caveat itself, so it is not restated here.
    if (cfg.get("scorecard_report_enabled", True)
            and today.weekday() == cfg.get("scorecard_report_weekday", 4)):
        def run_scorecard():
            from kala.live_scorecard import weekly_scorecard_text
            raw = json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {}
            # Reuse the histories already downloaded above — no second fetch.
            prices = {t: float(h["Close"].iloc[-1])
                      for t, h in histories.items() if len(h)}
            return weekly_scorecard_text(
                raw, prices, cfg.get("scorecard_benchmark", "XIJI.JK"))
        scorecard_text = stage("live_scorecard", run_scorecard, errors)
        if scorecard_text:
            msg += "\n\n" + scorecard_text

    if errors:
        msg += "\n\n⚠️ Stage errors: " + " | ".join(errors)
    send_telegram(tg_token, tg_chat_id, msg)
    log(f"Run complete. {len(report.get('tickets', []))} tickets, {len(errors)} errors.")


if __name__ == "__main__":
    main()
