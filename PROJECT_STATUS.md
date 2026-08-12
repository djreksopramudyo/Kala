# PROJECT_STATUS — 2026-07-20 (updated 2026-07-23: bandarmology, long-horizon momentum, US-large-cap momentum, then US long-horizon momentum results added — RESEARCH PHASE CLOSED; updated 2026-07-24: low-volatility anomaly tested on both markets, confidently negative on both — see "Low-volatility anomaly result"; same day, turn-of-month calendar effect also tested on both markets — confidently negative on IDX, noise-level on US, same sign-flip pattern as long_momentum — see "Turn-of-month calendar effect result"; same day, ramadan_effect tested using a user-supplied verified date table — underpowered null, not a confident rejection (alpha t=-0.64 on only ~10 independent yearly occurrences) — see "Ramadan effect" section; same day, two more tested — high_proximity (52-week-high, 13th hypothesis) is a NULL on both markets (IDX weak-null t=-1.45; US clean re-run beta-not-alpha t=-0.56); and the weighting study's promising US inverse-vol result did NOT transfer to the user's actual correlated IDX basket (tiny drawdown cut, big return cost), so no new tradeable lever was found — see "Two more additions" section; same day, volatility targeting tested on real data — DECISIVE, both long/clean IDX windows (user's real basket AND a broad 40-name diversified sample) show a real return cost not justified by the drawdown cut; only the US reference was positive — closes the last mechanically distinct lever; tradeable-lever space now exhausted (13 signals + 4 weighting + 1 exposure overlay, all rejected or not-transferring) — see "Volatility targeting" -> Results; CORRECTION, same day: "exhausted" was an over-claim — a fourth category, portfolio-CONSTRUCTION decisions (lump-sum vs DCA, basket selection, holdings count), had never been tested and two studies were built for it — see "Portfolio-CONSTRUCTION decisions"; updated 2026-07-25: core-satellite result CONFIRMED REAL (XIJI listing verified by user as April 2013, ruling out a data-artifact concern) — the satellite sleeve earned its risk, beating XIJI-only in 90% of rolling windows over the full available 8y window — the single most decisive, actionable finding in the project; see "Core-satellite" -> Results; updated 2026-08-03: support/resistance (daily-bar
version of the classic retail level method, prompted by a user question about a
day-trading video) tested — 15th hypothesis, CONFIDENTLY NEGATIVE, not a weak null
(raw t=-3.52, alpha t=-3.40, n=1432 OOS trades, both agreeing in sign on real
statistical power) — see "Support/resistance result"; same day, multi-horizon
sign-sum trend (AHL/time-series-momentum construction, prompted by a user
question about a crypto backtest video) tested — 16th hypothesis: trained-arm
flat (t≈0.2-0.4) but the naive fixed-threshold rule most people would actually
trade is confidently NEGATIVE (t=-2.66/-2.50, n=3009) — training retreated to
the thinnest strict subset rather than finding real structure, textbook
overfitting-to-noise — see "Multi-horizon trend result")

> **This file is the CANONICAL validation status for the project.** Any other
> doc (`HOW_IT_WORKS.md`, `CHANGES.md`, `README_*`) that describes whether the
> signal "works" is secondary — if it conflicts with this file, this file
> wins. The code-adjacent detail of *how* this verdict was reached lives in
> `kala/edge.py`'s module docstring. Don't restate the verdict elsewhere
> with copied numbers that can go stale; link here instead. For the narrative
> version of this same finding — written for a reader, not a grep — see
> `CASE_STUDY.md`. For the operational path from "research done" to "money
> actually invested", see `DEPLOY_CHECKLIST.md`.

---

## SUMMARY — read this first

This file grew by append-only correction over many sessions and is now long.
The title line above is a changelog, not an orientation. This section is the
map; everything below is the evidence in the order it arrived.

**The one-line answer**: no predictive edge survived honest testing, but
several *structural* choices did — and one late result (core-satellite)
reversed an earlier conclusion, so read the Results subsections rather than
trusting any single summary line.

### Signals — 16 hypotheses, all null after the alpha check

| hypothesis | verdict |
|---|---|
| momentum (short-horizon) | no OOS edge |
| momentum + ADX regime gate | no OOS edge (underpowered) |
| mean-reversion | **actively negative** (t≈-3.9) |
| long-horizon 12-1 momentum | negative IDX / noise US — sign flip = no real effect |
| order flow (foreign, broker concentration) | inconclusive, vendor-data-limited |
| low volatility | **confidently negative both markets** |
| turn-of-month | negative IDX / noise US |
| Ramadan effect | underpowered null (~10 independent events) |
| 52-week-high proximity | null both markets |
| ML (ridge re-weighting) | no edge |
| dividend yield | **negative, real power** (raw t=-2.75, alpha t=-2.56, n=1988) — clean rejection, not a beta mirage |
| support/resistance (daily bars) | **actively negative, real power** (raw t=-3.52, alpha t=-3.40, n=1432) |
| multi-horizon trend (sign-sum, 4 lookbacks) | trained arm flat (t≈0); naive fixed threshold **negative** (t=-2.66/-2.50, n=3009) |

Recurring lesson: **every US raw result looked spectacular and died under the
alpha check** (largest raw t=10.54 → alpha 0.78). Raw numbers alone would have
"found" several strategies here.

#### Caveat on every t-statistic above (added 2026-08-05)

They were computed by `trade_stats`, which divides by `std/sqrt(n)` — correct
only if the n trades are independent draws. They are not: trades opened on the
same day across different tickers share that day's move. Subtracting the
benchmark removes the index component; sector and style moves survive it.

Simulated on trades whose true edge is exactly zero, `|t| >= 2` fires at 4.4%
when nothing is shared (correct), 13.1% at 10% shared variance, 20.8% at 20%,
31.5% at 40%. **The plain t over-rejects.** Which cuts both ways:

* **The nulls get STRONGER.** A test biased toward finding edges that found
  none anyway is more damning, not less. Nothing in the table above is
  weakened by this — if anything the rejections are more decisive.
* **The one positive number deserves discounting**: the walk-forward
  t=3.06 on momentum, cited as validated. Under a cluster-robust standard
  error it will read lower; how much lower depends on how clustered the
  entries actually were.

`walkforward.clustered_t_stat` now computes the corrected figure and
`summary_text()` prints it beside the plain one, so re-running any study
reports both. This is a measurement caveat, not a retraction — no verdict
above changes.

### Portfolio construction — where the real answers were

| question | answer |
|---|---|
| optimized weighting vs 1/N | 1/N not reliably beaten (DeMiguel, reproduced) |
| volatility targeting | negative on both clean IDX windows |
| basket selection (low-correlation picking) | null — correlations don't persist |
| how many holdings | risk still falling at K=16, but unbuyable at 30M IDR |
| lump sum vs DCA | **62% → 54% with realistic cash yield — a coin flip for IDX**, unlike the ~2/3 US figure |
| core-satellite (8 names vs XIJI) | **sleeve won 90% of windows** — the one strong positive |
| survivorship check on the above | **SURVIVES** — 100% of random baskets also beat the core; hand-picked 8 at the 1st percentile (unremarkable-to-below-average, not hindsight-inflated) |

### Open, and how to close it

- **Fundamental value/quality** — blocked on the monthly archive accumulating
  calendar time. Verify `kala-fundamentals.timer` is actually installed.
- **Ramadan effect** — needs more independent years, not more code.

### Where things live

| file | what it is |
|---|---|
| `CASE_STUDY.md` | the narrative version, written for a reader |
| `DEPLOY_CHECKLIST.md` | operational path to a funded portfolio |
| `kala/edge.py` docstring | code-adjacent detail of the original verdict |
| `*_study.py` at repo root | the runnable CLIs for each study |

---

## Verdict

