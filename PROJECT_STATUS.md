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

> **CORRECTION, 2026-08-17 — read this before the table below.**
>
> Everything in this SUMMARY was written from results measured THROUGH the
> exit ladder (stop -5% / target +8% / trailing / 20-bar hold). The full
> universe now shows that ladder is not neutral: on its own it is
> significantly NEGATIVE — excess -0.45%/trade, clustered t -3.79, losing in
> 12 of 14 folds across 18,931 trades.
>
> Remove it and the SAME signal on the SAME universe and folds returns
> excess +4.70%/trade, clustered t +5.09, DSR 1.000. The liquidity split
> confirms this is not survivorship (present in both halves, STRONGER in the
> liquid half at t +4.31) and not universe drift (threshold-0 control is
> zero in both halves).
>
> So the one-line answer below is WRONG as stated, and every verdict in the
> table carries the same handicap — see "What the ladder does to all sixteen
> verdicts" further down. The evidence is in "FULL-UNIVERSE EXIT-PROFILE
> COMPARISON" and "FULL-UNIVERSE LIQUIDITY SPLIT" at the end of this file.

**The one-line answer** (SUPERSEDED — see the correction above): no predictive
edge survived honest testing, but several *structural* choices did — and one
late result (core-satellite) reversed an earlier conclusion, so read the
Results subsections rather than trusting any single summary line.

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

## Exit-ladder result (2026-08-13) — the ladder SUBTRACTS value; no holding period is decidable yet

The first out-of-sample test of the exit engine itself. Entry side, folds, costs
and universe held fixed throughout; only the exit geometry varies, so every
comparison below is like-for-like. Built for this:
`diagnose_exit_param_sweep.py`.

Prompted by a live observation, not a hypothesis: the paper book kept returning
either a scratch or a stop-sized loss. The closed-trade log showed three
clusters sitting exactly on `hard_stop_pct`, `target_profit_pct` and
`breakeven_trigger_pct` — the ladder's own geometry, printed in the P&L.

### What was run

```
python diagnose_exit_param_sweep.py --max-tickers 40 --period 5y --tick-spread
python diagnose_exit_param_sweep.py --max-tickers 40 --period 5y --tick-spread \
    --targets 10 12 16 20 --breakevens 6 8 99
python diagnose_exit_param_sweep.py --max-tickers 40 --period 5y --tick-spread \
    --sweep-holding 10 20 40 60 90 120
```

35 usable tickers, 14 folds, train 252 / test 63, tick-floored spread.

### Result 1 — the ladder subtracts value. This one stands.

Every one of 48 stop x target x breakeven cells came back with negative
expectancy, and in every cell the realised win rate sat BELOW the break-even
win rate its own geometry demands. A control line — same entries, same folds,
all price-based exits switched off so only `holding_max_days` closes a position
— beat every managed cell by roughly half a percentage point per trade.

The mechanism is in the payoff column, not the win column. Managing the exit
RAISES the win rate and LOWERS the payoff ratio, and the payoff loss dominates.
The median trade is negative everywhere including the control: this is a
positive-skew system whose expectancy lives in a thin right tail, and a target
profit is precisely the rule that amputates it.

Note which way the multiple-comparison bias runs: taking the best of 48 cells
inflates the winner, and the winner was still negative. That makes this a
CONSERVATIVE negative — deflation cannot rescue it and is not needed.

### Result 2 — no holding period is decidable. This one does NOT stand.

With all exit rules off, sweeping `holding_max_days` produced its best
expectancy at 60 days. It fails on three independent counts:

  * **t below 1.0.** The project's bar is |t| >= 2. Nothing in the column
    clears it.
  * **The column is not monotone** — it rises, dips, then rises again. A real
    effect produces a smooth surface; this is the shape of noise.
  * **Best of six trials**, unadjusted.

Payoff rises smoothly with holding period while win rate falls, and the two
roughly cancel. That is a coherent story with no measurable edge attached.

### Why it is undecided: the sweep used 6% of the universe

At the best holding period the implied per-trade standard deviation puts the
sample needed for |t| = 2 at roughly four and a half times what the sweep
produced. That reads like a structural wall, and it is not one — the run
sampled 35 of the 615 tickers in `ALL_SHARIA_STOCKS` because `--max-tickers`
defaulted low. Extrapolating the observed trades-per-ticker to the full
universe clears the required sample with room to spare.

**So the honest status of Result 2 is UNTESTED AT ADEQUATE POWER, not
"no effect".** Re-run across the whole universe before drawing any conclusion
about holding periods. That is the single cheapest open experiment in the
project — one flag.

### What this does and does not license

  * **Supported:** the configured ladder costs money. `target_profit_pct` and
    `breakeven_trigger_pct` as they stand are value-destroying on this
    universe, consistently, across dozens of configurations.
  * **NOT supported:** that holding longer makes money. The control's absolute
    expectancy is thin and its t is not close to the bar.
  * **NOT supported:** any specific holding period as a config value. 60 days
    is the top row of a noisy column, not a setting.

### The constraint this points at

Across every configuration tried, the gap between realised win rate and the
break-even win rate the geometry demands was small and usually negative. No
exit rule can manufacture that margin — it is a property of the entry signal.
This is the third independent line of evidence pointing the same way, after the
look-ahead retraction and the momentum walk-forward.

Consistent with the standing position: the entry signal remains unvalidated,
and nothing here changes that.

## Holding-period result (2026-08-14) — survives every correction available; blocked on survivorship

Full universe, exits off, benchmark-excess measured. This is the strongest
result the project has produced, and it is still NOT a validation. Both halves
of that sentence matter.

### What was run

```
python diagnose_exit_param_sweep.py --max-tickers 615 --period 5y --tick-spread \
    --warehouse results/warehouse.db --min-price 0 --sweep-holding 20 40 60 90 120
```

569 usable tickers, 14 folds, train 252 / test 63, tick-floored spread, no
price screen. All price-based exit rules off — only `holding_max_days` closes a
position.

```
hold_d     n     EV%    med%   win%  be-win%  payoff    PF  clust_t   exEV%  ex_clt
    20  12184  +0.927  -3.05   32.9    29.6    2.38  1.17   +2.82  +1.055   +3.60
    40   8986  +2.134  -3.89   29.5    23.6    3.24  1.36   +3.94  +2.200   +4.43
    60   7877  +2.403  -4.01   29.0    22.5    3.44  1.40   +4.01  +2.447   +4.51
    90   7286  +1.967  -4.07   28.4    23.0    3.35  1.33   +3.28  +2.066   +3.74
   120   7091  +2.021  -4.15   28.4    22.9    3.37  1.33   +3.29  +2.098   +3.70
```

### What holds

Benchmark-excess clears |t| = 2 at every holding period on the CLUSTERED
figure, between +3.60 and +4.51. The curve is a broad plateau from 40 days
outward rather than a sharp peak, which is the shape a real effect makes; a
spike at one setting would be the shape of a fit.

`exEV%` EXCEEDS `EV%` in every row, meaning IHSG fell on average across the
holding windows. The raw return was already beating a declining index, so this
is not market exposure wearing a disguise.

### The three corrections it survived — and where they came from

Each of these changed the answer, and **each was a defect in the sweep tool
rather than planned rigour**. Recording that honestly, because the sequence is
the reason to trust the number:

1. **Wrong result field.** The tool read `res.trades`; the field is
   `res.closed`. Guarded by a `getattr` default, so every cell silently
   returned zero and the first full grid printed as a tidy table of zeros. Had
   this not been caught, the conclusion would have been "the exit ladder makes
   no difference".
2. **Look-ahead price screen.** The sweep inherited `fetch()`'s `--min-price`
   filter, which tests each ticker's LATEST close — the exact mechanism behind
   this project's earlier retraction. Re-run at `--min-price 0`.
3. **No alpha check.** Only raw expectancy was measured. A long-only book held
   for weeks shows raw expectancy from market exposure alone; the project's bar
   has always been |t| >= 2 on raw AND excess.

A plain t was also being reported where a clustered one was required — 569
tickers entering on shared dates are not independent draws. `clustered_t_stat`
had existed in `walkforward.py` the whole time.

### What blocks it

**Survivorship, and it cannot be corrected — only stated.** The universe is
CURRENT index membership. Every ticker in it survived to today; names delisted
or dropped from the index, usually after falling, are absent from all of
history. That bias falls hardest on exactly this kind of result: a long-hold
strategy whose expectancy sits in a right tail, because the tail is made of
survivors.

This is not a bug to be fixed in a later pass. It is a limit of the data, and
closing it needs point-in-time DES constituents, which IDX revises about twice
a year and the project does not have.

**These figures are an UPPER BOUND with a bias of unknown size.**

### Status

NOT VALIDATED. The correct reading is narrower and more useful than a verdict:
*survived every correction that could be applied, blocked on one bias that
cannot be*. That is a stronger position than anything else in this log, and it
is not the same as an edge.

Nothing here licenses sizing up. What it licenses is the next round of tests —
see "what would settle it".

### What would settle it

  * **Signal-contribution control.** Sweep `score_entry_threshold` with exits
    off. If expectancy is flat from threshold 0 to 80, the entry signal is
    contributing nothing and the result is universe drift over the period, not
    stock selection.
  * **Cross-market replication.** Run the same holding sweep on
    `US_SHARIA_STOCKS`. The project has used the US market as a reference
    before. An effect that appears in both is far less likely to be an artefact
    of IDX-specific survivorship.
  * **Forward paper test.** The only clean answer to survivorship: trade it
    forward, where the bias cannot exist by construction. Slow, and the only
    method that actually closes the question.

## Signal-contribution control (2026-08-14) — the composite score DOES select. Dose-response, monotone.

The control that was missing from the holding-period result above, and the one
that could have killed it. It did the opposite.

The alpha check subtracts IHSG, but the universe is IDX SHARIA names, not
IHSG. If that segment simply outperformed the index over these five years, the
holding-period result would show a strong excess figure while the composite
score selected nothing. Sweeping `score_entry_threshold` with exits off
separates the two: a threshold of 0 enters almost every bar, so its row IS the
universe.

```
python diagnose_exit_param_sweep.py --max-tickers 615 --period 5y --tick-spread \
    --warehouse results/warehouse.db --min-price 0 --trust-short-cache \
    --sweep-threshold 0 30 60 80 --hold-days 60
```

```
thresh      n      EV%    med%   win%  payoff     PF  clust_t    exEV%  ex_clt
     0  15907   -0.201   -2.41   30.0    2.25   0.97    -0.49   +0.220   +0.68
    30  13467   +0.621   -2.44   27.5    2.94   1.11    +1.41   +0.875   +2.43
    60   7878   +2.401   -4.01   29.0    3.44   1.40    +4.01   +2.445   +4.50
    80   5635   +4.037   -4.79   32.8    3.30   1.61    +4.73   +4.009   +4.97
```

### What this establishes

**The universe alone has no edge.** At threshold 0 the raw expectancy is
NEGATIVE and the clustered excess t is +0.68 — not significant. Whatever is
happening at higher thresholds is not the segment drifting up.

**The signal selects, and it does so in proportion to how hard it is asked
to.** EV, excess EV, profit factor and clustered excess t all rise monotonically
across all four levels. A dose-response of that shape is much harder to
manufacture than a single winning cell: it is not "best of N", it is a gradient.

**It substantially defuses — though does not remove — the survivorship
objection.** Survivorship inflates every row roughly equally, threshold 0
included, so it cannot produce the gradient. The ABSOLUTE level remains an
upper bound; the SELECTION effect is robust to a universe-level bias.

### What it does not establish

  * The absolute expectancy. Survivorship still biases the level, by an unknown
    amount, and there is still no point-in-time constituent data.
  * A setting. Threshold 80 is the highest value swept and the best one, so the
    gradient has not turned over — the optimum is outside the box.
  * That this is tradeable as-is. The median trade is NEGATIVE at every
    threshold (-4.79% at 80) and the win rate is under 33%. The expectancy sits
    in a right tail, which means holding a majority of losing positions to
    collect a minority of large winners. Backtests do not measure whether the
    operator can actually do that.

### The implication for the standing verdict on the momentum score

The composite score has been recorded as unvalidated, on walk-forward runs that
evaluated it THROUGH the exit ladder. That ladder has since been measured as
value-destroying (see "Exit-ladder result"). The earlier negative may therefore
have been a property of the exits rather than of the signal — the entry score
was being judged through a lens that was subtracting roughly half a point per
trade.

That is a hypothesis, not a correction to the record. Settling it means re-running
the original walk-forward with exits disabled and comparing like for like.

### Next

  * Extend the threshold sweep (90, 95) until the gradient turns over or the
    sample gives out.
  * Feed the winner through `overfitting.deflated_sharpe`.
  * Replicate on `US_SHARIA_STOCKS` — an effect present in both markets is
    unlikely to be IDX-specific survivorship.
  * Re-run the original momentum walk-forward with exits off.

## Survivorship discriminator + benchmark corrections (2026-08-16) — the objection does not hold up

The holding-period and signal-contribution results above were recorded as
blocked on survivorship. This round attacks that objection directly, and it
does not survive. Three separate tests, plus two benchmark corrections that
changed how the earlier numbers should be read.

### Liquidity split — the discriminator

Survivorship bias lives in names that COULD have been delisted or dropped from
the index and were not. Large, liquid IDX names rarely leave; the thin end
carries most of the exposure. If the bias produces the alpha, the alpha must
concentrate in the illiquid half.

`--split-liquidity`, median daily turnover, benchmark XIJI.JK, exits off, 60d:

