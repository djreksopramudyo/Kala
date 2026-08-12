# Kala — how the pieces fit (read this when it feels confusing)

**⚠️ See PROJECT_STATUS.md first.** As of 2026-07-20 the trading signal is
UNVALIDATED — no out-of-sample edge survived honest, point-in-time-correct
testing, confirmed by two independent methods. The project is now archived
as a paper-trading / validation-infrastructure reference, not a live
strategy. Everything below describes how the pieces fit together
mechanically; it does not claim the signal works.

**For day-to-day trading you only ever touch the Telegram bot.** Everything
below is the map of what's underneath, which file to trust, and what the
rest is for.

## The one rule that prevents every confusion

**The composite trading signal lives in ONE place**: `composite_score`
(kala/scoring.py) at threshold 60, gated by `evaluate_entry`'s vetoes
(kala/entries.py). It is what `/scan`, `/run`, and the 17:00 scheduler
compute — so if any other output disagrees with `/scan`, follow `/scan` for
what the SYSTEM would do. That is a statement about internal consistency,
not about whether the signal is profitable — see PROJECT_STATUS.md and
`kala/edge.py`'s module docstring for that answer (currently: no).

## The trading lifecycle = 4 stages

| Stage | What happens | Where it lives | How you trigger it |
|------|--------------|----------------|--------------------|
| 1. Recommend | Scan ~600 sharia stocks with the validated signal | `kala_daily_trader.py` → `kala/scoring.py` + `entries.py` | `/scan` |
| 2. Buy | Record the trade you took | `kala/papertrade.py` (`manual_buy`) | `/buy ANTM 200 1500` |
| 3. Manage | Stop rises as profit grows (4 phases, never loosens) | `kala/exits.py` (`governing_stop`) | `/review` |
| 4. Exit | Stop / target / exit rule hit → SELL ticket | `kala/exits.py` + `live.py` | `/review`, then `/sell ANTM 1650` |

The 4-phase trailing stop: initial (−5%/ATR) → breakeven at +4% → trail 3%
below peak at +8% → tight 2.5% trail at +12%. `/review` shows the phase and
exact stop price per holding.

## Your daily routine on the phone

```
/capital 5jt        ← today's buy budget CEILING (doesn't touch real cash)
/maxpositions 10    ← how many concurrent names to plan around. Each position
                       is capped at budget÷N — a HIGHER N means SMALLER
                       positions. Cash sitting idle despite a full budget
                       usually means this number is too high, not too low
                       (check /status: it shows the per-slot cap directly)
/deposit 3jt        ← add REAL money mid-cycle (raises cash + start capital,
                       so the deposit never shows up as a "gain")
/scan               ← today's ranked BUYs, sized to budget (read-only).
                       Price line shows a likely OPEN RANGE, not one number —
                       each stock's own historical open-vs-prior-close gap
                       (IDX's pre-opening auction moves the real open away
                       from last close by an amount that varies per ticker)
/priority           ← ONE ranked to-do list merging /review + /scan: SELL
                       NOW > TAKE PROFIT > ADD TO WINNERS > NEW BUY IDEAS,
                       numbered, best score first within each tier. Start
                       here if reading both reports separately is confusing
/buy ANTM 200 1500  ← record what you actually bought; buying a ticker you
                       already hold ADDS to it (blended average price)
                       forgot to log it? append @date to backdate it:
                       /buy ANTM 200 1500 @kemarin | @3 hari lalu | @2026-07-10
/review             ← HOLD / SELL / "could add" for everything you own,
                       with held bars vs the max-hold rule shown per position.
                       "could add" is now SIZED (shares + a ready /buy line,
                       same math /scan uses). A take-profit hit also offers
                       trimming HALF the position — advisory, not a
                       backtested rule; the auto-queued order still sells
                       100% on this trigger, unchanged.
/sell ANTM 1650     ← sell the WHOLE position (realised P/L); @date works too
/sell ANTM 100 1650 ← sell PART of it (take-profit); rest keeps its cost
                       basis. Price can be a decimal either way (1650.5).
/undo               ← typed the wrong number on /buy, /sell, or /deposit?
                       revert it (keeps the last 5); /redo brings it back
/history 10         ← your last N closed trades, most recent first
/edge               ← live track record vs the VALIDATED backtest numbers
                       (EV/trade, win rate, hold time). Small-sample honest:
                       under 10 closed trades it says TOO EARLY instead of
                       crying wolf. |t|>=2 vs expectation = re-validate.
                       Expected numbers live in kala/edge.py, override
                       via "edge_expectations" in runner_config.json after
                       each re-run of compare_exit_engines.py
/checkstop          ← RIGHT NOW: has any HELD position hit its stop, target,
                       or a limit-down band? ALSO lists every position's
                       stop-loss AND take-profit target, not just breaches —
                       "when to sell" has two sides (cut the loss or lock in
                       the gain) and both are shown at a glance. Same
                       detection logic the 15-min scheduled push watcher
                       uses (intraday_watch.py + setup_intraday_scheduler.ps1
                       — set that up too if you want it pushed to you
                       automatically instead of asking), just on demand.
                       Quotes are delayed ~15min, NOT real time.
/positions /status  ← holdings (with days held) / equity vs IHSG
/news ANTM          ← headlines + sentiment (ADVISORY ONLY — never a signal)
/run                ← full daily cycle: manage exits + list BUY ideas
                       (does NOT auto-buy unless auto_paper_trade=true)
/reset              ← wipe cash/positions/history to a clean slate
                       (2-step: /reset previews, /reset confirm executes)
```