**No out-of-sample trading edge was found, after honest costs, in the
composite momentum signal, at any price tier, confirmed two independent
ways.** A second, mechanically opposite hypothesis (mean-reversion — buy
oversold weakness instead of strength) was tested the same honest way on
2026-07-22 and came back not just flat but actively **negative** (see
"Mean-reversion result" below). A third variant — momentum gated by an
ADX ranging-stock veto, i.e. only trade momentum when the stock's own
price action is trending — was tested the same day and also came back
with **no OOS edge** (see "Regime-conditional momentum result" below):
one cut nudged slightly positive but is statistically indistinguishable
from noise (t=0.18), and the alpha-vs-benchmark check stayed flat-to-
negative regardless. Three tested variants across two hypotheses, all
flat or negative. A fourth, mechanically distinct hypothesis — order
flow / bandarmology, via real backfilled Invezgo data — was tested
2026-07-23, twice (initial 40-ticker pass, then a widened 55-ticker
pass to grow the sample), and came back **inconclusive both times**
rather than negative (see "Bandarmology result" below): the second
pass's raw numbers superficially look significant, but the
benchmark-adjusted alpha check — the one that actually isolates skill
from a historic -25.4% IHSG crash sitting inside one of only 2 possible
test folds — stays flat and insignificant throughout. A hard limit of
the vendor's 2-year history cap on fold count, likely not fully
resolvable with this vendor regardless of further ticker-breadth
backfilling. A fifth hypothesis — classic 12-1 month momentum
(trailing ~11-month return, skipping the most recent month), a
structurally different TIME SCALE from every daily/short-horizon
variant above and requiring no paid data — was tested 2026-07-23 on
free 10y yfinance history and came back **NO OOS EDGE, and this time
NEGATIVE with real statistical power** (t=-3.05 raw, t=-2.43 on the
alpha/excess check, n=3,043 trades — see "Long-horizon momentum
result" below). Unlike bandarmology's underpowered inconclusive, this
one is a clean, well-powered rejection: five hypotheses tried across
two mechanisms (price/volume, order flow) and two very different time
scales, all flat, negative, or (for bandarmology alone)
under-determined by vendor data limits. A sixth test — plain momentum
again, but on a DIFFERENT MARKET (US sharia large-caps, `--universe us`,
free 10y yfinance data) instead of a different mechanism/time-scale —
was run 2026-07-23 specifically to check whether IDX's thinness/cost
structure, not the strategies themselves, was the limiting factor. It
came back the most instructive result yet: the raw pooled numbers look
spectacular (t=8.29, PF=1.33, "EDGE CONFIRMED" by the harness's own
raw-check wording) but the alpha check — measuring each trade against
SPUS held over the same window — collapses to flat/insignificant
(t=-0.67 to -1.15). See "US large-cap momentum result" below: this is
a textbook demonstration of beta-capture (riding a historic US mega-cap
bull run) dressed up as stock-picking skill, exactly the failure mode
the alpha-vs-beta check exists to catch, and exactly the mechanism by
which OTHER PEOPLE'S "successful" trading bots usually look good — they
report the raw number, not the alpha-adjusted one. A seventh and final
test — long-horizon (12-1) momentum, the one strategy that had come back
CONFIDENTLY NEGATIVE on IDX (t=-3.05/-2.43), retried on the same US
sharia large-cap universe — was run 2026-07-23 to close the loop. It came
back the one genuinely different-shaped result of the whole project:
neither confirmed nor cleanly rejected, but WEAK AND STATISTICALLY
INDISTINGUISHABLE FROM ZERO despite a large, well-powered sample (raw
t=7.06 -- same beta-capture mirage as every other US raw number; alpha
t=0.68/1.04, EV=+0.07%/+0.11%, n=3,773/3,190 -- see "US long-horizon
momentum result" below). That the SAME strategy flips from confidently
negative on one market to insignificantly-positive-but-noise on another,
rather than agreeing in sign, is itself evidence AGAINST a real transferable
edge, not for one.

**RESEARCH PHASE CLOSED as of the seventh test; reconfirmed closed after an
eighth on 2026-07-24.** An eighth hypothesis — the low-volatility anomaly, a
mechanically distinct "buy calm, not strong or weak" signal, structurally
unlike any of the first seven — was tested on both markets the same day it
was built (see "Low-volatility anomaly result" below) and came back the
MOST confidently negative result of the whole project on IDX (|t| > 6, both
raw and alpha) and a real, well-powered negative alpha on the US universe
too (t=-2.05/-2.19, n≈5,700) — worse than a null, and unlike momentum's US
result, not even explainable as pure beta-capture once alpha-adjusted.
Nine hypothesis/market combinations tried overall now across two markets
(IDX, US sharia large-caps), three mechanisms (price/volume, order flow,
volatility), and two time scales (days-to-weeks, months): six clean
rejections, one vendor-data-limited inconclusive, one statistically-noise
result, and one confidently negative on both markets. None survive an
honest alpha check. This is the first time this project's strategy-zoo
harness was run against new hypotheses on real data (on the user's own
machine, since the build sandbox has no network access). The project is
archived as a paper-trading / validation-infrastructure reference. It is
not a live strategy and should not be funded with money you intend to
grow. No further hypothesis tests are planned unless a genuinely new data
source, market, or mechanically distinct idea becomes available — see
"What's still true and still useful here" below for the two items
(fundamental-value point-in-time check, broader US test coverage) that
remain open but require real calendar time or further work to resolve, not
more backtesting of what's already been tried.

If you're deciding whether to trust anything else in this repo's docs: the
signal claims in older files (e.g. "t=3.06, validated") predate this
finding and are superseded by this document and `kala/edge.py`'s
module docstring.

## How this was established

1. **Flat-cost backtest**: composite score + entry vetoes looked weakly
   positive (t≈1.65) — the number every early doc in this repo cites.
2. **Tick-size-aware costs** (`--tick-spread`, IDX's real bid/ask floor for
   cheap stocks): the edge flipped negative on the full universe (t=-1.35).
3. **Fold-level diagnosis**: the original positive result was concentrated
   in 2 of 14 folds coinciding with the two biggest IHSG rallies in the test
   window — a signature of market-beta capture, not stock-picking skill.
4. **Alpha-vs-beta diagnostic** (`excess_returns` in `kala/walkforward.py`):
   built to measure trade returns against the benchmark over the same
   holding window, not in isolation — confirming (4) is a testable claim,
   not just circumstantial.
5. **A promising-looking reprieve**: filtering to stocks priced >= IDR 1,000
   (tick-floor costs hit cheap stocks hardest) showed a strong, well-powered
   edge (n=2,338, t=3.38, alpha t=4.79) — briefly shipped as validated.
6. **Retraction**: that filter (`run_walkforward.py --min-price`) turned out
   to select on each ticker's LATEST close, not the price at each historical
   trade — a look-ahead bug. Stocks priced high *today* are mechanically
   ones that already went up; filtering on that inflates historical returns
   with no real signal skill involved.
7. **Two independent confirming tests**, both point-in-time correct:
   `compare_exit_engines.py` (n=3,433, t=-3.06) and a re-run of
   `run_walkforward.py` with the ticker-level filter removed and the
   point-in-time price veto left in its place (t=0.00 to -0.09). Both agree:
   flat to negative. No tier has a demonstrated edge.

Full detail, exact numbers, and the reasoning at each step: `kala/edge.py`'s
module docstring (kept as the living source of truth) and `CHANGES.md`.

## Mean-reversion result (2026-07-22)

`kala/strategy_mean_reversion.py` (buy deep-negative z-score + oversold
RSI, the mirror image of momentum's "reward strength" score) was registered
in the strategy zoo but explicitly marked UNTESTED for weeks — no network
access in the sandbox that built it. Run for real via
`python run_walkforward.py --strategy mean_reversion --period 5y --tick-spread`
(55 tickers, 5y, tick-floored costs, point-in-time):

```
POOLED OOS (walk-forward threshold)   n=1248  EV/trade=-1.13%  win=35%  PF=0.74  t=-3.91
POOLED OOS (fixed baseline 60)        n=1573  EV/trade=-0.89%  win=35%  PF=0.80  t=-3.23
EXCESS OOS (walk-forward threshold)   n=1248  EV/trade=-1.24%  win=36%  PF=0.71  t=-4.35
EXCESS OOS (fixed baseline 60)        n=1573  EV/trade=-0.92%  win=38%  PF=0.79  t=-3.38
VERDICT: NO OOS EDGE (both raw and vs-benchmark; not a power/sample-size question — t is
consistently beyond -3 on n in the thousands, and PF < 1 on every cut).
```

Read plainly: buying oversold dips in this universe loses money, with high
statistical confidence, on both an absolute basis and against the
benchmark — not "no edge," but a *negative* one. Plausible mechanism (not
verified further): a stock trading well below its own recent mean in this
universe is more often a falling knife (bad news, earnings miss, one-way
flow) than a mean-reverting dip, so buying the weakness tends to buy more
weakness. A "quality mean-reversion" filter (only buy oversold dips in
fundamentally strong names) might behave differently, but that needs
point-in-time fundamentals this project doesn't have (see
`kala/fundamental_screen.py`'s module docstring) — untested, and
likely to stay that way without a paid historical-fundamentals source.

Two mechanically opposite hypotheses tested now, both ruled out honestly.
That's information, not just a null result — it narrows what's actually
left to try (see "What's still true and still useful here" below).

## Regime-conditional momentum result (2026-07-22)

The one piece of momentum left genuinely untested per the "What's still
true" section below: `entries.py`'s ADX-based ranging-stock veto
(`--veto-ranging-stock`, only trade momentum when the ticker's OWN price
action is trending, not choppy — see `kala/regime_filter.py`) was
built and unit-tested but had no walk-forward run behind it. Run for
real via
`python run_walkforward.py --strategy momentum --period 5y --apply-entry-vetoes --tick-spread [--veto-ranging-stock]`
(55 tickers, 5y, tick-floored costs, point-in-time, baseline vs. treatment):

```
                         WITHOUT veto                    WITH veto
POOLED (wf threshold)    n=204  EV=-0.22%  t=-0.40        n=164  EV=+0.12%  t=+0.18
POOLED (fixed 60)        n=195  EV=-0.31%  t=-0.56        n=147  EV=-0.39%  t=-0.60
EXCESS (wf threshold)    n=204  EV=-0.08%  t=-0.15        n=164  EV=-0.04%  t=-0.06
EXCESS (fixed 60)        n=195  EV=-0.18%  t=-0.33        n=147  EV=-0.39%  t=-0.60
VERDICT: NO OOS EDGE, printed by the harness on both runs.
```

Read plainly: the veto does NOT rescue momentum. One cut (pooled,
walk-forward threshold) moved from negative to barely positive, but
t=0.18 is noise, not signal — and the more conservative fixed-baseline
cut moved the other way (worse). The alpha/excess check, which is the
one that actually separates stock-picking skill from just being in the
market, stayed flat-to-negative under the veto on both cuts. The veto
also nearly halved trade count (204→164, 195→147), leaving several
folds with only 2-4 trades — too thin to trust on their own, which
makes the one "improved" number more fragile, not more credible, than
it looks. Sample size here (n≈150-200) is much smaller than
mean-reversion's (n≈1,250-1,570), so this is a weaker, less powerful
test than that one — an underpowered null rather than a confident
ruling-out — but nothing in it points toward a real edge either.

Three variants of two hypotheses tested now (momentum, momentum +
regime filter, mean-reversion), all flat or negative out-of-sample.

## Bandarmology result (2026-07-23, updated same day after a 2nd backfill) — still INCONCLUSIVE, and likely structurally so

The one genuinely different KIND of signal tested so far — order flow
(who's buying, via Invezgo's broker data), not price/volume. Two
strategy-zoo entries: `foreign_flow` (z-scored net foreign buying vs. the
ticker's own recent norm) and `broker_concentration` (same flow, refined
by whether it's concentrated in one broker or diffuse — free second
signal, same already-fetched data, see `kala/strategy_broker_concentration.py`).

**First pass** (37 of 40 sampled sharia tickers, ~19,600 API calls):
n=14-22 trades, harness printed INCONCLUSIVE, correctly — too small a
sample to conclude anything.

**Second pass, same day**: backfilled 18 more (disjoint) tickers (~9,270
more calls) specifically to grow trade count within the same fold
structure — 55 tickers total, 46 usable. Re-run via the same command with
`--tickers` covering all 55:

```
                         foreign_flow                    broker_concentration
POOLED (wf threshold)    n=23  EV=-3.51%  t=-3.35         n=24  EV=-2.68%  t=-2.14
POOLED (fixed 60)        n=25  EV=-3.44%  t=-3.39         n=26  EV=-2.24%  t=-1.98
EXCESS (wf threshold)    n=23  EV=-1.79%  t=-1.28         n=24  EV=-0.32%  t=-0.20
EXCESS (fixed 60)        n=25  EV=-1.40%  t=-1.04         n=26  EV=-0.40%  t=-0.26
VERDICT: INCONCLUSIVE — too few OOS trades to judge the edge (printed by the harness itself, all four runs).
```

**Read carefully — the raw (POOLED) numbers now LOOK significant
(`|t|` up to 3.39), but this is very likely a single-event artifact, not
a real finding, and the harness's continued INCONCLUSIVE call is the
right one to trust over eyeballing the t-stats:**

- Fold 1's test window (`2026-02-12..2026-05-22`) contains a **-25.4%
  IHSG crash** — a historic, market-wide event that hit nearly every
  stock simultaneously, sharia universe included.
- The **EXCESS (alpha) numbers — the ones specifically built to strip
  out "the whole market moved" and isolate real stock-picking/flow-
  picking skill — stay weak and insignificant across all four cuts**
  (`|t|` between 0.20 and 1.28, nowhere near the ≥2 bar). That is exactly
  the signature of "looked bad because the market crashed," which is
  precisely the failure mode this alpha-vs-beta check exists to catch
  (see `kala/walkforward.py`'s `excess_returns` and the original
  momentum fold-level diagnosis under "How this was established" above
  — same mechanism, different signal).
- This is a **structural** ceiling, not a sample-size one that more
  tickers can fix: adding tickers grows trade count WITHIN existing
  folds but not fold COUNT, and this 2-year window (the vendor's hard
  cap) only contains 2 test folds, one of which is dominated by an
  extreme single event. More backfilling from here would keep hitting
  the same 2 folds. A genuinely clean verdict would need either a
  vendor with deeper history, or simply waiting for more calendar time
  to pass so the archive naturally accumulates a 3rd/4th fold outside
  this crash window.

Bottom line: **not ruled out, not validated, and unlikely to get fully
resolved with this vendor's 2-year cap and this particular historical
window.** Budget used across both backfills: ~28,900 of a 30k/month-class
Invezgo tier — little room left this cycle for a third pass. The honest
per-strategy summary if someone reads only the alpha numbers: no
evidence of real edge so far, but also no confident ruling-out — the same
"underpowered, not negative" caveat as the regime-conditional-momentum
result above, now compounded by one fold being a historic outlier.

## Long-horizon momentum result (2026-07-23)

`kala/strategy_longhorizon_momentum.py` (registered as `long_momentum`):
classic 12-1 month momentum (trailing ~11-month return, skipping the most
recent month to drop short-term reversal). Structurally different from
every prior hypothesis in TIME SCALE, not just indicator — the failed
`momentum`/`mean_reversion`/regime variants all operate on days-to-weeks;
this operates on months. Price-only, no paid data needed, so it ran on
free 10y yfinance history.

First attempt produced 0 trades on all 34 folds — a harness bug, not a
result: the walk-forward's default 60-bar warmup left the 252-bar lookback
feature all-NaN on every fold. Fixed by letting a `Strategy` declare its
own `warmup_bars` requirement (`kala/strategies.py`); `long_momentum`
declares 283. Re-run via
`python run_walkforward.py --strategy long_momentum --period 10y --tick-spread`
(53 tickers, 10y, tick-floored costs, point-in-time):

```
POOLED OOS (walk-forward threshold)   n=3043  EV/trade=-0.62%  win=35%  PF=0.87  t=-3.05
POOLED OOS (fixed baseline 60)        n=2924  EV/trade=-0.51%  win=35%  PF=0.89  t=-2.43
EXCESS OOS (walk-forward threshold)   n=3043  EV/trade=-0.48%  win=37%  PF=0.89  t=-2.43
EXCESS OOS (fixed baseline 60)        n=2924  EV/trade=-0.39%  win=37%  PF=0.91  t=-1.91
VERDICT: NO OOS EDGE (both raw and vs-benchmark). Unlike bandarmology, this is NOT
underpowered -- n in the thousands, |t| >= 2 on 3 of 4 cuts, PF < 1 throughout.
```

Read plainly: unlike bandarmology's inconclusive, this is a clean,
well-powered rejection — a real negative, same shape as the
mean-reversion result. The alpha/excess check (which strips out "the
whole market moved") staying negative at real power is the important
part: this isn't market-beta capture wearing a momentum costume, the
picks lost money even relative to the benchmark over their own holding
windows. Five hypotheses now tested across two mechanisms (price/volume,
order flow) and two time scales (days-to-weeks, months); four are clean
rejections (momentum, momentum+regime, mean-reversion, long-horizon
momentum) and one (bandarmology) remains vendor-limited rather than
ruled out. At this point the more likely explanation is that
this specific corner of the market (EOD swing or longer, sharia-only,
IDX, retail costs) doesn't have easy price/volume/flow-based edge in
it, not that the next variant will be the one that works.

## US large-cap momentum result (2026-07-23)

The one variable NOT yet isolated: was IDX itself (thin, small-cap-heavy,
high relative costs) the limiting factor, or the strategies? Tested by
holding the strategy fixed (plain `momentum`, the original signal) and
swapping the MARKET: `kala.universe.US_SHARIA_STOCKS` (a hand-curated
~55-name starter list of large, liquid sharia-compliant US names — see
that module's docstring for its provenance caveat), `kala.config.
us_equity_costs()` (near-zero commission, tight flat spread — no IDX tick
tiers), benchmarked against SPUS (a real sharia-compliant US large-cap
ETF). Free 10y yfinance data, no paid feed. Run via
`python run_walkforward.py --universe us --cost-preset us_equity --benchmark SPUS --min-price 5 --strategy momentum --period 10y`:

```
POOLED OOS (walk-forward threshold)   n=4815  EV/trade=+0.78%  win=48%  PF=1.33  t=8.29
POOLED OOS (fixed baseline 60)        n=5029  EV/trade=+0.74%  win=48%  PF=1.31  t=8.00
EXCESS OOS (walk-forward threshold)   n=3649  EV/trade=-0.07%  win=45%  PF=0.97  t=-0.67
EXCESS OOS (fixed baseline 60)        n=3826  EV/trade=-0.11%  win=44%  PF=0.96  t=-1.15
VERDICT (raw): EDGE CONFIRMED OOS (t=8.29 -- looks spectacular in isolation)
ALPHA VERDICT: RAW EDGE IS BETA, NOT ALPHA -- positive vs cash but flat/negative
vs the benchmark held over the same days (printed by the harness itself).
```

**Read this one carefully — it's the most instructive result in the whole
project, not because the edge is real, but because of how convincingly
fake it looks before the alpha check.** The raw pooled t=8.29 is by far
the largest of any test run here; on its own it would read as a slam-dunk
"found it." Fold-by-fold, the mechanism is visible directly: the best raw
folds (EV +3.65%, +2.32%) coincide with the SPUS benchmark's biggest
rallies (+15.5%, +20.6%) in that same window; the worst raw folds
(EV -1.13%, -2.12%) coincide with SPUS drawdowns (-13.9%, -10.5%). The
strategy wasn't picking stocks — it was long a universe of exactly the
mega-cap tech names that drove one of the best bull markets in US history,
and "momentum" mostly just meant "stay invested." Once measured against
SPUS held over the same holding windows, that entire raw edge disappears
(t=-0.67 to -1.15, not distinguishable from noise in either direction).

**Data-completeness caveat, stated plainly**: 1,166 of the 4,815 raw
trades (folds 0-7, spanning 2017-10 to 2019-10) show no alpha figure at
all -- SPUS didn't exist as an ETF yet that far back, so those trades have
no valid benchmark to compare against and were correctly EXCLUDED from
the alpha check rather than silently faked. The "no real edge" conclusion
is solid for the ~76% of trades from late 2019 onward, where a fair
alpha comparison exists; the 2017-2019 slice is genuinely unmeasurable
this way, not resolved.

This is also a real answer to "how do other people's trading bots look
successful" (see the parallel conversation this session): this exact
run, reported ONLY as the raw pooled numbers, is what that looks like --
a great-looking backtest that is 100% market exposure and 0% skill. The
harness catching it is the point.

Six hypothesis/market combinations tested overall (five on IDX, this one
on US large-caps); none survive an honest alpha check.

## US long-horizon momentum result (2026-07-23) — the closing test

The last open question: `long_momentum` (12-1 month momentum) had been
the ONE strategy with a confidently negative, well-powered result on IDX
(t=-3.05 raw, t=-2.43 alpha — see "Long-horizon momentum result" above).
Retrying that exact strategy on the US sharia large-cap universe closes
the loop on both open threads at once (does the strategy transfer, does
the market matter). Same command shape as the momentum/US run:
`python run_walkforward.py --universe us --cost-preset us_equity --benchmark SPUS --min-price 5 --strategy long_momentum --period 10y`:

```
POOLED OOS (walk-forward threshold)   n=4422  EV/trade=+0.74%  win=48%  PF=1.29  t=7.06
POOLED OOS (fixed baseline 60)        n=3640  EV/trade=+0.75%  win=47%  PF=1.29  t=6.39
EXCESS OOS (walk-forward threshold)   n=3773  EV/trade=+0.07%  win=46%  PF=1.03  t=0.68
EXCESS OOS (fixed baseline 60)        n=3190  EV/trade=+0.11%  win=46%  PF=1.05  t=1.04
ALPHA VERDICT: EV positive but WEAK (t < 2): could be noise (printed by the harness itself).
```

**Read this one differently from every other result above — it's not a
clean rejection, and that itself is the interesting part.** Raw pooled
looks "confirmed" again (t=7.06, PF=1.29), the same beta-capture mirage
as plain momentum on this universe. But the alpha check this time doesn't
land cleanly negative like IDX's version of this exact strategy did — it
lands at t=0.68/1.04, EV barely positive (+0.07%/+0.11%), PF just above
1 (1.03/1.05). With n=3,773/3,190 — a LARGE sample, not an underpowered
one like bandarmology — this is a genuinely small, statistically
indistinguishable-from-zero effect, not a "not enough data yet" case.

**The cross-market comparison is itself the evidence**: the identical
strategy is confidently NEGATIVE on IDX and insignificantly-flat-to-
positive on US large-caps. A real, transferable edge should show the
same sign across related markets, even if the magnitude differs. A sign
flip between "confident negative" and "noise-level positive" is the
signature of NO REAL EDGE EITHER PLACE — the true effect is plausibly
zero on both, and the IDX result's negative t-stat reflects IDX-specific
cost/liquidity drag more than a universal "this factor loses money"
finding, while the US result's near-zero t-stat reflects "no detectable
effect" rather than "found a small positive edge."

Seven hypothesis/market combinations tested overall now (six on IDX/US
covered above plus this one); none survive an honest alpha check with
real statistical power. See the Verdict section at the top: research
phase is closed as of this test.

## Low-volatility anomaly result (2026-07-24)

`kala/strategy_low_volatility.py` (registered as `low_volatility`): the
FIRST mechanically distinct hypothesis after the seven direction-based
nulls above — scores each stock inversely to its trailing ~quarter realized
volatility, buying the CALMEST names regardless of whether they rose or
fell (Baker-Bradley-Wurgler / Blitz-van Vliet). Price-only, no paid data.
Run on both markets the same day it was built, closing the loop
immediately rather than leaving it untested:

```
python run_walkforward.py --strategy low_volatility --period 10y --tick-spread
python run_walkforward.py --universe us --cost-preset us_equity --benchmark SPUS --min-price 5 --strategy low_volatility --period 10y
```

**IDX** (53 tickers, 10y, tick-floored costs):
```
POOLED OOS (walk-forward threshold)   n=3531  EV/trade=-0.82%  win=28%  PF=0.74  t=-6.40
POOLED OOS (fixed baseline 60)        n=3166  EV/trade=-0.82%  win=28%  PF=0.73  t=-6.30
EXCESS OOS (walk-forward threshold)   n=3531  EV/trade=-0.85%  win=32%  PF=0.73  t=-6.70
EXCESS OOS (fixed baseline 60)        n=3166  EV/trade=-0.78%  win=32%  PF=0.74  t=-6.06
VERDICT: NO OOS EDGE (both raw and excess) -- the most confidently NEGATIVE result of
any hypothesis tested on IDX so far, |t| > 6 on every cut, n in the thousands.
```

**US sharia large-caps** (57 tickers, 10y, vs SPUS):
```
POOLED OOS (walk-forward threshold)   n=7509  EV/trade=+0.64%  win=48%  PF=1.29  t=8.91
POOLED OOS (fixed baseline 60)        n=7778  EV/trade=+0.59%  win=47%  PF=1.27  t=8.49
EXCESS OOS (walk-forward threshold)   n=5629  EV/trade=-0.16%  win=45%  PF=0.93  t=-2.05
EXCESS OOS (fixed baseline 60)        n=5744  EV/trade=-0.17%  win=45%  PF=0.93  t=-2.19
ALPHA VERDICT: RAW EDGE IS BETA, NOT ALPHA -- positive vs cash, NEGATIVE vs the
benchmark held over the same days, with real power (not noise-level like momentum's
US alpha check, which landed at t=-0.67 to -1.15).
```

**Read this one carefully — it's a step worse than a null, and worse than the
US momentum beta-capture case.** On IDX, both the raw and excess checks land
confidently negative (|t| > 6 on every cut) — not "no edge," an actively bad
signal: buying the calmest stocks in this universe systematically
underperformed. On the US universe, the raw numbers again look spectacular
(t=8.91, the same beta-capture shape momentum showed — low-vol stocks are
low-beta by construction, so "positive vs cash" mostly just means "was
invested during a market that went up"), but this time the alpha check
doesn't land at noise-level like momentum's did — it lands at t=-2.05/-2.19
on n≈5,700, a real, well-powered NEGATIVE. That means the picks
underperformed the benchmark even measured over their own holding windows,
not just "no detectable stock-picking skill" but actual mild anti-skill.

**Same sign (negative) on both markets once alpha-adjusted is itself the
important part** — a real, transferable, if small, negative effect showing
up consistently on two different universes is more informative than one
inconclusive market. Plausible mechanism (not verified further): in this
factor's classic form, low-vol's edge comes from higher volatility stocks
being systematically OVER-owned/over-bid by leverage-constrained investors
(the "betting against beta" story) — a mechanism that may just not be
present, or may run the other way, in a sharia-screened retail universe
where leveraged institutional players are largely absent by construction.
Untested further; not worth chasing given two confidently negative alpha
reads already.

Eighth hypothesis, ninth overall market/hypothesis combination (counting
both IDX and US runs for momentum, long_momentum, and now low_volatility):
still none survive an honest alpha check. This closes the low-vol lead the
same day it opened rather than leaving it open — see the Verdict section at
the top; research remains closed.

## Turn-of-month calendar effect result (2026-07-24)

`kala/strategy_calendar_effects.py` (registered as `turn_of_month`): the
FIRST calendar-based hypothesis, mechanically unlike all nine above —
scores the first few trading days of each month highest, agnostic to any
price/volume/flow/volatility. Classic Ariel (1987) / Lakonishok-Smidt (1988)
turn-of-month anomaly. Only the provably point-in-time-safe half of the
textbook definition is implemented — "first N trading days of the month" —
NOT "last trading day of the month," because a naive implementation of the
latter would answer "is today the month's last trading day" by checking
whether more rows for that month exist later in the array, which is future
information relative to any bar short of the dataset's final one. That is
structurally the same mistake as the retracted min-price look-ahead bug
under "How this was established" above. Rather than risk repeating it, only
the safe half shipped; the other half is a known, clearly-labeled gap (see
the module's docstring) for whoever wants to wire in a real exchange
trading-day calendar later.

A Ramadan-effect variant (real published finding for Indonesia specifically
— White 2013 — plausibly the single most IDX-specific, best-motivated
calendar hypothesis available) was considered in the same session and
initially DELIBERATELY NOT shipped: Indonesia's Kemenag announces Ramadan's
start by moon-sighting (sidang isbat), not pure calculation, and this
session's own network access could not retrieve a verified, complete
historical table of those exact dates (search results gave confident
figures for 2020-2026 but conflicting or missing ones for 2016-2019 and
even some 2022/2024 figures). Hardcoding a guessed date table into a
point-in-time-sensitive backtest was judged not worth the silent-error
risk — same standard this project already held itself to on the
fundamental-value archive (wait for verified data rather than ship a
plausible-looking guess).

**Update, same session**: the user supplied an official Tanggal Mulai (1
Ramadan) / Hari Terakhir Puasa table covering 2017-2026 directly. This IS
the verified table that was missing — `kala/strategy_ramadan_effect.py`
(registered as `ramadan_effect`) implements it as a straight per-row date
lookup (``RAMADAN_PERIODS``), which needs no future-row information at all
(unlike turn-of-month's "last day" half, a date-range membership check
can't leak future price/row data even in principle — verified anyway with
the same truncation-based point-in-time test as everything else, matching
house style). Coverage gap stated plainly in the module: the table starts
2017, so Ramadan 2016 (~June-July) is NOT covered by a `--period 10y` run
today, which fails closed (undercounts, not fabricates) and doesn't affect
any actual OOS test fold (`turn_of_month`'s real run above shows the first
fold starting August 2017, safely inside the table's range). 10 new unit
tests, including a sanity check on the supplied table itself (chronological,
non-overlapping). Run it yourself (no network in the build sandbox):

    python run_walkforward.py --strategy ramadan_effect --period 10y --tick-spread

IDX-only by construction (Indonesia-specific calendar) — no US-universe
comparison is meaningful here. This is the eleventh hypothesis/market-
combination-generating idea overall.

**Run 2026-07-24, same day it was built** (53 tickers, 10y, tick-floored):
```
POOLED OOS (walk-forward threshold)   n=1116  EV/trade=-0.92%  win=34%  PF=0.81  t=-2.89
EXCESS OOS (walk-forward threshold)   n=1116  EV/trade=-0.20%  win=39%  PF=0.95  t=-0.64
VERDICT: NO OOS EDGE -- raw looks negative-with-power, but the alpha check
collapses to noise (t=-0.64).
```

**Read this one differently from low-volatility and turn-of-month — it's a
genuine UNDERPOWERED NULL, not a confident rejection either direction.**
Most fold windows show ZERO trades (Ramadan occupies roughly one month a
year; a ~3-month test window frequently misses it entirely) — of the 35
folds, only 11 actually contain a Ramadan period. Eyeballing those 11
directly: several of the ones with the worst raw EV coincide with IHSG
itself being down hard that quarter (fold 26: IHSG -6.0%; fold 29: IHSG
-14.6%; fold 33: IHSG -15.0%), which is exactly what the alpha/excess check
exists to strip out — and once it does, t=-0.64 is squarely noise. **The
`n=1116` figure is also misleading on its own**: it's 53 tickers trading
through the same roughly-10 independent yearly Ramadan windows, not 1,116
independent events — the same structural weakness the bandarmology result
flagged (real information content bounded by the number of DISTINCT
calendar occurrences, not the ticker-multiplied trade count). Closer in
spirit to bandarmology's "inconclusive, not ruled out" than to the clean
rejections above; more years of data (not more tickers) is what would
actually sharpen this, and that needs calendar time, not more code — same
category as the fundamental-value archive. Twelfth hypothesis/market
combination overall; still none survive an honest, well-powered alpha
check.

Run 2026-07-24, same day it was built:

**IDX** (53 tickers, 10y, tick-floored):
```
POOLED OOS (walk-forward threshold)   n=4195  EV/trade=-0.44%  win=33%  PF=0.89  t=-2.79
EXCESS OOS (walk-forward threshold)   n=4195  EV/trade=-0.62%  win=36%  PF=0.85  t=-4.01
VERDICT: NO OOS EDGE (both raw and excess) -- confidently negative, real power.
```

**US sharia large-caps** (57 tickers, 10y, vs SPUS):
```
POOLED OOS (walk-forward threshold)   n=4913  EV/trade=+1.00%  win=49%  PF=1.43  t=10.54
EXCESS OOS (walk-forward threshold)   n=3707  EV/trade=+0.08%  win=47%  PF=1.03  t=0.78
ALPHA VERDICT: EV positive but WEAK (t < 2): could be noise.
```

**Read this the same way as the long-horizon momentum cross-market result
above — this is the SAME shape, not a new pattern**: confidently negative
on IDX (t=-4.01, real power), noise-level flat on US (t=0.78) once
alpha-adjusted. The raw US t-stat (10.54) is in fact the single highest
raw number recorded anywhere in this project — the same beta-capture shape
every US run has shown (turn-of-month, being roughly market-wide by
construction, is close to "was invested during the test window," so a huge
raw number here is expected and uninformative on its own). A strategy that
flips from confidently negative to statistically-indistinguishable-from-
zero across markets, rather than agreeing in sign, is itself evidence
against a real transferable effect — the same read applied to
`long_momentum`'s cross-market result. IDX's negative more likely reflects
IDX-specific cost/liquidity drag around month boundaries than a universal
"turn-of-month loses money" finding; US's near-zero reflects "no detectable
effect," not "found a small positive edge."

Tenth hypothesis/market-combination-generating idea overall, eleventh
combination counting both markets: still none survive an honest alpha
check with real statistical power on both sides. Closes the loop the same
day the idea was built.

## Two more additions (2026-07-24) — after an explicit "search literally everything" pass

A deliberate, exhaustive sweep of what remained genuinely untried (not just
re-skinned versions of the failures) surfaced exactly two things worth
building that are testable today, sharia-compatible, and need only free
price data. Both are ADDED and unit-tested but NOT yet run on real data
(no network in the build sandbox). The same sweep also confirmed what is
NOT worth building: ML re-weighting of the base features was already run
and recorded as no-edge (`HOW_IT_WORKS.md`); value/quality/earnings-drift
are the highest-evidence ideas left but are BLOCKED on the point-in-time
fundamental archive accumulating calendar time (already running monthly on
the VPS); and pairs/stat-arb — the one genuinely novel *mechanism* — needs
SHORTING, which is both non-sharia and unavailable to IDX retail, so it was
deliberately not built.

**1. `high_proximity` — 52-week-high anchoring (George & Hwang 2004), the
13th hypothesis.** A price signal empirically DISTINCT from the three failed
momentum variants: it scores a stock by how close its price sits to its
trailing 52-week high, not by its trailing return (a stock can have strong
momentum yet sit below its high, or vice versa). `kala/strategy_high_
proximity.py`, registered in the zoo, 10 unit tests including a point-in-
time proof and one that pins the momentum-distinction (run-up-then-pullback
has strong return but weak nearness). Honest prior: most of its documented
strength is US cross-sectional large-cap, anchoring effects arbitrage away
as markets mature, and "near its high" is long a rising market by
construction — so judge it on the EXCESS (alpha) check, expecting the same
beta-capture trap the other signals hit. Run:
```
python run_walkforward.py --strategy high_proximity --period 10y --tick-spread
python run_walkforward.py --universe us --cost-preset us_equity --benchmark SPUS --min-price 5 --strategy high_proximity --period 10y
```

**2. Weighting-scheme study — the first PORTFOLIO-CONSTRUCTION test, not a
timing signal.** Every one of the 13 hypotheses above is about WHICH stock
or WHEN to trade. This asks the orthogonal question that actually fits a
buy-and-hold allocation: given a fixed basket, does an OPTIMIZED weighting
(inverse-volatility, or classic min-variance) beat naive equal weight (1/N)
out of sample, after costs? `kala/weighting_backtest.py` (pure numpy/pandas,
point-in-time: weights estimated only from each rebalance's trailing window,
held forward) + `weighting_study.py` CLI + 13 unit tests. Honest prior is
the famous DeMiguel-Garlappi-Uppal (2009) result: 1/N is hard to beat OOS
because covariance estimation error swamps the theoretical gain — expect
optimized schemes to lower VOLATILITY but not reliably improve risk-adjusted
return once costs are paid. This is the most decision-relevant of the two
for the user's actual (buy-and-hold, long-horizon) situation. Run:
```
python weighting_study.py --period 10y                    # IDX sharia sample
python weighting_study.py --universe us --cost-preset us_equity
```
Record both verdicts in this file the same honest way as everything else
once run — raw numbers, and (for high_proximity) whether the alpha check
survives.

### Results (2026-07-24, run on the user's machine)

**`high_proximity` — IDX: weak null, no edge.** (48 usable tickers, 10y,
tick-floored):
```
POOLED OOS (walk-forward threshold)   n=1689  EV/trade=-0.35%  win=33%  PF=0.91  t=-1.38
EXCESS OOS (walk-forward threshold)   n=1689  EV/trade=-0.37%  win=35%  PF=0.91  t=-1.45
VERDICT: NO OOS EDGE (raw and excess) -- but weak, NOT the confident negative
low-volatility/momentum showed. Just no signal.
```

**`high_proximity` — US: first run INVALID (Yahoo throttled), clean re-run
confirms BETA-NOT-ALPHA.** The first attempt was unusable — Yahoo
rate-limited it (41 of 57 tickers plus the SPUS benchmark failed, no alpha
check ran). The clean re-run (all 57 tickers + SPUS present, 10y) came back
exactly as predicted:
```
POOLED OOS (walk-forward threshold)   n=6651  EV/trade=+0.70%  win=48%  PF=1.31  t=9.12
EXCESS OOS (walk-forward threshold)   n=5416  EV/trade=-0.04%  win=45%  PF=0.98  t=-0.56
ALPHA VERDICT: RAW EDGE IS BETA, NOT ALPHA -- raw t=9.12 collapses to alpha t=-0.56 (noise).
```
The raw t=9.12 is the biggest-looking "edge" and the usual mega-cap
beta-capture mirage; the alpha check strips it to noise (t=-0.56). So
high_proximity is a NULL on BOTH markets — weak-null on IDX (t=-1.45),
beta-not-alpha on US. 13th hypothesis fully closed, no edge either place.

**Weighting study — the US result did NOT transfer to the user's real
basket; inverse-vol is NOT worth adopting here.** Three runs, and the
cross-basket comparison is the actual finding:

US sharia large-caps (12 names, ~10y, 37 rebalances) — looked encouraging:
```
  scheme            CAGR    ann vol   max DD   ret/vol   cost%
  equal_weight     19.77%   21.04%   -33.0%    0.94     0.51%
  inverse_vol      18.06%   19.40%   -29.5%    0.93     0.68%
  min_variance     13.97%   16.88%   -27.6%    0.83     1.53%
```
inverse-vol there cut ~3.5pp of drawdown for almost no ret/vol cost — the
textbook DeMiguel "lower vol, not better Sharpe" result, and briefly looked
like an actionable drawdown-reducer.

The user's ACTUAL 8-name IDX allocation basket (TLKM/UNVR/ICBP/KLBF/ANTM/
INDF/BRIS/SMGR, 8y, 29 rebalances) — tells the opposite story:
```
  scheme            CAGR    ann vol   max DD   ret/vol   cost%
  equal_weight      5.56%   23.23%   -49.2%    0.24     1.71%
  inverse_vol       2.24%   21.40%   -47.1%    0.10     1.83%
  min_variance     -5.36%   20.74%   -52.9%   -0.26     2.87%
```
Here inverse-vol cuts only ~2pp of drawdown AND more than halves the return
(5.56%→2.24% CAGR, ret/vol 0.24→0.10); min-variance is outright destructive
(negative CAGR, WORSE drawdown, 2.87% cost). **The US "free drawdown
reduction" does NOT transfer.** Mechanism: the 8 sharia blue-chips are highly
CORRELATED — they crash together in IDX-wide selloffs (2020, 2025), so there
is little diversification for inverse-vol/min-variance to exploit, unlike the
lower-correlation US large-caps. Decision: **do NOT wire inverse-vol into
`/rebalance`; equal weight is correct for this basket.** The tentative
"actionable lever" from the US-only run was withdrawn once tested on the real
holdings — honest reversal, recorded here rather than buried.

The deeper takeaway reinforces the original conclusion: those ~-49% drawdowns
are the EQUITY SLEEVE ALONE. What actually softens portfolio drawdown is not
within-equity weighting (barely helps, correlated basket) but ASSET-CLASS
diversification — the 15% sukuk + cash buffer the target allocation already
holds. Construction choices at the equity level are a wash-to-negative here;
the multi-asset allocation is the real risk lever, exactly as concluded
before the search began.

**Two follow-up runs, requested by the user to push further, settle it with a
real sample size instead of leaving it on one ambiguous data point.**

A `--max-tickers 40` auto-sample (alphabetic across the full 615-name ISSI
list, blind to listing date) hit a real bug: one thin/recent-listing ticker
collapsed the whole strict inner join to 1 overlapping day. Fixed in
`kala/weighting_backtest.py` AND `kala/rebalance_backtest.py` (identical
copy-pasted `_align_closes`, same latent bug there too, not yet hit) — any
ticker with much shorter history than the rest of the basket is now dropped
BEFORE alignment and reported, not left to silently wreck the comparison
(`dropped_short_history` field, 5 new tests). Also fixed a spurious
`RuntimeWarning: divide by zero` in `_inverse_vol_weights` (cosmetic —
`np.where` was evaluating both branches eagerly; switched to
`np.divide(..., where=mask)`).

With the bug fixed, the retry (26 surviving names, but only ~5.1y overlap —
short window, noisy) came back the ONE outlier: inverse-vol beat 1/N on
ret/vol (0.99 vs 0.91). A hand-curated, sharia-VERIFIED (checked against
`ALL_SHARIA_STOCKS` in code, not memory) list of 40 well-established IDX
blue/mid-caps was built specifically to get a clean, long, undropped run:
```
python weighting_study.py --tickers TLKM.JK UNVR.JK ICBP.JK KLBF.JK ANTM.JK INDF.JK BRIS.JK SMGR.JK PTBA.JK SIDO.JK MYOR.JK CPIN.JK JPFA.JK ACES.JK AKRA.JK TINS.JK ADRO.JK PGAS.JK SMRA.JK PTPP.JK JSMR.JK EXCL.JK ISAT.JK MEDC.JK ELSA.JK BSDE.JK CTRA.JK MNCN.JK ITMG.JK TPIA.JK UNTR.JK AALI.JK LSIP.JK ERAA.JK MAPI.JK WTON.JK SMBR.JK TOTL.JK ASSA.JK ARNA.JK --period 10y
```
```
  40 names, 8.0y, 29 rebalances, none dropped (all verified-sharia blue-chips):
  scheme            CAGR    ann vol   max DD   ret/vol   cost%
  equal_weight      8.78%   20.82%   -51.4%    0.42     1.93%
  inverse_vol       7.91%   19.33%   -49.1%    0.41     2.80%
  min_variance      4.62%   16.81%   -45.5%    0.28     7.91%
```
Back to textbook DeMiguel — ret/vol essentially flat (0.41 vs 0.42), NOT
beaten. min-variance is worse on every axis AND costs 4x more (7.91% vs
1.93% cumulative friction over 29 rebalances) — the practical cost of
constantly re-solving a 40x40 covariance as the estimate wobbles, exactly
the fragility flagged in the module's docstring.

**Final tally across all four weighting runs, largest/cleanest first:**
| basket | window | n | inverse-vol vs 1/N (ret/vol) |
|---|---|---|---|
| Curated 40 IDX blue-chips (verified sharia) | 8.0y | 40, none dropped | ~flat (0.41 vs 0.42) |
| US 12 sharia large-caps | 10y | 12 | ~flat (0.93 vs 0.94) |
| User's real 8-stock allocation | 8y | 8 | WORSE (0.10 vs 0.24) |
| Auto-sampled IDX (noisy, short) | 5.1y | 26 | better (0.99 vs 0.91) |

3 of 4 agree on "no Sharpe improvement," including the two largest/cleanest
runs. The one positive result is the shortest, noisiest sample — the one a
reasonable prior says is most likely a fluke of that particular window, not
a signature of a real effect. **Verdict stands, now with real weight of
evidence behind it, not one ambiguous run: do not adopt inverse-vol or
min-variance weighting. Equal weight is the right choice**, and the actual
risk lever remains asset-class diversification (sukuk/cash), not equity
weighting tricks.

Bottom line after the exhaustive "search literally everything" pass, now
including a properly-powered follow-up rather than stopping at one
ambiguous data point: thirteen timing/factor hypotheses, NONE with a
surviving alpha edge; and the weighting-construction idea, tested four ways
across two markets and sample sizes from 8 to 40 names, does not reliably
beat naive equal weight either. Net result: no new tradeable lever found —
the buy-and-hold, multi-asset, low-cost, equal-weight allocation stands as
the honest answer, now stress-tested from every angle available without a
paid data source or more calendar time.

## Volatility targeting — the last mechanically distinct lever (2026-07-24, built, UNTESTED on real data)

After a fourth "explore everything" push, a full taxonomy of the strategy
space was written out to find anything genuinely untried (not a re-mix of
failed signals). The result of that taxonomy, recorded so it doesn't get
re-litigated:

* **Signals/timing** — 13 hypotheses, all null (above). A 14th is
  multiple-testing noise.
* **Cross-sectional weighting** — 4 studies, no edge over 1/N (above).
* **Leverage, options, futures, short-selling / pairs / market-neutral** —
  all riba or otherwise non-sharia, AND unavailable to IDX retail. Ruled out
  on constraints, not effort.
* **Tax-loss harvesting** — structurally absent in Indonesia (stock sales
  carry a 0.1% final tax on gross proceeds, not a capital-gains tax, so there
  are no gains to offset). N/A.
* **International diversification** — blocked by the Stockbit (IDX-only)
  broker constraint.
* **Fundamental value / quality / earnings-drift, sentiment** — the
  highest-evidence ideas left, but BLOCKED on point-in-time archives that
  need calendar time (already accruing monthly on the VPS).
* **Portfolio-level volatility targeting (time-series exposure)** — the ONE
  genuinely distinct, buildable, sharia-compatible lever not yet touched.
  Built now.

`kala/vol_targeting_backtest.py` (+ `vol_targeting_study.py`, 10 unit tests):
Moreira & Muir (2017) volatility-managed portfolios. Every prior lever is
cross-sectional (WHICH stock / how much of each); this is the orthogonal
TIME-SERIES question — how much TOTAL exposure to carry right now — scaling
exposure inversely to recent realized vol, since vol clusters and is
predictable in a way returns are not. Point-in-time safe (exposure on day t
uses realized vol through t-1 via `.shift(1)`), cost-aware (charges friction
on every exposure change).

**The sharia constraint is the crux, stated in the module up front:** the
textbook strategy LEVERS UP in calm periods, and much of its historical
benefit comes from that leverage — which is riba. So the backtest reports
two variants: `targeted_capped` (exposure clamped to [0, 1.0] — the sharia
version, can only de-risk into cash) and `targeted_uncapped` (allows
leverage — NOT sharia, included only as the upper-bound reference to show
how much the no-leverage constraint costs). Honest prior: the capped version
likely keeps most of the DRAWDOWN reduction (that comes from de-risking,
which the cap allows) but little of the RETURN enhancement (that came from
levering calm periods, which the cap forbids) — a risk tool, not a return
booster, like everything else here. On synthetic vol-clustering data it
behaves as designed (cuts drawdown sharply); real IDX data is messier and
the benefit is expected to be smaller. Run:
```
python vol_targeting_study.py --tickers TLKM.JK UNVR.JK ICBP.JK KLBF.JK ANTM.JK INDF.JK BRIS.JK SMGR.JK --period 10y   # the user's real basket
python vol_targeting_study.py --period 10y                              # broad IDX sharia sample
python vol_targeting_study.py --universe us --cost-preset us_equity     # US reference
```
### Results (2026-07-24, run on the user's machine) — DECISIVE, both clean IDX windows negative

Three runs, two of them long/clean IDX windows plus one clean US reference.
(A `--period 10y` broad-sample run first hit the SAME short-history join bug
already fixed twice elsewhere — the alphabetic 12-ticker auto-sample from
`ALL_SHARIA_STOCKS` happened to draw only young listings, all under ~1.4y —
fixed a third time in `kala/vol_targeting_backtest.py` itself, same
`MIN_HISTORY_FRACTION` pattern, `dropped_short_history` now reported. Not a
correctness bug — the fix worked, there was just nothing longer to keep in
that particular random sample. Re-run on the same 40-name verified
sharia blue-chip list built for the weighting study, which gave a clean 8y
window there too.)

**User's real 8-stock allocation** (8.0y, cost 0.32%/change):
```
                      CAGR    vol    maxDD   ret/vol  avgExp  cost
buy & hold           5.08%  22.5%  -48.9%    0.23     1.00     -
vol-target CAPPED    0.60%  17.7%  -37.3%    0.03     0.92    5.8%
```
ret/vol 0.23→0.03 — an 87% collapse, not "flat" (the auto-generated READ
text calls a >2pp drawdown gain "flat" on return whenever the raw ret/vol
delta is < 0.05 in absolute terms, which is misleading when the BASE ret/vol
is itself small — a labeling weakness worth fixing if this module gets used
again, not restated as a numeric claim here).

**Broad 40-name verified-sharia blue-chip basket** (8.0y, cost 0.32%/change):
```
                      CAGR    vol    maxDD   ret/vol  avgExp  cost
buy & hold          10.84%  22.1%  -51.0%    0.49     1.00     -
vol-target CAPPED    4.27%  16.8%  -36.7%    0.25     0.94    3.1%
```
ret/vol 0.49→0.25 — a 49% cut. CAGR more than halved (10.84%→4.27%).

**US 12 sharia large-caps** (10.0y, cost 0.05%/change — the us_equity preset):
```
                      CAGR    vol    maxDD   ret/vol  avgExp
buy & hold          19.87%  20.7%  -32.6%    0.96     1.00
vol-target CAPPED   17.19%  16.4%  -26.6%    1.05     0.92
```
ret/vol 0.96→1.05 — a genuine, modest improvement, alongside a real
drawdown cut.

**Read plainly: this is MORE decisive than the weighting study, not less.**
The weighting study's negative result could be explained away as "the
user's 8 stocks are just too correlated for any construction trick to
help." Vol-targeting kills that explanation — the BROAD 40-name diversified
IDX blue-chip sample fails too (49% ret/vol cut), just less severely than
the correlated 8-stock basket (87% cut). Both long, clean IDX windows are
negative; only the US sample is positive. The pattern is now: **vol-
targeting works (modestly) on this US large-cap sample and fails on IDX
broadly**, not just on the user's specific holdings.

**Plausible mechanism, distinct from the weighting study's correlation
story**: this overlay recalculates exposure off a ROLLING 21-DAY vol window
— far more frequent than the weighting study's quarterly rebalance — against
IDX's per-trade cost (0.32%/change here vs 0.05%/change for the US preset,
a 6x difference). High-frequency exposure changes multiplied by IDX's much
higher relative transaction costs is a structural, plausible explanation
for why this loses money specifically on IDX, independent of the
correlation argument — consistent with the very first finding in this
project (tick-floored IDX costs flipping momentum negative). Not verified
further (would need a cost-vs-window-length sensitivity sweep to confirm,
which isn't worth building for a lever already rejected twice over).

**Verdict: do not adopt volatility targeting for the user's portfolio.**
Two clean, long IDX windows (correlated 8-stock and diversified 40-stock)
both show a real return cost that isn't justified by the drawdown reduction,
especially given the user's stated tolerance for drawdowns "as long as they
recover." This closes the last mechanically distinct lever in the taxonomy.
With this result, the tradeable-lever space is exhausted: 13 signals + 4
weighting schemes + 1 exposure-timing overlay, 18 tests total, zero that
clear the bar for the user's actual situation. What remains is genuinely
either structurally unavailable (leverage/shorting/international access/
tax-loss harvesting) or blocked on calendar time, not code (fundamental
value, sentiment, and the still-underpowered Ramadan effect).

## Portfolio-CONSTRUCTION decisions (2026-07-24) — a whole category previously missed

**Correcting an over-claim.** After the vol-targeting result, this file said
the tradeable-lever space was "exhausted." That was wrong, and the user was
right to keep pushing. The taxonomy above enumerated SIGNALS (which stock),
WEIGHTING (how much of each), and EXPOSURE (how much in total) — but omitted
a fourth category entirely: **portfolio-construction decisions** that involve
no prediction at all. Three of these were never tested, and one of them
answers a question the user asked at the very start of the project that was
never answered with evidence.

**1. Lump sum vs DCA (`kala/deployment_backtest.py`, `deployment_study.py`).**
The user's opening question was whether to deploy 30jt IDR all at once or
nyicil (in installments). It was answered from general reasoning, never
tested. This compares both schedules on identical price history across MANY
rolling start dates (a distribution, not one lucky path — the same discipline
`kala.walkforward` uses many folds for). Cost-aware; `cash_yield_annual`
models what undeployed cash earns, so DCA can be given its fair best case.

The honest prior (Vanguard 2012; Constantinides 1979): lump sum wins ~2/3 of
historical windows, because cash waiting to be deployed misses the market's
average upward drift. But a return-only verdict would be practically
misleading, so the formatter reports BOTH the win rate AND the worst-case
outcomes — DCA's real product is regret/sequence protection, not return, and
that trade is a preference rather than a math error. 13 unit tests pin the
structural truths (rising market → lump wins; falling market → DCA wins;
DCA cuts worst-case drawdown when the crash comes early; 1-slice DCA ≡ lump
sum).

**2. Basket SELECTION + holdings-count curve (`kala/basket_selection.py`,
`selection_study.py`).** Three studies above all blamed the same culprit —
the user's sharia blue-chips are highly correlated, leaving little for any
overlay to work with — but every one of them took the BASKET AS GIVEN. This
tests the follow-up those results point at: if correlation is the problem,
can you fix it by CHOOSING different stocks?

  * *Correlation-aware selection*: greedily pick the K least-correlated names,
    re-selected periodically, vs a RANDOM-K baseline repeated over hundreds of
    draws (compared against the distribution, not one lucky draw).
    **Look-ahead trap deliberately avoided**: selecting "historically
    least-correlated" names using the whole sample would be exactly the class
    of bug this project already retracted a validated result over
    (`--min-price`, see "How this was established"). Selection here is strictly
    walk-forward — trailing-window correlation only, then held forward.
  * *Holdings-count curve*: median vol / max drawdown / average pairwise
    correlation as K goes 1, 2, 4, 8, 16, 32. Answers "is an 8-name satellite
    sleeve enough?" and, more importantly, quantifies the UNDIVERSIFIABLE
    remainder — if risk stops falling past ~15 names, that residual is market
    risk, which is the quantitative reason every weighting/exposure overlay in
    this project had so little to work with, and confirms the only real fix is
    a different ASSET CLASS (sukuk/gold/cash) rather than more or better stocks.

Honest prior for selection: trailing correlations are notoriously unstable
out of sample and converge toward 1 in exactly the crashes you wanted
protection from, so the expected result is that this helps less than its
in-sample appeal suggests — possibly not at all. Either answer is worth
having: a win is a genuine (modest) finding; a null is a clean quantitative
demonstration that the correlation problem is structural to this market
rather than a stock-picking failure.

**3. Still untested, noted for completeness:** dividend YIELD as a factor.
Trailing-12-month dividends ÷ price is computable from free yfinance data and
is point-in-time safe (dividends are known at payment date), so — unlike the
value/quality factors — it is NOT blocked on the fundamental archive. It is
partly a value proxy, and dividend income is directly relevant to a sharia
investor. Not built yet; the honest next candidate if these two come back
null.

### Results (2026-07-24, run on the user's machine) — the first ACTIONABLE findings in the project

Two formatter bugs were found and fixed by inspecting these outputs against
the raw numbers; both had made the printed READ line misleading, and both now
have regression tests:
* the deployment verdict checked only the WORST-case drawdown, so on a basket
  where both schedules share the same single worst crash it announced DCA
  "did not buy better protection" while DCA was ~3pp better in the TYPICAL
  window — the drawdown a user actually lives through most of the time;
* the holdings-curve knee search scanned all points including the last, and
  the last point is trivially within 10% of itself, so a still-falling curve
  reported "most of the benefit is captured by K=<largest tested>" — exactly
  backwards, telling you to stop where more names were still helping most.
Numbers below are the corrected reads.

**1. Lump sum vs DCA — the answer for IDX is NOT the textbook answer.**
User's real 8-stock basket, 8.0y, 250 rolling start dates, 0.29% buy cost:
```
                          LUMP SUM      DCA(12mo)
median terminal              1.237        1.080
mean terminal                1.269        1.205
5th pct (bad luck)           0.879        0.872
worst case                   0.792        0.774
median max drawdown         -32.4%       -29.5%
worst max drawdown          -48.9%       -48.9%
lump sum won 62% of start dates (median gap +2.9%)
```
With a realistic 4%/yr on undeployed cash (Indonesian deposit/sukuk rates are
materially higher than US ones, so 0% is an unrealistically harsh assumption
for DCA): **lump-sum win rate falls to 54%, median gap +0.9% — a coin flip**,
while DCA's median drawdown stays better (-28.9% vs -32.4%).

**Why this differs from the US literature (~2/3 lump-sum win rate):** that
result is driven by cash missing a strong equity drift. Over this IDX window
the basket's drift was modest (~5% CAGR — see the weighting study above)
while Indonesian cash yields are high. When equity drift is low and the
risk-free rate is high, the structural penalty for holding cash shrinks, and
with it lump sum's edge. This is a real, mechanistic reason the answer is
market-specific rather than universal — **not a reason to assume DCA is
better, but a genuine reason the honest answer here is "close enough that
behavior decides."** Practical read for the user's actual decision: deploying
the 30jt at once is still slightly ahead on expected wealth, but the margin
is small enough that spreading it over ~12 months costs very little and
meaningfully smooths the typical drawdown — so the choice can legitimately be
made on what would keep them invested through a bad first year, which is
the real risk to a long-horizon plan.

**2. Basket selection — NULL. Correlation is structural, not fixable by picking.**
K=8 from 26 names, 5.1y, walk-forward, 200 random draws:
```
                            CAGR     vol    maxDD  ret/vol  avgCorr
low-correlation pick      13.60%   24.1%   -34.8%    0.56    -0.03
random pick (median)      13.79%   25.4%   -44.3%    0.54     0.04
34% of random draws achieved LOWER volatility than the low-correlation pick
```
Landing at the 34th percentile of the random distribution is
indistinguishable from picking at random — trailing correlation carried no
reliable information about future co-movement, the classic instability.
**Caveat on the drawdown column, stated rather than spun:** the low-corr
basket's -34.8% vs the random MEDIAN's -44.3% looks impressive, but that
compares one realized path against a median, and the percentile of the
drawdown was never computed — so it cannot be claimed as significant. On the
metric selection actually targets (volatility) the result is a clean null.
This closes the "can I fix the correlation problem by choosing different
stocks" question: not this way.

**3. Holdings-count curve — the most actionable result in the whole project.**
26 names, 5.1y, 100 random baskets per K:
```
  K      median vol   median maxDD   avg pair corr
  1          67.5%         -76.5%           0.00
  2          45.3%         -65.1%           0.03
  4          33.2%         -51.9%           0.04
  8          25.1%         -41.1%           0.03
  16         19.3%         -34.9%           0.04
```
The curve had **NOT flattened by K=16** — the 8→16 step still cut 5.8pp of
volatility and 6.2pp of drawdown. Diversification was still paying at the
edge of the tested range, which is a genuine, prediction-free risk reduction
of exactly the kind every signal/weighting/exposure study failed to find.

**But three caveats decide whether it's actionable for THIS user, and they
mostly point the other way:**
  a. The 8 satellite names are only 20% of the target allocation; the other
     55% is XIJI, a broad ETF that ALREADY holds a wide slice of the index.
     The user's true equity diversification is therefore far better than
     "8 names" implies, and the curve overstates the marginal gain available
     to them specifically.
  b. At 30jt IDR, 20% = 6jt. Split across 16 names that is ~375k per name —
     below one IDX lot (100 shares) for any stock priced above 3,750, so a
     16-name satellite sleeve is **not physically buyable** at this account
     size. This is a hard constraint, not a preference.
  c. Both (a) and (b) point at a question this project has never tested and
     which is now the highest-value one remaining: **does the 8-name satellite
     sleeve add anything at all versus simply putting that 20% into XIJI
     too?** The holdings curve gives strong prior reason to think a
     concentrated 8-name sleeve is riskier than the index for no compensating
     return — but that is a hypothesis, not yet a result.

Also worth re-running: `selection_study.py` auto-sampled alphabetically again
and got 26 usable names over only 5.1y. The curated 40-name verified-sharia
blue-chip list (used for the weighting and vol-targeting studies) would give
a longer window and a larger K range:
```
python selection_study.py --tickers <curated 40> --period 10y --k 8
```

**4. Core-satellite (`kala/core_satellite_backtest.py`, `core_satellite_study.py`)
— built 2026-07-24 in direct response to caveat (c) above, UNTESTED on real data.**
The holdings curve established that ~8 names carry real extra risk versus a
broad index. That alone doesn't settle anything: the sleeve is worth holding
only if it PAYS for that risk with return. Nothing in this project had tested
that, and it is the one open question whose answer could actually change what
the portfolio holds (all thirteen signal studies came back null and changed
nothing). Like the deployment study, it contains no prediction — both arms are
buy-and-hold, so there's no timing edge to be wrong about.

Three arms — `core_only` (100% index), `blend` (`core_weight` index + rest
equal-weight satellites), `satellite_only` — which separates two things easy
to conflate: whether the satellites are good on their own, and whether adding
them to a core improves the COMBINED portfolio (the actual decision). Default
`core_weight=0.73` is the user's real equity split (55% XIJI vs 20% satellites
normalized within the equity sleeve; the 25% sukuk/cash is a different asset
class and excluded). Robustness via rolling sub-windows: reports how OFTEN the
blend beat core-only, so a sleeve riding one lucky episode is exposed rather
than flattered by a single full-sample number. 13 unit tests.

**Known risk for the real run**: IDX index ETFs are young. If XIJI.JK's history
is much shorter than the satellites', the overlap collapses to the ETF's
lifetime — so the module deliberately does NOT apply the usual short-history
drop filter to the core (it's the reference asset; the honest response is a
loud caveat, not silently excluding the thing being tested), refuses outright
when the overlap can't support the rolling check, and shouts `SAMPLE IS SHORT`
in the verdict under ~3 years. If XIJI proves too short, `--core ^JKSE` gives a
long-history broad-index proxy, with the caveat that IHSG is not sharia-screened
so it answers the structural concentration question rather than the exact
allocation one. Run:
```
python core_satellite_study.py --core XIJI.JK \
    --satellites TLKM.JK UNVR.JK ICBP.JK KLBF.JK ANTM.JK INDF.JK BRIS.JK SMGR.JK
python core_satellite_study.py --core ^JKSE --satellites <same 8>   # fallback if XIJI too young
```

### Results (2026-07-24, run on the user's machine) — verified real, the most decisive finding in the project

Two runs came back disagreeing sharply: with XIJI.JK as core, the satellite
sleeve won 90% of rolling windows; with ^JKSE (IHSG) as core, it was a 51%
coin flip. The entire gap traced to one number — XIJI.JK itself returned
-3.25% CAGR over the 8y window, versus IHSG's +0.61% and the same 8
satellites' +5.10%. An index fund losing money for 8 straight years while
its own reference stocks gained 5%/yr on average was suspicious enough to
check before trusting either result (`_diagnose()` added to
`core_satellite_study.py` for exactly this — prints each series' date range,
start/end price, and year-by-year return before running the comparison).

**The diagnostic ruled out a data artifact**: XIJI.JK's ~2447 bars showed
continuous, plausible year-by-year swings (no flat/stale stretches, no
absurd single-period jumps) matching the satellites' bar counts. The
remaining open question — could yfinance be splicing in a DIFFERENT,
delisted fund that once used the recycled "XIJI" ticker code before the
real XIJI existed — was closed by the user directly: **XIJI (Premier ETF
JII) has been listed on IDX since April 30, 2013**, three years before this
test window even starts. The data is real and continuous.

**This means the XIJI run is not just valid but the MORE relevant of the
two** — it compares the satellites against what the user actually holds as
core, not an abstract broad-market proxy. Corrected verdict:
```
CORE-SATELLITE (core=XIJI.JK, 8 satellites, 8.0y, 72 rolling 504d windows):
  core only (100%):    CAGR -3.25%   vol 22.9%   maxDD -46.1%   ret/vol -0.14
  blend (73/27):        CAGR -0.53%   vol 20.3%   maxDD -45.1%   ret/vol -0.03
  satellites only:      CAGR +5.10%   vol 22.6%   maxDD -48.9%   ret/vol +0.23
  blend beat core-only in 90% of rolling windows
```
The satellite sleeve earned its risk consistently — not one lucky episode —
over the full window this project has data for. **XIJI's own weak return is
the real story here**, not an artifact: an 830bp/yr gap versus the hand-
picked blue-chips is too large to be fees alone (IDX ETF expense ratios are
typically <1%/yr); the more likely explanation is that XIJI tracks the JII
(Jakarta Islamic Index) universe, which is broader and more heterogeneous
than 8 hand-picked large, liquid, well-known names, so some of this gap is
plausibly survivorship/selection bias in how the satellite list was chosen
(picked as "well-known, established, sharia-verified," which correlates
with "did reasonably well," even though it was never selected on backtested
returns). That mechanism is not verified further here — it would need XIJI's
actual holdings/index methodology, which is out of scope for a price-only
backtest.

**Practical read for the user's actual allocation**: over the only 8-year
window available, holding more satellite and less core would have paid off,
consistently. This does not prove the mechanism persists — one continuous
regime is still one draw of history, and if XIJI's underperformance is
mean-reverting (weak periods followed by catch-up) rather than structural,
the past 8 years understate its case going forward. But absent evidence of
mean reversion, this is the strongest, most decision-relevant finding in the
whole project: it says do NOT simplify toward more core (the opposite of
what the initial "wash" reading suggested before XIJI's data was verified),
and if anything raises rather than settles the question of whether the
satellite sleeve should be a LARGER share of the equity allocation than
20%. That sizing question is not tested here and would need its own study
before acting on it at a larger scale.

## Survivorship check, sizing sweep, and dividend yield (2026-07-25) — results

**Survivorship check: FINDING SURVIVES, with an unexpected extra data point.**
Run (broad ~44-name sharia sample, 5.6y overlap — shorter than the
core-satellite study's 8.0y because the auto-sampled universe includes
younger listings the short-history filter trims):
```
                                    CAGR    ret/vol
core only                         -0.27%    -0.01
random basket (median draw)        6.01%     0.31
hand-picked 8 (the real basket)    1.18%       —
100% of 300 random baskets beat core-only on both CAGR and ret/vol.
The hand-picked 8 sit at the 1st percentile of the random distribution.
```
100% of random baskets beating the core is about as clean a "SURVIVES" as this
kind of test produces — the edge is driven by the core being weak, not by
skillful selection. The 1st-percentile placement is the genuinely interesting
part: **the hand-picked 8 did not just fail to be special, they underperformed
nearly every random alternative.** That is reassuring in the way that matters
most (the result does not depend on having picked well, so it is not a
hindsight artifact) but also humbling — a random 8-name draw from the same
universe would, on this evidence, likely have done BETTER than the specific
satellites chosen. Restated because it matters: this pool is still today's
ISSI list, so the residual universe-level survivorship bias flagged in the
module docstring is real, unmeasured, and flatters every arm including this
one.

**Sizing sweep: monotonic in this basket, refuses to name a weight, correctly.**
```
core weight    CAGR     vol    maxDD   ret/vol
     0%        5.10%   22.6%  -48.9%    0.23
    25%        3.47%   20.2%  -47.0%    0.17
    50%        1.53%   19.5%  -45.2%    0.08
    73%       -0.53%   20.3%  -45.1%   -0.03
    90%       -2.20%   21.8%  -45.3%   -0.10
   100%       -3.25%   22.9%  -46.1%   -0.14
```
Monotonic and fairly steep — more core was worse at every step tested, on this
one realized history. Given the survivorship result above, a more diversified
(and less hindsight-flavored) satellite sleeve than these specific 8 might sit
even further left on this curve. Still not a basis for picking a weight: this
is one window, and the formatter's own refusal to crown an optimum applies
here as much as to any other sweep.

**Dividend yield: the first run was a DATA GAP, not a market result — found,
fixed, and the real result is a clean rejection.** `python run_walkforward.py
--strategy dividend_yield` initially returned 0 trades across all 31 folds,
printing INCONCLUSIVE. Investigation found the cause in `run_walkforward.py`'s
`fetch()`: it unconditionally kept only `["Open","High","Low","Close",
"Volume"]` and never called `yf.download(..., actions=True)`, so a
`Dividends` column was structurally unreachable for ANY strategy, not
something specific to this one. Fixed by adding `Strategy.needs_dividends`
(declared `True` on `dividend_yield`) and a dividends-aware fetch path that
keeps the column, threaded through from `main()` — deliberately bypassing the
warehouse cache on that path rather than risk two incompatible on-disk
schemas under one store. 4 new tests cover the flag being honored, the
default path staying unchanged, and a fallback to an all-zero column if a
vendor quirk omits `Dividends` for some ticker.

Re-run with the fix (53 tickers, 10y, tick-floored — "10y, with dividends" in
the download log confirms the fetch path actually fired this time):
```
POOLED OOS (walk-forward threshold)   n=1988  EV/trade=-0.55%  win=35%  PF=0.85  t=-2.75
EXCESS OOS (walk-forward threshold)   n=1988  EV/trade=-0.50%  win=39%  PF=0.86  t=-2.56
VERDICT: NO OOS EDGE (both raw and excess) -- a clean rejection, not the
beta-capture mirage every US raw number here has shown: raw and alpha AGREE
in sign and both clear |t|>2.5 on a large sample.
```
Read plainly: buying the highest-yielding sharia names in this universe lost
money, with real statistical power, both in isolation and against the
benchmark. Plausible mechanism (not verified further, but exactly the risk
the module's own docstring flagged before this was tested): the taper-down
guard above `CAP_YIELD` (15%) stops the most extreme yield-trap cases, but a
5-15% trailing yield can still often mean "price fell partway, dividend
hasn't been cut yet" rather than "healthy sustainable payer" — the same
mean-reversion-flavored trade this project already found actively negative
elsewhere (t=-3.91). Fourteenth hypothesis; still none survive an honest
alpha check.

## Support/resistance result (2026-08-03) — the fifteenth hypothesis, confidently negative

Prompted by a user question about a day-trading YouTube video ("master
support and resistance"). Operationalized the folk method literally on daily
bars — cluster confirmed swing lows into zones, require >=2 touches, score by
proximity to the nearest strong zone, drop broken levels — with pivot
confirmation deliberately LAGGED (a swing low isn't recognizable until
several bars after it prints) so the backtest can't use knowledge the market
didn't have yet, the single most common way S/R backtests cheat. See
`kala/strategy_support_resistance.py`'s module docstring for the full method
and `tests/test_strategy_support_resistance.py` for the look-ahead guard
test and a flat-price-stretch bug it caught during development (a dead-flat
illiquid name was manufacturing a 246-touch "support zone" from zero real
swings).

Run (53 tickers, 5y, tick-floored):
```
POOLED OOS (walk-forward threshold)   n=1432  EV/trade=-0.93%  win=32%  PF=0.77  t=-3.52
EXCESS OOS (walk-forward threshold)   n=1432  EV/trade=-0.89%  win=37%  PF=0.78  t=-3.40
POOLED OOS (fixed baseline 60)         n=615  EV/trade=-1.55%  win=29%  PF=0.65  t=-3.76
EXCESS OOS (fixed baseline 60)         n=615  EV/trade=-1.49%  win=35%  PF=0.66  t=-3.66
VERDICT: NO OOS EDGE both arms, both raw and excess -- not a weak/underpowered
null, a confident rejection: |t| > 3.4 on all four cuts, on 1432 OOS trades,
raw and alpha agreeing in sign and magnitude (no beta-capture mirage to strip
away, unlike most of the US raw numbers in this file).
```
Read plainly: buying near a well-touched daily support zone did not just fail
to help, it lost money with real statistical power, both in isolation and
against the benchmark held over the same days. Consistent with the two
closest cousins already in the zoo — `mean_reversion` (buy-the-dip, t=-3.9)
and `high_proximity` (52-week-high nearness, null) — all three "price
relative to a reference level" framings have now failed on this universe.
Fifteenth hypothesis; still none survive an honest alpha check. Does **not**
test the intraday version of the method (this project has no intraday IDX
data), so it says nothing about day-trading timeframes specifically — it
tests whether the level CONCEPT carries predictive content at daily
frequency, and on this evidence it does not.

## Multi-horizon trend result (2026-08-03) — the sixteenth hypothesis, null-to-negative

Prompted by a user question about a YouTube backtest of the AHL/time-series-
momentum construction on crypto. Built the one component of that recipe not
already tested here — sum of `sign(close_t - close_{t-L})` over L in
5/10/21/42 days — deliberately EXCLUDING vol-scaled sizing (separately
rejected on IDX, see "Volatility targeting" above) and long/short exposure
across many markets (unavailable: long-only universe, ~50 correlated IDX
names vs the 700 uncorrelated futures markets that make diversified trend
following work). See `kala/strategy_multihorizon_trend.py`'s module
docstring for why that makes this a test of the signal SHAPE alone, not of
diversified trend following as a category.

Run (53 tickers, 5y, tick-floored):
```
POOLED OOS (walk-forward threshold)   n=1882  t=-0.38   -- ~flat, indistinguishable from 0
POOLED OOS (fixed baseline 60)        n=3009  t=-2.66   -- confidently negative
EXCESS OOS (walk-forward threshold)   n=1882  t=+0.22   -- ~flat, indistinguishable from 0
EXCESS OOS (fixed baseline 60)        n=3009  t=-2.50   -- confidently negative
```
The two arms disagree in an informative way, not a contradictory one. The
walk-forward threshold column shows the trained arm almost always picked
thr=90 (the strictest rule: all four horizons must agree) rather than the
looser thr=60 most people would actually trade — and that strict subset
came back statistically FLAT, not positive. The fixed-baseline-60 arm, which
applies one simple rule uniformly across all history without letting each
fold retune it, is confidently NEGATIVE with real power (n=3009, |t|>2.5,
raw and alpha agreeing in sign). Read together: training did not find real
structure, it retreated to the thinnest, strictest subset of trades where
the previously-negative effect became too noisy to distinguish from zero —
textbook overfitting-to-noise, exactly the failure mode the walk-forward
harness's baseline-vs-trained comparison exists to catch. There is no
version of this signal worth trading: the strict filter does nothing, the
naive filter loses money with statistical power. Sixteenth hypothesis;
still none survive an honest alpha check.

## What's still true and still useful here

- The **engineering is sound**: no-look-ahead backtesting, ARB/limit-lock
  handling, asymmetric IDX costs, tick-floored spreads, crash-safe state,
  atomic saves, a real walk-forward harness with anti-overfit guards
  (train-only threshold selection, minimum trade counts, and now a
  per-strategy `warmup_bars` declaration so a long-lookback signal can't
  silently starve on default warmup), an alpha-vs-beta diagnostic, a
  strategy-zoo plugin interface. Momentum (plain, regime-gated, and
  long-horizon 12-1) and mean-reversion are all now tested and cleanly
  ruled out (see above); bandarmology/broker-flow (`foreign_flow`,
  `broker_concentration`) was tested against real backfilled data and
  came back genuinely inconclusive rather than ruled out — see
  "Bandarmology result" above for exactly what a larger-ticker-count
  re-run would take to settle it for real. What's still genuinely
  untested and reusable-if-you-want-it:
  a *fundamental-value* tilt (needs point-in-time fundamentals this
  project doesn't have — see `kala/fundamental_screen.py`). The
  `/analysis/financial-statement/{code}` lead was probed: it DOES return
  real multi-period history, but its response carries no revision flag and
  no filing date, so a single pull can't prove point-in-time integrity
  (whether "FY2020" today equals FY2020 as-first-reported, or a
  restatement). That's now handled the same way sentiment and broker-flow
  were: `kala/fundamental_archive.py` stores dated snapshots
  (`observed_date` in the key) with `as_of` (point-in-time read) and
  `diff_observations` (restatement detector), and `archive_fundamentals.py`
  is the CLI that lays them down. The catch is structural, like
  bandarmology's: the restatement check needs two snapshots taken real
  calendar time apart, so it can't be settled this session — start the
  monthly archival now and it answers itself. The "different market"
  question (see `LIBRARY_NOTES.md` for how market-agnostic the harness
  already is) is no longer fully open either: momentum was retested on
  US sharia large-caps (`kala.universe.US_SHARIA_STOCKS`,
  `--universe us --cost-preset us_equity`) and, once the alpha check
  strips out the historic 2019-2026 US bull run, still shows no real
  edge — see "US large-cap momentum result" above. `long_momentum` (the
  one IDX result with real negative statistical power) was retried on
  the same US universe too, closing the loop: it came back weak/noise
  rather than negative (t=0.68/1.04 — see "US long-horizon momentum
  result" above), and the SIGN FLIP between markets on the identical
  strategy is itself evidence against a real transferable edge, not for
  one. Two strategies now tried on the US universe, both no-edge; the
  "IDX/thinness was the problem" theory is no longer a live open
  question worth more backtesting to settle — **research is closed as
  of 2026-07-23** (see the Verdict section). The one thing still
  genuinely unresolved is the fundamental-value archive above, and it
  needs calendar time, not more code.
- The **paper trader, Telegram bot, and safety features** (undo/redo,
  backdating, atomic state, edge tracking) work as built and are fine to
  keep running as a low-stakes way to keep testing ideas — just not with
  money you need to grow.

## What actually happened as a result

Decided to stop chasing an active edge in this specific corner of the
market (EOD swing, sharia-only, IDX, retail costs) and instead invest via a
low-cost, sharia-compliant index fund/ETF (ISSI/JII-tracking), monitored
quarterly rather than traded daily. See the separate `INVESTMENT_PLAN.md`
(kept outside this repo, since it holds personal financial numbers).

## Accounting change: manual fills now charge costs (v3.9)

`manual_buy`/`manual_sell` (the bot's `/buy` and `/sell`) used to record the
raw price typed in, adding no commission, while automated fills embedded
costs via the cost model. A 100%-manual book — which the real one is —
therefore reported returns optimistic by roughly the round-trip friction on
every trade: **~0.64% per round trip** at the default IDX rates, against
few-percent target moves. `/friction` measured that gap but never closed it.

Manual fills now apply the same `CostModel` multipliers the automated path
uses, so `entry_price` is genuinely cost-inclusive as `PaperPosition` always
documented. **Trades booked before this change are untouched** — rewriting
them would falsify history — so a live book is MIXED. Records carry markers
(`"costed"` on fills and closed trades, `"entry_costed_frac"` for a buy leg
that predates the change), and `kala.friction` reads them per record so
money already inside the recorded prices is reported as spent but never
deducted twice. A book with no markers reports exactly as it did before.

Set `"charge_manual_costs": false` in `runner_config.json` to go back to raw
prices for new fills.

## Outstanding housekeeping (unrelated to the edge finding)

- **Rotate the Telegram bot token** via @BotFather (`/revoke`) — it has
  appeared in plaintext in `runner_config.json` across every export of this
  project. Do this regardless of what else you do with the repo.
- `UNIVERSE_UPDATED` in `kala/universe.py` — set when the ISSI list is
  next refreshed (IDX revises ~May & ~Nov).
- `python tidy_repo.py --apply` — archives stray `results/` output.

## Foreign-flow OOS result (2026-08-10) — NO RAW EDGE; excess positive but not robust. NOT VALIDATED.

The first adequately-powered out-of-sample test of `foreign_flow`. The
2026-07-23 passes printed INCONCLUSIVE on n=23-25 trades, which was the
correct call on that sample. This run reaches **n=115-125**, so for the first
time the harness is answering the question rather than declining it.

**What changed since then.** Three things, and only the first two are about
data quality:

1. The archive's gap structure was measured rather than assumed. Of 515
   business days, 47 are absent for EVERY full-span ticker — IDX market
   holidays, not fetch failures — leaving 468 real trading days. Mean coverage
   against that denominator is 96.7% (min 64.3%), with 490 isolated
   (ticker, date) holes.
2. `strategy_foreign_flow` no longer sums missing days as 0. That estimator
   understated cumulative flow by 20% (median) on the 26% of bars whose window
   was holey; it now takes the mean over OBSERVED days scaled to the window,
   which is unbiased at any coverage. These numbers are computed on the
   corrected estimator.
3. A different, smaller cohort (29 usable of the 32 tickers with real flow
   history) and different fold windows than the July run. **The July and August
   numbers are therefore NOT directly comparable** — the shift from a raw
   t=-3.35 to t=-0.04 is a change of sample, not a measured improvement, and
   should not be read as one.

**Command**

```
python run_walkforward.py --strategy foreign_flow --broker-flow-db --period 2y \
  --tickers <the 32 with flow history>      # 29 usable after the price filter
```

**Results**

```
fold  test window                thr  trades  EV/trade  win%  IHSG%
0     2025-11-28..2026-03-05      50      83   +0.33%    36%   -9.4
1     2026-03-06..2026-06-12      80      32   -2.01%    38%  -20.8

POOLED RAW (wf threshold)   n=115  EV=-0.32%  median=-3.81%  win=37%  PF=0.94  t=-0.27
POOLED RAW (fixed 60)       n=125  EV=-0.05%  median=-4.91%  win=37%  PF=0.99  t=-0.04
EXCESS    (wf threshold)    n=115  EV=+0.68%  median=-0.76%  win=47%  PF=1.17  t=+0.59
EXCESS    (fixed 60)        n=125  EV=+1.45%  median=-0.39%  win=47%  PF=1.39  t=+1.32
clustered t (by entry date) = 0.52   deflated Sharpe = 0.274 (5 thresholds tried)
```

**Raw returns: no edge.** PF 0.94 / 0.99, t indistinguishable from zero. The
harness's NO OOS EDGE verdict stands.

**Excess returns: positive, and not to be trusted.** The +1.45% is real
arithmetic but fails four independent checks, any one of which is
disqualifying against this project's own bar (|t| >= 2 on both raw and excess,
confirmed more than one way):

  * t = 1.32 at best, and the clustered t — the one to trust, since same-day
    trades share that day's move — is **0.52**;
  * deflated Sharpe **0.274**, i.e. after deflating for the 5 thresholds tried,
    P[true Sharpe > 0] is ~27%, worse than a coin flip;
  * the **median excess is NEGATIVE** (-0.39%) with a **47% win rate** — the
    typical trade underperforms the benchmark and the positive mean rests on a
    few large winners, which n=125 across 2 folds cannot support;
  * both OOS folds sit inside a -9.4% and -20.8% IHSG drawdown, so the result
    describes one regime only.

**Two overfitting signatures.** The selected threshold swung 50 -> 80 between
consecutive folds; and the FIXED baseline (60) beat the walk-forward selection
on excess (+1.45% vs +0.68%). When per-fold parameter selection does worse than
one constant, what is being selected is noise.

**Verdict: NOT VALIDATED.** Consistent with the standing INCONCLUSIVE, now on
evidence rather than an underpowered sample. Do not size on this signal. Same
posture as `veto_cheap_stock`: a thing may be kept for cost or prudence
reasons, but not on an edge claim that has not stood up.

**One open thread, stated as a hypothesis and not a finding.** Raw-negative
with excess-positive is the shape of a DEFENSIVE characteristic — foreign flow
may mark names that fall less when the market falls. That is a different
question from "is there an edge", it was not tested here, and 468 trading days
that are entirely downtrend cannot distinguish it from chance.

**What would settle it:** history spanning a RISING regime. Not more tickers,
and not re-fetching the 490 gaps (measured: the old estimator moved only 1.9%
of BUY signals). Two folds that are both crashes cannot separate defensive
stock-picking from luck, however many trades they contain.