```
LIQUID (284 tickers)          thresh 0     thresh 60    thresh 80
  exEV%                        +0.714       +2.422       +3.527
  ex_clt                        +2.02        +4.25        +4.10

ILLIQUID (285 tickers)
  exEV%                        +0.660       +2.823       +4.692
  ex_clt                        +1.62        +3.62        +3.87
```

The effect is present in BOTH halves, monotone in both, and the CLUSTERED t is
HIGHER in the liquid half at every comparable threshold. The illiquid half
shows a larger raw excess with a smaller t — the signature of more volatility,
not more edge.

**Survivorship is no longer the leading explanation.** That is not the same as
ruled out: index membership shifts touch mid-caps too, and no point-in-time
constituent list exists to settle it outright. But the test built to find the
bias looked exactly where it should live and did not find it.

### Two benchmark corrections

**The US replication was judged against the wrong index.** This strategy holds
one stock per trade — equal-weighted by construction — and was being compared
with cap-weighted `^GSPC`, which five years of mega-cap concentration made
nearly unbeatable by an equal-weight basket. Re-run against `RSP`:

```
thresh        0       30       60       80
^GSPC     -2.91    -1.22    -0.44    +0.41
RSP       -0.42    +0.66    +0.76    +1.18
```

The whole column lifts. The dose-response replicates in the US; the absolute
alpha still does not clear the bar there (best +1.18 on n=714).

**IHSG is the wrong benchmark for a sharia universe.** Against `XIJI.JK`,
threshold 0 — buy almost everything — already shows +0.685% excess at
ex_clt +2.18. The universe beats the sharia index before any selection
happens, which is an equal-weight-versus-cap-weight premium, the same effect
visible in the US pair.

**This changes the honest attribution.** Of the +4.099% excess at threshold 80:

  * **+0.685%** is the universe beating its benchmark — available by buying at
    random, and NOT a contribution of the composite score;
  * **+3.414%** is the increment from tightening the score. That is the number
    that belongs to the signal.

Quote +3.4, not +5.2. The larger figure will not survive scrutiny.

### The gradient turns over

Extending the threshold sweep to 95 / 97 / 99 flattens: excess EV moves 0.051
points across that range while ex_clt DECLINES from +5.22 to +4.57 as the
sample thins. The surface plateaus around 80-95 rather than climbing without
limit — the healthier shape, and it means the exact threshold inside that band
does not matter much.

### Where this leaves the finding

Established, in order of how hard each was to dislodge:

  * the exit ladder destroys value — every one of 32 cells negative at full
    universe, clustered t from -4.68 to -9.72, control beats the best cell by
    1.599 points per trade;
  * the entry score selects — monotone dose-response across four thresholds, in
    TWO markets;
  * it is not universe drift — threshold 0 has negative raw expectancy;
  * it is not a benchmark artefact — holds against XIJI.JK and RSP;
  * it is not concentrated in survivorship-exposed names — holds in the liquid
    half, more strongly by t.

Not established:

  * the absolute magnitude. Some survivorship inflation remains, unquantified.
  * that it is tradeable. The median trade is NEGATIVE at every threshold
    (-4.79% at 80) with a win rate near a third. This requires holding a
    majority of losing positions to collect a minority of large winners, and no
    backtest measures whether the operator can do that. The live log shows the
    opposite instinct: manual selling clustered at -5%.
  * that it persists. One five-year window, no forward test.

### What is left

The only remaining objection that data on hand cannot address is survivorship's
residual size, and the only clean answer is a FORWARD test, where the bias
cannot exist by construction. Everything else has been tried.

---

## State-file durability (2026-08-16) — four ways the watchlist could vanish silently

Not a research result. This is the forward test's precondition: the forward
test is the only remaining answer to the survivorship objection, it runs for
months, and it depends on state files that turned out to be losable without
anything reporting a loss.

The audit lens that found everything else applies here unchanged — the
arithmetic is never wrong, the bug is where missing data quietly becomes a
number. Here the number is zero, and it means four different things.

### What was measured

`repro_watchlist_silence.py` puts `watchlist.json` in four states and asks the
code what it sees:

| state on disk | what the caller was told |
|---|---|
| genuinely empty (`{}`) | `len == 0` |
| file absent / process in another directory | `len == 0` |
| truncated by an interrupted save | raised — into three `except Exception: pass` |
| healthy, three researched names | `len == 3` |

Rows two and three were indistinguishable from row one at every call site. The
consequences were not equal:

  * **`archive_sentiment.py`, `archive_fundamentals.py`, `foreign_flow_monitor.py`**
    built their ticker universe from open positions plus the watchlist and
    ended BOTH reads with `except Exception: pass`. Their archives are
    point-in-time, so a day archived from a silently empty universe is a hole
    that cannot be backfilled — and nothing in the data marks it as a hole
    rather than a quiet day.
  * **All four of those scripts plus `check_watchlist.py`** resolved
    `watchlist.json` and `paper_state.json` against the caller's working
    directory. Measured: the same command returned 3 names from the repo root
    and 0 from one directory up. The shipped systemd units set
    `WorkingDirectory=`, so the packaged deployment was safe; running the
    scripts by hand was not.
  * **`check_watchlist.py`** printed "Watchlist is empty. Run
    kala_fundamental_only.py first" — advice to redo research that was
    already done and sitting in a file it had failed to find.
  * **`WatchlistStore.save` and `PositionStore.save`** used `write_text`,
    which truncates the target before writing. `papertrade.py` had used
    tmp-then-`os.replace` since v3.x for exactly this reason; these two never
    got it. `PositionStore` holds `peak_price`, a running maximum accumulated
    across sessions with no other source — it cannot be recomputed after loss.

### The deployment finding

`docker-compose.yml` mounted `paper_state.json`, `runner_config.json` and
`results/`. It did not mount `watchlist.json`, which the weekly Saturday
fundamental screen writes INSIDE the container. Every `docker compose up
--build` discarded the fair values and theses, and `daily_run.py`'s dip-alert
step then reported zero alerts — which looks exactly like a quiet week.

Separately, `DOCKER.md`'s own setup block said `touch paper_state.json
runner_config.json`. A zero-byte file is not valid JSON; all three loaders
raise `JSONDecodeError` on one. The documented procedure produced a container
that died on first run. `paper_state.json` additionally cannot be seeded with
`{}` — `PaperTrader.load` raises `KeyError: 'cash'` — so the doc now calls
`reset_paper.py`, which writes the correct skeleton.

### What changed

  * both stores write tmp-then-`os.replace`, and create missing parents;
  * `WatchlistStore.load` records WHY a store is empty (`load_note`), naming
    the resolved absolute path when the file is absent;
  * `load()` still RAISES on a damaged file — that loudness is correct and was
    not softened. `load_or_report()` is the opt-in for callers that must
    survive, and it reports rather than swallows;
  * `kala/universe_sources.py` holds one copy of the positions+watchlist
    logic the three archivers each had their own version of. It still degrades
    rather than aborting a run, and now says which source degraded, with its
    path, plus a warning that an incomplete point-in-time archive cannot be
    backfilled;
  * the four scripts anchor their paths to `Path(__file__).parent`;
  * compose mounts `watchlist.json`; DOCKER.md seeds correctly;
  * `check_watchlist.py` distinguishes absent from empty, and uses argparse —
    `--help` previously raised `ValueError: could not convert string to float`.

### Verification

20 new tests in `tests/test_state_files_are_durable.py`. Eight mutations,
one per defect, reinserted mechanically by
`repro/mutate_state_durability.py`: all eight go red. Full suite 1635 passed,
1 skipped.

### What this does NOT claim

No trading number changes. Nothing here touches entries, exits, scoring or
the walk-forward. It removes ways the forward test could quietly stop being a
test of the strategy — the same failure the discipline report exists to catch,
one layer down: a strategy that was never run, reported as one that did not
work.

---

## Circuit-breaker state loss (2026-08-17) — a safety device that switched itself off quietly

Same lens, applied to the one component whose entire job is to stop trading.
The breaker is OFF by default, so this affects only an operator who
deliberately turned it on — which is exactly the operator who would be relying
on it.

### What was measured

`results/breaker_state.json` holds two things: the deposit-adjusted high-water
mark, and whether the breaker is currently halted. `load_breaker_state`
returned `(None, False)` for a file that does not exist YET and for a file that
exists but will not parse. Downstream those are the same event, and the
consequence is not symmetric:

```
stored_peak=None  -> high-water mark re-anchors to TODAY's equity
was_halted=False  -> the "still halted" branch is skipped entirely
                  -> drawdown computes as 0.0%, halt threshold not met
                  -> new buys resume, satisfying none of the resume hysteresis
