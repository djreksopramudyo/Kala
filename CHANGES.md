# kala — what changed

> **Validation status is NOT tracked here.** For "does the signal work?" the
> canonical answer is `PROJECT_STATUS.md` (short version: no demonstrated
> out-of-sample edge — archived as a learning/paper-trading tool). This file
> is a changelog of *what was built*, not a claim that any of it is profitable.

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