Nothing opens a position by itself: `/scan` and `/run` only recommend, and a
position exists only after YOUR `/buy` (unless you set `auto_paper_trade`
to true in runner_config.json for a hands-off simulated benchmark book).

## What runs automatically (`daily_run.py`, 17:00 via Task Scheduler)

- **Daily**: scan → paper-trade within budget → exits → watchlist dips →
  advisory news check on tickets+holdings → ONE Telegram message.
- **Weekly** (Sat): fundamental value screen refreshes `watchlist.json`.
- **Quarterly** (first weekday of Jan/Apr/Jul/Oct): out-of-sample
  walk-forward on a 60-ticker sample — **the edge-decay alarm**. If its
  VERDICT degrades quarter over quarter, the edge is fading: don't size up.
- Every daily message also warns if the ISSI list is stale
  (`UNIVERSE_UPDATED` in `kala/universe.py` — set it when you refresh
  the list; IDX revises ~May & ~Nov).

## Validation & research tools (run occasionally, not daily)

- `run_walkforward.py` — is the edge real, out-of-sample? (`--apply-entry-vetoes`
  for the realistic version). The quarterly autopilot runs this for you.
  `--tick-spread` floors the spread cost at half an IDX tick at the fill
  price — cheap stocks can't trade tighter than their tick (a 67-rupiah
  stock's 1-rupiah tick is a ~1.5% spread vs the 0.10% flat assumption
  every historical number used). CAUTION: `--min-price` filters on each
  ticker's LATEST close only, not point-in-time — a 2026-07 run that
  appeared to confirm a real >= IDR 1,000 edge (n>2,100, |t| >= 2.9) turned
  out to be a look-ahead artifact of that filter (currently-expensive
  stocks are mechanically ones that went up) and was retracted after
  `compare_exit_engines.py`'s point-in-time vetoes measured the same tier
  negative instead. `EntryConfig.veto_cheap_stock` / `min_price_idr`
  (default on, IDR 1,000) stays on as a cost-hygiene default, not as a
  demonstrated-edge claim. See `kala/edge.py`'s module docstring for
  the full sequence and what would actually settle it.
- `run_portfolio_sim.py` — the per-trade edge under real capital constraints
  (slots, cash, lots, ADV cap). Verdict from the full study: `max_positions`
  is a risk knob, not a return knob; every setting 3–15 beat IHSG; expect
  ~30% max drawdowns.
- `diagnose_bear_folds.py` / `diagnose_entry_param_sweep.py` — the studies
  that proved the entry vetoes help and that loosening them doesn't.
- `run_ml_walkforward.py` / `run_ml_walkforward_nested.py` — the fitted-model
  experiments. Verdict: no ML edge survived honest validation; kept for
  reproducibility, not for use.
- `reset_paper.py --capital 5000000 [--sync-config]` — start a fresh, honest
  paper track record (backs up the old state first).

## Housekeeping

- `tidy_repo.py` — dry-run by default; `--apply` archives old `results/`
  output + stray artifacts into `results/archive/` and clears caches. Never
  touches state, config, or source.
- `cleanup_repo.sh` — the git-side equivalent (untrack junk, .gitignore).

## Legacy / secondary (fine to ignore)

- `kala_engine.py` — the original all-in-one **research dashboard**
  (fundamentals, macro, news sentiment). Its multi-factor blend was never
  backtested; it now runs the same entry vetoes so it can't recommend what
  the live system would refuse, and its banner says exactly this. Research
  color, not signals.
- `kala_fundamental_only.py` + `check_watchlist.py` — the separate
  value-investing screen (feeds the watchlist; also run weekly by the
  scheduler).
- `check_my_stocks.py` — superseded by `/buy` + `/review`.
- `intraday_watch.py` — read-only 15-min alerts (stops/ARB/TP/dips) during
  market hours; never places or signals trades.
- `portfolio_optimizer.py` — position-sizing math behind interactive menus.
- `test_ping.py` — one-off Telegram credentials check.

## What "more return" actually means here (hard-won, don't relearn it)

Signal tuning is DONE: weights, thresholds, entry params and ML alternatives
were all tested to their honest end — every "improvement" beyond the current
config failed out-of-sample. The remaining levers are: let the paper track
record accumulate (~20–30 closed trades) before real money, watch the
quarterly verdict, keep the ISSI list fresh, and size real capital in steps.
Anything that "improves the backtest" beyond this should be treated as
overfitting until it survives the same walk-forward gauntlet.