```

Measured on an account halted 30% below its peak: with the sidecar intact,
`halted=True`. With the same sidecar unreadable, `halted=False` and
`drawdown_pct=0.0` — a 30% drawdown reported as zero — while the run printed
"First run: high-water mark anchored to today's equity", which is false.

The module comment said the lost-sidecar case means "no false halt, no crash".
True, and only one direction. It never named the missed halt, which arrives
precisely when the halt was doing its job.

### The part that was not obvious

The first fix was wrong, and the test caught it. Carrying `was_halted=True`
across an unreadable sidecar does NOTHING: with `stored_peak=None` the peak
re-anchors to today, drawdown reads 0.0%, and the hysteresis branch reports
RESUMED immediately. **The halt is not recoverable from the flag** — the
measurement it was made against is what was lost. That required a separate
`state_lost` input that halts on its own authority rather than through
`drawdown`, and it is now pinned by
`test_carrying_was_halted_alone_does_NOT_hold_the_halt`.

### What changed, and what deliberately did not

The DEFAULT is unchanged. Re-anchoring rather than halting was a documented
choice with an explicit test behind it, and it is not overruled — the trading
numbers are identical unless an operator opts in. What changed:

  * `read_breaker_state()` returns `existed` and `error`, keeping "absent"
    and "damaged" apart;
  * `evaluate_breaker(state_lost=True)` plus
    `BreakerConfig.preserve_halt_when_unreadable` (default False) let an
    operator fail closed instead. The halt cannot stick: the reason string
    says to delete the sidecar to re-anchor deliberately;
  * `daily_run` reports `⚠️ BREAKER STATE LOST` with the parse error and
    states plainly whether the halt was carried over.

### Verification

10 new tests in `tests/test_breaker_state_loss_is_visible.py`; 6 mutations, all
6 red. Suite 1645 passed, 1 skipped.

A note on the mutation run itself: the first pass reported all six mutations
SURVIVED. The harness had been launched under a Python without pytest, so every
run produced zero `FAILED` lines and read as green — including the baseline
assertion, which was equally vacuous. The harness now refuses to score a run
that collected no tests. This is the third time in this project a
green-looking result came from a check that could not fail.

---

## Partial Telegram delivery (2026-08-17) — the message is the forward test's only output

The forward test produces one artefact a human ever sees: the daily message.
If that arrives incomplete, the missing part is indistinguishable from a day
on which there was nothing to say.

### What was measured

Telegram caps a message at 4096 characters, so `send_telegram` splits long
ones and posts them in sequence. A failure part-way leaves the earlier parts
delivered. Measured on an 11,007-character message (tickets + friction report
+ scorecard = 3 parts) with the network failing after the first:

```
chunks actually delivered : 1 of 3
send_telegram returned    : False
```

Two separate losses, in opposite directions:

  * **On the phone.** One message arrives, begins with the tickets, and simply
    stops. Nothing in it says a second and third part existed. The daily
    message is ordered tickets-first and friction/scorecard last, so the tail
    — the part that reports what the strategy is costing — is exactly what
    goes missing.
  * **In the log.** `daily_run` discarded the return value and wrote "Run
    complete. N tickets, 0 errors." `results/daily_run.log` therefore reads
    identically for a run delivered whole, delivered in part, and not
    delivered at all. The failure text went to stdout only — journald, not the
    file anyone opens after a quiet week.

The bare bool could not express the difference either: `False` covered both
"nothing sent" and "half sent", which are different problems with different
responses.

### What changed

  * `send_telegram_detailed()` returns `Delivery(ok, sent_chunks,
    total_chunks, error)` with a `partial` property and a `describe()` that is
    never blank — it goes straight into a log line, where an empty string
    would read as "fine".
  * Split messages are labelled `(i/N)`. This is the fix that reaches the
    reader: a message that stops at `(1/3)` is visibly incomplete on the
    phone, which is where the reader actually is, rather than only in a log
    they would have to think to check. Single-part messages are unlabelled, so
    the ordinary day gains no noise.
  * `send_telegram()` keeps its bool signature for the three callers that only
    need yes/no, and a PARTIAL send returns False — "some of it arrived" is
    not success.
  * `daily_run` records the outcome in the log line and counts a failed or
    partial delivery as a stage error.

### Verification

9 new tests in `tests/test_telegram_partial_delivery.py`; 6 mutations, all 6
red — including one that reports a partial send as a total failure, and one
that lets the bool wrapper call a partial send successful. Suite 1654 passed,
1 skipped. Evidence: `repro/repro_partial_telegram.py`.

### What this does NOT claim

No trading number changes. Like the two findings before it, this only removes
ways the forward test could stop reporting without saying so.

---

## The live log, measured (2026-08-17) — the tested strategy has never been run

Not a new hypothesis. This is the standing complaint — *"it kept telling me to
hold, but I ended up with less than 1k IDR profit, or -5%"* — answered from the
25 closed trades in `paper_state.json` rather than from theory.

### Payoff

```
avg win / avg loss    +3.97% / -4.81%     payoff 0.82
win rate              56.0%
break-even win rate   54.8%               margin +1.2 pts
expectancy            +0.105% per trade over 25 trades
```

The payoff being below 1.0 is not the problem by itself; it just sets the win
rate the system has to clear. 56.0% against a 54.8% requirement is a **+1.2
point margin over 25 trades** — inside the noise. The honest description is
break-even, not "slightly profitable". +0.105% per trade on a few million
rupiah is the "less than 1k IDR" in the complaint, exactly.

Best trade +8.39%, worst -5.47%, against `target_profit_pct=8` and
`hard_stop_pct=-5`. Every close is logged `"manual sell"`, so the ladder is
being executed by hand rather than by the engine — but it is still the ladder
setting the bounds.

### Horizon

```
median hold 7 d      longest 29 d      reached 60 bars: 0 of 23
```

**Not one trade reached the horizon the strategy was validated at.** 19 of 23
closed inside 14 days. Against the *legacy* profile's 20-bar limit it is 3 of
23; against `forward_test`'s 60 bars it is zero. Either way, whatever these
trades measure, it is not the configuration the sweeps validated.

This is a fact about the log, not a statistical claim, and it is the cleanest
statement of the gap: the strategy that was tested has never actually been run.

### The gradient, and why it is NOT the finding

```
bucket         n      mean    median
0-7 d         12    -0.36%    -2.25%
8-14 d         7     0.60%     0.40%
15-30 d        4     3.19%     1.91%
```

Monotone, and it agrees with the OOS result that the exit ladder subtracts
value. It is still **not independent evidence for it.** A stop-loss closes
losers early by construction, so the longer buckets are pre-selected for
trades that never hit the stop — a rising gradient is what that mechanism
produces on its own, on any data, edge or no edge. Four trades in the top
bucket besides.

The caveat is printed beside the table in `discipline_report.py` and pinned by
a test, so it cannot get separated from the numbers later.

### Where it lives

`payoff_arithmetic()` and `holding_horizon_gap()` in `kala/discipline.py`,
printed by `discipline_report.py`. Both computed from the log alone, so they
run offline and do not need `--counterfactual`'s network. `rule_days` follows
the live `exit_profile`, so the comparison is always against the rule actually
in force.

Tests: `tests/test_payoff_and_horizon.py` (12 new); 8 mutations, all 8 red —
including one that drops the selection caveat and one that hardcodes the
break-even rate to 50%. Suite 1666 passed, 1 skipped.

---

## ATR fallback, named (2026-08-17) — the volatility stop is not running on any live position

Follow-on from the live-log measurement. All 9 open positions in
`paper_state.json` carry `entry_atr=None`.

### What that means, and what it does not

`governing_stop` falls back to the hard floor when ATR is missing:

```
have_atr:  atr_stop = entry - atr_stop_multiple * ATR   (2 x ATR by default)
no ATR:    atr_stop = hard                              (-5% by default)
base    =  max(atr_stop, hard)
```

The fallback is safe, deliberate and documented. It is also **not the rule the
strategy specifies**: the phase-1 stop is supposed to scale with the name's own
volatility — tighter than the floor on a quiet stock, identical to it on a
volatile one. Every live position is on the floor.

Sizing is not affected: `size_position` takes its stop from
`governing_stop(price, price, atr_val, …)` at BUY time, where `atr_val` comes
from the scanner signal. Only the ongoing exit management of already-open
positions loses the ATR stop, which is why this went unnoticed.

### The reporting defect

The label was `"fixed/atr stop"` for all three phase-1 outcomes: ATR stop
governing, hard floor overriding a wider ATR stop, and no ATR at all. One
string for three rules, so a position on the fallback was indistinguishable
from one whose ATR stop simply happened to be tighter. There was also no
book-level count, so "all 9" was invisible without inspecting each position.

Now:

```
atr stop                          the volatility stop is governing
hard stop (floor; atr stop was wider)   ATR existed, floor won
hard stop (NO ATR — fallback)     no ATR; this is the fallback
```

plus `atr_coverage()` in `discipline.py`, printed by `discipline_report.py`:

```
open positions 9   without entry_atr: 9 (100%)
AADI.JK, AUTO.JK, BSML.JK, CASS.JK, ICBP.JK, INDF.JK, KBLI.JK, SRTG.JK, STAA.JK
```

`entry_atr` is recorded for new positions from v4.4; the existing 9 keep None
until they close. No backfill is attempted — reconstructing ATR as of each
entry date would need historical data this session cannot reach, and a
guessed value in a risk field is worse than an honest gap.

### Verification

13 new tests in `tests/test_atr_fallback_is_named.py`; 6 mutations, all 6 red —
including one that collapses the three labels back to a single string and one
that lets a phase-1 label overwrite the trailing labels. Suite 1679 passed,
1 skipped. No stop level changed; only what the stop is called and whether the
book-level gap is counted.

---

## Exit-profile comparison on cached data (2026-08-17) — the flag works, and the direction holds

Yahoo is unreachable from this session (proxy 403), so the two full-universe
walk-forwards still need to be run locally. But `results/price_cache/` holds 71
pickles — 64 with >= 800 bars, spanning 2020-03 to 2026-08 — plus `^JKSE`. That
is enough to answer two questions before paying for a long download.

### 1. Is `--exit-profile` inert?

No. It reaches the engine, and the trade sets differ substantially. This
mattered because the flag once passed its unit tests while `main()` ignored it
entirely — a full-universe download spent on an inert flag is the expensive
version of that mistake.

### 2. Walk-forward, 64 cached tickers, 19 folds

```
                    trades   EXCESS/trade   plain t   clustered t   DSR P(>0)
legacy                3423        +0.286%     +1.84         +1.64       0.705
forward_test          1077        +6.596%     +3.44         +3.46       0.984
```

### The correction that per-trade numbers need

+6.6% against +0.29% is a 23x ratio and it is NOT the honest comparison:
`forward_test` holds roughly four times as long, and per-trade EV mechanically
rewards longer holds. Measured properly on the same 64 tickers (full-history
in-sample backtest, run separately to get real entry->exit dates):

```
profile         trades  mean hold   EV/trade   EV/day held   trade-days
legacy            4764      12.1 d     0.514%       0.0425%      57,608
forward_test      1198      47.2 d     7.926%       0.1680%      56,520
```

Trade-days match within 2%, so capital-time is comparable. Normalised that way
the advantage is **~4x, not ~15x**. Still a large gap, and in the same
direction as the 2026-08-13 exit-ladder sweep, which is the point.

### What this is NOT

  * **Not a universe result.** The cache holds whatever past runs happened to
    fetch — open positions, watchlist names, scan candidates. 64 of 615, and
    selected by past interest.
  * **Survivorship-exposed.** Every cached name exists today. The magnitude is
    inflated by an unquantified amount; only the full run with the same
    liquidity split can bound it.
  * **Not a portfolio.** `walk_forward` pools trades. It does not model capital
    constraints or overlapping positions, so 1077 trades at +6.6% is not a
    return anyone could have earned.
  * The per-day table is **in-sample**, used only to normalise the holding-length
    artefact — not as an edge estimate.

The full-universe run remains the measurement. What changed is that it is now
worth running: the flag works, and the direction on data already on disk agrees
with the sweep.

### A note on how this nearly went wrong

The first run of `compare_exit_profiles_cached.py` printed a perfectly aligned
table of `+nan%` in every EV cell. The cause was `.get(key, float("nan"))` with
the wrong key names — `trade_stats` returns `ev_pct`/`t_stat`, not `mean`/`t`.
A broken script read as a measurement that had come back empty. The script now
uses `_need()`, which raises and names the keys that ARE present. That is the
fourth time this session a green- or plausible-looking result came from a check
that could not fail.

Tests: `tests/test_cached_profile_comparison.py` (6 new); 3 mutations, all 3
red. Suite 1685 passed, 1 skipped.

---

## Liquidity split on the cached comparison (2026-08-17) — the gap survives, at a smaller size

The one objection the cached run could not answer was survivorship. It can be
attacked partially with the same discriminator the entry-score work used:
split by median daily turnover and look at both halves. Large, liquid names
rarely delist, so their survivorship exposure is low; thin names carry most of
it.

```
  half      profile             n   excess%  clust t    DSR
  LIQUID    legacy           1615    +0.024    +0.11  0.118
  LIQUID    forward_test      561    +2.666    +2.68  0.902
  ILLIQUID  legacy           1775    +0.649    +2.66  0.930
  ILLIQUID  forward_test      545   +10.420    +2.87  0.940

  gap (forward_test - legacy):  LIQUID +2.642 pts   ILLIQUID +9.771 pts
```

### What this establishes

The gap is present in the LIQUID half — +2.64 pts, clustered t +2.68, DSR
0.902 — where survivorship exposure is low. So survivorship is not what
PRODUCES the gap. That is the same shape as the 2026-08-16 finding for the
entry score, reached independently for the exit profile.

The ladder itself earns nothing in liquid names: `legacy` excess +0.024% with
clustered t +0.11 and DSR 0.118. That is as close to exactly zero as this kind
of measurement gets.

### What it revises, downward

The headline +6.3 pts from the full cached sample is **inflated**. The gap is
3.7x larger in the illiquid half (+9.77 vs +2.64), and the conservative read is
the liquid number: **~+2.6 pts/trade, not ~+6.3**. Two mechanisms could produce
that spread and this data cannot separate them:

  * survivorship, which is concentrated exactly there; and
  * a genuine illiquidity/small-cap premium, which would be real but largely
    untradeable under the ADV cap the paper trader already enforces.

Either way the liquid half is the number to plan against, and it is the half
that is actually tradeable at size.

### Still not a universe result

64 selected tickers. The split narrows the survivorship objection; it does not
close it, and it does not bound the bias's magnitude. The full-universe run
with the same split remains the measurement.

### A tautological test, caught by mutation

The first two tests for the split reimplemented the turnover ranking inline
instead of calling the script's code, so they tested a copy of the logic rather
than the logic. Both mutations — ranking by price instead of turnover, and
letting a volume-less frame crash the run — SURVIVED. The ranking is now
`rank_by_turnover()` in the script and the tests call it; all four mutations
now go red, including one that sorts ascending and silently swaps the two
halves. Fifth instance this session of a check that could not fail.

Tests: `tests/test_cached_profile_comparison.py` (9 total, 3 new); 4 mutations,
all 4 red.

---

## Holding-period sweep on cached data (2026-08-17) — a hump, not a cliff

`forward_test` (60 bars) beats `legacy` (20). That said nothing about whether
60 is right. Sweeping the horizon with all exit rules off, 64 cached tickers,
19 folds:

```
  bars  trades   excess%  clust t    DSR   ex/day
    10    2996    +0.851    +2.90  0.980   0.0851
    20    1908    +1.843    +3.82  0.998   0.0922
    30    1507    +3.172    +3.64  0.990   0.1057
    45    1194    +5.400    +3.40  0.978   0.1200
    60    1077    +6.596    +3.46  0.984   0.1099
    90     954    +8.339    +3.60  0.987   0.0927
   120     958    +9.958    +3.58  0.988   0.0830
```

### Reading the two columns

Excess PER TRADE rises monotonically, 0.85 -> 9.96. That is close to mechanical:
hold longer, accumulate more. It cannot say which horizon is efficient, and
quoting it alone would overstate the long end badly.

Excess PER DAY HELD divides that out and is a smooth hump — 0.085 at 10 bars,
peaking 0.120 near 45, back to 0.083 at 120. Capital-time efficiency is best
somewhere in the 30-60 band.

### What is actually established

**Every one of the seven horizons is positive, with clustered t between +2.90
and +3.82.** That is the finding. The effect does not depend on picking a
horizon; it is present across a 12x range of them.

**The peak is NOT a finding.** Taking the argmax of a 7-point sweep on one
sample is a best-of-N pick — precisely what deflated Sharpe exists to discount,
and what sixteen previous hypotheses in this file were rejected for resembling.
"45 is optimal" is not supported. "The 30-60 band is where capital-time
efficiency sits, and anything in it beats 20" is.

Beyond ~90 bars the trade count stops falling (954 -> 958), so the holding cap
is rarely the binding exit any more and the last two rows are nearly the same
trade set.

### Against the live book

The legacy profile caps at 20 bars, which is already the weakest positive row.
The live log's MEDIAN hold is 7 days — below the shortest horizon tested here.
That is the gap, stated in the units of this table.

### Same caveats as everything cached

64 selected tickers, all currently listed, pooled trades rather than a
portfolio. The liquidity split above suggests the magnitudes are inflated;
the SHAPE is what this table is for.

`compare_exit_profiles_cached.py --sweep-holding 10 20 30 45 60 90 120`.
The script refuses to read a shape from fewer than 3 points and prints the
best-of-N caveat next to the peak, pinned by tests.

---

## FULL-UNIVERSE EXIT-PROFILE COMPARISON (2026-08-17) — the standing verdict was measuring the ladder

The decisive run. 569 usable tickers of 615 requested, 5y, 14 walk-forward
folds, tick-floored spreads, `--min-price 0`. Same universe, same folds, same
signal in both; the substantive difference is the exit rules.

```
                    trades   EXCESS/trade   clustered t     DSR   verdict
