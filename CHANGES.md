# kala — what changed

> **Validation status is NOT tracked here.** For "does the signal work?" the
> canonical answer is `PROJECT_STATUS.md`. Short version, corrected 2026-08-17:
> the composite score DOES select out-of-sample once the exit ladder is
> removed (+2.90 pts/trade excess in the liquid half, clustered t +4.31,
> monotone dose-response, zero control at threshold 0) — but the result is
> concentrated in a few quarters, has a 30% win rate with a negative median
> trade, and has never been run forward. The previous banner here said "no
> demonstrated out-of-sample edge"; that was measured THROUGH the ladder,
> which is itself significantly negative. This file is a changelog of *what
> was built*, not a claim that any of it is profitable.

## 1. New package `kala/` (all 22 of your tests pass)

Your test suite was the spec; the package now satisfies it. Run it yourself:

```bash
cd /path/to/this/folder
pytest -q          # 22 passed
```

Bugs fixed (each was live in `kala_daily_trader.py` and is covered by a test):

| Bug | Old behaviour | Fix | Module |
|---|---|---|---|
| Urgency downgrade | a later CONSIDER rule overwrote an earlier URGENT | final urgency = **max** over all fired rules | `exits.py` |
| Death cross as state | flagged "DEATH CROSS today" every day below trend | fires only on the **crossing bar**; below-trend is `[ADVISORY]` | `exits.py`, `indicators.cross_below` |
| MACD absolute threshold | `hist < -0.05` (IDR) — meaningless across price levels | scale-invariant `hist_pct` | `indicators.macd` |
| `compute_features` mutation | wrote columns into the caller's DataFrame | returns a copy; input untouched | `scoring.py` |
| RSI panic = URGENT | sold the capitulation low | `[ADVISORY]` only | `exits.py` |
| RSI / ATR via simple mean | non-standard values | **Wilder's** smoothing | `indicators.py` |
| ADX +DM/-DM sequencing | -DM compared to a zeroed +DM | computed from **raw** moves | `indicators.adx` |

## 2. Limit-down ("ARB") realism in the backtest

`backtest.py` will not fantasy-fill a stop on a locked limit-down bar. It carries
the position (counted in `arb_locked_bars`) until the first tradable bar.
Verified: a two-bar lock books **−27.7%**, not the nominal −5% stop.

## 3. Asymmetric IDX cost model

`config.CostModel` charges buy fee, sell fee, **sell tax**, and spread on the
correct legs. Verified: a flat round-trip loses exactly
`buy + sell + tax + 2·spread`.

## 4. Migration into the scripts

- **Universe deduped.** The 672-ticker `ALL_SHARIA_STOCKS` list was copy-pasted
  in all three scripts (~7.6 KB each). All three now
  `from kala.universe import ALL_SHARIA_STOCKS`.
- **`kala_daily_trader.py` exit logic delegated.** `check_exit_signals`
  now calls `kala.live.evaluate_position`, so the script you actually run
  (and that `check_my_stocks.py` imports) is backed by the tested engine. The
  return-dict contract is unchanged. `get_live_signal` now also returns the raw
  OHLCV under `_history` so no second download is needed.

### What I deliberately did NOT do (so you can review, not trust blind)

- `kala_engine.py` and `kala_fundamental_only.py` still contain their own
  inline indicator/scoring code — I only deduped their universe. Porting their
  signal logic to `kala.*` is the same delete-and-delegate move applied to
  `check_exit_signals`, and is the next step.
- The scripts' live network paths (yfinance) can't be exercised here, so the
  delegation was validated offline against synthetic histories. Smoke-test it
  on one real position before trusting it end to end.

> Caveat: these fixes make the backtest **more honest**, which usually means it
> looks **worse** before it looks better. That's the point. This is code review,
> not financial advice.

---

# kala_engine.py — council follow-up (v3.0)

The multi-factor script now practises what the daily trader does.

1. **Backtests the strategy you actually trade.** `run_backtest` no longer runs
   `ShariaStrategy` (a crossover-only system with no stops) and no longer
   curve-fits SMA periods in-sample. It routes through `kala.backtest_ticker`
   — composite-score entries, the trailing-stop ladder, IDX limit-down carry,
   and asymmetric costs — so the number you validate is the number you run.
   `print_results` is unchanged (fed a compatible stats dict). Expect the figures
   to look *worse* than the old crossover backtest; the old ones were fiction.
   `ShariaStrategy` is kept but marked DEPRECATED.

2. **Scraped factors fail loudly.** Previously a failed fundamentals/news scrape
   fell back to a fake-neutral 50 and silently dragged every score toward the
   middle (~35% of the weight on a bad day). Now unavailable factors are
   **dropped and the remaining weights renormalised**, and the result carries
   `data_quality` ("FULL" / "DEGRADED: scored without fundamental, sentiment")
   and `degraded_factors`. In testing, dropping two failed factors moved a score
   from a diluted 62.5 to its true 69.2 — a ~7-point hidden distortion.

3. **`calculate_live_indicators` ported to the package.** No longer mutates the
   caller's DataFrame; uses Wilder's RSI via `kala.indicators`.

4. **Survivorship bias flagged (not silently ignored).** `universe.py` now
   carries a `UNIVERSE_IS_POINT_IN_TIME = False` flag and a warning, and
   `analyze_watchlist` prints a caveat: the list is *current* DES membership, so
   multi-year backtests over it are optimistic. Real fix needs point-in-time DES
   constituents, which IDX revises ~twice a year — supply those to remove it.

---

# Buy-side guardrails (v3.1) — the missing half

The exit engine was tested; the BUY scanner wasn't. Because it scores momentum,
it rewarded stocks that had already surged — and made PTPW (+46% in 20 days, RSI
78.6, OBV distribution, 1.13x volume, BEARISH market) its single top pick the day
before it dropped.

New `kala/entries.py` (`evaluate_entry`) turns the worst red flags into hard
VETOES; a BUY that trips any of them is downgraded to HOLD:

  * overbought (RSI >= 75)
  * parabolic / already extended (+25% over 20 sessions)
  * OBV distribution (price up while volume distributes)
  * surge not confirmed by volume (thin / illiquid)
  * bearish market regime

Thresholds live in `config.EntryConfig`. Covered by `test_entries.py` (7 tests,
incl. a PTPW-shaped regression), and wired into `kala_daily_trader.py`'s
buy dashboard. On a faithful PTPW reconstruction the candidate is now rejected on
FOUR independent grounds. Full suite: 29 passing.

Note: `kala_engine.py`'s screener has the same buy logic and would take the same
one-block wiring — not yet applied.

---

# Final consistency pass (v3.1)

- **Daily trader backtest migrated.** `kala_daily_trader.py`'s `run_backtest`
  no longer runs the crossover `ShariaStrategy` through backtesting.py with
  in-sample SMA optimization. Like `kala_engine.py`, it routes through
  `kala.backtest_ticker` (live ruleset: stops, trailing, ARB carry, honest
  costs). There is now NO misleading backtest left anywhere in the project.