legacy              18,931        -0.45%         -3.79   0.000   NO OOS EDGE
forward_test         5,945        +4.70%         +5.09   1.000   EDGE CONFIRMED
```

### What this retires

`PROJECT_STATUS` has said "no demonstrated out-of-sample edge" for the life of
this project. **That verdict was measured through the exit ladder**, and the
ladder is not neutral: on its own it is significantly NEGATIVE, clustered
t = -3.79, negative in 12 of 14 folds. Sixteen hypotheses were rejected while
the harness that judged them carried a value-destroying exit rule. That does
not resurrect those sixteen — each was tested on its own merits — but it does
mean the composite score's own rejection was not a clean read.

### What is strongly established

**The ladder destroys value.** 12 of 14 folds negative, clustered t -3.79,
DSR 0.000, on 18,931 trades. This is not a noisy zero; it is reliable damage,
and it agrees with the 2026-08-13 sweep (32 of 32 cells negative) and the
cached comparison reached independently.

### What is real but FRAGILE

The positive result is concentrated. Per-fold P&L contribution:

```
  fold 10   n=542   EV=+36.49%   +76.4% of all pooled P&L
  fold  9   n=558   EV=+15.28%   +32.9%
  fold  6   n=558   EV=+10.03%   +21.6%
  ------------------------------------------
  best three folds             +131.0%
  the other eleven folds        -31.0%
  folds with negative EV:  7 of 14
```

One quarter carries three quarters of the profit. The pooled t is honest
arithmetic over 5,945 trades, but pooling hides that this is a regime bet
rather than a steady process, and the next regime is not in the sample.

### Two things that should temper any decision

**The two most recent folds are the two worst.** Fold 12 (2026-01..2026-05)
-9.29%, fold 13 (2026-05..2026-07) -11.56%, against IHSG -22.3% and -12.6%.
A forward test started now begins immediately after the worst evidence in the
sample.

**Win rate 27%, median trade -6.25%.** Three of every four trades lose; the
expectancy comes from a minority of large winners. The live log shows 26
closes, 100% of them manual, median hold 8 days. Running this configuration
means holding three losers for every winner, and the operator has never once
done that.

### A correction to how the two are compared

The profiles differ in the exit rules AND in the fixed baseline threshold
(60 vs 80). Compare the "walk-forward threshold" lines, not the "fixed
baseline" lines: the walk-forward threshold is chosen per fold from TRAIN data
in both runs and both mostly selected 75, which leaves the exit rules as the
substantive difference. The cached holding sweep (all exits off, horizon swept
10-120 bars, every horizon positive) supports the same attribution
independently.

### Still not bounded

Survivorship. The universe is CURRENT index membership; 183 of 615 tickers had
history too short for 5y. The cached liquidity split suggested the gap survives
among liquid names (+2.9 pts, clustered t +3.00) where delisting exposure is
low, but that was 67 selected tickers. The full-universe liquidity split has
not been run.

### Next

`diagnose_exit_param_sweep.py --split-liquidity` on the full universe is the
remaining check. Nothing else in the data can narrow survivorship further.

Reproduce the fold arithmetic: `python repro/fold_concentration.py`.

---

## FULL-UNIVERSE LIQUIDITY SPLIT (2026-08-17) — survivorship does not produce the result

The last check the data could answer. 569 usable tickers split by median daily
turnover, threshold swept with all exit rules OFF and a 60-bar hold.

```
half      thr   win%  payoff  BE win%   margin   exEV%   ex_t      n
LIQUID      0   33.8    1.90     34.5     -0.7  +0.124  +0.33   7355
LIQUID     40   30.1    2.75     26.7     +3.4  +1.127  +2.61   5387
LIQUID     60   30.6    3.13     24.2     +6.4  +2.039  +3.70   3779
LIQUID     80   34.1    2.94     25.4     +8.7  +2.900  +4.31   2874
ILLIQUID    0   27.8    2.50     28.6     -0.8  +0.048  +0.12   8546
ILLIQUID   40   23.1    3.63     21.6     +1.5  +0.537  +1.12   6731
ILLIQUID   60   27.2    3.79     20.9     +6.3  +2.509  +3.26   4109
ILLIQUID   80   32.4    3.44     22.5     +9.9  +4.563  +3.76   2772
```

### Three findings, in order of how hard each is to dismiss

**1. Universe drift is ruled out.** The threshold-0 control is indistinguishable
from zero in BOTH halves: +0.124% (t +0.33) and +0.048% (t +0.12), with
break-even margins of -0.7 and -0.8 points. If the result were "IDX sharia
names rose over five years", that row would be positive. It is not.

**2. Dose-response, monotone, in both halves.** 0 -> 40 -> 60 -> 80 rises in
six columns simultaneously — EV, excess EV, t, payoff-implied margin, and win
rate at the top end. A best-of-N pick does not produce a monotone ladder in
two independent subsamples.

**3. The LIQUID half is statistically STRONGER.** t +4.31 vs +3.76 at
threshold 80. Survivorship is concentrated in names that could have been
delisted — the thin end — so if the bias produced this result it would be
strong there and weak among large liquid names. The opposite is observed.

### The conservative number

Magnitude is larger in the illiquid half (+4.563 vs +2.900). Two mechanisms
could do that and this data cannot separate them: survivorship inflation, or a
genuine illiquidity premium that the ADV cap would prevent trading at size.
Either way the number to plan against is the LIQUID half: **+2.90 pts/trade at
threshold 80, clustered t +4.31**, and that is the half that is tradeable.

For scale, the live book's own margin is +1.5 points over 26 trades. This is
+8.7 points over 2,874.

### What it still does NOT settle

Every name in BOTH halves is a survivor — the universe is current index
membership. The split tests whether the effect CONCENTRATES where delisting
risk was highest; it does not remove survivorship from either half, and it
cannot. A name that is liquid today may have been thin five years ago.

The fold concentration from the walk-forward also still stands: these are
pooled OOS trades over the same 14 folds, so the same three windows dominate.

### Where this leaves the project

Established, in order:

  * the exit ladder destroys value — 12 of 14 folds negative, clustered
    t -3.79 on 18,931 trades;
  * the entry score selects — monotone dose-response in two liquidity halves,
    with a clean zero control;
  * it is not survivorship — present and stronger in the low-exposure half;
  * it is not universe drift — threshold 0 is zero;
  * it is not benchmark exposure — every figure above is excess.

Not established:

  * that it is steady. One fold carries 76% of the walk-forward P&L, 7 of 14
    folds are negative, and the two most recent are the two worst.
  * that it is executable. Win rate 30-34%, median trade negative. The live
    log shows 26 closes, 100% manual, median hold 8 days.
  * that it persists out of this 5-year window. Only a forward test answers
    that, and by construction it cannot be run faster than real time.

---

## What the ladder does to all sixteen verdicts (2026-08-17)

The uncomfortable consequence of the exit-profile result, stated plainly
because the alternative is leaving sixteen confident rejections standing on a
foundation now known to be tilted.

### The mechanism

Every hypothesis in this file was validated through the same harness, and that
harness applied the exit ladder to the STRATEGY side only. The alpha check
compares each trade against the benchmark held over that trade's own window —
buy-and-hold, no stop, no target, no trailing. So the ladder's cost was
subtracted from the strategy and from nothing else.

Measured size of that cost: -0.45%/trade excess on the composite, and the
control-vs-best-cell gap in the 2026-08-13 sweep was 1.599 points.

### What that does and does not mean

It does NOT resurrect any of the sixteen. Each was tested on its own merits,
several with real statistical power, and a handicap does not turn a null into
a finding.

It DOES mean none of them is a clean read. The rejections most affected are
the ones whose measured effect is of the same order as the handicap:

```
hypothesis                       reported verdict            reported t
mean-reversion                   actively negative           ~ -3.9
support/resistance               actively negative, powered   -3.52 / -3.40
dividend yield                   negative, real power         -2.75 / -2.56
multi-horizon trend (naive)      negative                     -2.66 / -2.50
low volatility                   confidently negative both    (see section)
```

A signal measured at -3 through a harness that itself scores -3.79 on the same
universe is not distinguishable from a signal that is merely flat. That is not
a claim any of them is positive; it is a statement that the file currently
reports more confidence than the measurements support.

### What would settle it, cheaply

The warehouse is now fully populated, so re-running these costs no downloads:

```
python run_walkforward.py --max-tickers 615 --period 5y --tick-spread \
  --warehouse results/warehouse.db --min-price 0 --trust-short-cache \
  --exit-profile forward_test --strategy mean_reversion
```

and the same for `support_resistance`, `dividend_yield`,
`multihorizon_trend`, `low_volatility`. Five runs, same universe, same folds,
only the exit rules changed.

Predicted outcome, recorded BEFORE running so it can be wrong: most should
move upward by roughly the ladder's cost and land near zero rather than
turning positive, because the composite score's dose-response is what
distinguishes it and these signals showed no such ladder. If one of them
instead turns strongly positive, that is a new finding and it should be
treated with the same suspicion this file has applied to every other
promising raw number.

### Status of the table above

Left in place, with the correction banner at the top of SUMMARY pointing here.
Rewriting sixteen verdicts on the basis of an inference rather than a re-run
would be exactly the kind of unearned confidence this file exists to prevent.
They are marked as measured-through-the-ladder, not as overturned.

---

## The re-run instruction was wrong, and mean_reversion is now open (2026-08-17)

### The defect in the command

`--exit-profile forward_test` sets `score_entry_threshold = 80`, and
`walk_forward_strategy` documents that an explicit `cfg` overrides the
strategy's own `default_threshold` — "used exactly as given, no magic". So the
FIXED BASELINE arm ran every strategy at 80, a number from the composite
score's scale:

```
strategy              own default   own grid    forced to
mean_reversion             60        40-80         80   top of grid
support_resistance         50        20-60         80   OUTSIDE the grid
dividend_yield             50        30-70         80   OUTSIDE the grid
low_volatility             60        40-80         80   top of grid
multihorizon_trend         60        20-90         80   inside
```

`_edge_verdict` is computed from that arm (`pooled_excess_baseline`), and
computing it there is CORRECT — judging on the per-fold chosen threshold is
the multiple-testing trap. The error was the threshold, not the choice of arm.
For support_resistance and dividend_yield the baseline sat above the entire
grid, so it would have traded almost nothing and printed a verdict about
nothing.

The four remaining re-runs were stopped before being run.

### What mean_reversion actually returned

```
                                    n     excess EV    plain t   clustered t
walk-forward threshold (40-80)   8800       +2.09%      +4.33        +3.58
fixed baseline 80                4766       -0.01%      -0.01            -
```
DSR 0.999. Printed verdict: NO OOS EDGE — computed from the baseline row.

**The prediction recorded in "What the ladder does to all sixteen verdicts"
was wrong.** It said most should "land near zero rather than turning
positive". On the walk-forward arm mean_reversion turned positive and
significant. Recording that plainly is the whole point of having written the
prediction down first.

### Why this is NOT yet a finding

Its chosen threshold is UNSTABLE across folds — 60, 60, 60, 60, 70, 80, 60,
60, 60, 60, 40, 50, 60, 40. The composite score chose 75 in 13 of 14 folds.
A signal whose optimal threshold wanders across its whole grid every quarter
is the signature of fitting noise in the train window, and the deflated Sharpe
deflates for the thresholds tried WITHIN a fold, not for that instability
ACROSS folds.

So mean_reversion is not "positive". It is **open**, and its earlier
"actively negative" verdict is withdrawn as unclean rather than replaced.

### The fix

  * `build_run_config(..., baseline_threshold=...)`, and `run_walkforward.py`
    defaults it to `strategy.default_threshold` for any strategy other than
    momentum. Momentum is unchanged, so no historical number moves.
  * `--baseline-threshold` exposes it explicitly.
  * Every run now prints which arm the verdict comes from, the strategy's own
    default and grid, and a WARNING when the baseline falls outside the grid.

Tests: `tests/test_baseline_threshold_scale.py` (7 new, parametrised over the
registered strategies); 4 mutations, all 4 red. Suite 1751 passed, 2 skipped.

### The corrected re-run command

```
python run_walkforward.py --max-tickers 615 --period 5y --tick-spread \
  --warehouse results/warehouse.db --min-price 0 --trust-short-cache \
  --exit-profile forward_test --strategy mean_reversion
```

Identical text — the fix is in the default, not the invocation — but the
baseline arm now runs at 60 for mean_reversion, 50 for support_resistance and
dividend_yield, and the header states which threshold the verdict used.

---

## mean_reversion re-tested at its own baseline (2026-08-17) — and a problem with BOTH results

### The result

```
                                    n     excess EV    plain t   clustered t
walk-forward threshold (40-80)   8800       +2.09%      +4.33        +3.58
fixed baseline 60                8858       +1.84%      +3.99            -
```
DSR 0.999. VERDICT: EDGE CONFIRMED OOS, on both arms.

Its previously recorded verdict was "actively negative, t ~= -3.9". The swing
is roughly 8 t-units and is entirely attributable to removing the exit ladder.
That confirms, by direct measurement rather than inference, the claim made in
"What the ladder does to all sixteen verdicts".

**The threshold-instability objection is withdrawn.** It applied to the
walk-forward arm, where the chosen threshold wanders 40-80 fold to fold. The
FIXED baseline arm selects no threshold at all — there is nothing to deflate —
and it returns +1.84% excess at t 3.99 on 8,858 trades. A pre-specified
threshold, set when the strategy was written, is not a multiple-testing
artefact.

### The problem, which applies to the composite result too

Momentum and mean-reversion are near-opposite signals: one buys what has
risen, the other buys what has fallen. Their per-fold EV over the same 14
folds, same universe, same exit profile:

```
correlation of per-fold EV        +0.857
sign agreement                     14 of 14 folds
```

Two opposite selections do not agree in sign fourteen times out of fourteen if
each is capturing its own distinct stock-selection edge. **They are not two
independent confirmations; they are close to one observation.**

### What that does and does not imply

It is NOT explained by market exposure: every excess figure is already
benchmark-subtracted per trade, over each trade's own window.

It is NOT explained by "any basket held 60 days beats the index": the
threshold-0 control is flat in both liquidity halves — +0.124% (t +0.33) and
+0.048% (t +0.12). Random selection from this universe earns nothing. So the
selection is doing something.

The remaining reading is that both selections, despite opposite stated logic,
tilt toward the same underlying characteristic — plausibly high volatility or
small size — which had a good five years. That would make one factor, not two
edges, and it would mean the composite's +2.90 pts in the liquid half is a
tilt this project has not identified rather than skill it has demonstrated.

### The diagnostic that would settle it

Ticker overlap between the two selections, fold by fold. If the momentum-80
basket and the mean_reversion-60 basket share most of their names, that is the
answer. If they are largely disjoint yet still move together, the common
factor is something else and worth naming before any of this is traded.

A second, cheaper check: the remaining four strategies. If low_volatility,
dividend_yield, support_resistance and multihorizon_trend ALSO come back
positive with the same fold shape, that is the common factor showing itself
five more times — not five more edges. **Recorded before running, so it can be
wrong.**

### Status

`mean_reversion`: its "actively negative" verdict is overturned, not merely
withdrawn — it is positive at a pre-specified threshold with real power.

The composite result and this one are now BOTH conditional on the common-factor
question. Neither should be traded until it is answered.

---

## All four re-runs positive — and a false alarm I raised, corrected (2026-08-17)

### The results

Every strategy re-tested without the exit ladder, at its own baseline:

```
strategy              baseline   n(base)  excess EV(base)   plain t   clustered t   verdict
momentum                    80     5,259          +5.44%      6.27         5.09    CONFIRMED
mean_reversion              60     8,858          +1.84%      3.99         3.58    CONFIRMED
low_volatility              60    10,926          +0.35%      1.16         2.28    WEAK
dividend_yield              50     2,760          +1.51%      3.31         3.12    CONFIRMED
support_resistance          50     4,828          +4.23%      5.96         5.23    CONFIRMED
multihorizon_trend          60     9,741          +3.09%      5.84         4.51    CONFIRMED
```

Five confirmed, one weak. Every previously "actively negative" verdict is
overturned. The prediction recorded before running — that most would land near
zero — was wrong for the second time; they landed positive.

### The alarm I raised, and why it was wrong

I computed the correlation of PER-FOLD EV between strategies, found +0.857 to
+0.965, and concluded that six signals could not all be edges and something
common was producing them.

**That was the wrong quantity.** The fold table's `EV/trade` column is the RAW
per-trade return. Two long-only baskets drawn from the same universe rise
together when the index rises, so their raw fold returns correlate strongly
whether or not either has an edge. Correlating them measures the market. Each
strategy's own correlation with IHSG (+0.55 to +0.75) was sitting in the same
table and should have told me.

The overlap diagnostic then contradicted the story outright:

```
                                    TOP baskets   BOTTOM baskets
random baseline                           0.133            0.133
mean_reversion / momentum                 0.021            0.021
mean_reversion / multihorizon_trend       0.007            0.037
MEAN over all pairs                       0.161            0.191
```

momentum and mean_reversion pick almost disjoint baskets — BELOW the random
baseline, as two opposite signals should — and their bottom baskets are equally
disjoint, which also kills the "they share what they avoid" version. Neither
shared selection nor shared exclusion is happening.

### What is actually still open

Whether the EXCESS returns share a common factor is **not answered by any
output produced so far**, because per-fold excess was never printed — only the
pooled figure. The data existed in `FoldResult.oos_excess_chosen` and was
discarded at the formatting step.

The fold table now prints an `excess%` column, so the correlation can be
computed on the right quantity. Until someone does that, the honest position is
that the common-factor question is UNTESTED, not answered either way — and my
earlier statement that these are "one observation measured six times" is
withdrawn as unsupported.

### What this run does establish

  * Every one of the six is positive at a pre-specified threshold, OOS,
    benchmark-adjusted, with the ladder removed. That is a real and large
    change from the file's previous verdicts.
  * The selections are genuinely different — verified, not assumed.
  * The exit ladder was penalising all of them, which was the claim made
    earlier by inference and is now measured six times.

Still unresolved: fold concentration (every strategy has its best folds in
mid-2025 and its worst in early-2026), survivorship beyond the liquidity split,
and whether these six are independent once measured on excess.

Tools: `diagnose_selection_overlap.py` (`--bottom` for the exclusion variant).
Tests: 2 new in `tests/test_baseline_threshold_scale.py`; both mutations red.
Suite 1753 passed, 2 skipped.

---

## Per-fold excess, at last (2026-08-17) — the edge is REGIME-CONDITIONAL

The fold table now prints excess, so the question that could not be answered
before can be. `mean_reversion`, 14 folds, forward_test profile:

```
korelasi RAW    vs IHSG : +0.685
korelasi EXCESS vs IHSG : +0.477
```

Benchmark subtraction removes some market exposure and **not all of it**. If
this were pure stock selection the excess would be roughly uncorrelated with
the index. It is not.

### The number that matters

```
                          mean excess    folds
market DOWN (IHSG < 0)         -0.16%        7
market UP                      +4.93%        7
```

**The excess is zero when the market falls and large when it rises.** The
pooled +1.80% is the average of "nothing in a decline" and "a lot in a rally".

Against the tidy version of that story: the two WORST market quarters were
positive — fold 12 (IHSG -22.3%) excess +4.24%, fold 8 (IHSG -11.5%) excess
+3.35%. What drags the down-market average is fold 13 (-6.67%) and fold 0
(-2.75%). So in falling markets the signal is not dead, it is NOISY: sometimes
strongly positive, sometimes strongly negative, averaging nothing.

Concentration survives into the excess column: best fold 40.7% of pooled excess
P&L, best three 102%, the other eleven net negative.

### Why this is the answer to the original question

The complaint that opened this work was that the system cannot tell when to
buy, hold or sell. At the trade level that turned out to be the exit ladder.
At the PORTFOLIO level the answer is now visible: the signal works, but its
payoff is conditional on the market regime, and nothing in the system tells
you which regime you are in before the fact.

Two of the last three folds in the sample are falling markets. A forward test
started now, in a declining market, should expect approximately nothing — and
that is a prediction, recorded so it can be wrong.

### The obvious next test

`momentum + ADX regime gate` is already in the file, rejected as "no OOS edge
(underpowered)" — measured THROUGH the ladder, like everything else. The
regime classifier exists (`kala/regime.py`). Re-running the gated variant
without the ladder is the direct test of whether conditioning on regime
converts a conditional edge into a usable one.

If it does not, the honest conclusion is that this system finds stocks well in
rising markets and has no way to know when those are — which is a real finding
and a much weaker one than "EDGE CONFIRMED" reads on its own.

### Caveat on the numbers above

These come from a run whose warehouse had been refreshed by the intervening
`low_volatility` and `dividend_yield` runs: n = 8,891 versus 8,858 in the
earlier `mean_reversion` run, pooled excess +1.80% versus +1.84%, and fold
boundaries shifted by a day. Small, but it means results in this file are not
byte-reproducible across sessions unless the warehouse is pinned.

## Two "different" strategies, one edge (2026-08-19) — the alarm re-established on the right column

Momentum and mean_reversion were re-run with `--save-folds`, on identical fold
calendars, and compared mechanically instead of by eye:

```
strategy              profile        base  folds  tickers
momentum              forward_test     80     14      615
mean_reversion        forward_test     60     14      615

pair                                        RAW corr  EXCESS corr
momentum / mean_reversion                     +0.866       +0.803
```

**Subtracting the benchmark barely moved it: 0.866 -> 0.803.**

That is the finding. A high RAW correlation between two long-only baskets is
mechanical — both are long the same market — which is exactly why the first
version of this alarm was withdrawn. The EXCESS column is the one that can
carry the claim, and it carries it: after the market is removed, two strategies
that are near-opposites by construction still move together at 0.80.

### Why that is strange

These are not two views of the same idea. Their selections were measured
directly (`diagnose_selection_overlap.py`):

| pair | mean Jaccard | vs random |
|---|---|---|
| momentum / mean_reversion | 0.021 | 0.2x |
| (random baseline for top-15 of 240) | 0.133 | 1.0x |

They overlap *less* than two random picks would. Momentum buys what has been
rising; mean_reversion buys what has fallen. They hold different stocks, in
different quarters, for different reasons — and their excess returns correlate
at 0.80.

Near-disjoint holdings with strongly correlated residual returns means the
residual is not coming from the holdings. Something common to both is doing
the work.

### What it costs, practically

Running momentum and mean_reversion together is **not diversification**. Split
a book in half between two strategies whose excess correlates at rho, and the
combined volatility relative to putting it all in one is `sqrt((1+rho)/2)`:

| rho | variance vs one position | volatility vs one position |
|---|---|---|
| 0.00 (truly independent) | 0.50 | 0.71 |
| 0.50 | 0.75 | 0.87 |
| **0.803 (measured)** | **0.90** | **0.95** |
| 1.00 (same bet twice) | 1.00 | 1.00 |

At 0.803 the split buys a 5% reduction in volatility, against the 29% that two
independent edges would give. That is a rounding error away from holding one
position, for the same expected return and twice the operational surface. Any
plan that sizes these as independent bets is sizing on a number that is not
true.

This also cuts the evidence base. Six strategies all going positive once the
exit ladder was removed read as six confirmations. If they share a common
driver, that is closer to **one** observation measured six times — and the
deflated Sharpe of 1.000, which discounts for multiple testing across
thresholds, does not discount for this at all.

### The leading hypothesis, and it has NOT been tested

**The benchmark is probably wrong.** IHSG is cap-weighted and bank-heavy. These
baskets are equal-weighted and sharia-screened, so banks are excluded *by
construction*. Subtracting IHSG from any sharia basket therefore leaves a
systematic residual — the sharia-vs-conventional sector tilt, plus a
small-cap-vs-large-cap tilt from equal weighting — and every strategy in this
system would inherit the same residual regardless of what it picks.

If that is the explanation, then "excess vs IHSG" has been measuring the
sharia screen and the weighting scheme, not stock selection, in every result
in this file.

The discriminating test:

```
python run_walkforward.py --max-tickers 615 --period 5y --tick-spread \
  --warehouse results/warehouse.db --min-price 0 --trust-short-cache \
  --exit-profile forward_test --strategy momentum \
  --benchmark XIJI.JK --save-folds results/f_mom_xiji.json