- **`ShariaStrategy` retired** in both scripts (reduced to a deprecated name stub).
- **Dead dependencies removed.** `pandas_ta` and `backtesting` are no longer used;
  their imports are guarded (a missing/broken install can't block the scripts) and
  both were dropped from `requirements.txt`. Only genuinely-used packages remain.

---

# Alpha measurement + watchlist memory (v3.2)

**1. Benchmark-relative alpha reporting.** `backtest_ticker` now uses its
`benchmark` parameter (previously a stub): pass an IHSG frame and the result
carries `buy_hold_return_pct`, `benchmark_return_pct`, `alpha_vs_buy_hold_pct`
and `alpha_vs_benchmark_pct`. Both scripts' `run_backtest` auto-fetch a cached
^JKSE benchmark (gracefully skipped offline) and print the verdict:
strategy return vs holding the ticker vs holding the index. Without this the
system could not answer the only question that defines alpha: did all the
signals, stops and costs beat doing nothing?

**2. Watchlist with thesis memory (`kala/watchlist.py`).**
`WatchlistStore` persists BUY-grade names with fair value + a one-line thesis.
`kala_fundamental_only.py` now saves its BUYs to `watchlist.json`
automatically after each screen, and the new `check_watchlist.py` alerts when a
researched name dips >= 15% (configurable) below your saved fair value —
research once, act when price cooperates. Alerts are re-check signals, not
blind buys: a big discount can mean a bargain OR a broken thesis.

Tests: `tests/test_alpha_watchlist.py` (6 new). Full suite: 35 passing.

---

# Automation: rungs 1–3 (v3.3)

**`daily_run.py`** — one orchestrator on the right cadence: DAILY buy-scan ->
paper-trade within your allocation -> exit checks -> watchlist dips -> one
Telegram message with tomorrow's order tickets; WEEKLY (Sat) fundamental screen;
MONTHLY backtest validation with alpha vs IHSG. Stages are isolated — one
failure can't kill the run. Capital: edit `daily_capital_idr` in
runner_config.json any evening, or `python daily_run.py --capital 3000000`.

**`kala/papertrade.py`** — automated paper trader: signal at close t,
fill at open t+1 with the honest cost model, IDX lots of 100, risk-based sizing
capped by your allocation, exits via the tested engine, JSON state, live track
record directly comparable to the backtest.

**`kala/notify.py`** — Telegram tickets ("SELL X — 1,000 shares at open |
stop breached"); degrades to console if unconfigured, never blocks the run.

**`setup_scheduler.ps1`** — registers "Kala Daily Run" (Mon–Sat 17:00 WIB)
using THIS project's .venv explicitly.

runner_config.json (holds your Telegram token) + paper_state.json are
gitignored. Tests: tests/test_papertrade.py (6 new). Suite: 41 passing.
No real orders are placed anywhere — rung 4 stays locked behind the broker
wall and this paper track record.

---

# A failed IHSG fetch was not a bear market — it was no market at all (v4.0)

Found while chasing why a scan logged `Market_Status: UNKNOWN`.

`check_market_health` returned `status='UNKNOWN'` whenever the `^JKSE` download
raised, came back empty, or returned fewer than 50 bars. But `'UNKNOWN'` was
already taken: `regime.classify_market_regime` emits it for benchmark warm-up
bars, and the entry veto deliberately lets those through — otherwise the first
49 bars of every backtest would veto every candidate. One string, two meanings,
and the veto could not tell them apart:

```python
if cfg.block_buys_in_bear and market_status in cfg.bear_statuses:   # ("BEARISH", "MODERATE_BEAR")
```

`'UNKNOWN'` is not in that tuple, so a failed fetch scored as *not bearish* and
every BUY sailed through the regime gate.

That gate is the only hard regime protection the live scanner still has. The
soft score multiplier was retired on purpose — the comment above the call says
regime risk "is handled by the hard `block_buys_in_bear` veto in
`evaluate_entry` below". So the fallback that used to blunt a bear tape is gone,
and the veto that replaced it silently stopped firing. A momentary network blip
removed regime protection **entirely**, and printed a tidy, normal-looking scan
while doing it. `exits.py` carried the same hardcoded bear list, so a blind run
also stopped flagging losers it would otherwise have flagged.

Reproduced on all three failure paths (network error, empty frame, short
history): status `UNKNOWN`, multiplier `1.0`, `buy_allowed=True` on a candidate
that a `BEARISH` tape correctly vetoes.

**The fix is to stop conflating the two unknowns**, not to add `'UNKNOWN'` to
`bear_statuses` — that would have made warm-up bars veto everything and moved
every backtest number.

  * `'UNKNOWN'` — *not knowable yet* (warm-up). Still fails **open**.
  * `'UNAVAILABLE'` — *we tried to look and failed*. Now fails **closed**.

`classify_market_regime` never emits `UNAVAILABLE`, so it is a live-path
sentinel only and **no backtest or walk-forward number changes**. Off switch:
`EntryConfig.block_buys_when_regime_unavailable` (default `True`).

Tests (`tests/test_regime_unavailable.py`, 13 new) pin both halves — the
consumers reacting to `UNAVAILABLE` *and* the producer actually emitting it.
That second half matters: with only consumer tests, reverting
`check_market_health` to `'UNKNOWN'` would have restored the bug with the whole
suite still green. Each of the three parts of the fix was reverted in turn and
the matching tests went red.

> Same shape as the earlier findings: the arithmetic was never wrong. A failure
> was spelled the same way as a benign state, and the guard read it as consent.

---

# A trade with no P&L is not a breakeven trade (v4.1)

Hardening found while auditing `edge.py`. **Latent, not live** — every current
writer in `papertrade.py` populates `pnl_pct`, and the log only ever holds
sells, so this could not fire today. It is closed because the trap is silent
and the log outlives the code.

`live_stats` scored the track record with:

```python
returns = [float(t.get("pnl_pct", 0.0)) for t in log]
```

`0.0` is not a neutral placeholder — it is a real observation meaning "this
trade broke exactly even," and it lands in the one number that judges whether
the system still works. An entry missing `pnl_pct` would have:

  * inflated `n`, which gates `MIN_TRADES_FOR_VERDICT` (10) — phantom rows can
    carry a log over the threshold and trigger a verdict that should not exist;
  * pulled `ev_pct` toward zero (demo: `+0.775%` -> `+0.387%`);
  * shrunk `std_pct`, the denominator the t-statistic divides by;
  * counted as a **loss** in `win_rate_pct`, since wins are `r > 0`.

Demonstrated on a 12-trade log padded with 12 unscoreable rows: t moved
`+0.11` -> `-0.94` and reported live EV halved, while the report still read
`ON TRACK`.

What makes this worth closing rather than noting: three lines below, the same
function already does it right. Hold time skips entries without `entry_date`
and publishes `n_with_hold`, precisely because `entry_date` only arrived in
v3.4 — proof that this persisted, long-lived log's schema does grow, and that
the next added field will meet the same `.get(..., default)` shape.

Now an entry without a usable `pnl_pct` (missing, `None`, NaN, unparseable) is
excluded rather than scored, and `n_skipped_no_pnl` reports how many were
dropped — so a shrinking sample is visible instead of invisible. Numeric
strings still parse, since this JSON state has been hand-edited before.

A strict no-op on every well-formed log: `test_real_trades_are_unaffected`
pins that. Tests: `tests/test_edge_missing_pnl.py` (6 new); restoring the
`0.0` default turns 4 of them red.

---

# A broker-flow day we failed to fetch is not a zero-flow day (v4.2)

Found auditing the archive modules. Two halves of one defect, and unlike the
`edge.py` item this one is **live** — the 2-year foreign-flow backfill already
ran, so any holes it took are already on disk.

**Holes form silently.** `InvezgoClient._get` retried `429` only. A `500`/`502`/
`503`/`504`, a timeout, or a dropped connection escaped to
`fetch_daily_foreign_net`'s per-day `except Exception: log_swallowed; continue`
— the day was dropped. That is the same `continue` a genuinely empty day takes,
so **a failed fetch and a no-activity day are indistinguishable on disk.**

**Holes are then invisible.** `covered_range` only reads MIN and MAX stored
date. If the first and last day of a backfill succeeded, a range riddled with
holes reports as fully covered, `get_or_fetch` short-circuits to the cache, and
the gap is never re-fetched. Permanent.

**Holes then become a number.** `compute_features_foreign_flow` summed the
window with missing days filled as `0.0` and published the result whenever
**one** real observation was present:

```python
filled   = raw.fillna(0.0)
have_any = raw.notna().rolling(CUM_WINDOW, min_periods=1).sum()
flow_cum = filled.rolling(CUM_WINDOW, min_periods=1).sum().where(have_any > 0)
```

Four fabricated zeros and one real day produced a "5-day cumulative flow"
indistinguishable from five measured days.

The damage was not dilution, it was **scale**. A summed window shrinks in
proportion to what is missing, and `flow_z` normalizes it against a 20-day norm
built mostly from fully-covered windows — so a *coverage* artefact is read as a
change in *flow*. Measured on a 40%-holey series: the estimator came in at
**0.613x** the true cumulative flow, published on 392 of 400 bars. On the
reproduction quarter `flow_z` went **+1.54 -> -1.01** and the score **61.5 ->
0.0**: sustained net foreign BUYING read as net SELLING.

Fixes:

  * `_get` retries `5xx` and transient network errors with the same backoff as
    `429` — the docstring's own argument for `429` ("sleeping here, not raising,
    is what makes a big sequential backfill self-heal instead of quietly losing
    days") applies unchanged. `429`/`Retry-After` semantics are untouched, and a
    persistent failure still raises.
  * `fetch_daily_foreign_net` counts days lost after retries and prints a
    warning naming them as GAPS, so a holey backfill cannot pass for a clean one.
  * `compute_features_foreign_flow` takes the mean over the days actually
    OBSERVED and scales it to the window, instead of summing fabricated zeros.
    That is unbiased at any coverage (measured 1.000x), so windows stay
    comparable; `min_periods` counts only real days, so a window too thin to
    estimate from stays NaN — which the backtest already reads as do-not-enter.

> Worth re-reading in light of this: the bandarmology result is recorded as
> INCONCLUSIVE (PROJECT_STATUS.md). That verdict was computed off this archive.
> A signal whose magnitude was being scaled by fetch reliability is not a clean
> test of the hypothesis — re-running it on a re-fetched archive is the honest
> way to settle what that result actually was.

Tests: `tests/test_flow_gaps_not_zero.py` (15 new). Reverting the retry list
turns 6 red; reverting the estimator turns 2 red, including the bias check.

---

# The untagged count disagreed with the bucket it described (v4.3)

Last unaudited module. A reporting defect, not a strategy one — but it lives in
the report that decides whether the edge is real or just a bull-market artefact,
so an over-confident reading of it is expensive.

Two different things are untaggable, and both land in the same `'UNKNOWN'`
bucket:

  * an entry BEFORE the benchmark's first bar — `regime_at` returns `None`;
  * an entry inside the benchmark's SMA50 WARM-UP — the *string* `'UNKNOWN'`
    (`regime.classify_market_regime` sets it for the first 49 bars).

`n_untagged` incremented only on `status is None`, so warm-up trades were
bucketed as untagged but never counted as such. The table's `UNKNOWN` row and
the footer then reported different numbers for the same trades, and the footer
was the smaller one. Its label — "before benchmark warmup" — described only the
first route while silently omitting the second.

It bites whenever the benchmark's history is shorter than the tickers' (pass a
3y `^JKSE` against 5y of prices and every trade in the benchmark's first 49
bars is silently uncounted). Verified both routes directly:
`regime_at(reg, before_start) -> None` vs `regime_at(reg, warmup_bar) ->
'UNKNOWN'`.

`n_untagged` now counts both, so it equals the `UNKNOWN` row by construction,
with `n_before_benchmark` / `n_in_warmup` giving the split. The footer states
the share, and a run where >= 20% of trades carry no regime tag prints a
warning instead of a confident-looking per-regime table.

Tests: `tests/test_regime_breakdown_untagged.py` (6 new); reverting to the
single-route count turns 4 red.

---

## Audit closed

Every module on the list has now been read. Findings, in order:

| # | Module | Status |
|---|---|---|
| 1 | `kala_daily_trader.check_market_health` | **live** — IHSG fetch failure opened the bear gate |
| 2 | `edge.live_stats` | latent — missing `pnl_pct` scored as a breakeven trade |
| 3 | `invezgo_fetch` + `strategy_foreign_flow` | **live** — failed fetch read as zero foreign flow |
| 4 | `regime_breakdown` | reporting — untagged count disagreed with its own bucket |

Audited clean: `friction`, `scoring`, `indicators`, `entries`, `exits`,
`config`, `portfolio_analytics`, `regime_filter`, `positions`, `ml_scoring`,
`heartbeat`, `notify`, `intraday`, `watchlist`, `strategies`, `warehouse`,
`sentiment_archive`, `fundamental_archive`, `broker_flow_archive`.

Open hardening, deliberately not fixed (both fail LOUD, which is the correct
mode): `warehouse.upsert` / `broker_flow_archive.upsert` raise `IntegrityError`
on a NaN in a `NOT NULL` column; `PositionStore.save` / `WatchlistStore.save`
write non-atomically, so a torn write loses the `peak_price` the trailing stop
ratchets against.

---

# Measuring the archive before re-fetching it — and a correction (v4.4)

The v4.2 note ended by suggesting the INCONCLUSIVE bandarmology verdict might
be an artefact of the zero-flow bug. **That was over-stated.** The bug is real
and the fix stands, but measured against the actual archive
(`results/broker_flow.db`, 16,304 rows / 68 tickers / 2024-08 to 2026-07) its
effect is far too small to have manufactured that verdict.

WHAT THE ARCHIVE ACTUALLY LOOKS LIKE
-------------------------------------
Of 515 business days in the window, **47 are absent for every one of the 32
full-span tickers** — those are IDX market holidays, not fetch failures, which
leaves 468 real trading days. Against that denominator:

  * mean coverage **96.7%** (min 64.3%, max 100%)
  * 27 of 32 tickers at >= 95%
  * 490 isolated (ticker, date) holes — the scattered kind the old guard missed

The v4.2 reproduction used a 40%-holey series. That was a stress test chosen to
make the mechanism visible, not a description of this data, and reading it as
one was the error.

WHAT THE BUG ACTUALLY COST
---------------------------
Old estimator vs new, on the real series:

  * bars whose 5-day window is FULLY covered — 74.3% — identical (ratio 1.000)
  * bars whose window is HOLEY — 25.7% — old understated cumulative flow by
    **20% (median), 27% (mean)**
  * aggregate: z-score correlation **0.989**, BUY-threshold days 1403 -> 1336,
    disagreement on **1.9%** of 14,026 bars

So the bias is real, confined to a quarter of bars, and moves ~2% of signals.
That will not turn an inconclusive result into a conclusive one. A re-run is
still worth doing on clean data — but as housekeeping, not because the verdict
is in doubt.

`refetch_flow_gaps.py`
-----------------------
Fills only the missing cells. `fetch_daily_foreign_net` costs one API call per
ticker per day, so a fresh 2-year backfill of the cohort is ~15,000 calls
against a 30,000/month budget; the measured gap set is **490**. Market holidays
are excluded by default — re-fetching them spends calls to re-learn the market
was closed.

    python refetch_flow_gaps.py --dry-run      # free, reports the plan
    python refetch_flow_gaps.py                # fills; needs the token

`--dry-run` is the default posture: it makes no calls. `--max-calls` (2000)
refuses to start on a runaway set, and the run reports mean coverage before and
after. Tests: `tests/test_refetch_flow_gaps.py` (5 new) — the load-bearing one
pins that a date absent for EVERY ticker is classified as a holiday, not a gap.

---

# A missing archive is not a strategy result (v4.5)

A real run of `--strategy foreign_flow` reported:

```
broker-flow: merged foreign_net_value/... onto 0/29 ticker(s)
VERDICT: INCONCLUSIVE — too few OOS trades to judge the edge.
```

There was no archive at that path. sqlite creates a database file on connect,
so `BrokerFlowArchive(path)` produced a valid, EMPTY archive; it merged onto 0
tickers, generated 0 trades, and the runner printed a verdict *about the edge*.
The cause was a missing file, and the output named the strategy.

Three layers each hid it, and all three are the pattern this audit has been
chasing — a failure wearing the costume of a result:

1. **The archive created itself.** No way to tell "you pointed me at nothing"
   from "the vendor has no rows".
2. **`attach_foreign_flow` swallowed every exception** (`except Exception:
   stored = None`), so a corrupt file or schema mismatch was indistinguishable
   from an empty one.
3. **The verdict printed anyway**, converting a data outage into
   `INCONCLUSIVE`, which is a claim about the hypothesis.

Fixes:

  * `BrokerFlowArchive.created_empty` records whether the file had to be
    created, plus `row_count()`.
  * `attach_foreign_flow` logs the swallowed exception via `log_swallowed`
    instead of discarding it. Still non-fatal — a partial archive must stay
    runnable — but no longer invisible.
  * `run_walkforward` refuses to run and exits 1 on: a database it had to
    create, an existing-but-empty one, or an archive whose tickers do not
    intersect `--tickers` at all. Each message prints the RESOLVED absolute
    path, and the ticker mismatch lists what the archive actually holds.

The verdict line is now reachable only when there was real data to judge.

Tests: `tests/test_missing_archive_is_not_a_verdict.py` (6 new).

> Note for anyone rebuilding from a zip: `results/broker_flow.db` is NOT in the
> Kala zips — it is committed to the Kala repo. A tree restored from a zip
> alone has no archive, which is exactly how this run happened.

## State files that could be lost silently (2026-08-16)

The forward test is the only remaining answer to the survivorship objection.
It runs for months over state files that could be destroyed, or simply not
found, without anything reporting a loss. Fixed before the test, not after it
returns an unreadable result.

`len(watchlist) == 0` meant four different things at once: nothing researched
yet, the process is running in another directory, the file was truncated by an
interrupted save, or the watchlist really is empty. Callers received the same
number in each case and three of them swallowed the difference outright. Full
measurement and consequences in `PROJECT_STATUS.md` -> "State-file durability".

Fixes:

  * `WatchlistStore.save` and `PositionStore.save` write tmp-then-`os.replace`
    and create missing parent directories. `write_text` truncates the target
    before writing, so an interrupted save left the research nowhere on disk.
    `papertrade.py` has used this discipline since v3.x; these two never got
    it. `PositionStore` holds `peak_price` — a running maximum accumulated
    across sessions, with no other source to recompute it from.
  * `WatchlistStore.load` sets `load_note` with the RESOLVED absolute path
    when the file is absent. It still RAISES on a file that exists but will
    not parse; that loudness is correct and was not softened.
  * `kala/watchlist.load_or_report()` is the opt-in for callers that must
    survive a damaged file. It degrades exactly as before and reports instead
    of swallowing.
  * New `kala/universe_sources.py` holds one copy of the
    positions-plus-watchlist selection that `archive_sentiment`,
    `archive_fundamentals` and `foreign_flow_monitor` each carried their own
    version of, each ending both reads with `except Exception: pass`. It still
    degrades rather than aborting a run, and names every degraded source —
    plus a warning that an incomplete point-in-time archive cannot be
    backfilled.
  * Those three scripts plus `check_watchlist.py` anchor `WATCHLIST_PATH` and
    `STATE_PATH` to `Path(__file__).parent`. Measured before the fix: the same
    command returned 3 names from the repo root and 0 from one directory up.
  * `check_watchlist.py` distinguishes an absent file from an empty one — it
    used to advise redoing research that was already done — and now uses
    argparse; `--help` previously raised
    `ValueError: could not convert string to float: '--help'`.
  * `daily_run.py`'s dip-alert step says when the watchlist file is missing
    rather than reporting zero alerts, which looks like a quiet week.
  * `docker-compose.yml` mounts `watchlist.json`. The weekly Saturday screen
    writes it INSIDE the container; without the mount every `up --build`
    discarded it.
  * `DOCKER.md` no longer says `touch paper_state.json runner_config.json`. A
    zero-byte file is not valid JSON and all three loaders raise on one — the
    documented procedure produced a container that died on first run.
    `paper_state.json` also cannot be seeded with `{}` (`PaperTrader.load`
    raises `KeyError: 'cash'`), so the doc calls `reset_paper.py`, which
    writes the correct skeleton.

Tests: `tests/test_state_files_are_durable.py` (20 new). Suite 1635 passed,
1 skipped.

Evidence you can run yourself, shipped in `repro/`:

```bash
python repro/repro_watchlist_silence.py      # the four states, old vs new
python repro/mutate_state_durability.py      # 8 defects reinserted; all 8 go red
```

## Circuit-breaker state loss is now visible (2026-08-17)

`load_breaker_state` answered `(None, False)` for both a sidecar that does not
exist yet and one that exists but will not parse. On a halted account the
second case silently resumed buying — the peak re-anchored to today, drawdown
read 0.0% instead of 30%, and the run reported "First run". Details and the
measurement in `PROJECT_STATUS.md` -> "Circuit-breaker state loss".

The DEFAULT is unchanged (re-anchor, do not halt); that was a documented choice
with a test behind it. What is new:

  * `read_breaker_state()` -> `BreakerLoad(peak, halted, existed, error)`,
    keeping "absent" and "damaged" apart.
  * `evaluate_breaker(state_lost=True)` + `BreakerConfig.
    preserve_halt_when_unreadable` (default False, config key
    `breaker_preserve_halt_when_unreadable`) to fail closed instead.
    A separate input is required because carrying `was_halted=True` alone does
    nothing — with no stored peak the drawdown reads 0% and the hysteresis
    branch resumes immediately.
  * `daily_run` prints `⚠️ BREAKER STATE LOST` with the parse error.

Tests: `tests/test_breaker_state_loss_is_visible.py` (10 new). Suite 1645
passed, 1 skipped.

## Partial Telegram delivery is now visible (2026-08-17)

Long daily messages are split across several requests. A failure on part 2 of 3
left part 1 in the chat and returned a bare `False`, which cannot distinguish
"nothing sent" from "half sent". `daily_run` discarded that return value and
logged "Run complete. N tickets, 0 errors" either way. Measured detail in
`PROJECT_STATUS.md` -> "Partial Telegram delivery".

  * `send_telegram_detailed()` -> `Delivery(ok, sent_chunks, total_chunks,
    error)`, with `partial` and a never-blank `describe()`.
  * Split messages are labelled `(i/N)`, so a message that stops at `(1/3)` is
    visibly incomplete on the phone. Single-part messages stay unlabelled.
  * `send_telegram()` keeps its bool signature (three callers rely on it); a
    partial send returns False.
  * `daily_run` counts a failed or partial send as a stage error and puts the
    outcome in the log line.

Tests: `tests/test_telegram_partial_delivery.py` (9 new). Suite 1654 passed,
1 skipped.

    python repro/repro_partial_telegram.py    # 1 of 3 parts, old vs new

## Payoff and holding-horizon reporting (2026-08-17)

`discipline_report.py` now prints two things the P&L column cannot show, both
computed from the log alone (no network, so they work without
`--counterfactual`):

  * `payoff_arithmetic()` — avg win / avg loss, the payoff, and the win rate
    that payoff needs to BREAK EVEN, side by side. "56% of trades win" is not
    a result until 54.8% is on the line next to it. A margin inside ±5 points
    is labelled as noise rather than reported as an edge.
  * `holding_horizon_gap()` — realised holding periods against the configured
    limit, with `n_reached_rule`. `rule_days` follows the live `exit_profile`.

The per-bucket P&L table always prints its selection caveat: a stop-loss closes
losers early by construction, so longer buckets are pre-selected for survivors
and a rising gradient is not evidence that patience pays. A test asserts the
caveat is present so it cannot be separated from the table later.

Measured on the live log: expectancy +0.105%/trade, margin +1.2 pts over 25
trades, and 0 of 23 trades reached the validated 60-bar horizon. See
`PROJECT_STATUS.md` -> "The live log, measured".

Tests: `tests/test_payoff_and_horizon.py` (12 new). Suite 1666 passed, 1 skipped.

## The ATR fallback is now named (2026-08-17)

`governing_stop` returned the label `"fixed/atr stop"` for three different
phase-1 outcomes: the ATR stop governing, the hard floor overriding a wider ATR
stop, and no ATR at all. All 9 open positions in the live book have
`entry_atr=None`, so all of them run the fallback — and the display could not
say so.

  * three distinct labels: `atr stop`, `hard stop (floor; atr stop was wider)`,
    `hard stop (NO ATR — fallback)`. Stop LEVELS are unchanged.
  * `atr_coverage()` in `kala/discipline.py`, printed by
    `discipline_report.py`: how many open positions cannot run the volatility
    stop, and which ones.

Sizing is unaffected — `size_position` takes its stop from the scanner's ATR at
buy time. Only ongoing exit management of already-open positions was on the
fallback. Details in `PROJECT_STATUS.md` -> "ATR fallback, named".

Tests: `tests/test_atr_fallback_is_named.py` (13 new). Suite 1679 passed,
1 skipped.

## Offline exit-profile comparison (2026-08-17)

New `compare_exit_profiles_cached.py` — runs the walk-forward harness over
`results/price_cache/` with both exit profiles, no network. It answers whether
`--exit-profile` actually reaches the engine before a full-universe download is
spent on it (the flag once passed unit tests while `main()` ignored it).

On 64 cached tickers, 19 folds: `legacy` excess +0.286%/trade (clustered
t +1.64), `forward_test` +6.596% (clustered t +3.46). Normalised for holding
length on matched trade-days the gap is ~4x, not ~15x. Selected sample,
survivorship-exposed, NOT a universe result — see `PROJECT_STATUS.md` ->
"Exit-profile comparison on cached data" for the full caveats.

`_need()` replaces `.get(key, nan)` so a wrong key raises and names the keys
that exist, instead of printing an orderly table of NaN.

Tests: `tests/test_cached_profile_comparison.py` (6 new). Suite 1685 passed,
1 skipped.

## Liquidity split for the cached comparison (2026-08-17)

`compare_exit_profiles_cached.py --split-liquidity` — the survivorship
discriminator, applied to the exit-profile gap. Splits the cached universe by
median daily turnover (same definition `diagnose_exit_param_sweep.py` uses) and
runs both profiles on each half.

Result: the gap is present in BOTH halves, so survivorship is not what produces
it — but it is 3.7x larger in the illiquid half, so the headline number is
inflated. The conservative read is the liquid half: ~+2.6 pts/trade rather than
~+6.3. See `PROJECT_STATUS.md` -> "Liquidity split on the cached comparison".

`rank_by_turnover()` is extracted so the tests exercise the script's own
ranking. They previously reimplemented it inline and two mutations survived.

Tests: `tests/test_cached_profile_comparison.py` (9 total). Suite 1688 passed,
1 skipped.

## Holding-period sweep, plus two swallowed writes (2026-08-17)

`compare_exit_profiles_cached.py --sweep-holding 10 20 30 45 60 90 120` — the
horizon sweep with exits off, reporting excess per trade AND per day held. The
per-trade column rises mechanically with the horizon; the per-day column is the
honest comparison. Result: a smooth hump peaking in the 30-60 band, with every
horizon positive at clustered t +2.9 to +3.8. The script prints the best-of-N
caveat beside the peak and refuses to read a shape from fewer than 3 points.
See `PROJECT_STATUS.md` -> "Holding-period sweep on cached data".

Two swallowed writes, found by following the last change's own foundation:

  * `daily_run.log()` discarded every file-write failure. Once the Telegram
    delivery outcome started being recorded there, a log that cannot be written
    became a record that silently does not exist. The failure is now reported
    once per process to stderr, and `mkdir` takes `parents=True`.
  * `AlertDedup` in `kala/intraday.py` now writes tmp-then-`os.replace`
    and reports both a failed save and an unreadable file. Milder than the
    other state stores — losing it causes duplicate alerts, not lost data —
    fixed for consistency.

Tests: `tests/test_log_and_dedup_report_failures.py` (8 new),
`tests/test_cached_profile_comparison.py` (13 total). Suite 1700 passed,
1 skipped.

## Root conftest.py — `pytest` and `python -m pytest` now agree (2026-08-17)

`python -m pytest` prepends the current directory to `sys.path`; the bare
`pytest` console script does not, and pytest's default import mode adds the
TEST file's directory rather than the repository root. Two modules imported
`kala` / `archive_sentiment` at module scope and so raised
ModuleNotFoundError under the bare form only:

    python -m pytest -q   ->  1700 passed
    pytest -q             ->  ModuleNotFoundError: No module named 'kala'

Pre-existing, and easy to miss because the error names the module rather than
the invocation — it points at a broken install instead of at `sys.path`. A root
`conftest.py` (loaded before collection) inserts the repo root, so both forms
work from any directory.

`tests/test_pytest_invocation_parity.py` runs BOTH forms as subprocesses
against three modules and asserts each collects a non-zero number of tests.
It uses the console script beside `sys.executable` rather than whatever PATH
resolves to, and strips `PYTHONPATH` so an inherited one cannot make the test
pass for the wrong reason. Removing `conftest.py` reddens 3 tests.

Tests: `tests/test_pytest_invocation_parity.py` (7 new). Suite 1707 passed,
1 skipped under BOTH invocations.

## Explicit UTF-8 everywhere; no reliance on the platform default (2026-08-17)

`Path.read_text()` and `open()` without `encoding=` use the locale codepage:
UTF-8 on Linux, cp1252 on the Windows machine this project is actually run
from. Two tests read `daily_run.py`'s source, which now contains a warning
emoji, and failed on Windows only:

    UnicodeDecodeError: 'charmap' codec can't decode byte 0x8f in position 7618

Scope, measured rather than assumed: the JSON state files were never at risk.
`json.dumps` defaults to `ensure_ascii=True`, so every write is pure ASCII and
round-trips under cp1252 intact — `paper_state.json`, `watchlist.json`,
`runner_config.json` and `breaker_state.json` are unaffected. What broke was
reading non-ASCII TEXT.

  * 194 `read_text`/`write_text` call sites across 32 files now pass
    `encoding="utf-8"` explicitly.
  * `friction_report.py` and `live_scorecard.py` had a bare
    `json.load(open(args.state))`; both now pin the encoding.
  * `subprocess.run(..., text=True)` is the same hazard twice — the parent
    decodes with the locale codepage and a Python child ENCODES its stdout with
    one, so they can disagree. The four test modules that shell out now pass
    `encoding="utf-8"` and set `PYTHONIOENCODING=utf-8` in the child, and
    `kala/preflight.py` pins its `systemctl` read with
    `errors="replace"` so a stray byte cannot abort a preflight check.

Verified two ways: the whole suite passes under
`python -X warn_default_encoding -W error::EncodingWarning -m pytest`, and
`tests/test_no_platform_default_encoding.py` scans every source file for the
pattern so a regression fails at the line that introduces it rather than only
on Windows. The scanner blanks comments and string literals via `tokenize`
first — without that it matched its own prose, and a noisy guard is a guard
that gets switched off.

Tests: `tests/test_no_platform_default_encoding.py` (5 new). Suite 1712 passed,
1 skipped, under `pytest` and `python -m pytest` alike.

## Subprocess encoding: pin BOTH ends, not one (2026-08-17)

The previous change pinned only the PARENT's decoder (`encoding="utf-8"` on
`subprocess.run`). On Windows that made things worse rather than better: before
it, both ends used cp1252 and agreed by accident; after it, the child still
encoded its stdout with the locale codepage while the parent decoded UTF-8.
`--help` output is full of em-dashes from this project's docstrings, so every
subprocess test broke:

    UnicodeDecodeError: 'utf-8' codec can't decode byte 0x97 (an em-dash in cp1252)
    TypeError: argument of type 'NoneType' is not iterable

The TypeError is the decode dying on subprocess's reader THREAD, which leaves
`stdout` as None — an error naming nothing about encodings.

Two things were needed and only one was done. A regex applied the fix to calls
whose argument list ended right after `text=True`, and silently skipped the two
that mattered because they had `cwd=...` after it. Every `subprocess.run` in
the test suite now passes, applied by walking balanced parens rather than by
matching a guessed shape:

  * `env=_utf8_env()` — sets `PYTHONIOENCODING=utf-8` so the child encodes what
    the parent decodes;
  * `errors="replace"` — so a surprise yields a readable string rather than
    `stdout=None` and a misleading TypeError.

`tests/test_subprocess_encoding_agreement.py` reproduces the Windows pairing on
any platform by forcing `PYTHONIOENCODING=cp1252` in a child that prints an
em-dash, then verifies the fix. It also asserts every subprocess call in the
suite pins all three of encoding/env/errors. Verified by running the subprocess
tests under an inherited `PYTHONIOENCODING=cp1252`: 23 passed.

Tests: `tests/test_subprocess_encoding_agreement.py` (11 new). Suite 1723
passed, 1 skipped.

## Full-universe exit-profile result recorded (2026-08-17)

The two full-universe walk-forwards were run. `legacy` excess -0.45%/trade
(clustered t -3.79, negative in 12 of 14 folds); `forward_test` +4.70%
(clustered t +5.09, DSR 1.000). The project's standing "no OOS edge" verdict
was measured through the exit ladder, and the ladder is significantly negative
on its own.

The positive result is concentrated: one fold carries 76% of the pooled P&L and
7 of 14 folds are negative. `repro/fold_concentration.py` computes the per-fold
contribution from the printed fold table so the concentration is checkable
rather than asserted. Full reading, including what this does and does not
retire, in `PROJECT_STATUS.md` -> "FULL-UNIVERSE EXIT-PROFILE COMPARISON".

## Full-universe liquidity split recorded (2026-08-17)

The survivorship discriminator, run on all 569 usable tickers. The gap is
present in both halves, monotone in both, and statistically STRONGER in the
liquid half (t +4.31 vs +3.76) where delisting exposure is lowest — the
opposite of what the bias would produce. The threshold-0 control is
indistinguishable from zero in both halves, ruling out universe drift.

Conservative number: +2.90 pts/trade at threshold 80 in the liquid half.
Full reading in `PROJECT_STATUS.md` -> "FULL-UNIVERSE LIQUIDITY SPLIT".

## Stale headline verdicts corrected (2026-08-17)

The banner at the top of this file and the SUMMARY at the top of
`PROJECT_STATUS.md` both still said "no demonstrated out-of-sample edge". That
is the first thing any reader sees, and it now contradicts the evidence at the
bottom of the same file. Both corrected, with the superseded line left visible
rather than deleted.

Added `PROJECT_STATUS.md` -> "What the ladder does to all sixteen verdicts":
every hypothesis in the file was validated through a harness that applied the
exit ladder to the strategy side only (the alpha-check benchmark is
buy-and-hold, unladdered). The ladder measures -0.45%/trade excess, so the
rejections whose reported effect is of the same order — mean-reversion,
support/resistance, dividend yield, multi-horizon trend, low volatility — are
not clean reads. They are marked as measured-through-the-ladder, NOT
overturned; re-running them is five commands and no downloads, and the
expected outcome is recorded in advance so it can be wrong.

## Baseline threshold now follows the strategy's own scale (2026-08-17)

`--exit-profile forward_test` forced `score_entry_threshold = 80` on every
strategy, and that overrode each strategy's own `default_threshold`. The
printed VERDICT is computed from that fixed-baseline arm, so for
`support_resistance` (grid 20-60) and `dividend_yield` (grid 30-70) the verdict
came from an arm sitting above the strategy's entire grid.

  * `build_run_config(..., baseline_threshold=...)`; `run_walkforward.py`
    defaults it to `strategy.default_threshold` for non-momentum strategies.
    Momentum is unchanged — no historical number moves.
  * New `--baseline-threshold` to set it explicitly.
  * Each run prints the baseline used, the strategy's own default and grid,
    that the verdict comes from THAT arm, and a warning if it is outside the
    grid.

Consequence for the results: the `mean_reversion` re-run printed "NO OOS EDGE"
from a baseline arm at 80 while its walk-forward arm showed excess +2.09% at
clustered t +3.58. Its earlier "actively negative" verdict is withdrawn as
unclean, NOT replaced — its chosen threshold wanders across the whole grid
fold to fold, which is what fitting noise looks like. See `PROJECT_STATUS.md`
-> "The re-run instruction was wrong, and mean_reversion is now open".

Tests: `tests/test_baseline_threshold_scale.py` (7 new). Suite 1751 passed,
2 skipped.

## mean_reversion overturned; a common-factor problem opened (2026-08-17)

Re-run at its own baseline (60, not the profile's 80): excess +1.84%/trade at
t 3.99 on 8,858 trades from the FIXED baseline arm — no threshold selection,
nothing to deflate. Its recorded "actively negative (t ~= -3.9)" verdict is
overturned; the ~8 t-unit swing is entirely the exit ladder.

But momentum and mean_reversion — near-opposite signals — correlate +0.857 in
per-fold EV and agree in sign 14 of 14 folds. They are not independent
confirmations. The threshold-0 control being flat rules out "any basket works",
so the selection does something; what it does may be one shared tilt rather
than two edges. See `PROJECT_STATUS.md` -> "mean_reversion re-tested at its own
baseline".

## Per-fold excess is printed; a false alarm withdrawn (2026-08-17)

The walk-forward fold table printed only RAW per-trade EV. Comparing two
strategies on that column measures the market — two long-only baskets from one
universe rise together — and doing so produced a false "hidden common factor"
alarm. `FoldResult.oos_excess_chosen` already held the right number; it was
dropped at the formatting step. The table now carries an `excess%` column, and
prints `n/a` rather than 0.00 when there is no benchmark.

New `diagnose_selection_overlap.py`: Jaccard overlap between each pair of
strategy selections, with a random-overlap baseline, and `--bottom` to test
whether they share what they AVOID rather than what they pick. Measured on the
local cache: momentum and mean_reversion overlap 0.021 against a 0.133 random
baseline — genuinely opposite selections.

Results of the four re-runs and the withdrawal are in `PROJECT_STATUS.md` ->
"All four re-runs positive — and a false alarm I raised, corrected".

Tests: 2 new in `tests/test_baseline_threshold_scale.py`. Suite 1753 passed,
2 skipped.

## The excess column answers the regime question (2026-08-17)

With per-fold excess printed, `mean_reversion`'s excess correlates +0.477 with
IHSG (raw: +0.685) — benchmark subtraction removes some market exposure, not
all. Split by market direction: mean excess -0.16% in the 7 falling folds,
+4.93% in the 7 rising ones. The edge is REGIME-CONDITIONAL, and the system has
no forward-looking way to say which regime it is in. See `PROJECT_STATUS.md` ->
"Per-fold excess, at last".

## Saved fold tables, compared mechanically (2026-08-17)

Ten walk-forward runs have now been compared by pasting terminal output and
reading columns by eye. Two mistakes came out of that loop: correlating the RAW
per-fold EV of two long-only strategies (mechanical, ~+0.86 regardless of
edge) and reading a table from a run whose warehouse had been refreshed in
between, shifting fold boundaries.

  * `run_walkforward.py --save-folds PATH` writes the per-fold table to JSON,
    including strategy, exit profile, baseline threshold and ticker count — a
    fold table without those cannot be placed later.
  * New `compare_folds.py` reads saved runs and reports RAW and EXCESS
    correlations side by side, plus each run's excess split by market
    direction. It REFUSES to correlate runs whose fold calendars differ,
    unless `--allow-misaligned` is passed.

Verified against the hand computation it replaces: mean_reversion excess vs
IHSG +0.477, up folds +4.93%, down folds -0.16%.

Tests: `tests/test_compare_folds.py` (8 new). Suite 1761 passed, 2 skipped.

## The common-factor alarm, re-established on the right column (2026-08-19)

Both momentum and mean_reversion were re-run with `--save-folds` on identical
fold calendars, and `compare_folds.py` was pointed at the pair:

```
pair                                        RAW corr  EXCESS corr
momentum / mean_reversion                     +0.866       +0.803
```

Subtracting the benchmark moved the correlation from 0.866 to 0.803 — almost
nothing. Two strategies whose SELECTIONS are near-disjoint (Jaccard 0.021,
below the 0.133 random baseline) still move together at 0.80 after the market
is taken out. That is not the mechanical correlation of two long-only baskets.

This is the alarm raised on 2026-08-17 and withdrawn the same day. Withdrawing
it was right: it had been computed on the RAW column, where a high correlation
says nothing, so the evidence did not support the claim even though the claim
turned out to be true. It now stands on the excess column.

What it means for position sizing: momentum and mean_reversion are NOT two
independent edges to be run side by side for diversification. Whatever they
share is doing most of the work in both, and running both is closer to
doubling one position than to holding two.

The leading hypothesis for what is shared is the benchmark itself. IHSG is
cap-weighted and bank-heavy; these baskets are equal-weighted and sharia-
screened, so banks are excluded by construction. Subtracting IHSG from a
sharia basket leaves a systematic sector tilt in the residual, and both
strategies would carry it. `--benchmark XIJI.JK` (the sharia index) is the
test that would separate a real shared signal from a benchmark artefact, and
it has NOT been run.

## Baseline-arm reporting extracted from `main()` (2026-08-19)

The pre-run grid warning claimed a baseline outside the strategy's search grid
made the verdict "meaningless". That was wrong on this project's own headline
result: momentum's baseline of 80 sits outside its 50-75 grid and traded 5,241
times. Outside the SEARCH grid is not outside the range of valid scores. The
warning is now a NOTE, and the real check is made AFTER the run from the
measured trade count — the only place the question can actually be answered.

The tests covering this were asserting on the SOURCE TEXT of `main()`. A
mutation run showed why that is worthless: making the entire block unreachable
(`if False:`) left all of them passing, because the strings were still in the
file. Source-text assertions cannot tell live code from dead code.

`baseline_provenance_lines()` and `thin_baseline_arm_warning()` are now pure
functions that `main()` prints, and the tests call them. Ten mutations run
against the new versions; nine killed. The tenth — dropping the `not n_chosen`
guard — survived as an EQUIVALENT mutant: with `n_chosen` at 0 the threshold
is 0 too, so the arithmetic already returns None. The guard was dead code and
has been removed rather than propped up with a test.

Tests: `tests/test_baseline_threshold_scale.py` rewritten off source-text
assertions, +2 new. Suite 1765 passed, 2 skipped.

## Finding 8: a skipped alpha check was silent (2026-08-19)

Found while preparing the `--benchmark XIJI.JK` run recommended above — the
command itself exposed it.

`--benchmark` accepts any string. When the ticker does not resolve on
yfinance, `run_walkforward.py` printed a WARNING to **stderr** and continued.
`summary_text()` gated the entire ALPHA CHECK section on
`pooled_excess_baseline["n"] > 0` with no else branch, so what reached stdout
was:

```
VERDICT: EDGE CONFIRMED OOS — positive EV, statistically distinguishable from 0.
```

...and nothing else. No alpha check, and no statement that there wasn't one.

Same shape as the other seven findings: the failure reads as normal operation.
A missing section looks like a shorter report, not a broken one. Redirect
stdout to a log file — which is how every result in `PROJECT_STATUS.md` was
captured — and the stderr warning is gone as well, leaving a saved report that
reads as a clean confirmed edge measured against nothing.

**A test was holding it in place.** `test_walk_forward_no_alpha_section_without
_benchmark` asserted `"ALPHA" not in report.summary_text()`, on the reasoning
that the alpha check was "additive and opt-in". True when it was new; false
now that it is the measurement that overturned the exit-ladder result.

Fixed:

  * the raw verdict is labelled `VERDICT (raw, vs cash)` — it was never a
    verdict on alpha, and unlabelled it became one by default;
  * an explicit `ALPHA CHECK: NOT RUN` block states that the verdict is
    measured against cash, that it cannot separate stock-picking from market
    exposure, and names the usual cause (`--benchmark` naming a ticker that
    does not resolve, or a benchmark that does not overlap the test windows).

Repro: `repro/repro_missing_benchmark.py` — prints a healthy report and a
broken one side by side, and asserts exactly one of "ran" / "skipped" is true.

Tests: the old test replaced by two in `tests/test_walkforward.py` (the skip is
visible; the notice does NOT fire when the check did run). Five mutations, all
killed, including reinstating the original bug. Suite 1766 passed, 2 skipped.

### Not verified: whether XIJI.JK resolves

Probed from this container and got proxy 403s for every ticker including
`^JKSE`, which certainly exists — so that says nothing about XIJI.JK either
way. The ticker for the sharia index is UNCONFIRMED. Thanks to the fix above,
a wrong guess now announces itself instead of printing a raw verdict with the
alpha check quietly missing.

## The mutation harness reported a gap that did not exist (2026-08-19)

`repro/mutate_state_durability.py` ended with:

```
2 mutation(s) survived: ['M1 watchlist.save non-atomic', 'M2 positions.save non-atomic']
```

That reads as "nothing tests the atomic writes" — the core of Finding 1. It was
false. Two lines earlier the same run printed, for those same two entries:

```
M1 watchlist.save non-atomic               SKIPPED — mutation did not apply
```

The harness counted a mutation that **never applied** as one that survived. Its
search string still expected `tmp.write_text(payload)`, from before the UTF-8
work added `encoding="utf-8"` to every write. The anchor stopped matching, the
mutation was never made, no test could have failed — and that was reported as
a test-coverage gap.

Both failure modes are now separated, because they call for opposite actions:

  * **SURVIVED** — the mutation applied and no test failed. A real gap; write
    a test.
  * **STALE ANCHOR** — the mutation did not apply. Nothing was measured at all;
    fix the harness. Reported as `!!! STALE ANCHOR — NOTHING WAS MEASURED`,
    and still exits non-zero, because an unmeasured case must not read as a
    pass either.

Anchors updated. All 8 mutations now apply and are caught — the atomic writes
were covered the whole time, by `test_watchlist_survives_a_crash_during_save`
and `test_positions_survive_a_crash_during_save`. Verified non-vacuous by
breaking an anchor deliberately and confirming it reports STALE, not SURVIVED.

This is the third defect found in my own measuring tools rather than in the
system under test, and the same shape as the rest: a broken measurement that
produced a confident, readable, wrong answer.

### Packaging defect in v60, fixed

The first v60 build dropped four repro scripts that v59 shipped
(`fold_concentration.py`, `mutate_state_durability.py`,
`repro_partial_telegram.py`, `repro_watchlist_silence.py`). The zip is built
from the dev tree, and those four lived outside it. All five now ship, and each
is verified to RUN from the packaged layout — not merely to be present.

## A benchmark that matches the universe (2026-08-19)

The benchmark probe settled which sharia indices exist on yfinance:

```
^JKSE    240 rows   (control — the network works)
^JKII    240 rows   Jakarta Islamic Index: sharia, but only the 30 largest, cap-weighted
XIJI.JK  246 rows   trades on IDX itself, so an ETF — expense drag and tracking error
JII.JK     0 rows
ISSI.JK    1 row    resolves to something with no usable history
^ISSI      0 rows
```

ISSI is the index that would match a ~600-name equal-weighted sharia basket,
and it is not there. `ISSI.JK` returning exactly ONE row is the nastier case:
it resolves, so nothing errors, and the excess computed against it would be
built on a single price.

New `kala/synthetic_benchmark.py` builds the benchmark that fits exactly:
an equal-weighted, daily-rebalanced index over the SAME tickers the strategy
selects from. `--benchmark EQUAL_WEIGHT` on `run_walkforward.py`. The question
it answers is the one that matters: **did picking these beat buying all of
them?**

Construction detail that is not cosmetic: it averages DAILY RETURNS across
whatever names traded that day, then compounds. Averaging normalised price
LEVELS would reweight toward names with the longest history — a survivorship
tilt the benchmark would introduce by itself.

### A bug the tests caught before it shipped

The first version anchored the series on the first date carrying a RETURN,
then forced the base level to 1.0 after compounding had already started. The
second bar still held two days compounded together, so the benchmark's first
observed move was DOUBLE the real one — +4.04% on a day every name moved
+2.00%. On a chart it looked perfectly ordinary.

`test_it_equal_weights_rather_than_following_the_biggest_price` and
`test_a_non_trading_day_does_not_get_counted_as_a_flat_day` both failed on it.
Fixed by anchoring on the first date with enough PRICES: that date is the base
bar, a base bar has no return, and the level then starts at 1.0 by
construction rather than by being overwritten.

Seven mutations run; six killed. The seventh — re-adding `level.iloc[0] = 1.0`
— survives as an EQUIVALENT mutant under the corrected anchoring, since the
base row is already 0.0. The guard that actually kills the original bug is
"anchor on prices, not returns", which is killed.

`describe()` excludes the base bar from its breadth range (a base bar has no
return, so counting it makes every healthy benchmark report a minimum of 0
names — indistinguishable from a genuinely empty stretch) and counts and dates
thin days separately instead of smoothing them into a min-max.

Tests: `tests/test_synthetic_benchmark.py`, 15 new. Suite 1781 passed, 2
skipped.

### NOT a result yet

A smoke build over the 70 locally cached tickers gives EQUAL_WEIGHT +489.7%
against IHSG +18.2% over the same span. **That number must not be quoted.**
Those 70 are a selected subset that still exists today, so equal-weighting
them from the March-2020 low is close to a pure survivorship measurement. It
is motivation to run the real thing on the full 615-ticker warehouse, nothing
more.

## Finding 9: a missing excess was written as 0.00, into a saved file (2026-08-19)

Surfaced by a real run. `--benchmark EQUAL_WEIGHT` was issued against a build
that did not yet have the flag, so it went to yfinance, 404'd, and produced a
fold table whose excess column read:

```
excess%
  +0.00      <- fourteen times
```

`+0.00` is a measurement. The truth was "never measured". The IHSG column
correctly printed `n/a` right beside it.

Cause: `trade_stats([])` returns a FULLY POPULATED dict — `{"n": 0, "ev_pct":
0.0, ...}` — and a populated dict is truthy. So both guards in the codebase
sailed past it:

```python
fr.oos_excess_chosen.get("ev_pct") if fr.oos_excess_chosen else None   # table
(fr.oos_excess_chosen or {}).get("ev_pct")                             # JSON
```

Each returns 0.0, never None, so the `else "n/a"` branch was unreachable.

**The saved JSON is the worse half.** `--save-folds` wrote `excess_pct: 0.0`
for all fourteen folds — a file that outlives the terminal and gets read back
by `compare_folds.py` later. And fourteen identical zeros have zero variance,
so correlating against them returns NaN, which reads as the comparison tool
correctly declining to answer when in fact it was handed invented data.

**A test for exactly this existed and passed.** `test_a_fold_without_a_
benchmark_prints_n_a_not_zero` asserted that walkforward.py CONTAINED the
string `ex_s = f"{ex:+.2f}" if ex is not None else "  n/a"`. The string was
there. The branch was dead. A source-text assertion cannot tell reachable code
from unreachable code — the third time that has bitten in this audit.

Fixed with `walkforward.excess_ev(stats)`, which returns None when `n <= 0` and
is used by both the table and the save path. Both tests rewritten to CALL the
code: one renders a fold and reads the row back, one checks the JSON
serialises to `null`.

Four mutations, all killed — including reinstating the exact truthiness guard,
and including the opposite error (suppressing a GENUINE zero excess, which is
a real measurement and must still print).

Tests: 3 in `tests/test_baseline_threshold_scale.py`, two of them replacing
source-text assertions. Suite 1784 passed, 2 skipped.

### Anyone holding a fold JSON from a failed-benchmark run should delete it

The corruption is in the file, not the reader. `compare_folds.py` cannot
distinguish a fabricated 0.0 from a measured one.

### A fourth source-text test — this one required the bug

`test_run_walkforward_can_save_a_fold_table` asserted that the runner contained
the literal string `"excess_pct": (fr.oos_excess_chosen or {}).get("ev_pct")`.
That expression IS the defect. The test did not merely fail to catch it — it
mandated it, and failed when the fix landed.

Rewritten to assert the property instead: a missing excess serialises as
`null`, and a MEASURED zero still serialises as `0.0`. A companion test records
why the fix had to be at the writer: a constant series has zero variance, so
`compare_folds.corr` returns NaN, and there is nothing the reader can inspect
to distinguish a fabricated zero from a real one.

## Finding 10: the verdict disagreed with its own evidence (2026-08-19)

The purest instance of this project's signature failure, and the most
consequential, because it is the one line a reader acts on.

A real run against `--benchmark EQUAL_WEIGHT` printed:

```
  clustered t (by entry date) = 1.60  vs plain t = 1.74
  Trust the clustered figure — a null gets stronger under it, a positive
  gets weaker.
  deflated Sharpe = 0.670  (after deflating for 6 thresholds tried)
  Below ~0.95, the winning threshold is not distinguishable from the best
  of that many coin flips.
----------------------------------------------------------------
ALPHA VERDICT: ALPHA CHECK: EDGE CONFIRMED OOS — positive EV, statistically
distinguishable from 0.
```

Both corrections said no. The verdict said yes.

`_edge_verdict` read only `stats["t_stat"]` — the PLAIN t — and never saw
`pooled_excess_clustered_t` or `pooled_excess_dsr`. Nothing was missing from
the report; the summary line simply ignored the two numbers printed
immediately above it, which the surrounding prose had just told the reader to
trust instead of the one being used.

### A second defect underneath it

The clustered t and the deflated Sharpe were computed for the WALK-FORWARD arm
(`pooled_exc_c`), while the ALPHA VERDICT is rendered from the FIXED-BASELINE
arm (`pooled_excess_baseline`). So even wiring the corrections in naively would
have judged one arm by another arm's evidence.

Fixed properly: the baseline arm's entry dates are now collected, and its own
clustered t and deflated Sharpe are computed
(`pooled_excess_baseline_clustered_t`, `pooled_excess_baseline_dsr`). Both are
printed, marked `<- the ALPHA VERDICT is judged on THIS`, and both gates must
pass before anything is called confirmed:

  * clustered t (where it exists) governs, not the plain t;
  * a deflated Sharpe below 0.95 blocks confirmation outright, with the number
    and the trial count quoted in the verdict text.

`T_CONFIDENT` and `DSR_CONFIDENT` are module constants so the thresholds in the
verdict cannot drift away from the ones the prose quotes.

Six mutations, all killed — including reinstating the original plain-t-only
logic, and including feeding the verdict the wrong arm's clustered t.

Tests: `tests/test_verdict_uses_the_corrected_statistics.py`, 15 new.

## EQUAL_WEIGHT: exchange holidays were injecting noise (2026-08-19)

The same run reported `breadth: 2-569 names/day` and eight days below twenty
names between 2026-05-01 and 2026-08-18.

2026-05-01 is IDX Labour Day and 2026-08-17 is Independence Day. On an exchange
holiday most tickers have no bar while a handful carry a phantom one, and the
construction was averaging THOSE — putting the move of two names into the
index. Because the level compounds, that noise then persisted through every
later date, including the whole of fold 13, the most recent and worst fold.

A real equal-weighted portfolio does not move on a day it cannot trade. Days
below `min_names` are now carried at 0%, which is what holding through a closed
session does. The bar is KEPT rather than dropped, so every trade's entry/exit
window can still be matched — removing dates would have silently discarded
trades instead, trading one invisible failure for another.

Three mutations, all killed, including dropping the bars instead of flattening
them. Suite 1802 passed, 2 skipped.

## Warehouse coverage churn — reported, NOT diagnosed (2026-08-19)

Two runs minutes apart on the same day:

```
run A:  warehouse: 615/615 ticker(s) already covered, fetching 0
run B:  warehouse: 1/615 ticker(s) already covered, fetching 614
        (never stored: 0, history too short for 5y: 183, stale tail: 431)
```

Nothing was written to the warehouse between them (run A fetched nothing; the
run in between failed at argparse).

Both cache-hit paths in `run_walkforward.fetch` depend on
`warehouse.is_as_fresh_as_it_gets(t, end_iso)`, which requires the recorded
fetch ATTEMPT date to equal `end_iso`. For 614 tickers that condition flipped
without an intervening write.

Costs: a full universe re-download (the code's own comments record that Yahoo
has rate-limited this project mid-study before), and consecutive runs on the
same day not being reproducible — which matters because `compare_folds.py`
exists specifically to compare saved runs against each other.

LEADING HYPOTHESIS: the day rolled over. `is_as_fresh_as_it_gets` requires the
attempt date to equal today, so at local midnight every marker in the warehouse
goes stale at once and the next run re-downloads the universe. That is expected
behaviour once per day, and it would explain 614 tickers flipping together with
no intervening write.

New `diagnose_warehouse_churn.py` decides it from the warehouse itself: it
prints the fetch-attempt date distribution against the end_iso being asked for,
classifies every ticker by which path it will take, and says plainly whether
stale markers are from a previous DAY (expected) or from earlier the same day
(a real bug). Verified against a synthetic warehouse seeded with both shapes.

## Finding 11: the position cap switched OFF when exceeded (2026-08-21)

Found from a live paper account: **17 positions open against a cap of 10**, and
the bot still proposing new buys.

```python
slots = max(0, max_pos - len(held))     # 10 - 17 = 0
...
if shown >= slots and slots > 0:        # slots > 0 is False -> guard skipped
```

`/maxpositions` rejects `n <= 0`, so `slots == 0` can only ever mean "already
at or over the cap" — never "unlimited". The `and slots > 0` clause made the
condition False for EVERY candidate in exactly that case, so the scan proposed
its entire buy list while the same message printed the limit it was ignoring.

Measured across the boundary:

```
held    slots   proposed
   9        1          1     correct
  10        0          8     <- inverts here
  17        0          8
```

The cap worked at 9 held and stopped existing at 10.

**The same inversion appeared twice.** The header count read
`min(slots, len(buys)) or len(buys)` — and `0 or N` is `N`, so a legitimate
zero rendered as the full count.

Fixed: the guard is now `if shown >= slots:`, and the header is replaced by an
early return. `max_positions` hand-edited to 0 or negative in the JSON now
fails CLOSED (nothing proposed) rather than open.

### Withholding silently would have been the next bug

An empty candidate list reads as "no BUY signals today" — a different fact
entirely. `position_cap_notice()` states the holdings, the limit, the number of
signals withheld, and that this is NOT "no signals".

It is a pure function because the first version of its test grepped
telegram_bot.py for the strings and SURVIVED a mutation that made the whole
block unreachable. That is the fifth source-text assertion in this audit to
fail the same way; the pattern is now: if a test greps the source, it is not
testing behaviour.

Six mutations, all killed — including restoring the original clause, the header
inversion, moving the boundary by one, and dropping the withheld count.

Tests: `tests/test_position_cap_binds_when_exceeded.py`, 16 new. Suite 1818
passed, 2 skipped.

## The daily buy budget is a stored constant, not a computed one

`daily_capital_idr` in `runner_config.json` is set by `/capital`, by
`/deposit` (which ADDS the deposit to it, telegram_bot.py), or by
`reset_paper.py --capital`. Nothing recomputes it from cash or equity, so it
drifts: an account showing IDR 4,748,425 budget against IDR 25,882,600 cash and
IDR 38,666,600 equity is not a bug, it is an old number nobody re-set.

Not changed — making it a percentage of equity would silently alter position
sizing for anyone relying on the fixed figure. Documented instead.

## compare_folds refusals now name the FILE (2026-08-21)

Comparing three runs of the same strategy printed:

```
FOLD CALENDARS DIFFER from momentum: momentum
```

Three files, all `strategy: momentum`, so the message named neither the
reference nor the offender — the one fact the reader needs in order to know
which run to repeat. Strategy names are not unique across saved runs; paths
are.

The refusal now lists each offending FILE with its fold-0 window beside the
reference's, and states the fix. The summary table and the pair labels are
keyed on filename too, so `base / vetoes` replaces `momentum / momentum`.

Five mutations, all killed. Tests: 4 new in `tests/test_compare_folds.py`.
Suite 1822 passed, 2 skipped.

(One of those tests initially broke four existing ones: the helper I added was
also called `_run`, shadowing an existing helper with a different signature.
Renamed to `_run_compare`.)

## `--disable-veto`: the five entry vetoes can now be separated (2026-08-21)

`--apply-entry-vetoes` costs about 4.2 points of excess (+1.71% -> -2.52%,
clustered t -3.10) and switches on FIVE filters at once. Every one already had
its own `EntryConfig` flag; nothing exposed them to the CLI, so the cost could
not be attributed.

```
--disable-veto rsi parabolic obv thin_volume bear
```

| name | EntryConfig field | what it blocks |
|---|---|---|
| `rsi` | `veto_overbought` | RSI >= 75 |
| `parabolic` | `veto_parabolic` | +25% in 20 sessions |
| `obv` | `veto_distribution` | price up while OBV falls |
| `thin_volume` | `veto_thin_volume` | surge unconfirmed by volume |
| `bear` | `block_buys_in_bear` | market regime BEARISH / MODERATE_BEAR |

`--veto-ranging-stock` is deliberately NOT in the map — it has its own flag and
was already attributed (it is not the cause).

Guards, both the same shape as the existing ranging-veto guard:

  * `--disable-veto` without `--apply-entry-vetoes` is REFUSED. With no vetoes
    running, disabling one is a no-op that would reproduce the plain no-veto
    arm and save it under a filename claiming to measure a specific veto — a
    result that reads as evidence and contains none.
  * an unknown name is rejected by argparse (`choices=`), so a typo cannot
    silently disable nothing.

The run banner prints which vetoes are ON and which are OFF, and says so
explicitly when all five are disabled ("the NO-VETO arm with extra steps").

**CORRECTION (2026-08-22): the sentence that stood here — that the saved fold
JSON carries `apply_entry_vetoes` and `disabled_vetoes` — was FALSE when
written.** See "Finding 12" below.

Five mutations, all killed — including a wrong field name in the registry and
sweeping the ranging veto in with the five.

Tests: `tests/test_disable_individual_vetoes.py`, 13 new. Suite 1835 passed, 2
skipped.

## Leave-one-out ran; it found no culprit, and that is the result (2026-08-21)

The five `--disable-veto` runs are in. Removing all five vetoes recovers +4.23
points of excess; removing them one at a time recovers −0.11 points in total.
Each single removal restores 29-82 trades out of 4,279 missing.

The filters are almost entirely redundant — they fire on the same candidates,
so dropping one arm of a five-way AND barely changes the intersection.
Leave-one-out cannot attribute a conjunction.

Two predictions of mine were wrong: `rsi` has exactly zero marginal effect, and
`parabolic` is the only veto that HELPS (removing it costs 0.51 points and
pushes clustered t from −3.10 to −3.68). I had named both as the prime
suspects.

Recorded in `PROJECT_STATUS.md` -> "Leave-one-out: no single veto is
responsible", together with the leave-one-IN design that can price each filter
individually.

No code change — `--disable-veto` already supports leave-one-in by disabling
the other four.

## Finding 12: I shipped a silent no-op and documented it as done (2026-08-22)

The v68 entry above claimed the saved fold JSON records which veto arm produced
it. It did not. Fifteen real runs later, every saved table was missing
`apply_entry_vetoes` and `disabled_vetoes` — the user's own files are the
evidence, and the only thing distinguishing a no-veto table from an all-veto
one was its filename.

Cause: the patch that added the fields used a replacement anchor with the wrong
indentation and **no assertion that the anchor matched**. It replaced nothing,
raised nothing, and I wrote the changelog entry from intent rather than from
the file.

This is the same failure this audit has documented eleven times in other
people's code — an operation that fails while reporting success — committed by
me, in the tooling built to catch it, and then written up as complete.

Two fixes:

  * The metadata half of the saved table is now `run_provenance(args, strategy,
    cfg, n_tickers)`, a pure function `main()` splats into the payload. Tests
    CALL it. The previous check was a source-text assertion that was never even
    written.
  * Every anchored replacement in that patch now asserts before replacing.

Five mutations, all killed, including reinstating the original silent failure
and letting `main()` stop using the function.

Tests: 6 more in `tests/test_disable_individual_vetoes.py` (19 total).

### The affected files

`f_mom.json`, `f_mom_ew*.json`, `f_mom_jii.json`, `f_veto_no_*.json` and
`f_only_*.json` — 15 tables — carry no veto provenance. They are still valid
(the numbers are unaffected); they simply cannot say what they measured except
through their filenames. Re-running is only needed if those filenames are ever
in doubt.

## The live bot's entry vetoes are now configurable (2026-08-22)

The measurement said turn them off. The live bot had no way to.

Both live call sites — `kala_daily_trader.py` and `kala_engine.py` —
called `evaluate_entry(data, market_status=...)` with **no `cfg`**, so
`EntryConfig()`'s defaults applied: all five vetoes hardcoded ON, the
measured-worst of the seven configurations tested, and the only one reachable
without editing source. `EntryConfig` was never built from
`runner_config.json`.

New `kala/entry_settings.py`. In `runner_config.json`:

```json
"disabled_entry_vetoes": ["rsi", "parabolic", "obv", "thin_volume", "bear"]
```

Names match the walk-forward's `--disable-veto`, so a setting and the
experiment that justified it are written the same way.

**The default is unchanged.** Absent the key, behaviour is byte-for-byte what
it was. Flipping a live trading bot's entry logic as a side effect of adding a
config hook would be precisely the silent change this audit exists to find —
the measured-better setting is opt-in.

Three failure modes closed:

  * **An unknown name RAISES.** `"rsii"` would otherwise leave the RSI veto
    enabled while the user believed it was off, with nothing on screen
    differing. The error names the bad entry and lists the valid ones.
  * **A bare string is rejected**, not iterated into characters that match
    nothing.
  * **The active setting is printed**, because a setting nobody can see is a
    setting nobody can verify took effect.

A missing or unparseable config file still yields the defaults: the scanner
must not stop scanning over a file problem. A file that EXISTS and names a
veto wrongly does raise — that is a statement the user made and got wrong, not
an absence.

### And a fail-open swallowed exception, alongside it

`kala_daily_trader.py` wrapped the veto check in `except Exception: pass`.
A crash there left the BUY standing with an empty veto list — and an empty veto
list means "nothing fired", which is not the same fact as "nothing ran". The
failure is now carried in the veto list itself
(`VETO CHECK FAILED (...) — entry guardrails did NOT run on this name`).

Six mutations, all killed, including flipping the default to all-off and
silently ignoring an unknown name.

Tests: `tests/test_entry_settings.py`, 21 new. Suite 1862 passed, 2 skipped.

## Silent-exception sweep of the live path (2026-08-22)

The fail-open veto check found in v71 prompted a systematic AST sweep for
exception handlers that swallow: `except: pass`, `except: continue`, and
handlers that only assign a default without logging or re-raising.

**40 in the live path.** Most are benign — news fetching, log formatting, HTML
rendering. The audit's criterion is narrower: *does a swallowed failure change
a trading decision, or produce a number that reads as real?* On that test:

| file | count |
|---|---|
| kala_daily_trader.py | 9 |
| kala_engine.py | 8 |
| telegram_bot.py | 6 |
| kala/news.py | 6 |
| others | 11 |

### Fixed: `recent_performance` dropped trades it could not date

```python
try:
    d = date.fromisoformat(str(t["date"]))
except (KeyError, TypeError, ValueError):
    continue          # <- silently, and it is not counted anywhere
```

That function's own docstring sells it as *"the same kind of number a
signal-service ad leads with (win rate, W/L this week) ... every closed trade
in the window counts, wins and losses alike, nothing held back"*. A trade with
an unreadable date was held back. **A dropped LOSS raises the advertised win
rate** — the one figure the docstring is selling.

Now returns `skipped_unparseable`, and `/performance` says so:

```
⚠️ 2 closed trade(s) have an unreadable date and are in NONE of the figures
   below — the win rate is computed on an incomplete log.
```

Additive: no existing key changed, so nothing downstream breaks.

Three mutations, all killed, including restoring the silent drop and
mis-counting merely out-of-window trades as corrupt.

### Examined and deliberately NOT changed

  * `recent_performance` returns `win_rate_pct: 0.0` for an empty window. Both
    renderers guard on `n == 0` first, so "0%" is never displayed. Changing the
    contract to None would risk breaking a caller for no gain.
  * `twr.py:174` leaves `cagr_pct = None` on an unparseable start date, and
    `portfolio_analytics.py:130` leaves `bench_return_pct = None` on a failed
    benchmark lookup. Both already fail to a HONEST None rather than a
    fabricated zero. Worth surfacing eventually; neither invents a number.
  * `kala/news.py` (6) — sentiment is advisory and never gates a trade.

Tests: 5 new in `tests/test_papertrade.py`. Suite 1867 passed, 2 skipped.

## The engine's silent handlers, triaged (2026-08-22)

`kala_engine.py` is the legacy all-in-one research dashboard. It is NOT in
`deploy/`, the Dockerfile or docker-compose — nothing runs it automatically —
but it is run by hand and prints BUY/HOLD signals and backtest statistics, so a
failure that reads as a normal result still misleads. It is also excluded from
ruff, so nobody had looked.

Eight swallowing handlers. **Five were already honest and were left alone:**

| handler | why it is fine |
|---|---|
| `pandas_ta` import | optional dependency, documented, script runs without it |
| `backtesting` import | explicitly unused, guarded on purpose |
| SMA-parameter fallback | prints `Status: DEFAULT` vs `Status: OPTIMIZED` |
| two download-loop handlers | skipped tickers are counted in `✓ (45/50 OK)` |

Recorded in a test so a later sweep does not "fix" them and call it progress.

**Three hid something that changed a reader's conclusion:**

  * **The veto check failed open** — `except Exception: pass` left the BUY
    standing with an empty veto list. Exact twin of the bug fixed in
    `kala_daily_trader.py`.
  * **A missing IHSG benchmark silently dropped every alpha line.** The
    docstring called this "alpha lines are then skipped", which is Finding 8
    again: a skipped section is indistinguishable from a report that had no
    alpha to show. It now says so once, names the cause, and stays cached so it
    does not repeat per call.
  * **The survivorship warning could vanish.** If
    `from kala.universe import UNIVERSE_IS_POINT_IN_TIME` failed, the
    "backtests are survivorship-biased" warning simply did not print and a
    biased backtest ran looking clean. The fallback now assumes BIASED — a
    warning that can disappear is worse than none, because its absence reads
    as "no problem".

### One helper, because two scanners drifted immediately

Writing the engine's fix duplicated the daily trader's message, and my own
cross-check test failed — not because a scanner was wrong, but because in one
of them the string was split across two f-string literals. Correct at runtime,
invisible to a grep.

That is the sixth time a source-text assertion has misfired in this audit, and
this time it misfired in the useful direction: it flagged duplication. Both
scanners now call `entry_settings.veto_check_failed_note(exc)`, and the tests
assert on what it returns. Two further source-text tests broke when the string
moved into the function — which is itself the evidence they were testing a
string's location rather than behaviour. Both rewritten.

Four mutations, all killed, including restoring the fail-open and flipping the
survivorship fallback to optimistic.

Tests: `tests/test_engine_failures_are_visible.py` (11 new). Suite 1877 passed,
2 skipped.

## `sweep_holding_walkforward.py` — the last untouched parameter (2026-08-22)

`holding_max_days` is 60. That value was tuned while the exit ladder was still
in place; the ladder was later measured significantly negative and removed, and
nobody has swept the holding period since. It is the last parameter in this
system still carrying a number chosen under conditions that no longer hold.

`compare_exit_profiles_cached.py --sweep-holding` already sweeps it, but on the
locally cached subset — a few dozen tickers that still exist today, which is
close to a pure survivorship sample. This drives the real walk-forward over the
full warehouse:

```
python sweep_holding_walkforward.py --holds 20 30 45 60 90 \
  --max-tickers 615 --period 5y --tick-spread \
  --warehouse results/warehouse.db --min-price 0 --trust-short-cache \
  --exit-profile forward_test --strategy momentum --benchmark EQUAL_WEIGHT
```

It **shells out to `run_walkforward.py`** rather than importing the harness.
Re-implementing the measurement would create a second code path that can drift
from the one every published number in this project came from, and a comparison
between two subtly different harnesses is worse than no comparison.

What it refuses:

  * duplicate or non-positive `--holds`;
  * a passthrough `--holding-days` or `--save-folds`, which it sets per run —
    accepting either would silently mean something other than what was typed;
  * **tabulating runs whose fold calendars differ**. A warehouse refresh
    mid-sweep shifts boundaries, and comparing holding periods across different
    quarters measures the quarters. Same rule `compare_folds.py` enforces, put
    here because a sweep is where the mistake is easiest to make.

What it says out loud:

  * the BASELINE arm's clustered t and deflated Sharpe, since that is the arm
    the verdict is judged on;
  * that the result is **a shape, not a pick** — choosing the best of N holding
    periods is the same multiple-testing move the deflated Sharpe column exists
    to discount, and this project already retracted one edge to it;
  * when the best value sits at the EDGE of the swept range, because the
    optimum may then lie outside it.

### A gap it exposed in the saved tables

`--save-folds` recorded `pooled_excess_clustered_t` and `pooled_excess_dsr` —
both from the walk-forward arm — while the ALPHA VERDICT is rendered from the
FIXED-BASELINE arm. A saved table therefore could not reproduce the verdict it
was printed with. `pooled_excess_baseline_clustered_t` and
`pooled_excess_baseline_dsr` are now saved too.

Seven mutations. Six killed on the first pass; the seventh SURVIVED and was a
real hole: rendering a missing excess as `+0.00%` passed, because the test only
checked that "n/a" appeared *somewhere* in the output and the other two columns
still said it. Zero-versus-missing, in the tool built to compare measurements.
The test now asserts on the EV cell itself, and the mutation is killed.

Tests: `tests/test_sweep_holding_walkforward.py`, 18 new. Suite 1895 passed, 2
skipped.

## The sweep grew an ex-best-fold column, because its first answer was wrong (2026-08-22)

The holding sweep ran and produced a clean monotone ramp: +2.08%/trade at 90
days, clustered t 2.03, best at the edge of the range. It read as a parameter
with an optimum somewhere past the sweep.

Decomposing it by fold showed the ramp was one quarter growing. Remove the
single biggest-contributing fold and every holding period lands at or below
zero — including the 90-day winner.

`excess_excluding_best_fold()` now computes that, the table carries it as a
column, and the run prints a verdict when every setting collapses under it:

```
  hold   trades    excess  ex-best fold  clustered t  defl. Sharpe  folds<0
    20     8317    -0.05%        -0.84%        -0.14         0.075    12/14
    45     5773    +1.50%        +0.22%        +1.95         0.776     7/14
    90     5038    +2.08%        -0.06%        +2.03         0.788     8/14

EVERY holding period collapses to <= +0.25%/trade once its biggest
fold is removed. The ramp in the headline column is that fold growing,
not the strategy improving. Do not read this sweep as a parameter choice.
```

Reported as a re-pooled AVERAGE, deliberately not as "fold N is X% of the
total": on the 20-day run that share computes to −456%, because the total is
near zero. A percentage of nothing reads as a dramatic finding about nothing.
A test pins that the share is not printed.

Five mutations, all killed — including picking the biggest fold by percentage
rather than by contribution, which would have selected a three-trade fold.

Tests: 7 new in `tests/test_sweep_holding_walkforward.py` (25 total). Suite
1,902 passed, 2 skipped.

## Finding 13: the daily screen recommends without ever stating an expectation (2026-08-23)

The user's original complaint was never about a wrong number. It was: *"it kept
on telling me to hold, but then i ended up only having a profit of less than 1k
IDR or even a -5%."* Twelve findings later, that complaint had still not been
answered by anything on the screen the user actually reads.

Here is how a daily run ends:

```
TOP PICK: BRIS.JK (Score: 82/100 | ADX: 31 | R:R: 2.4:1)
v2.1 FEATURES ACTIVE:
  [x] Time Series Analysis (ROC, slope, acceleration, momentum persistence)
  [x] Relative Strength vs IHSG (outperforming stocks rank higher)
  ... seven more ticks ...
```

Nine checkmarks, a score to the point, a risk/reward to one decimal — all of it
about what the system is DOING, none of it about what any of it has been WORTH.
Precision about a signal reads as confidence about its payoff.

The payoff had been measured. It was sitting in a JSON fold table that the daily
run does not open: +1.71%/trade excess against an equal-weighted sharia
benchmark, clustered t 1.92, deflated Sharpe 0.766 — under both of the report's
own bars. On the walk-forward-chosen arm, which pools to +1.27%/trade, removing
the single biggest fold takes it to −0.44%.

`kala/expectation.py` reads that table and prints it under the
recommendations. Three states, all of them explicit:

**No measurement on disk.**

```
MEASURED EXPECTATION: NOT MEASURED
  No usable walk-forward table at results/expectation.json.
  The signals above carry no measured out-of-sample expectation.
  That is NOT the same as an expectation of zero — it is an absence of
  evidence, and it should be read as one.
  To measure it:  python run_walkforward.py --strategy momentum ...
```

Zero-versus-missing is the defect this audit has found more often than any
other. The live screen is the last place it would ever be noticed, so the rule
is stated to the user in words rather than left implicit in a blank.

**A measurement of a different configuration.** This is the live system as
shipped, and it is the important case:

```
MEASURED EXPECTATION (what a BUY from this system has been worth, OOS)
  measured 2026-08-21 (2d ago) · momentum · forward_test · hold 60d · vs EQUAL_WEIGHT
  615 tickers · 14 folds · 5945 pooled OOS trades

  NOT APPLICABLE to the configuration about to trade:
    exit_profile         measured forward_test             live legacy
    holding_max_days     measured 60                       live 20
    vetoes disabled
      measured: bear, obv, parabolic, rsi, thin_volume
      live:     (none)
  A measurement of a different configuration is not a
  measurement of this one. The number is withheld rather than
  printed beside signals it does not describe.
```

`runner_config.json` names no `exit_profile`, so the exit ladder is ON and
`holding_max_days` is 20 — while every fold table on disk was made under
`forward_test` at 60 days with the ladder off. Those are not the same strategy
holding for different lengths; they are different strategies, and the ladder
was measured at roughly −1.6 points per trade. Quoting +1.71% here would be a
sourced, specific, wrong figure — worse than printing nothing.

**A measurement that applies.** The number appears, and it is not flattering:

```
  excess over benchmark: +1.71%/trade   clustered t +1.92   deflated Sharpe 0.766
  concentration is only available for the WALK-FORWARD-CHOSEN
  arm in this table — it predates the per-fold baseline column:
    chosen arm pooled: +1.27%/trade
    chosen arm excluding its biggest fold (#10): -0.44%/trade
  Re-run to get this decomposition for the arm above.
  8 of 14 folds negative (chosen arm).
  VERDICT: EV positive but WEAK (clustered t 1.92 < 2): could be noise.
```

### The arm mix-up, found in this module's own first version

The headline, the clustered t, the deflated Sharpe and the VERDICT are all
computed on the FIXED-BASELINE arm. The only per-fold excess the saved tables
carried was the WALK-FORWARD-CHOSEN arm's. So the first version of this block
printed `excluding the biggest single fold: -0.44%/trade` directly under
`+1.71%/trade` — subtracting one arm's quarter from the other arm's total. The
two pool to +1.71% over 5,241 trades and +1.27% over 6,082; the result was a
decomposition of neither.

The v76 holding sweep shipped with the same defect in its `ex-best fold`
column, and its collapse verdict was read off it. Both are corrected here:

- `fold_row()` now saves `excess_baseline_pct` and `n_baseline`, and
  `saved_table()` saves `pooled_excess_chosen`, which was never kept at all —
  the chosen arm's clustered t and DSR were saved with nothing to correct.
- `excess_excluding_largest_fold()` takes the column names explicitly. There is
  no default that mixes arms.
- The live block uses the baseline column when the table has it. When it does
  not — all fifteen tables on disk — it falls back to the chosen arm, **says
  so**, and prints that arm's pooled figure beside it, so the two numbers a
  reader compares come from one measurement.
- The sweep does not fall back. Its `ex-best fold` cell reads `n/a` for a table
  without the column, with a note saying the v76 figures were computed the
  wrong way and should not be carried over.

The audit's own recurring signature, in the tool built to detect it, for the
third time. It was caught by writing the fixture with the chosen column 100
points higher than the baseline column, so a function reading the wrong arm
cannot land on the right answer by accident.

### The trap every fold table on disk was sitting in

A walk-forward made WITHOUT `--apply-entry-vetoes` applied no vetoes at all and
records `disabled_vetoes: []` — byte-identical to what a full-veto run records.
Compared on that field alone, the no-veto arm matches a live bot running all
five. Those two arms differ by 4.23%/trade (+1.71 against −2.52). It is the
single most misleading figure this module could have printed, and all fifteen
saved tables are in exactly that state. `measured_vetoes_off()` reads the
`apply_entry_vetoes` flag first; a table that never recorded it is reported as
"not recorded", which withholds the number the same as a difference does.

### `entry_settings.describe()` was called by nothing

Its docstring reads: *"A setting that cannot be seen from the output is a
setting nobody can verify took effect."* It was in no output — only in its own
tests. This audit told the user in writing to apply `disabled_entry_vetoes` and
then verify the log reads `entry vetoes: ALL OFF`. No code was capable of
printing that line. The instruction was unfollowable and nothing would have
said so. `live_lines()` now emits it above the expectation block.

### Supporting changes

- **`run_provenance` records `measured_at` and `threshold_grid_size`.** Without
  a stamp the live path can only ever say "age unknown", and staleness read off
  the file mtime lies in the reassuring direction (copying a table makes a
  two-year-old measurement look fresh). Without the grid size the verdict
  cannot apply its deflation clause at all — and an old table with a sub-bar
  deflated Sharpe would otherwise render `EDGE CONFIRMED OOS` directly beneath
  the 0.766 that contradicts it, which is precisely the bug `edge_verdict`'s
  extra arguments were added to fix. When the count is unknown the deflation is
  stated separately rather than skipped or invented.
- **`saved_table()` extracted from `main`.** The tie between `run_provenance`
  and the bytes on disk was asserted by grepping this module's own source. That
  is not a test: it passes whenever the line exists, and it would have passed
  unchanged through the v68 defect it was written to prevent. A test now calls
  `saved_table` with a stand-in report and reads the dict.
- **The concentration arithmetic has one home.** `excess_excluding_largest_fold`
  moved into `kala/expectation.py`; `sweep_holding_walkforward.py` calls
  it. Two copies of a concentration check is how two answers start to disagree.

Thirty-one mutations, all killed, plus one documented EQUIVALENT mutant (the
threshold comparison's epsilon — every threshold reaching that code round-trips
exactly through JSON, so no test can distinguish `!=` from a tolerance, and
writing one that pretended to would be theatre).

Repro: `python repro/repro_unmeasured_recommendation.py` prints all four
states. Its per-fold rows are a reconstruction — the trade counts are real, the
per-fold excess column of that run is not in front of me — and the script
refuses to print unless the reconstruction still reproduces the four recorded
facts (+1.71%, −0.44% ex-fold-10, fold 10 largest, 8 of 14 negative).

Tests: `tests/test_expectation.py`, 50 new, plus 4 in
`tests/test_sweep_holding_walkforward.py` for the arm fix. Suite 1,959 passed,
2 skipped.

## Finding 14: a position whose entry date is not a trading bar is held forever (2026-08-23)

`papertrade._bars_held` matched the entry date against the price index by exact
date equality and returned a bare `None` on any miss. Both callers then wrote:

```python
if bars_held is not None and bars_held >= max_days:
```

with no `else`. A `None` therefore took the identical branch to a two-day-old
position: no exit queued, and no line in any report — not `exits_queued`, not
`unevaluated`, not `skipped`, not `tickets`. The position was not on the daily
message at all.

Two positions, same history, both 189 bars past a 15-bar limit, differing only
in whether the entry date lands on a bar:

```
  what the old branch did with each position:
    GOOD.JK   held=189   -> queue SELL
    GHOST.JK  held=None  -> no branch taken, nothing recorded

  queued for sale : ['GOOD.JK']
  unevaluated     : []
  skipped         : []
```

### Why this is not a corner case

Two ordinary routes produce an entry date that is not a trading bar, both read
off the source rather than imagined:

- **`manual_buy(ticker, shares, price, date=...)`** accepts any date string and
  validates nothing about it being a trading day.
- **`daily_run.main()` has no trading-day guard.** It books fills stamped
  `today_wib()` whenever the scheduler fires, and this project has no IDX
  exchange calendar — 2026-05-01 and 2026-08-17 are market holidays it does not
  know about. The fill price comes from `h.iloc[-1]`, the last available bar,
  while `entry_date=today`. On a holiday those are different days by
  construction: the price is the previous session's, the date is the holiday,
  and the position can never be aged again.

### Why it matters most under the profile v77 recommends

Under `forward_test` every price-based exit is inert **by design** —
`holding_max_days` is the only rule that closes a position. A position that
cannot be aged under that profile has no exit rule at all. And `telegram_bot`
carried a second copy of the same `is not None` guard, so `/review` and
`/priority` printed a bare HOLD for it, indefinitely.

The audit opened with *"it kept on telling me to hold."* This is a mechanism
that does precisely that.

### The fix

`bars_held_or_reason()` returns `(bars, reason)`:

- An **off-bar** date is counted from the first bar at or after it. A Saturday
  entry is not ambiguous — the position started at the next open — and the
  result is byte-identical to the old behaviour whenever the date is on a bar.
- An entry **before the first bar in the window** is NOT snapped forward.
  Doing so would measure from the window's start, over-count the bars held and
  sell the position early: trading a silent non-exit for a silent wrong exit is
  not a fix. It returns a reason.
- A **future** date, an **unparseable** one, and `NaT` each return their own
  reason. The bare `except Exception` now names the exception instead of
  swallowing it.

Both call sites report the skip. `step()` appends to `report["unevaluated"]`,
the same list the missing-history branch three lines above already used — that
branch was fixed for exactly this reason and this one was missed. `/review`
replaces the bare HOLD with `max-holding rule NOT checked — <reason>`.

### The user's current book is clean

All 66 dated records in `paper_state.json` — 9 open positions, their fills, and
every closed trade — fall on weekdays, and none on a known IDX holiday. This is
a latent defect, not one that has already cost money. It is stated that way
deliberately: overclaiming here would be the same failure the audit exists to
find.

### An off-by-one the tests did not cover

Mutation M10 swapped `held >= max_days` for `held > max_days` and **survived**
the entire suite: nothing held a position for exactly the limit. Under
`forward_test` that is not a rounding detail — every position would run one bar
longer than the validated rule, on every trade. Fixed with a parametrised
boundary test at 14/15/16 bars.

Thirteen mutations, all killed after that. M1 restores the exact date match:
it does not raise, does not warn, and produces a report that looks like a
healthy day, so if M1 had survived nothing here would be testing the finding.

Repro: `python repro/repro_position_that_never_ages.py`. The "before" half is a
re-enactment of the old call site rather than a monkeypatch of the helper —
patching only the helper would let the new reporting branch fire and show the
defect as already half-fixed.

Tests: `tests/test_max_holding_is_always_checked.py`, 19 new. Suite 1,978
passed, 2 skipped.

## Finding 15: the daily log printed one entry threshold, the scanner used another (2026-08-23)

Auditing v77's recommendation found Finding 14. Auditing it again found this.

`daily_run.main` resolves the profile and logs it on every single run:

```python
trade_cfg = config_for_profile(cfg.get("exit_profile"))
...
log("exit profile: FORWARD_TEST — no stop/target/trailing, "
    f"entry score >= {trade_cfg.backtest.score_entry_threshold:.0f}, "
    f"hold {trade_cfg.backtest.holding_max_days}d. ...")
```

`kala_daily_trader.get_live_signal` decided the BUY cutoff like this:

```python
buy_threshold = _Config().backtest.score_entry_threshold  # validated BUY cutoff (60)
```

`_Config()` is the bare default class. It never read `runner_config.json`. So
under `"exit_profile": "forward_test"` the log said **entry score >= 80** while
the scanner labelled everything from **60** upward a BUY — and the paper trader
buys every name labelled BUY or STRONG BUY.

```
  runner_config.json : exit_profile = forward_test
  daily_run LOGGED   : entry score >= 80
  scanner USED (old) : 60   <-- the defect

  buy cutoff = 60                    buy cutoff = 80
    score  label                       score  label
       76  BUY           <- bought        76  HOLD
       68  BUY           <- bought        68  HOLD
       61  BUY           <- bought        61  HOLD
```

The comment sitting directly above that log line reads: *"a strategy change
this large must never be something you have to read the source to discover."*
It was printed on every run, and it was not what ran.

### Why the number matters

The +1.71%/trade headline was measured at **baseline threshold 80**, over 5,241
trades — `run_walkforward`'s own provenance note records exactly that. A live
bot entering at 60 takes trades that measurement does not contain. Finding 13
said the running configuration matches no measurement in this repository; this
is a fourth axis where that was true, and the only one the daily log actively
asserted was fine.

### The fix, and why it is safe to ship

`kala.config.live_config()` reads `runner_config.json` and resolves the
profile, with the same tolerance as everything else here: a missing,
unreadable or non-dict config yields the LEGACY defaults, byte-identical to the
hardcoded `Config()` it replaces. An unknown profile name still raises.

**Nothing changes for anyone who has not opted in.** `runner_config.json` as it
stands has no `exit_profile`, so the cutoff stays 60 and today's behaviour is
unchanged. The new cutoff only takes effect when the user sets the profile —
which is exactly the moment they are asking for it.

### The band ladder is now testable

The five-branch BUY/HOLD/SELL ladder was inline in a 200-line function whose
only exercise was running the whole networked scan. `signal_for_score(score,
buy_threshold, strong_threshold=80, is_safe=True)` is pure and pinned at every
boundary.

Extracting it surfaced an ordering bug that was latent at the old cutoff:
`STRONG BUY` was hardcoded at `>= 80` and tested *before* the buy cutoff, so a
cutoff above 80 would label a score of 85 STRONG BUY — above the strong line
and below the line that decides whether to buy at all. `strong` is now
`max(strong_threshold, buy_threshold)`. At the forward_test cutoff of exactly
80 the plain-BUY band is empty and every qualifying name is STRONG BUY; that is
correct, the paper trader buys both, and a test pins it as a consequence of the
numbers rather than an accident of ordering.

Ten mutations, all killed. M1 restores the hardcoded `Config()`: it raises
nothing, logs nothing, and produces a scan that looks entirely normal.

Repro: `python repro/repro_threshold_the_log_lied_about.py`.

Tests: `tests/test_live_entry_threshold.py`, 31 new. Suite 2,009 passed, 2
skipped.

## Finding 16: preflight told the user the headline recommendation does nothing (2026-08-23)

The same question as findings 14 and 15 — *is the number this reports the
number this uses?* — asked of the tool whose entire job is answering it.

Run the configuration this audit recommends through `preflight`:

```
$ python -c "...check_config_keys({'exit_profile': 'forward_test',
                                   'disabled_entry_vetoes': [...]})"
WARN  'disabled_entry_vetoes' is not read by any code. It is silently
      ignored, so whatever you set it to is having no effect.
```

That is false, and it is the opposite of the truth about the single most
valuable change in this audit — worth **+4.23 points per trade**. A user who
followed the instruction and then ran preflight was told, in those words, to
take the setting back out.

`breaker_preserve_halt_when_unreadable` was in the same state: a live circuit
breaker option, read at `daily_run.py`, reported as inert. Telling someone a
safety toggle has no effect is the worst possible polarity for this bug.

### Why the existing guard missed both

`KNOWN_CONFIG_KEYS` is hand-maintained. `test_preflight.py` guarded that every
key in `daily_run.DEFAULT_CONFIG` is registered — and both missing keys are
read somewhere else: one by `entry_settings.entry_config_from`, one inline in
`daily_run`'s `BreakerConfig`. Nothing covered them.

A registry that is wrong in this direction is worse than no registry. A missing
warning is a missed opportunity; a false one argues the user out of a correct
configuration.

### The fix

- `breaker_preserve_halt_when_unreadable` registered.
- `disabled_entry_vetoes` **imported** from `entry_settings.CONFIG_KEY` rather
  than spelled out again. Duplicating the string is what let the two disagree;
  now there is one of them.
- `tests/test_config_keys_are_registered.py` scans every `*.py` outside
  `tests/` for `cfg.get("literal")` and asserts each key found is registered.
  25 keys, all of them real — the scan produced no false positives.

The scan is deliberately narrow and cannot see a key read through a variable,
which is exactly how `disabled_entry_vetoes` hid. That case is covered
separately by renaming `entry_settings.CONFIG_KEY`, reloading `preflight`, and
asserting the registry followed the rename — a registry with its own copy of
the string does not. Grepping preflight's source for the import would have
passed on a file that also carried a stale literal.

Six mutations, all killed, including both original defects restored (drop each
key back out) and the wording ("is unrecognised" instead of "is having no
effect" — a bare unknown-key notice is ignorable, the claim about effect is the
useful part).

Tests: `tests/test_config_keys_are_registered.py`, 10 new. Suite 2,019 passed,
2 skipped.

### Three findings, one question

14, 15 and 16 all came from asking whether a number this system *reports* is
the number it *uses*:

| | reported | used |
|---|---|---|
| 14 | position aged, exit rule live | rule silently skipped for an off-bar entry |
| 15 | `entry score >= 80` | bought from 60 |
| 16 | "this setting has no effect" | the setting works, and is the best change available |

None of the three is an arithmetic error. All three are a claim about the
system that the system contradicts.

## Finding 17: two cost models in one run — the dearer one reports, the cheaper one books (2026-08-23)

Same question again, asked of money instead of settings.

`daily_run.py`, weekly friction report:

```python
friction_report(raw, costs=CostModel(spread_mode="tick_floor"), ...)
```

`daily_run.py`, the config the paper trader books its fills through:

```python
trade_cfg = config_for_profile(cfg.get("exit_profile"))   # costs = default = flat
```

The same run tells the user what their trading costs under the honest
tick-floored model and records those trades at the optimistic flat one. Every
validated number in this project was measured with `--tick-spread`, i.e.
tick_floor.

### The size of it, on this account's own book

```
ticker      entry IDR   booked  measured     gap
KBLI.JK           323    0.64%     1.05%   0.42%
BSML.JK           519    0.64%     1.39%   0.76%
STAA.JK         1,104    0.64%     0.89%   0.25%
...
mean gap                                   0.23%
```

Every gap is positive — flat is never the dearer model, so this is a **bias,
not noise**: 0.23 points per trade, always in the direction that makes the live
account look better than the backtest. The measured excess is +1.71%/trade, so
it is about **14% of the headline the forward test will be compared against**.
On a 67-rupiah name, which cannot trade inside its own 1-rupiah tick, the gap
is 1.28 points.

This lands squarely on the forward test — the one piece of evidence this
project has never had, and the thing every recent release has been clearing the
way for. Left alone it would have been biased toward "live is beating the
model" before a single trade was placed.

### The fix, and what was deliberately not done

The default stays `flat`. Changing it would silently rewrite a live book's
arithmetic, which is the move this audit keeps finding in other people's code.
Instead:

- `"costs_spread_mode": "tick_floor"` in `runner_config.json` aligns the book
  with every measurement. An unknown value **raises** rather than quietly
  leaving the optimistic model in place.
- `config_from_settings()` resolves profile **and** costs together.
  `daily_run` used `config_for_profile(...)` alone, which resolves the profile
  and drops the cost model — so the setting would have reached the scanner and
  never the thing that charges the fills. One function, both callers.
- `run_provenance` records `spread_mode`, and the expectation block treats it
  as **binding**: a tick-floored measurement is not quoted at a flat-booked
  account, and a table that never recorded the field is reported as "not
  recorded" rather than assumed to be the cheaper one.
- The daily log states which model is booking today's fills.

### A dead registry entry, the mirror of Finding 16

`"costs"` was in `KNOWN_CONFIG_KEYS` and **read by nothing**. A user could put
a whole cost model in `runner_config.json`, have preflight report the config
clean, and have it ignored entirely — Finding 16 with the polarity reversed.
Removed, and the registry is now checked in both directions: every literal key
read in the source must be registered, and every registered key must appear as
a read somewhere (with an explicit, justified allowlist for the one key read
through a constant). A non-vacuity test injects a fake dead key and asserts the
check catches it.

Eleven mutations. Three survived the first pass, all three real gaps:

- the saved table dropping `spread_mode` — every test supplied it by hand in a
  fixture rather than asking the writer for it,
- `LiveSetup.from_config` hardcoding `"flat"` — every test built a `LiveSetup`
  directly, so nothing exercised the path the daily run takes,
- the new key going unregistered — the mutation ran only the registry tests,
  which do not assert on that particular key.

All three now covered; 11 of 11 killed.

Repro: `python repro/repro_two_cost_models_one_run.py`.

Tests: `tests/test_live_spread_model.py`, 24 new. Suite 2,045 passed, 2 skipped.

### Footnote: the harnesses caught my own refactor

Running every mutation harness from the packaged zip — not just the new one —
turned up two defects introduced by this release's own refactor:

- `mutate_live_threshold.py` M2 reported **STALE ANCHOR**. Splitting
  `live_config` into `config_from_settings` moved the line it anchored to. The
  harness reported it as "nothing was measured" rather than as caught or
  survived, which is the distinction that made it visible at all.
- M4 **SURVIVED**: the non-dict guard now existed in both functions, so
  deleting either one changed nothing. An untestable branch is dead code, and
  the practice here is to remove it rather than write a test that cannot fail.
  The duplicate is gone.

Neither would have been visible from the test suite, which stayed green
throughout.

## Finding 18: the block printed a command and then rejected the command's output (2026-08-23)

Before shipping v81 I ran the three-key recommendation through the whole live
path to check my own claims. Every one held — and the check surfaced a defect
in the instruction itself.

The NOT MEASURED block ended with a fixed string:

```
To measure it:  python run_walkforward.py --strategy momentum --exit-profile forward_test
                  --benchmark EQUAL_WEIGHT --save-folds results/expectation.json
```

Follow that literally with `"costs_spread_mode": "tick_floor"` set, and the
resulting table records `spread_mode: flat` — because the command has no
`--tick-spread`. The block then **refuses the table it asked for**, on the
binding field added the same day. Same for a live `holding_max_days` or entry
cutoff that differs from the profile's default.

A printed instruction that cannot be followed to a working result is the same
defect as a warning that is wrong, and this one was mine, from v77.

### The command is now derived from the live setup

```
  python run_walkforward.py --strategy momentum --exit-profile forward_test \
      --apply-entry-vetoes --disable-veto bear obv parabolic rsi thin_volume \
      --tick-spread --holding-days 60 --baseline-threshold 80 \
      --benchmark EQUAL_WEIGHT \
      --save-folds results/expectation.json
```

and, for the same code with nothing configured:

```
  python run_walkforward.py --strategy momentum --exit-profile legacy \
      --apply-entry-vetoes --holding-days 20 --baseline-threshold 60 \
      --benchmark EQUAL_WEIGHT \
      --save-folds results/expectation.json
```

The NOT APPLICABLE block prints it too, in place of the old "Re-measure with
the live settings" with no command.

### The test that closes the loop

`build_parser()` was extracted from `run_walkforward.main` so the CLI can be
parsed without running. The round-trip test then: generates the printed
command, **parses it with the real parser**, builds the provenance that run
would save, and asserts `mismatches()` returns empty — across four
configurations, including the recommended one and the one shipped today.

Nothing short of parsing the real CLI catches this, because the defect is a
disagreement between two pieces of code that never met: a string in one module
and an argument parser in another.

Six new mutations (M32-M37), each making the command describe a slightly
different configuration from the one running. All caught; 37 of 37 across this
harness. Full sweep: all six mutation harnesses green.

Tests: 6 new in `tests/test_expectation.py` (56 total). Suite 2,051 passed, 2
skipped.

### What the verification confirmed

Everything else in the recommendation checks out, run end to end:

```
preflight            OK  3 keys, all recognised
entry cutoff         80          (was 60 before v79)
holding_max_days     60          (was 20)
spread_mode          tick_floor  (was flat)
trailing enabled     False
hard stop            -99.0       (inert by design)
target profit        999.0       (inert by design)
log line             entry vetoes: ALL OFF — the measured-best setting
```

## Finding 19: a money flag that three ordinary typos silently ignored (2026-08-23)

Finding 18 came from running an instruction instead of reading it. The obvious
next step was to do that for the documents — 6,600 lines of CHANGES.md and
PROJECT_STATUS.md, plus a summary quoting counts, filenames and commands from
all of it, every figure synced by hand.

`check_docs.py` compares four classes of documented claim against the
repository: quoted line counts, the test-file count, every `repro/`, `tests/`
and `kala/` path named in backticks, and every documented
`python foo.py --flag` command — the last checked against that script's real
`--help`.

**The counts and paths were all correct.** 39 documented commands, 14
documents, no broken references, no stale line counts. That is the honest
result and it is worth stating plainly rather than dressed up.

One command needed an exemption, and the exemption was the finding.

### `daily_run.py --capital` is not an argparse flag

```python
if "--capital" in sys.argv:
    cfg["daily_capital_idr"] = float(sys.argv[sys.argv.index("--capital") + 1])
```

`daily_run` has no parser at all, so `--help` cannot list it. Looking into why
it needed an exemption:

```
  --capital 3000000                  override -> 3,000,000
  --captial 3000000                  no override        <- typo
  --capital=3000000                  no override        <- the form every
                                                           other script here
                                                           accepts
  -capital 3000000                   no override
```

Three ordinary spellings ran at the **stored** `daily_capital_idr` — 4.7M
instead of the 3M asked for — and the log never mentioned capital at all. The
only symptom is that evening's position sizing being wrong.

It is a small finding next to 13 through 17, and it is on a money input, and it
is the signature shape: a flag that does nothing while looking like it did.

`parse_capital_override()` now accepts both spellings, refuses an unknown
`--flag` rather than ignoring it, rejects a non-numeric or non-positive amount,
and defines that the last `--capital` wins. `daily_run` is normally invoked by
a scheduler with no arguments, so nothing legitimate is refused.

### The checker caught its own arrival

Adding `tests/test_docs_match_the_repo.py` took the test-file count from 133 to
134, and the summary still said 133 — so the first full run of the new test
failed on the document it was written to guard. That is the intended behaviour
and it is why the check exists: six line-count and test-count figures have been
hand-synced in this session alone.

The repo's own encoding rule then caught the checker: `subprocess.run(...,
text=True)` with no `encoding=` failed `test_no_subprocess_text_mode_without_an_encoding`,
a test written for an earlier finding. Fixed.

### What it deliberately does not check

Measured results. +1.71%/trade cannot be re-derived without a five-year
warehouse and an hour of compute, and a checker that silently skipped it would
be worse than one that never claimed to. Those figures are guarded by the saved
fold tables and the repro scripts instead. Said in the module docstring, so
nobody reads a green run as more than it is.

Sixteen mutations, all killed. One survived the first pass and was a real gap:
the line-count check reported a MISSING claim while the test-count check
treated it as satisfied, so deleting the claim outright made the checker pass.

Tests: `tests/test_docs_match_the_repo.py`, 26 new. Suite 2,076 passed, 2
skipped.

### Footnote: the checker flagged its own release notes

Writing the paragraph above — "every documented `python foo.py --flag` command"
— produced three failures, one per document, because the checker read the
illustrative name as a command. The fix is an explicit `COMMAND_PLACEHOLDERS`
exemption rather than prose contorted to satisfy a regex, kept as narrow as the
path placeholder beside it, and a mutation confirms it does not widen to every
script name.

Seventeen mutations, all killed. Suite 2,078 passed, 2 skipped.

## Finding 20: a killed mutation harness left a live trading file mutated (2026-08-23)

Verifying v83 from the extracted zip, one test failed there that passed in the
source tree:

```
FAILED tests/test_live_entry_threshold.py::test_the_legacy_bands_are_unchanged[60-BUY]
```

The extracted copy differed from the source by one character:

```
<     if score > buy_threshold:
---
>     if score >= buy_threshold:
```

That is mutation M8 from `repro/mutate_live_threshold.py`. A ten-minute
command timeout had killed the harness mid-run, and its restore never
happened.

### `finally` does not cover a kill

Every harness wrote a defect into a real source file and restored it in a
`finally`. That covers an exception and a Ctrl-C. It does not cover SIGKILL, a
timeout kill, a container stop, or the harness process dying — and the file
left mutated is the one that decides which stocks the live bot buys, carrying
an inclusive bound turned exclusive: behaviour changed, nothing that looks like
damage.

**The shipped zip was clean** — it was built from a directory no harness had
been killed in, and that was verified byte-for-byte before saying so. But the
exposure is real: a build from a tree in that state would ship a mutated live
trading file, and the only symptom would be a test failing somewhere unrelated.

### The fix

`repro/_mutation_guard.py` writes the original bytes into an **fsynced
sentinel before touching the file**. At every instant either the file is intact
or the sentinel holds what it was. Every harness calls `restore_if_interrupted()`
on startup, which repairs the tree and **says so** — a silently self-healing
repair would hide that a run was killed at all.

The seven harnesses now share one `run_mutations()` implementation, so the
sentinel and the STALE-versus-SURVIVED distinction exist once rather than seven
times. It accepts both the anchored-text and callable mutation forms the
harnesses use.

Sixteen tests, including one that starts a real subprocess, **SIGKILLs it
mid-mutation**, and asserts the next invocation restores the file. Nothing
inside a dying process can do that, which is the point. Plus a repository-wide
check that no sentinel is left lying around, and one that every
`repro/mutate_*.py` actually goes through the guard — one unguarded harness is
enough.

### A guard that accused correct code

Fixing the above tripped `test_no_subprocess_text_mode_without_an_encoding`,
which reported this as a violation:

```python
subprocess.Popen([...], stdout=subprocess.PIPE,
                 text=True, encoding="utf-8")
```

`encoding=` is right there. The scan backed up to the nearest `subprocess.`
token to find the enclosing call and landed on **`subprocess.PIPE`**, then
parsed the wrong argument list. Any call passing `stdout=subprocess.PIPE`
before `text=True` was a false positive.

Finding 16 with a different subject: a checker wrong in the direction of
accusing working code is worse than one that misses, because the fix people
reach for is to silence it. It now locates the actual enclosing call, with a
test asserting both that a correct call passes and that a real offender is
still caught.

Suite 2,095 passed, 2 skipped.

---

## A checker that accused four working scripts (finding 21)

Found on a machine that was not this one. The suite was run on Windows, where
`pyportfolioopt` would not build — its `ecos` dependency wants a C compiler that
was not installed — and `check_docs.py` reported seventeen problems of this
shape:

```
PROJECT_STATUS.md: `python weighting_study.py --period` —
                   weighting_study.py does not accept --period
```

`weighting_study.py` accepts `--period`. It is in `add_argument`, and the
command in the document is one that has been run.

### What it was actually reading

The flag check runs each script's real `--help` and looks for the flag in the
output. It did not look at the **exit status**. On that machine the study
scripts cannot import, so `--help` produced:

```
Traceback (most recent call last):
  File "weighting_study.py", line 25, in <module>
    import pandas as pd
ModuleNotFoundError: No module named 'pandas'
```

No flag appears in a traceback. Every documented flag on every script that would
not import came back as "does not accept". Seventeen there; 162 here, from nine
scripts, once the same environment was reproduced without the dependencies
installed.

This is the defect the tool exists to find — *a failure that renders as an
ordinary negative result* — committed by the tool, and in the worst direction:
it accuses correct code, and the obvious way to make it quiet is to edit the
document until the false claim goes away.

### Three outcomes, not two

`--help` is now believed only when it exits 0.

| what happened | how it is reported | exit |
|---|---|---|
| the script answered, flag present | checked | 0 |
| the script answered, flag absent | **contradicted** — fix the doc or the code | 1 |
| the script would not run | **not checked** — reason quoted, flags compared against the script's own source text as weaker evidence | 2 |
| the script would not run, flag named nowhere in it either | **unverified** — an open question, not an accusation | 2 |

The exit status carries the distinction on purpose. A run that could check
nothing must not be indistinguishable from a run that checked everything, and
the summary line now states how many commands were settled by a real `--help`
and how many only by source text.

The "could not be run" block prints even under `--quiet`: *this was not checked*
is a result, not chatter.

### Which then found two real ones

With the exit status honoured, two scripts turned out to fail `--help` for
reasons that had nothing to do with dependencies:

```
$ python daily_run.py --help
unknown option '--help'. The only option here is --capital ...    # exit 1

$ python intraday_watch.py --help
                                                                  # exit 0, nothing
```

`daily_run.py` was passing the old checker **by accident**: the string
`--capital` appears inside the error message complaining about `--help`, so the
flag was "found" in the help text. The one script whose only option is
hand-typed was the one script that would not say what its option was.

`intraday_watch.py` is worse. It read `force = "--force" in sys.argv` — the same
pattern as the `--capital` defect of finding 19 — and it exits silently when the
market is closed. So a run typed as `intraday_watch.py --forse` went ahead
*unforced*, printed nothing, and returned 0 — which is exactly what a
successful forced run looks like. `--help` had the same fate.

(That typo is written without a leading `python` on purpose: with it,
`check_docs.py` reads the sentence as a command and correctly reports that
`--forse` is not a flag. It caught this paragraph on the first run.)

Both of these were the scripts `HAND_PARSED` had **exempted** from the flag
check, for reading `sys.argv` directly. The exemption was the bug's cover.

### Fixes

* `intraday_watch.py` uses `argparse`. `--force` is declared, `--help` prints
  usage, and `--forse` exits 2 with `unrecognized arguments` instead of running
  a different thing quietly.
* `daily_run.py` gains a `USAGE` block, and `-h`/`--help` prints it and exits 0.
* `daily_run.main()` parses the command line **before** `load_config()`.
  Previously `--help` reached its usage text only after the exit profile, the
  cost model and the whole measured-expectation block had been logged — and an
  unusable `--capital` was refused only after that same output had gone out,
  reading as if it described the run that was about to be refused.
* `HAND_PARSED` is empty, and a test asserts it stays empty. Every entry it ever
  held was a bug wearing a waiver.
* `tests/test_mutation_guard.py` used `proc.send_signal(signal.SIGKILL)`, which
  raises `AttributeError` on Windows — the constant does not exist there. It now
  uses `proc.kill()`: SIGKILL on POSIX, `TerminateProcess` on Windows, neither of
  which runs a `finally`, so the test's premise holds on both.

### Verification

The checker's tests were rewritten to run against synthetic one-file
repositories rather than the real scripts. They had been asserting things about
`run_walkforward.py` and `daily_run.py`, which meant the *environment* decided
what they proved: on a machine missing an optional dependency they passed or
failed for reasons unconnected to the checker. Six new tests cover the crash,
the timeout, the source-text fallback, the unverified case and the three exit
codes.

`repro/mutate_doc_consistency.py` grew from 16 mutations to 25 — including
reverting the exit-status check, making a timed-out `--help` an empty flag list,
letting an unverified claim exit 0, and putting both `sys.argv` command lines
back. All 25 applied and caught; no stale anchors, no survivors.

Suite 2,116 passed, 2 skipped.

---

## Two tests that only passed on a machine that had already been used

Caught by the standing check finding 20 put in place: build the zip, extract it
somewhere else, and run the suite **there** rather than in the working tree.

```
2 failed, 2114 passed, 2 skipped

tests/test_entry_atr_is_recorded.py::test_buy_command_passes_an_atr_through
tests/test_entry_atr_is_recorded.py::test_buy_reply_flags_a_missing_atr
  FileNotFoundError: .../runner_config.json
```

Both exercise `/buy`, which calls `telegram_bot.load_config()`. That reads
`runner_config.json` — a file holding Telegram credentials and personal capital
settings, correctly gitignored, and therefore **absent from every fresh clone**.
The tests passed in the working tree only because the tree had been run in.

Two ways that is wrong, not one:

* on a clone, they fail with `FileNotFoundError` from a test about ATR sizing —
  a failure that says nothing about what it was testing;
* on a machine where the file *does* exist, they read the operator's real
  capital and position limits, so what they exercised varied with settings that
  are not in version control.

Both now take an `isolated_config` fixture that copies
`runner_config.json.example` into a `tmp_path` and points `CONFIG_PATH` at it.
Verified by moving the real file aside and running them: 8 passed.

`telegram_bot.load_config()` itself is unchanged. A missing config there
surfaces to the operator as `⚠️ Error: [Errno 2] No such file or directory`,
printed with a traceback — ugly, but it neither swallows the failure nor
invents a default, so it is not a finding.

Suite 2,116 passed, 2 skipped — in the working tree and in the extracted zip.