```

...and the same for mean_reversion, then `compare_folds.py` on the pair.

**Recorded prediction, so it can be wrong:** against XIJI.JK the excess
correlation drops below 0.5, and both strategies' pooled excess falls
substantially — most of what is now called alpha is the sharia screen plus
equal weighting, not selection. If instead the correlation stays near 0.80,
the shared driver is something else and must be named before any of this is
sized.

### The honest order of events

The first version of this alarm (2026-08-17) reached the right conclusion from
the wrong evidence — it correlated the RAW column, where +0.86 is expected
whether or not either strategy has an edge. Withdrawing it was correct;
evidence that does not support a claim is not evidence, even when the claim
happens to be true. What is written above stands on the excess column, and the
tooling that made the difference (`--save-folds`, `compare_folds.py`) exists
precisely because the first attempt was done by reading pasted terminal output.

## Finding 8 (2026-08-19) — the alpha check could be skipped silently

Found while preparing the `--benchmark XIJI.JK` run proposed in the section
above. The proposed command exposed a bug in the harness that would have
scored it.

`--benchmark` accepts any string; nothing validates it. With a ticker that
does not resolve, `run_walkforward.py` warned on **stderr** and carried on,
and `summary_text()` dropped the whole ALPHA CHECK block (gated on
`pooled_excess_baseline["n"] > 0`, no else branch). stdout showed:

```
VERDICT: EDGE CONFIRMED OOS — positive EV, statistically distinguishable from 0.
```

and stopped there.

Every result in this file was captured by redirecting stdout to a log. The
stderr warning would not have been in any of them. What would have been saved
is a confident verdict with no indication that the measurement distinguishing
alpha from beta never ran.

This is the eighth finding with the same shape, and the most consequential,
because it sits on the harness that produced all the others. A missing section
reads as a shorter report.

**The test suite was enforcing the silence.** A test asserted `"ALPHA" not in
summary_text()` when no benchmark was supplied, calling the check "additive and
opt-in". That was accurate when it was written and stopped being accurate the
moment the alpha check became the basis for overturning the exit-ladder result.

Fixed and covered — see `CHANGES.md` -> "Finding 8". Five mutations killed,
including reinstating the original bug. Repro:
`repro/repro_missing_benchmark.py`.

### Does this invalidate the results in this file?

**No, and it is worth being precise about why.** Every headline result here
prints an ALPHA CHECK section with populated excess numbers — +2.90 pts/trade
in the liquid half, clustered t +4.31, and the regime split of +4.93% / -0.16%.
Those numbers cannot exist unless the benchmark resolved. The bug produces a
report with the section *absent*, not one with wrong numbers in it.

So this is a live trap that was never sprung, not a retraction. The one place
it was about to be sprung is the XIJI.JK run, where the ticker is a guess.

## The benchmark WAS wrong — and correcting it made the edge stronger (2026-08-19)

I predicted, in writing, that measuring against a sharia benchmark instead of
IHSG would cut the excess substantially — that most of the apparent alpha was
the sharia screen. **That prediction was wrong, and in the opposite direction.**

Same 6,082 trades, same folds, two benchmarks:

| | vs IHSG (^JKSE) | vs JII (^JKII) |
|---|---|---|
| pooled excess, walk-forward | +4.58% | **+5.34%** |
| pooled excess, fixed baseline | +5.52% | **+6.23%** |
| clustered t | 5.04 | **5.87** |
| folds negative | 6 of 14 | **5 of 14** |
| best fold's share of excess P&L | 60.1% | **51.6%** |
| best 3 folds | 99.5% | **83.2%** |

Every column moved in the strategy's favour.

### The part that changes a standing conclusion

The "regime-conditional edge" finding was the strongest negative result in this
file: excess +6.95% in rising folds, −0.35% in falling ones — an edge that
existed only in up markets, with no way to know which regime you were in.

Against JII that becomes:

| | up folds | down folds |
|---|---|---|
| vs IHSG | +6.95% (7) | **−0.35%** (7) |
| vs JII | +8.88% (6) | **+0.74%** (8) |

**The down-market excess is positive.** The edge is not conditional on a rising
market; it looked that way because of what it was being measured against.

### Why IHSG produced that illusion

Sharia stocks fell HARDER than the market in most drawdowns, because IHSG is
held up by the conventional banks a sharia portfolio can never own:

```
fold  1: IHSG  -3.8%   JII  -8.9%   (-5.1 pts)
fold  3: IHSG  +2.1%   JII  -5.8%   (-7.9 pts)
fold  4: IHSG  +4.7%   JII  +0.2%   (-4.5 pts)
fold  8: IHSG -11.5%   JII -17.9%   (-6.4 pts)
fold 13: IHSG -12.3%   JII -20.9%   (-8.6 pts)
```

Subtracting IHSG in those windows charged the strategy for a decline it had no
way to avoid and no way to hedge. Fold 3 is the clearest case: IHSG up 2.1%
while the sharia universe fell 5.8%. Measured against IHSG the strategy looks
like it lost ground in a rising market; it was actually beating a falling one.

### What is NOT settled

JII holds the **30 largest** sharia names, cap-weighted. This universe is 569
mostly smaller names. Small caps usually fall harder than large caps, so some
of the improvement above may be a size effect rather than selection skill.
`--benchmark EQUAL_WEIGHT` — an equal-weighted index over the same 569 tickers
— is the test that separates those, and it has not been run yet.

And the concentration problem survives: one fold is still half the excess P&L,
and fold 13 (the most recent, 2026-05-05..2026-07-30) is negative against BOTH
benchmarks (−7.46% vs IHSG, −5.54% vs JII). Whatever went wrong in the last
quarter is not a benchmark artefact.

### On the prediction being wrong

The reasoning was sound and the conclusion was backwards. I had the direction
of the sharia-vs-conventional gap inverted: I assumed the screen had helped
over this sample, when across most drawdowns it hurt. Recording it because a
prediction that is only cited when it lands is not a prediction.

## THE ANSWER (2026-08-19) — against the right benchmark, the edge does not survive

`--benchmark EQUAL_WEIGHT` builds an equal-weighted, daily-rebalanced index
over the SAME 569 tickers the strategy selects from. It answers the only
question that matters: **did picking these beat buying all of them?**

Same 6,082 trades, three benchmarks:

| | vs IHSG | vs JII | **vs EQUAL_WEIGHT** |
|---|---|---|---|
| excess, walk-forward arm | +4.58% | +5.34% | **+1.30%** |
| excess, fixed baseline | +5.52% | +6.23% | **+1.73%** |
| plain t | 6.36 | 7.17 | 2.05 |
| **clustered t** | 5.04 | 5.87 | **1.60** |
| **deflated Sharpe** | 1.000 | 1.000 | **0.670** |

Against the benchmark that actually matches the universe, the excess falls to
about a quarter of what IHSG suggested, the clustered t drops **below 2**, and
the deflated Sharpe drops to **0.670** — well under the 0.95 the report itself
names as the bar.

**Both corrections fail.** The measured edge is not distinguishable from
picking the best of six thresholds by luck.

### So my original prediction was right, and my retraction of it was wrong

Three positions in sequence, all recorded:

1. Predicted the sharia screen was doing the work and excess would collapse
   against a sharia benchmark.
2. Ran `^JKII`, saw excess RISE to +5.34%, and wrote "that prediction was
   wrong, and in the opposite direction."
3. Ran EQUAL_WEIGHT: excess +1.30%, clustered t 1.60, DSR 0.670.

Position 2 was the mistake. JII is 30 large caps; this universe is 569 mostly
smaller names. Against JII the strategy was being credited for the small-cap
premium of its own universe — a premium available by buying the whole basket
and requiring no signal at all. I flagged that limitation when reporting the
JII result and then still let the headline read as vindication.

The lesson is the same one this audit keeps producing: a benchmark that does
not match the portfolio does not measure skill, and it can err in EITHER
direction.

### What is actually true, stated plainly

  * **Raw returns are real.** +4.29%/trade OOS, t 5.54. Buying these names beat
    holding cash, and that is not in dispute.
  * **Almost all of it is available without the signal.** The equal-weighted
    sharia universe returned nearly as much. The selection adds ~+1.3%/trade,
    and that residual does not clear either significance bar.
  * **The regime-conditional finding survives, and gets worse.** Against
    EQUAL_WEIGHT: up folds +4.07% (6), down folds **-2.28%** (8). The excess is
    negative in down markets against the correct benchmark.
  * **Concentration survives.** Fold 10 alone still dominates.
  * **Fold 13 is negative against all three benchmarks** (-7.46 / -5.54 /
    -8.29). The most recent quarter is not a benchmark artefact.

### What this means for the original complaint

The complaint was that the system says HOLD and delivers under 1,000 IDR of
profit, or -5%.

That is now explained without any appeal to bugs in the exit logic. The signal
is not selecting well enough to beat simply owning the sharia universe. In a
rising market both make money and the difference is invisible. In a falling
market — folds 12 and 13, which is when the complaint was made — the selection
is actively worse than the basket, and a 5% win rate at -11.39%/trade is what
that looks like from the inside.

### What would change this conclusion

  * **More folds.** clustered t 1.60 is not "no edge", it is "not shown". A
    longer sample could move it either way.
  * **The gated variant.** `--apply-entry-vetoes --veto-ranging-stock` has
    still not been run against EQUAL_WEIGHT. If regime gating turns -2.28% in
    down folds into something non-negative, that is a real result.
  * **A different holding period.** 60 days was tuned when the ladder was in
    place.

What would NOT change it: re-running against IHSG and quoting +4.58%.

### Caveat on this run specifically

The benchmark reported `2-569 names/day` — IDX holidays left a handful of
tickers carrying phantom bars, and those were averaged into the index, inside
fold 13. Fixed (holidays now held flat), so **this run should be repeated**.
The direction will not change — the holiday effect is a handful of days out of
1,208 — but the exact figures above will move slightly.

## FINAL EQUAL_WEIGHT NUMBERS (2026-08-19) — holiday fix applied, verdict now honest

The run above was repeated after the exchange-holiday fix. Direction unchanged,
as predicted; figures moved slightly. **These supersede the previous section's
numbers.**

```
EXCESS OOS (walk-forward threshold)   +1.27%/trade   plain t 1.71   clustered t 1.57
EXCESS OOS (fixed baseline 80)        +1.71%/trade   plain t 2.02   clustered t 1.92
                                                     deflated Sharpe 0.766
ALPHA VERDICT: EV positive but WEAK (clustered t 1.92 < 2): could be noise.
```

Note the two arms' clustered t differ (1.57 vs 1.92). Computing each arm's own
correction was not pedantry: the verdict is rendered from the baseline arm, and
using the chosen arm's 1.57 would have reached the right answer for the wrong
reason.

### The result in one line

**Eight of fourteen folds have NEGATIVE excess.** In a majority of quarters,
buying the whole sharia universe beat the stocks this system picked.

| | |
|---|---|
| pooled excess, all 14 folds | **+1.27%/trade** |
| excluding fold 10 | **−0.44%/trade** |
| excluding folds 10 and 9 | **−1.00%/trade** |
| excluding folds 10, 9 and 6 | **−1.39%/trade** |

Fold 10 alone is **131.5%** of all pooled excess P&L — more than the total,
which means the other thirteen folds sum to negative. Remove one quarter
(2025-07-23..2025-10-21) and stock selection loses to buying everything.

### The basket, fold by fold

```
fold  basket%  strategy%  excess%
   0     -2.8     -5.78    -4.29   basket beat the picks
   2     +3.6     -0.51    -0.80   basket beat the picks
   3     -0.9     -3.47    -2.17   basket beat the picks
   4     -3.1     -4.04    -1.93   basket beat the picks
   5     -8.4     +0.03    -2.10   basket beat the picks
   7     +2.2     -1.40    -2.17   basket beat the picks
  12     -9.3     -8.97    -2.95   basket beat the picks
  13     -6.9    -11.39    -8.73   basket beat the picks
```

Fold 11 is the sharpest illustration: the equal-weighted sharia basket returned
**+28.4%** and the strategy returned **+4.25%**. The signal was in the market
and did not participate.

Compounded across the fourteen test windows, buying the whole basket returned
**+87.6%**.

### Regime split, against the correct benchmark

| | up folds | down folds |
|---|---|---|
| vs IHSG | +6.95% (7) | −0.35% (7) |
| vs JII | +8.88% (6) | +0.74% (8) |
| **vs EQUAL_WEIGHT** | **+4.07% (6)** | **−2.35% (8)** |

Against the benchmark that matches the portfolio, the excess is clearly
NEGATIVE in falling markets. The regime-conditional finding was right all
along; the JII run made it look resolved because JII's large caps fell harder
than this universe did, flattering the comparison.

### The honest bottom line

This system's raw returns are real and come almost entirely from being long a
sharia universe that did very well. The stock SELECTION adds about +1.3% per
trade, concentrated in a single quarter, not significant under either
correction, and negative in most quarters and in most falling markets.

For the original complaint — "it keeps telling me to hold and I end up with
under 1,000 IDR or −5%" — the mechanism is now identified and it is not a bug
in the exit logic. In the quarters when the complaint was made, the selection
was losing to its own universe.

## The regime gate: works exactly as designed, and the design is wrong (2026-08-19)

`--apply-entry-vetoes --veto-ranging-stock` against EQUAL_WEIGHT:

```
trades          6,082 -> 1,033   (83% removed)
pooled excess   +1.27% -> -2.44%
clustered t      +1.57 -> -2.69      (significantly NEGATIVE)
deflated Sharpe   0.766 -> 0.000
ALPHA VERDICT: RAW EDGE IS BETA, NOT ALPHA
```

This is not "the gate didn't help". The gate made the result **significantly
negative** — the one outcome nobody predicted.

### What it actually did, split by what the basket did

| basket move | ungated | gated | change |
|---|---|---|---|
| strong up (> +15%) | +6.57% | **−6.22%** | **−12.80** |
| mild up (0..+15%) | −1.40% | −3.76% | −2.37 |
| down (< 0%) | −2.02% | **+1.23%** | **+3.25** |

**The gate does what it was built to do.** In falling markets it turns −2.02%
into +1.23% — a genuine improvement, and the first thing in this whole audit
that has helped the down-market case at all.

And it is catastrophic anyway, because it removes the up markets, which is
where every rupiah was. Fold 10 (basket +38.3%): excess goes from **+19.21% to
−7.22%**. Fold 9 (+19.8%): +4.40% to −5.67%. Fold 11 (+28.4%): +1.68% to
−7.06%.

The mechanism is not mysterious. A ranging/choppy veto keeps you out of
consolidation, and large moves begin in consolidation. The filter is
structurally positioned to miss exactly the breakouts that pay.

### The real trade-off this exposes

There is a working down-market filter here (+3.25 points) attached to an
up-market disaster (−12.80). Applying it only in falling markets would beat
both arms. That requires knowing the regime in advance, which is the problem
this system has never solved and which this run does not solve either.

Note also that `--veto-ranging-stock` keys off each TICKER's own ADX, not the
market's. It is not a market-regime timer, and it should not be read as a test
of one.

### The control run is still missing

`--apply-entry-vetoes` alone (no `--veto-ranging-stock`) has not been run, so
the damage cannot be attributed between the general entry vetoes and the
ranging veto specifically. Both hypotheses fit these numbers.

### Data caveat on this run

The warehouse re-downloaded 614 of 615 tickers mid-sequence ("1/615 already
covered ... history too short for 5y: 183, stale tail: 431"), minutes after a
run that reported "615/615 already covered, fetching 0". The fold boundaries
came out identical and the benchmark moved only +164.6% -> +165.6%, so the
comparison stands — an effect of that size cannot manufacture a 3.7-point swing
in pooled excess. But `f_mom_ew.json` and `f_mom_ew_gated.json` were computed
on slightly different data, and consecutive runs on the same day are not
reproducing.

LEADING HYPOTHESIS, and it is probably benign: the cache-hit paths require the
recorded fetch-ATTEMPT date to equal today. If the session crossed local
midnight between the two runs, every marker went stale simultaneously and a
full re-download is EXPECTED once per day, not a defect. `diagnose_warehouse
_churn.py` settles it — if the stale attempt dates are yesterday's, that is the
answer; if they are from earlier the same day, the marker is being lost and
that is a real bug.

## THE ENTRY VETOES ARE THE PROBLEM (2026-08-21) — and the live bot runs them

The control run finally attributes the damage. Three arms, same strategy, same
benchmark, fixed-baseline column:

| arm | trades | excess/trade | clustered t | verdict |
|---|---|---|---|---|
| no vetoes | 5,241 | **+1.71%** | +1.92 | weak, not significant |
| `--apply-entry-vetoes` | 962 | **−2.52%** | **−3.10** | BETA, NOT ALPHA |
| + `--veto-ranging-stock` | 850 | **−2.31%** | **−2.69** | BETA, NOT ALPHA |

**It is not the ranging veto.** Adding `--veto-ranging-stock` on top of the
general vetoes changes excess from −2.52% to −2.31% — marginally BETTER, well
inside noise. Essentially all the damage is done by `--apply-entry-vetoes`
alone.

That flag is documented in this repo as "same as the live bot": the RSI /
parabolic / OBV / thin-volume / bear-regime filters. **They are running in
production right now.**

### What they cost

They remove 82% of trades (5,241 -> 962) and turn a weak-positive excess into a
**significantly negative** one. clustered t −3.10 is not "no edge" — it is
evidence the filters select worse-than-random entries from within the signal's
own candidate set.

The mechanism is visible in the folds. In the three strongest quarters the
vetoed arm gives up almost everything:

```
fold   basket%   no-vetoes excess   vetoed excess
   6    +19.5          +2.12            -4.81
   9    +19.8          +4.40            -4.01
  10    +40.3         +19.21            -7.48
  11    +27.4          +1.68            -4.51
```

These are momentum-style filters applied to a momentum signal. RSI-overbought
and parabolic vetoes fire precisely on the strongest names in the strongest
quarters — the ones that were paying. The filters are not removing risk, they
are removing the right tail.

### This closes the loop on the original complaint

The paper account shows alpha **−0.83%**, trailing IHSG over 35 closed trades.
The live bot applies these vetoes. The walk-forward now says that
configuration produces −2.52%/trade excess at clustered t −3.10.

The paper result and the backtest are no longer in tension. They agree, and
they agree on a negative number.

### The single highest-value change available

Turn the entry vetoes off. That alone moves the measured excess from −2.52% to
+1.71%: not a proven edge (clustered t 1.92, deflated Sharpe 0.766, still
concentrated in one quarter) but no longer a measured LOSS.

That is the largest effect found anywhere in this audit, and it costs nothing
to implement.

### Caveat, stated plainly

The vetoes run used a warehouse refreshed on 2026-08-21 while the no-veto run
used 2026-08-20 data — fold boundaries shifted by ~2 days and `compare_folds.py`
correctly refused to correlate them. The pooled comparison above survives that
(a 2-day boundary shift cannot manufacture a 4.2-point swing at clustered t
−3.10), but the per-fold correlations have not been computed. Re-running the
no-veto arm on today's warehouse would close it properly.

## Leave-one-out: no single veto is responsible (2026-08-21)

Five runs, each disabling exactly one veto, fixed-baseline arm vs EQUAL_WEIGHT:

| veto removed | excess | recovers | % of the gap | clustered t | trades | +trades |
|---|---|---|---|---|---|---|
| obv | −2.26% | **+0.26** | 6.1% | −2.73 | 991 | +29 |
| thin_volume | −2.36% | +0.16 | 3.8% | −2.92 | 1,006 | +44 |
| rsi | −2.52% | **+0.00** | 0.0% | −3.05 | 993 | +31 |
| bear | −2.54% | −0.02 | −0.5% | −3.06 | 1,044 | +82 |
| parabolic | −3.03% | **−0.51** | −12.1% | −3.68 | 1,024 | +62 |

Reference points: all five ON = −2.52% (n 962); all five OFF = +1.71% (n 5,241).
**The gap to explain is 4.23 points and 4,279 trades.**

### The finding

Removing all five at once recovers **+4.23 points**. Removing them one at a
time recovers **−0.11 points in total** — nothing.

Each single removal restores only **29 to 82 trades out of the 4,279 missing**.
The five filters are almost completely REDUNDANT: they fire on the same
candidates, so the intersection barely moves when one arm of the AND is
dropped. Leave-one-out cannot attribute a conjunction, and this one is a
conjunction.

That reframes the earlier conclusion. "The entry vetoes cost 4.2 points" stands
and is unchanged. "Therefore find and fix the bad veto" does not — there is no
bad veto to find. The cost is a property of applying five overlapping filters
together, not of any one of them.

### My prediction, and how it was wrong

Recorded before the runs: *"parabolic and rsi are the most damaging — both
fire on the strongest names in the strongest quarters."*

  * **rsi: exactly 0.00 effect.** Removing it changes nothing measurable.
  * **parabolic is the only veto that HELPS.** Removing it makes the result
    WORSE by 0.51 points and drives clustered t from −3.10 to −3.68. It is the
    single most useful filter of the five, and I named it as the prime suspect.

The reasoning ("momentum filters applied to a momentum signal remove the right
tail") is still the best available explanation for why the GROUP is harmful. It
simply does not decompose the way I assumed.

### The measurement leave-one-out cannot make, and what replaces it

To price each veto individually the design has to be **leave-one-IN**: enable
exactly one and disable the other four. Leave-one-out measures a veto's
*marginal* contribution given the other four are still running, which for
overlapping filters isnear zero by construction. Leave-one-in measures the
filter's own cost.

The comparison between the two is itself the answer on redundancy: if the five
leave-one-in costs sum to roughly 4.23 points the filters are independent; if
each is large but they do not sum, they overlap.

The `parabolic` run is the interesting one, because leave-one-in for parabolic
is exactly the "keep only the veto that helps" configuration.

### Data caveat

The `rsi` run used a benchmark with 1,208 bars ending 2026-08-21; the other
four used 1,207 bars ending 2026-08-20. That the rsi arm landed on −2.52%, the
same figure as the all-vetoes arm to two decimals, is coincidence rather than
identity — the two runs have different trade counts (993 vs 962). Worth
re-running rsi on a matched warehouse before quoting "exactly zero".

## Leave-one-IN closes it: every veto is harmful alone (2026-08-22)

Each veto enabled by itself, the other four off. Fixed-baseline arm, vs
EQUAL_WEIGHT:

| configuration | excess | clustered t | trades | kept | vs no-veto |
|---|---|---|---|---|---|
| **NO vetoes** | **+1.71%** | **+1.92** | 5,241 | 100% | — |
| only bear | −0.50% | −0.31 | 1,197 | 23% | −2.21 |
| only obv | −0.80% | −0.52 | 1,243 | 24% | −2.51 |
| only thin_volume | −1.25% | −0.82 | 1,241 | 24% | −2.96 |
| only rsi | −2.10% | −1.75 | 1,206 | 23% | −3.81 |
| only parabolic | −2.30% | −2.98 | 1,147 | 22% | −4.01 |
| ALL five | −2.52% | −3.10 | 962 | 18% | −4.23 |

**Monotone. Every configuration containing a veto is worse than none, and more
vetoes is worse than fewer.** There is no subset worth keeping. The mildest
single filter (bear) still costs 2.21 points.

### The redundancy, measured

**One veto alone already removes 76-78% of trades. All five remove 82%.**

The first filter does essentially all the blocking; the other four add four
percentage points. And the individual costs sum to 15.50 points while the five
together cost 4.23 — strongly sub-additive, which is what heavy overlap looks
like. These are close to the same filter wearing five different names.

That is why leave-one-out found nothing: with four near-identical filters still
running, removing the fifth cannot change the intersection.

### Correcting what I said yesterday

I wrote that `parabolic` was "the only veto that HELPS". Leave-one-in refutes
it as a general claim: **parabolic alone is the WORST single veto** (−2.30%,
clustered t −2.98).

Both measurements are correct and they answer different questions. Adding
parabolic to the other four does improve that combination (−3.03% -> −2.52%) —
a true marginal statement. It is not evidence that parabolic is a good filter,
and I presented it as though it were. Since the recommendation is to run no
vetoes at all, the conditional it holds under never applies.

### What the vetoes actually destroy

Per-fold excess split by market direction (`compare_folds.py`):

| arm | up folds | down folds |
|---|---|---|
| **no vetoes** | **+3.97%** | −2.26% |
| only bear | −0.64% | −0.85% |
| only obv | −0.79% | −1.12% |
| only rsi | −2.02% | −1.85% |
| only parabolic | −3.52% | −0.91% |

The unfiltered arm earns everything it earns in RISING folds. Every veto arm is
negative there. The filters are not trimming risk — they are removing the
up-market participation that was the entire result.

Parabolic is the extreme case: worst in up folds (−3.52%) and its per-fold
excess correlates **−0.085** with the unfiltered arm, versus +0.71 to +0.81 for
the others. It does not merely take fewer trades, it takes a different and
unrelated set.

### The recommendation, now unambiguous

**Turn all entry vetoes off.** Not a subset, not a tuned threshold — all of
them. That is +4.23 points of measured excess and it is the largest effect
found anywhere in this audit.

It does not create a proven edge: the no-veto arm is +1.71% at clustered t
1.92, deflated Sharpe 0.766, still concentrated in one quarter. It removes a
measured, significant LOSS.

For the live bot that means `apply_entry_vetoes` off. The paper account's
alpha of −0.83% against IHSG is the same finding measured forward.

## The holding sweep measured one quarter, not the parameter (2026-08-22)

Five walk-forwards, vs EQUAL_WEIGHT, fixed-baseline arm:

| hold | trades | excess | **ex-best fold** | clustered t | defl. Sharpe | folds<0 |
|---|---:|---:|---:|---:|---:|---:|
| 20 | 8,317 | −0.05% | **−0.84%** | −0.14 | 0.075 | 12/14 |
| 30 | 6,748 | +0.74% | **−0.63%** | +1.30 | 0.552 | 9/14 |
| 45 | 5,773 | +1.50% | **+0.22%** | +1.95 | 0.776 | 7/14 |
| 60 | 5,260 | +1.58% | **−0.11%** | +1.80 | 0.718 | 8/14 |
| 90 | 5,038 | +2.08% | **−0.06%** | +2.03 | 0.788 | 8/14 |

### My prediction was wrong, again in the opposite direction

Recorded before the run: *"the peak is shorter than 60 days, likely 20–30, and
the shape is a broad hump."* Both halves wrong. The headline column rises
monotonically to the edge of the range, and 20 days is the WORST setting
tested — negative, with 12 of 14 folds below zero.

### What the ex-best-fold column shows

Remove the single biggest-contributing fold and **every holding period
collapses to zero or below**. The headline ramp is not the strategy improving
with time; it is fold 10 growing:

```
fold 10 excess:   20d +5.75%   30d +8.82%   45d +12.61%   60d +16.70%   90d +22.40%
fold 13 excess:   20d -3.12%   30d -7.51%   45d  -9.47%   60d -10.11%   90d -11.07%
```

Holding longer captures more of the one quarter that worked and more of the
quarter that did not. It is a leverage knob on concentration, not a parameter
with an optimum.

### Two reasons not to chase 90 days

**Overlap.** Position-days go from 166k at 20d to 453k at 90d — 2.7x the
exposure from 40% FEWER trades. At 90 days against ~63-day test windows, most
of each trade's return accrues outside the window it was entered in, and
adjacent trades overlap heavily. The clustered t clusters by ENTRY DATE, not by
overlapping holding windows, so it does not correct for this. The +2.03 at 90d
is inflated relative to the +1.95 at 45d.

**The current regime.** Fold 13 — the most recent quarter, and the one the
original complaint came from — gets monotonically worse as holding lengthens,
from −3.12% at 20d to −11.07% at 90d. The setting that looks best on the pooled
number is the worst for the conditions actually being traded.

### The recommendation: leave it at 60

45 and 60 are indistinguishable (+1.50 vs +1.58, clustered t 1.95 vs 1.80), and
45 is the only setting whose ex-best-fold figure is positive at all (+0.22%,
which is not a result either). There is no case for changing the parameter and
no case for extending the sweep past 90 — the gain is one quarter and the
overlap inflation grows with it.

**The sweep did not find a better holding period. It found another way of
looking at the concentration that was already the headline problem.**

## The live bot has never run a configuration anyone measured (2026-08-23)

Adding a measured-expectation block to the daily run surfaced something no
walk-forward could, because it is not a property of the strategy — it is a
property of the gap between the strategy that was measured and the one that
runs.

`runner_config.json`, as it stands:

```json
{
  "daily_capital_idr": 4748425.0,
  "max_positions": 15,
  ...
}
```

No `exit_profile`. No `disabled_entry_vetoes`. That resolves to:

| | live bot | every fold table on disk |
|---|---|---|
| exit profile | `legacy` — stop/target/trailing ACTIVE | `forward_test` — no price exits |
| holding_max_days | 20 | 60 |
| entry vetoes | all five ON | varies by arm, mostly OFF |

Every number in this document — +1.71%/trade and clustered t 1.92 on the
fixed-baseline arm, −0.44% ex-fold-10 on the walk-forward-chosen arm, the veto
leave-one-in table, the holding sweep — describes the right-hand column. The bot the user runs, and whose results prompted the
original complaint, is the left-hand column. Nothing in this project has ever
measured it.

That is not a small discrepancy between neighbouring settings:

* the exit ladder was measured at roughly **−1.6 points per trade** and removed
  from the validated profile for that reason; the live bot still runs it,
* the five entry vetoes together were measured at **−2.52%/trade** against
  **+1.71%** with none of them; the live bot runs all five,
* `holding_max_days` 20 was the worst row of the holding sweep (−0.05%/trade
  headline, −0.84% ex-best fold); the live bot runs 20.

Each of the three live settings is, independently, the measured-worst option
available. The daily screen said none of this. It printed nine feature ticks
and a top pick.

### What the block does about it

It refuses to attach a measurement to a configuration that measurement was not
taken from, and names the differences instead. As shipped, the live run now
prints `NOT APPLICABLE` with the three-row table above rather than a number.
That is the honest output, and it is also the actionable one: the fix is to
make the two columns agree, in either direction.

### This does not vindicate the strategy

Aligning the config is not expected to produce a good result — the aligned
measurement is +1.71%/trade at clustered t 1.92 and deflated Sharpe 0.766,
below both bars, with the chosen arm at +1.27% falling to −0.44% without one
fold and 8 of 14 folds negative. The verdict
line for the aligned configuration reads `EV positive but WEAK ... could be
noise.`

What alignment buys is that the forward test finally tests something that was
measured. Today the paper account's −0.83% alpha over 35 closed trades cannot
be compared to any backtest in this repository, because no backtest ran that
configuration. Fixing that is worth more than another sweep.

### The order to do it in

1. Set `"exit_profile": "forward_test"` and
   `"disabled_entry_vetoes": ["rsi","parabolic","obv","thin_volume","bear"]`.
2. Run one daily scan and read the log. It should say `entry vetoes: ALL OFF`
   and `exit profile: FORWARD_TEST`. Until this release nothing printed the
   veto line at all, so this check was previously impossible to perform.
3. Re-run the walk-forward with those exact settings and
   `--save-folds results/expectation.json`. The block then reports the number
   instead of withholding it.
4. Let it run forward for several weeks. That is the one piece of evidence this
   project has never had, and no further backtesting substitutes for it.

**Twelve findings were about a failure that looked like normal operation. This
one is about a system whose entire body of evidence describes a configuration
it does not run.**

## The recommendation had a hole in it, and the hole was the exit rule (2026-08-23)

v77 told the user to set `"exit_profile": "forward_test"`. That switches off
every price-based exit — no stop, no target, no trailing — leaving
`holding_max_days` as the only rule that closes a position. It is the right
recommendation and it rests entirely on that one rule working.

It did not always work, and when it failed it failed silently.

`papertrade._bars_held` located the entry bar by exact date equality and
returned `None` on a miss; both callers wrote `if bars_held is not None and
bars_held >= max_days` with no else. A position whose entry date is not a
trading bar therefore never aged, never exited, and never appeared on any
report. Under `legacy` the trailing stop would eventually catch it. Under
`forward_test` nothing would. The profile this audit recommends is the profile
where the bug becomes unbounded.

Two verified routes create such a date:

1. `manual_buy` accepts any date string with no trading-day validation.
2. `daily_run` has no trading-day guard, and this project has no IDX exchange
   calendar. On a market holiday the fill price is read from the last available
   bar while `entry_date` is stamped `today_wib()` — the holiday. They are
   different days by construction.

Fixed in `bars_held_or_reason()`: an off-bar date counts from the next open
(unambiguous — that is when the position started), while a pre-window date, a
future date and an unparseable one each return a named reason that both call
sites now print.

### What this says about the audit's own method

Thirteen of the fourteen findings were located by asking "what does this look
like when it fails?" This one was located by asking it of a recommendation I
had just made. The measured-expectation block in v77 asserted that live
`holding_max_days` is 20; checking whether the live path even *uses* that
value — rather than inferring it from a config default — is what surfaced the
call site.

A claim about the live system that has only been read off a config file is not
a measurement. That is the same rule this document applies to returns.

### Still not fixed, and deliberately

`daily_run` still has no trading-day guard, and `manual_buy` still accepts any
date. Both are live-behaviour changes: a trading-day guard would skip runs, and
date validation would reject entries the user may have legitimate reasons to
record. The defect they feed is closed at the point where it did damage. Adding
an exchange calendar is a separate change with its own risk, and flipping live
trading behaviour as a side effect of a bug fix is what this audit keeps
finding in other people's code.

### The user's current book is unaffected

All 66 dated records in `paper_state.json` fall on weekdays, none on a known
IDX holiday. This is latent, not realised. Saying otherwise would be the same
overclaim the audit exists to catch.

## The live/measured gap was four axes wide, not three (2026-08-23)

The table in "The live bot has never run a configuration anyone measured" had
three rows. It should have had four.

| | live bot (as shipped) | every fold table on disk |
|---|---|---|
| exit profile | `legacy` — ladder ACTIVE | `forward_test` — no price exits |
| holding_max_days | 20 | 60 |
| **entry score cutoff** | **60** | **80** |
| entry vetoes | all five ON | mostly OFF |

The fourth row is worse than the other three, because the other three are
silent while this one was actively contradicted on screen. `daily_run` logs
`entry score >= {trade_cfg.backtest.score_entry_threshold}` off the resolved
profile; `kala_daily_trader` decided with a hardcoded `Config()`. Set
`exit_profile: forward_test` and the log would have read **80** on every run
while the scanner bought from **60**.

The +1.71%/trade measurement was taken at baseline 80 over 5,241 trades. Every
entry scoring 60-79 is outside it.

### What this run of the method has now produced

Findings 13, 14 and 15 all came from the same move: take a claim this audit
itself made about the live system, and check it against the code that decides
rather than the config that describes.

- **13** — the daily screen recommends without stating an expectation, and the
  measurement it would state describes a configuration the bot does not run.
  Found by asking what the live screen actually says.
- **14** — the max-holding rule silently never fires for a position whose entry
  date is not a trading bar. Found by checking whether the live path really
  uses `holding_max_days`, rather than reading it off a default.
- **15** — the entry cutoff the log prints is not the one the scanner applies.
  Found by checking the same thing for `score_entry_threshold`.

Two of the three were in code this audit had already read several times. What
changed was the question: not "is this correct?" but "is the number this
reports the number this uses?"

### The recommendation, restated

`runner_config.json`:

```json
"exit_profile": "forward_test",
"disabled_entry_vetoes": ["rsi", "parabolic", "obv", "thin_volume", "bear"]
```

That single key now moves all three of exit ladder, holding period and entry
cutoff to the measured configuration — which it always claimed to, and as of
this release actually does. Expect **far fewer BUY signals**: the cutoff goes
from 60 to 80, and at 80 the plain-BUY band is empty, so everything entered
will be labelled STRONG BUY. That is not a bug and not a data outage; it is the
threshold the measurement was taken at.

## The tooling argued against the recommendation (2026-08-23)

`preflight` exists to catch settings that silently do nothing. Run the
configuration this audit recommends through it and it reports:

```
WARN  'disabled_entry_vetoes' is not read by any code. It is silently
      ignored, so whatever you set it to is having no effect.
```

The setting is read by `entry_settings.entry_config_from`. The warning is
false, and it is about the change worth +4.23 points per trade — the largest
single effect anywhere in this study. Anyone who followed the instruction and
then checked their work was told to undo it.

`breaker_preserve_halt_when_unreadable` — a circuit-breaker safety option read
in `daily_run` — was reported the same way.

Both were missing from `KNOWN_CONFIG_KEYS`, whose only guard checked
`daily_run.DEFAULT_CONFIG`. Neither key lives there.

### The pattern is now explicit

Findings 14, 15 and 16 came from one question asked three times: **is the
number this reports the number this uses?**

- 14 — the max-holding rule reported nothing and checked nothing, for any
  position whose entry date was not a trading bar.
- 15 — the daily log printed `entry score >= 80` while the scanner bought
  from 60.
- 16 — preflight reported a working setting as inert.

Each was found by taking a claim this audit had made about the live system and
checking it against the code that decides, rather than the config that
describes. Two of the three were in files already read several times during
this audit. What changed was the question.

Worth stating because it generalises: in a system where the arithmetic is
right, the defects concentrate at the boundary between what the code does and
what the code says it does. Every one of the sixteen findings sits on that
boundary.

### What is left of the recommendation

Nothing blocking. As of this release:

* the entry-veto setting is read (v22), reported in the log (v77), and
  recognised by preflight (this release),
* `exit_profile` moves the exit ladder, the holding period **and** the entry
  cutoff together (v79) rather than two of the three,
* the only exit rule left under `forward_test` cannot silently fail to fire
  (v78),
* and the daily run states what the resulting configuration has been measured
  to be worth, or that it has not been (v77).

The remaining step needs elapsed time, not code.

## The forward test was set up to flatter itself (2026-08-23)

Every release since v77 has been clearing the way for one thing: run the
measured configuration forward and compare the result to the measurement. That
comparison had a systematic bias built into it.

The paper trader books fills through `cfg.costs`, which was always the default
`CostModel()` — `spread_mode="flat"`, a constant 0.10% half-spread at every
price. Every validated number in this project was measured with `--tick-spread`
(`tick_floor`), where the half-spread cannot be tighter than half an IDX tick.

On this account's nine open positions:

| | booked | measured | gap |
|---|---:|---:|---:|
| mean round trip | 0.64% | 0.87% | **0.23%** |
| KBLI @ 323 | 0.64% | 1.05% | 0.42% |
| BSML @ 519 | 0.64% | 1.39% | 0.76% |
| a 67-rupiah name | 0.64% | 1.91% | 1.28% |

Flat is never the dearer model, so this is not noise that averages out. It is
**0.23 points per trade in one direction** — about 14% of the +1.71%/trade the
forward test would be judged against, and more than half of the −0.44%
ex-fold-10 figure.

And `daily_run` already ran its **friction report** at `tick_floor`. The same
run has been telling the user what their trading costs under the honest model
and recording it at the optimistic one.

### Why the default is still flat

Because changing it rewrites a live book's arithmetic without being asked, and
this audit exists partly to catch exactly that. `"costs_spread_mode":
"tick_floor"` is the opt-in; the measurement records which model it charged;
and the expectation block now refuses to quote a tick-floored figure at a
flat-booked account rather than presenting a comparison that is 14% off.

### The recommendation, final form

```json
{
  "exit_profile": "forward_test",
  "disabled_entry_vetoes": ["rsi", "parabolic", "obv", "thin_volume", "bear"],
  "costs_spread_mode": "tick_floor"
}
```

Three keys. The first moves the exit ladder, holding period and entry cutoff to
the measured configuration; the second turns off the filters measured at
−4.23 points; the third makes the book charge what the backtest charged.

With all three set, the daily run will print the measured expectation instead
of withholding it — which is the signal that the live system and the evidence
finally describe the same thing.

Expect fewer trades and worse-looking fills. Both are the point.

### Seventeen findings, one boundary

13, 14, 15, 16 and 17 were all found by asking whether a number this system
reports is the number it uses. The last of them is about money rather than
configuration, and it is the one that would have quietly corrupted the
conclusion of the forward test rather than any individual trade.

## Verifying the recommendation found a defect in the recommendation (2026-08-23)

Before shipping the three-key configuration I ran it through the whole live
path and checked every claim I had made about it:

```
preflight            OK  3 keys, all recognised
entry cutoff         80          (was 60 before v79)
holding_max_days     60          (was 20)
spread_mode          tick_floor  (was flat)
trailing enabled     False
hard stop / target   inert by design
log line             entry vetoes: ALL OFF — the measured-best setting
```

All of it held. What did not hold was the instruction the block prints when
nothing has been measured yet. It was a fixed string with no `--tick-spread`,
no `--holding-days`, no `--baseline-threshold` — so following it against the
recommended configuration produces a table recording `spread_mode: flat`, and
the same block then **refuses the table it asked for**.

The command is now built from the live setup, and a test generates it, parses
it with the REAL argument parser, constructs the provenance that run would
save, and asserts the comparison comes back empty — for four configurations
including this one.

### Why this one needed a different kind of test

The defect lived between two pieces of code that never met: a string in
`expectation.py` and an `argparse` definition in `run_walkforward.py`. No unit
test of either module can see it. `build_parser()` was extracted from `main`
so the two could finally be put in the same room.

Six mutations, each making the command describe a slightly different
configuration from the one running. All caught.

### Where the audit stands

Eighteen findings. The last six all came from one question — *is the number
this reports the number this uses?* — and the last of them came from asking it
about my own instructions rather than about the system's.

Nothing is now blocking the forward test. The three keys resolve to the
measured configuration, the daily run states what that configuration has been
measured to be worth, the command it prints produces a table it will accept,
and the book charges what the backtest charged.

What remains needs weeks of elapsed time and no further code.

## The documents check out; the exemption did not (2026-08-23)

Having found Finding 18 by running an instruction rather than reading it, the
same treatment went to the documentation: `check_docs.py` compares quoted line
counts, the test-file count, every code path named in backticks, and every
documented `python foo.py --flag` command against the repository.

**Result: nothing wrong.** 14 documents, 39 commands, no broken references, no
stale counts. After nineteen findings it is worth recording a check that came
back clean, because a report that only ever contains bad news stops being
information.

What it did surface was a command needing an exemption — `daily_run.py
--capital`, which is read straight from `sys.argv` and so cannot appear in
`--help`. That exemption turned out to be hiding a defect: `--captial`,
`--capital=N` and `-capital` all ran at the stored capital with nothing in the
log to say so. Small, on a money input, and the same shape as everything else.

### Why a checker for prose was worth building

Six line-count and test-count figures have been hand-synced in this session
alone. The first full run of the new test failed on the summary it was written
to guard, because adding the test file itself moved the count. That is the
whole argument for the tool in one event.

It refuses to check measured results, and says so in its own docstring:
+1.71%/trade needs a five-year warehouse and an hour of compute to re-derive,
and a checker that silently skipped it would be worse than one that never
claimed to.

### Nineteen findings, and the shape of the last seven

| | reported | used |
|---|---|---|
| 13 | a confident BUY | no expectation stated at all |
| 14 | position aged, exit rule live | rule skipped for an off-bar entry |
| 15 | `entry score >= 80` | bought from 60 |
| 16 | "this setting has no effect" | it works, and it is the best change available |
| 17 | friction at tick-floored spreads | fills booked 0.23 pts/trade cheaper |
| 18 | "to measure it, run this" | the command's own output then refused |
| 19 | `--capital 3000000` | ran at the stored 4,748,425 |

Every one is a claim the system makes about itself that the system contradicts.
None is an arithmetic error.

### Still the only thing left

Set the three keys, let it run for several weeks. Nothing in the code is
blocking that now.
