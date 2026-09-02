# The arithmetic was never wrong

**Kala / Kala — forensic audit, 16–23 August 2026**

Twenty-one findings in a live IDX sharia trading system. Twelve of them the
same shape: an operation that failed while reporting success, or missing data
that quietly became the number zero. The thirteenth is larger than those twelve
together — the bot has never run a configuration anyone measured. Findings 14
through 21 came from auditing this audit's own work: its recommendation, its
printed instructions, its documents, and finally its own tooling — caught first
leaving a live trading file mutated after being killed mid-run, and then, on a
different machine, accusing four working scripts of rejecting flags they accept.

| | |
|---|---|
| Tests passing | 2,116 (2 skipped, 135 files) |
| Findings | 21 |
| New tools built | 11 |
| Arithmetic errors found | 0 |

This file is the summary. The full working record — including every run's raw
output — is in `CHANGES.md` (2,756 lines) and `PROJECT_STATUS.md` (4,264 lines).

---

## Contents

1. [Where it started](#1-where-it-started)
2. [The answer](#2-the-answer)
3. [The benchmark trail](#3-the-benchmark-trail)
4. [The entry vetoes](#4-the-entry-vetoes)
5. [One quarter](#5-one-quarter)
6. [Findings register](#6-findings-register)
7. [Corrections ledger](#7-corrections-ledger)
8. [What was built](#8-what-was-built)
9. [What is still open](#9-what-is-still-open)
10. [What to do next](#10-what-to-do-next)

---

## 1. Where it started

The audit began with an ordinary frustration and an unusually specific
instruction about where to look.

**The complaint:**

> The project still can't detect what time is best to buy/hold/sell. It kept on
> telling me to hold, but then I ended up only having a profit of less than 1k
> IDR or even a −5%.

**The lens — and it held for all twenty-one:**

> Aritmetikanya tidak pernah salah — bug selalu ada di tempat data yang hilang
> diam-diam berubah jadi angka, atau kegagalan yang terlihat normal. Setiap
> temuan wajib direproduksi dengan bukti yang bisa dijalankan, dan setiap
> perbaikan wajib punya tes yang sudah diverifikasi gagal kalau bug-nya
> dimasukkan lagi.

Every finding below was reproduced with a runnable script before it was called
a finding, and every fix carries a test that was verified to fail when the bug
was put back. That last step caught six tests that passed while testing nothing.

---

## 2. The answer

Measured against an equal-weighted index built from the same 569 tickers the
strategy selects from — the only benchmark that isolates stock-picking from
simply owning the universe.

| | value | meaning |
|---|---|---|
| Raw return | **+4.29%**/trade, t 5.54 | Real, and not in dispute |
| Excess over the basket | **+1.71%**/trade | Almost everything above is available by buying everything |
| Clustered t | **1.92** | Below the bar of 2 the report itself states |
| Deflated Sharpe | **0.766** | Below 0.95 — not distinguishable from the best of six coin flips |

### The honest reading

The signal is not selecting well enough to beat owning the sharia universe. In
a rising market both make money and the difference is invisible. In a falling
market the selection is *worse* than the basket — and that is when the
complaint was made.

Buying the whole basket returned **+87.6%** compounded across the fourteen test
windows. The selection adds about 1.3 points per trade on top, concentrated in
a single quarter, clearing neither significance bar.

The paper account agrees: alpha **−0.83%** against IHSG over 35 closed trades.
The backtest and the live result are no longer in tension. They agree, and they
agree on a negative number.

This is not a retraction of the system. It is a relocation of where its value
is: the universe screen and the discipline are doing the work; the stock
ranking is not yet earning its keep.

---

## 3. The benchmark trail

The same 6,082 trades, measured against three yardsticks. Which one you pick
changes the conclusion completely — and for most of this project's history, the
wrong one was in use.

| Benchmark | Excess/trade | Clustered t | Defl. Sharpe | Folds < 0 |
|---|---:|---:|---:|---:|
| IHSG `^JKSE` — the whole market | +5.52% | 5.04 | 1.000 | 6 / 14 |
| JII `^JKII` — 30 largest sharia | +6.23% | 5.87 | 1.000 | 5 / 14 |
| **Equal-weight — the traded universe** | **+1.71%** | **1.92** | **0.766** | **8 / 14** |

*(fixed-baseline arm; the "folds < 0" column is counted on the per-fold excess
the saved tables carry, which is the walk-forward-chosen arm — see section 5.)*

IHSG is cap-weighted and bank-heavy; a sharia portfolio can never hold those
banks, so subtracting IHSG credits the strategy for a sector tilt it did not
choose. JII removes that but is 30 large caps against a universe of 569 mostly
smaller names, so it credits the small-cap premium instead. Only the
equal-weight basket asks the question that matters: **did picking these beat
buying all of them?**

### Against the correct benchmark, the regime finding gets worse

| Benchmark | Rising folds | Falling folds |
|---|---:|---:|
| vs IHSG | +6.95% | −0.35% |
| vs JII | +8.88% | +0.74% |
| **vs equal-weight** | **+4.07%** | **−2.35%** |

Against the benchmark that matches the portfolio, the excess is clearly
negative in falling markets. Nothing in the system tells you which regime you
are in ahead of time.

---

## 4. The entry vetoes

The live bot ran five entry filters — RSI, parabolic, OBV distribution, thin
volume, bear regime — switched on together, hardcoded, with no way to turn them
off. They were the single most expensive thing in the system.

| Configuration | Excess/trade | Clustered t | Trades | Kept |
|---|---:|---:|---:|---:|
| **No vetoes** | **+1.71%** | **+1.92** | 5,241 | 100% |
| only bear regime | −0.50% | −0.31 | 1,197 | 23% |
| only OBV distribution | −0.80% | −0.52 | 1,243 | 24% |
| only thin volume | −1.25% | −0.82 | 1,241 | 24% |
| only RSI overbought | −2.10% | −1.75 | 1,206 | 23% |
| only parabolic | −2.30% | −2.98 | 1,147 | 22% |
| **All five — what the bot ran** | **−2.52%** | **−3.10** | 962 | 18% |

Monotone: every configuration containing a veto is worse than none, and more is
worse than fewer. **There is no subset worth keeping** — even the mildest
single filter costs 2.21 points.

### They are five names for nearly one filter

One veto alone already removes **76–78%** of trades. All five remove 82%. The
first filter does essentially all the blocking; the other four add four
percentage points. Their individual costs sum to 15.50 points while together
they cost 4.23 — strongly sub-additive, which is what heavy overlap looks like.

That is why leave-one-out found nothing: with four near-identical filters still
running, removing the fifth cannot change the intersection. Removing all five
recovers +4.23 points; removing them one at a time recovers −0.11 in total.

### What they actually destroy

The unfiltered arm earns everything it earns in *rising* folds. Every veto arm
is negative there. These are momentum-style filters applied to a momentum
signal: they fire on the strongest names in the strongest quarters — the ones
that were paying. They are not trimming risk, they are removing the right tail.

---

## 5. One quarter

Concentration is the finding that survives every benchmark change, and it is
the one that should govern position sizing.

Measured on the WALK-FORWARD-CHOSEN arm — the one whose per-fold excess the
saved tables carry. (The fixed-baseline arm quoted elsewhere in this document
pools to +1.71% over 5,241 trades; until this release nothing saved its
per-fold column, so it could not be decomposed at all. Mixing the two is a
defect this audit shipped twice before catching it — see Finding 13.)

| Sample | Excess/trade | Trades |
|---|---:|---:|
| All 14 folds | +1.27% | 6,082 |
| **Excluding fold 10** (2025-07-23 → 2025-10-21) | **−0.44%** | 5,552 |
| Excluding folds 10 and 9 | −1.00% | 4,980 |
| Excluding folds 10, 9 and 6 | −1.39% | 4,421 |

Fold 10 alone accounts for **131.5%** of all pooled excess P&L — more than the
total, which means the other thirteen folds sum to negative. **Eight of fourteen
folds have negative excess**: in a majority of quarters, buying the whole
universe beat the stocks the system picked.

The sharpest single illustration is fold 11: the equal-weighted sharia basket
returned **+28.4%** and the strategy returned **+4.25%**. The signal was in the
market and did not participate.

---

## 6. Findings register

Each was reproduced before being called a finding. The recurring signature —
*a failure that reads as normal operation* — is on every one.

### 1. One zero meant four different things

State files (watchlist, positions) could be lost, empty, corrupt or absent, and
every one of those rendered as the same empty result. Saves were non-atomic, so
an interrupted write left a truncated file that loaded as "no positions".
**Fixed.**

### 2. A 30% drawdown reported as 0%

The circuit breaker stored its peak in a sidecar file. When that file could not
be read, the peak re-anchored to today's value, drawdown computed as 0%, and
the breaker reported RESUMED — switching a safety device off precisely when its
state was unknown.

*The first fix was wrong*: carrying `was_halted=True` alone does nothing,
because the re-anchored peak still yields 0%. A test caught it. **Fixed.**

### 3. One Telegram message of three, logged as delivered

Long messages were chunked. If chunk two failed, the send returned success and
the log recorded a complete delivery. The forward test's only output was
silently partial. **Fixed.**

### 4. Break-even trades scored as wins

A missing `pnl_pct` defaulted to zero, and zero counted on the winning side of
the ledger. The live scorecard's win rate was measuring absent data. **Fixed.**

### 5. Nine of nine positions on the ATR fallback

When ATR was unavailable the stop silently fell back to a fixed percentage, and
the report called both "stop". Every live position was running the fallback and
the label gave no way to tell. **Fixed.**

### 6. The verdict was measured through a losing exit ladder

Every historical verdict in the project ran through a stop/target/trailing
ladder that was itself significantly negative: −0.45%/trade excess, clustered
t −3.79, negative in 12 of 14 folds. Removing it turned all six strategies
positive. The standing "no OOS edge" conclusion had been measuring the ladder.
**Corrected.**

### 7. A tidy table of `+nan%`, and two vacuous tests

Two defects in the audit's *own* measuring tools: a comparison script that
formatted missing keys as `nan` and printed them in a neat table, and a
mutation harness that reported six survivors while running under a Python
without pytest — zero FAILED lines read as green. **Fixed.**

### 8. A skipped alpha check was silent

`--benchmark` accepts any string. An unresolvable ticker warned on stderr and
carried on, and the whole ALPHA CHECK section simply vanished from stdout —
leaving a confident `VERDICT: EDGE CONFIRMED` measured against nothing. Every
result in the project was captured by redirecting stdout, where the warning
would not appear.

A test asserted this silence was correct behaviour. **Fixed.**

### 9. A missing excess written as `0.00`, into a saved file

`trade_stats([])` returns a fully populated dict whose `ev_pct` is 0.0 — and a
populated dict is truthy, so every guard sailed past it. Fourteen folds
rendered `+0.00` and the saved JSON recorded fabricated zeros that outlive the
terminal. Fourteen identical zeros have zero variance, so correlating against
them returns NaN — which reads as the tool correctly declining to answer.

Four source-text tests failed to catch it. One of them *required* the buggy
expression, and failed when the fix landed. **Fixed.**

### 10. The verdict disagreed with its own evidence

The report printed a clustered t of 1.60 and a deflated Sharpe of 0.670, told
the reader in as many words to trust them, and then rendered
`ALPHA VERDICT: EDGE CONFIRMED` from the plain t it had just finished
explaining was too generous. Nothing was missing; the headline simply ignored
the two numbers above it.

Underneath: those corrections were computed for the walk-forward arm while the
verdict is rendered from the fixed-baseline arm — so even wiring them in
naively would have judged one arm by another's evidence. **Fixed.**

### 11. The position cap switched off when exceeded

A real account held 17 positions against a limit of 10 and the bot kept
proposing more. The guard read `if shown >= slots and slots > 0` — and `slots`
is zero exactly when the cap binds, so the clause disabled the cap in the one
case it existed for. It worked at 9 held and stopped existing at 10.

The same inversion appeared twice: the header count read `min(slots, n) or n`,
and `0 or N` is `N`. **Fixed.**

### 12. I shipped a silent no-op and documented it as done

A patch adding provenance fields to the saved fold tables used a replacement
anchor with the wrong indentation and **no assertion that it matched**. It
replaced nothing, raised nothing, and the changelog entry was written from
intent rather than from the file. Fifteen real runs later, every saved table
was missing the fields — the user's own files were the evidence.

The same failure this audit documented eleven times in other people's code,
committed in the tooling built to catch it. **Fixed.**

### 13. The screen recommends, and never states an expectation

The daily run ends with nine feature checkmarks, a score out of 100 and a
risk/reward to one decimal — everything about what the system is *doing*,
nothing about what any of it has been *worth*. Precision about a signal reads
as confidence about its payoff.

The payoff had been measured, and was sitting in a JSON fold table the daily
run does not open. Reading it back exposed the larger problem: **the live
configuration matches no measurement in this repository.**

| | live bot | every fold table on disk |
|---|---|---|
| exit profile | `legacy` — ladder ACTIVE, measured at ≈ −1.6 pts/trade | `forward_test` — no price exits |
| holding_max_days | 20 — the worst row of the sweep | 60 |
| entry score cutoff | 60 — while the log printed 80 (finding 15) | 80 |
| entry vetoes | all five ON — measured at −2.52%/trade | mostly OFF — +1.71%/trade |

Each of the three live settings is independently the measured-worst option
available, and every figure in this audit describes the right-hand column.
`kala/expectation.py` now prints the measurement under the
recommendations — or refuses to, naming the differences, which is what it does
as shipped. **Fixed: the gap is now on screen. Closing it is a config change
the user has to make.**

Building it exposed a second defect, this one mine. The headline and the
concentration figure came from *different arms*: `+1.71%/trade` is the
fixed-baseline arm, and the only per-fold excess the saved tables carried was
the walk-forward-chosen arm's, which pools to `+1.27%` over a different trade
count. Printing `excluding the biggest fold: −0.44%` beneath `+1.71%` subtracts
one arm's quarter from the other arm's total. The v76 holding sweep shipped the
same mix in its `ex-best fold` column, and its collapse verdict was read off
it. Both arms are now saved per fold, the column names are explicit arguments
with no mixing default, and where an old table cannot support the baseline
decomposition the block says which arm it is showing and prints that arm's
pooled figure beside it. **Fixed, and caught by building the fixture with the
two columns 100 points apart so reading the wrong one cannot pass.**

### 14. A position that cannot be aged is held forever

`_bars_held` located the entry bar by exact date equality and returned a bare
`None` on a miss. Both callers wrote `if bars_held is not None and bars_held >=
max_days` with no `else`, so a `None` took the same branch as a two-day-old
position: no exit queued and no line in any report.

Two positions, same history, both 189 bars past a 15-bar limit, differing only
in whether the entry date lands on a trading bar — one was queued for sale, the
other appeared nowhere. `manual_buy` accepts any date string without validating
it as a trading day, and `daily_run` has no trading-day guard while the project
has no IDX exchange calendar, so a run on a market holiday stamps `entry_date`
with a day that has no bar.

Under `forward_test` — the profile finding 13 recommends — every price exit is
inert by design and this is the *only* rule that closes a position. `/review`
carried a second copy of the same guard and printed a bare HOLD for such a
position indefinitely.

Off-bar dates are now counted from the next open; pre-window, future and
unparseable dates return a named reason both call sites print. A mutation that
made the limit exclusive rather than inclusive **survived** the suite first
time — nothing held a position for exactly the limit — which under
`forward_test` would have run every position one bar long, forever. **Fixed.**

The user's current book is clean: all 66 dated records fall on weekdays, none
on a known IDX holiday. Latent, not realised.

### 15. The log printed one entry threshold, the scanner used another

`daily_run` logs `entry score >= {trade_cfg.backtest.score_entry_threshold}`
off the resolved profile, on every run. `kala_daily_trader` decided the
BUY cutoff with a bare `Config()` — the legacy default, 60, always, never
reading `runner_config.json`.

Under `forward_test` the log would read **80** while the scanner bought from
**60**, and the paper trader buys everything labelled BUY or STRONG BUY. The
+1.71%/trade headline was measured at baseline 80 over 5,241 trades; every
entry scoring 60-79 is outside it.

The comment directly above that log line reads: *"a strategy change this large
must never be something you have to read the source to discover."* It was
printed on every run, and it was not what ran.

Fixed via `config.live_config()`, which resolves the profile from disk and
falls back to the legacy defaults on a missing or unreadable file — so nothing
changes for a bot that has not opted in. Extracting the band ladder into a pure
`signal_for_score` also surfaced a latent ordering bug: STRONG BUY was
hardcoded at 80 and tested *before* the cutoff, so a cutoff above 80 would have
labelled 85 STRONG BUY — above the strong line, below the line deciding whether
to buy at all. **Fixed.**

### 16. Preflight said the headline recommendation does nothing

`preflight` exists to catch settings that silently have no effect. Run the
configuration this audit recommends through it:

```
WARN  'disabled_entry_vetoes' is not read by any code. It is silently
      ignored, so whatever you set it to is having no effect.
```

It is read, by `entry_settings.entry_config_from`, and it is the change worth
**+4.23 points per trade**. A user who applied the recommendation and then
checked their work was told to undo it.
`breaker_preserve_halt_when_unreadable` — a circuit-breaker safety option — was
reported the same way.

Both were missing from a hand-maintained registry whose only guard checked
`daily_run.DEFAULT_CONFIG`; neither key lives there. A registry wrong in this
direction is worse than none: a missing warning is a missed opportunity, a
false one argues the user out of a correct configuration.

Now the veto key is **imported** from the module that reads it rather than
spelled out twice, a source scan asserts every literal config key is
registered, and a test renames the constant and reloads preflight to prove the
registry tracks it. **Fixed.**

### 17. Two cost models in one run

`daily_run` runs its friction report at `spread_mode="tick_floor"` — the honest
model, where the half-spread cannot be tighter than half an IDX tick — and
books the trades those figures describe at the default `flat` 0.10%. Every
validated number in this project was measured at tick_floor.

On this account's nine holdings that is a mean round trip of **0.64% booked
against 0.87% measured**. Flat is never the dearer model, so it is a bias, not
noise: 0.23 points per trade, about **14% of the +1.71%/trade** the forward
test would be judged against, and more than half of the −0.44% ex-fold-10
figure. On a 67-rupiah name, which cannot trade inside its own 1-rupiah tick,
the gap is 1.28 points.

The forward test is the one piece of evidence this project has never had, and
every recent release has been clearing the way for it. Left alone it would have
been biased toward "live is beating the model" before a single trade.

The default stays flat — changing it rewrites a live book's arithmetic without
being asked. `"costs_spread_mode": "tick_floor"` is the opt-in, the measurement
records which model it charged, and the expectation block refuses to quote one
at the other. `"costs"`, meanwhile, was registered as a config key and read by
nothing — Finding 16 with the polarity reversed — so the registry is now
checked in both directions. **Fixed.**

### 18. The block printed a command and rejected the command's output

Verifying the three-key recommendation end to end — every claim held — turned
up a defect in the instruction itself. The NOT MEASURED block ended with a
fixed string carrying no `--tick-spread`, no `--holding-days`, no
`--baseline-threshold`. Follow it against the recommended configuration and the
resulting table records `spread_mode: flat`, which the same block then refuses
on the binding field added hours earlier. A printed instruction that cannot be
followed to a working result is the same defect as a warning that is wrong, and
this one was mine.

The command is now derived from the live setup. `build_parser()` was extracted
from `run_walkforward.main` so a test can generate the command, **parse it with
the real CLI**, build the provenance that run would save, and assert the
comparison comes back empty — across four configurations. The defect lived
between two pieces of code that never met: a string in one module and an
argparse definition in another. **Fixed.**

### 19. A money flag three ordinary typos silently ignored

The same treatment applied to the documents: `check_docs.py` compares quoted
line counts, the test-file count, every code path named in backticks, and every
documented `python foo.py --flag` command against the repository.

**The documents checked out** — 14 files, 39 commands, no broken references, no
stale counts. Worth recording plainly: a report that only ever carries bad news
stops being information.

One command needed an exemption, because `daily_run.py --capital` is read
straight from `sys.argv` and cannot appear in `--help`. The exemption was
hiding the finding:

```
--capital 3000000     override -> 3,000,000
--captial 3000000     no override        <- typo
--capital=3000000     no override        <- the form every other script accepts
-capital 3000000      no override
```

Three spellings ran at the **stored** capital — 4.7M instead of the 3M asked
for — with nothing in the log mentioning capital at all. The only symptom is
that evening's position sizing being wrong. **Fixed:** both spellings accepted,
unknown options refused, bad amounts rejected.

The checker caught its own arrival — adding its test file moved the test count
the summary quotes — and the repo's own encoding rule then caught the checker.

### 20. A killed harness left a live trading file mutated

Verifying v83 from the extracted zip, one test failed there and passed in the
source tree. The extracted copy differed by one character — mutation M8 from
`repro/mutate_live_threshold.py`, left behind when a ten-minute timeout killed
the harness mid-run. `finally` covers an exception and a Ctrl-C; it does not
cover SIGKILL.

The file left mutated decides which stocks the live bot buys, carrying an
inclusive bound turned exclusive. **The shipped zip was clean** — verified
byte-for-byte before saying so — but a build from a tree in that state would
ship a mutated live trading file with no symptom beyond an unrelated-looking
test failure.

`repro/_mutation_guard.py` now writes the original into an **fsynced sentinel
before touching the file**, and every harness restores from it on startup and
says that it did. A test SIGKILLs a real subprocess mid-mutation and asserts
recovery; another asserts no harness bypasses the guard.

Fixing it tripped `test_no_subprocess_text_mode_without_an_encoding`, which
flagged a call whose `encoding=` was right there: the scan backed up to the
nearest `subprocess.` token and landed on `subprocess.PIPE`. Finding 16 with a
different subject — a checker wrong in the direction of accusing working code,
because the fix people reach for is to silence it. **Both fixed.**

### 21. The checker accused four working scripts of rejecting their own flags

Found on a machine that was not this one. Running the suite on Windows, with
`pyportfolioopt` unbuildable there (its `ecos` dependency wants a compiler that
was not installed), produced seventeen reports of this shape:

```
PROJECT_STATUS.md: `python weighting_study.py --period` —
                   weighting_study.py does not accept --period
```

`weighting_study.py` accepts `--period`. It says so in `add_argument`. What
happened is that `check_docs.py` ran the script's real `--help`, read
**stdout + stderr without looking at the exit status**, and got

```
Traceback (most recent call last):
  File "weighting_study.py", line 25, in <module>
    import pandas as pd
ModuleNotFoundError: No module named 'pandas'
```

in which, naturally, no flag appears. A crash rendered as a flag list, and a
flag list that is missing a flag is a documentation error. Finding 16 and the
`subprocess.PIPE` false positive a third time, and the worst version of it: the
tool built to catch failures that look like normal outcomes committed one, and
in the direction that blames correct code.

Same environment, unbuilt: 162 of them here, from nine scripts.

**Three outcomes now, not two.** `--help` is trusted only when it exits 0. A
script that will not run is reported as *not checked*, with the reason quoted;
its documented flags are compared against its own source text as weaker
evidence, and that weakness is stated in the summary line. The exit status
carries the distinction — 0 clean, 1 contradicted, **2 incomplete** — because a
run that checked nothing must not look like a run that checked everything.

**And then it found two real ones.** With the exit status honoured, two scripts
turned out to fail `--help`:

| | before | after |
|---|---|---|
| `daily_run.py --help` | exit 1, "unknown option `--help`" | prints usage, exit 0 |
| `intraday_watch.py --help` | exit 0, prints **nothing** | prints usage, exit 0 |

The first was passing the old checker *by accident*: the string `--capital`
appears inside the error message complaining about `--help`, so the flag was
"found". The second is worse — `intraday_watch.py` exits silently when the
market is closed, so `--forse` (a typo) ran unforced, printed nothing and
returned 0, which is exactly what a successful forced run looks like. Both were
the `"--flag" in sys.argv` pattern of finding 19, in the two scripts that had
been *exempted* from the flag check for using it.

Both fixed: `argparse` in `intraday_watch.py`, a `USAGE` block in `daily_run.py`
whose parse now happens before any work — `--help` no longer runs the evening's
screen to reach its own usage text, and a bad `--capital` fails before a line is
logged rather than after the expectation block has already printed.

`HAND_PARSED`, the escape hatch, is now **empty**, and a test asserts it stays
that way. Every entry it ever held was a bug wearing a waiver.

### The shape of 13 through 21

| | reported | used |
|---|---|---|
| 13 | a confident BUY | no expectation stated at all |
| 14 | position aged, exit rule live | rule silently skipped for an off-bar entry |
| 15 | `entry score >= 80` | bought from 60 |
| 16 | "this setting has no effect" | the setting works, and is the best change available |
| 17 | friction at tick-floored spreads | fills booked at flat, 0.23 pts/trade cheaper |
| 18 | "to measure it, run this" | the command's own output is then refused |
| 19 | `--capital 3000000` | ran at the stored 4,748,425 |
| 20 | "restored in a finally block" | a kill left the tree mutated, silently |
| 21 | "`--period` is not a valid flag" | the script never got as far as its flags |

In a system whose arithmetic is right, the defects concentrate at the boundary
between what the code does and what the code says it does. All twenty-one
findings sit on that boundary — the last several on the boundary between what
this audit said and what it had checked, and the last one on a machine that was
not the one it was checked on.

---

## 7. Corrections ledger

Recorded because a prediction that is only cited when it lands is not a
prediction. These are the substantive reversals, not typos.

### The common-factor alarm

- **Claimed:** momentum and mean_reversion share a hidden common factor — their
  per-fold returns correlate at +0.86.
- **Actual:** withdrawn the same day. Two long-only baskets from one universe
  correlate mechanically on *raw* returns; that number says nothing.
- **Then:** re-established correctly on the excess column at **+0.803**. The
  conclusion was right and the evidence was wrong — and wrong evidence is not
  evidence, so withdrawing it was still the correct call.

### The sharia benchmark

- **Predicted:** measuring against a sharia benchmark will cut the excess
  substantially — most of the apparent alpha is the sharia screen.
- **Then:** JII raised it to +6.23%. I wrote: *"that prediction was wrong, and
  in the opposite direction."*
- **Actual:** equal-weight showed **+1.71%** — the original prediction was
  right and the retraction was the mistake. JII is 30 large caps; it credited
  the strategy for the small-cap premium of its own universe. I had flagged
  that limitation and still let the headline read as vindication.

### Which veto was worst

- **Predicted:** RSI and parabolic are the most damaging — both fire on the
  strongest names in the strongest quarters.
- **Actual:** RSI has *exactly zero* marginal effect. Parabolic was the only
  veto that *improved* the group.
- **Then:** leave-one-in reversed that too — parabolic *alone* is the worst
  single veto at −2.30%. Both measurements are correct and answer different
  questions, but I presented the marginal one as a general claim about the
  filter's quality.

### The wrong zip variant

- **Shipped:** a zip with the package renamed `kala/`, plus the instruction
  "v59 and later ship `kala/` — replace the whole folder."
- **Actual:** two variants ship every version. The working tree uses
  `kala/`. Following that instruction would have broken every import and
  the Telegram token name.
- **Why:** I read the zip list wrong and generalised from half of it. Checking
  the list first — one command — would have caught it.

### The encoding "fix"

- **Shipped:** a fix pinning subprocess encoding so Windows and Linux agree.
- **Actual:** it made things worse. Pinning only the parent's decoder broke a
  previously-accidental agreement, and the regex missed two call sites.
- **Also mine:** the original `UnicodeDecodeError` came from an emoji I had
  added, and a test that "verified" the fix was matching the string in a
  docstring rather than in code.

### The concentration figure and its headline

- **Shipped:** `+1.71%/trade, and −0.44% excluding the biggest fold` — in v76's
  holding sweep, in this document, and in the first version of the live
  expectation block.
- **Wrong:** those are two arms. `+1.71%` is the fixed-baseline arm over 5,241
  trades; `−0.44%` is the walk-forward-chosen arm's `+1.27%` over 6,082 trades
  with fold 10 removed. The subtraction was never a decomposition of either.
- **Why it survived:** the saved fold tables carried only one per-fold excess
  column, so there was nothing to compare it against. It looked like the only
  available number because it was.
- **Now:** both arms are saved per fold; the column names are explicit; the
  fallback is labelled rather than silent, and the sweep refuses it outright.

### Six source-text tests

- **Pattern:** six separate tests asserted on the *source text* of the code
  they claimed to test.
- **Actual:** every one passed while the behaviour was wrong or the block was
  unreachable. One *required* the buggy expression and failed when it was
  fixed.
- **Rule that came out of it:** if a test greps the source, it is not testing
  behaviour. Each was rewritten to call the code, which usually meant
  extracting a pure function first.

---

## 8. What was built

Most were built because a question could not otherwise be answered honestly —
and two were built after a measurement turned out to be wrong.

### Measurement

| Tool | What it does |
|---|---|
| `kala/synthetic_benchmark.py` | Equal-weighted, daily-rebalanced index over the traded universe. The benchmark that made the real answer visible. |
| `kala/expectation.py` | Reads a saved fold table back into the daily run: what a BUY has been measured to be worth, or NOT MEASURED in those words. Refuses to quote a measurement taken from a different configuration. |
| `compare_folds.py` | Compares saved fold tables on the excess column; refuses runs whose fold calendars differ. |
| `sweep_holding_walkforward.py` | Sweeps the holding period through the real walk-forward. Shells out to the runner rather than reimplementing it. |
| `diagnose_selection_overlap.py` | Jaccard overlap between strategy selections, against a random baseline. |
| `diagnose_warehouse_churn.py` | Explains why the price warehouse re-downloaded, from the warehouse itself. |
| `check_docs.py` | Compares documented counts, file references and commands against the repository. Refuses to check measured results, and says so — and distinguishes *contradicted* (exit 1) from *could not be checked here* (exit 2), which is finding 21. |

### Configuration and safety

| Tool | What it does |
|---|---|
| `kala/entry_settings.py` | Makes the five entry vetoes configurable from `runner_config.json`. Default unchanged; an unknown name raises rather than silently disabling nothing. |
| `kala/circuit_breaker.py` | Distinguishes "no drawdown" from "state could not be read". |
| `kala/universe_sources.py` | Replaced three copies of `except Exception: pass` around universe loading with one honest reader. |

### Reproductions

| Script | What it reproduces |
|---|---|
| `repro/repro_watchlist_silence.py` | The empty-watchlist failure, on demand. |
| `repro/repro_partial_telegram.py` | One chunk of three delivered, logged as complete. |
| `repro/repro_missing_benchmark.py` | A confident verdict with the alpha check silently absent. |
| `repro/mutate_state_durability.py` | Mutation harness for the state-file fixes. Now separates a stale anchor from a real survivor. |
| `repro/fold_concentration.py` | How much of a pooled result comes from how few folds. |
| `repro/repro_unmeasured_recommendation.py` | The four states of the daily screen: before, unmeasured, mismatched, aligned. |
| `repro/mutate_measured_expectation.py` | 37 mutations against the expectation block, plus one documented equivalent mutant. |
| `repro/repro_position_that_never_ages.py` | Two identical overdue positions; only one gets sold. |
| `repro/mutate_position_ageing.py` | 13 mutations against the max-holding path — the only exit rule left under forward_test. |
| `repro/repro_threshold_the_log_lied_about.py` | The cutoff the log printed vs the one the scanner applied. |
| `repro/mutate_live_threshold.py` | 10 mutations against the live BUY cutoff and its band ladder. |
| `repro/mutate_config_registry.py` | 6 mutations against the config-key registry preflight judges by. |
| `repro/repro_two_cost_models_one_run.py` | What the book charged vs what the measurement charged, per holding. |
| `repro/mutate_spread_model.py` | 11 mutations against the live cost model and its provenance. |
| `repro/mutate_doc_consistency.py` | 25 mutations against the doc checker and the two hand-parsed command lines it had exempted. |

Also: `--disable-veto` for per-filter attribution, `--benchmark EQUAL_WEIGHT`,
per-fold excess in the fold table, saved-run provenance (now including
`measured_at` and `threshold_grid_size`, without which the live path cannot
judge staleness or deflate a Sharpe), and a root `conftest.py` so `pytest`
and `python -m pytest` finally agree.

---

## 9. What is still open

Listed so nothing here reads as more settled than it is.

- **No forward test on any measured configuration.** The paper account's
  −0.83% alpha measures the live setting — legacy exits, 20-day hold, all five
  vetoes on — which no backtest in this repository has ever run. Until the two
  columns agree, the forward evidence and the backtest evidence are about
  different systems and cannot be compared at all.
- **"Not shown" is not "no edge."** A clustered t of 1.92 on fourteen folds is
  an underpowered sample, not a refutation. More history could move it either
  way.
- **Survivorship remains.** The warehouse holds tickers that exist today. The
  equal-weight benchmark shares that bias exactly, so the *excess* largely
  cancels it — but the raw figures do not.
- **The engine's remaining silent handlers.** Five were examined and
  deliberately left alone because they already announce themselves; that
  judgement is recorded in a test, not hidden.
- **No IDX exchange calendar.** `daily_run` has no trading-day guard and
  `manual_buy` does not validate its date. Finding 14's damage is closed at the
  point where it did harm, but the conditions that feed it are still there.
  Both fixes are live-behaviour changes — a guard would skip runs, validation
  would reject entries the user may have reason to record — and flipping live
  trading behaviour as a side effect of a bug fix is what this audit keeps
  finding in other people's code.

---

## 10. What to do next

The research has gone as far as the walk-forward can take it. What remains
needs elapsed time, not more code.

### 1. Make the running config the measured config

In `runner_config.json`:

```json
"exit_profile": "forward_test",
"disabled_entry_vetoes": ["rsi", "parabolic", "obv", "thin_volume", "bear"],
"costs_spread_mode": "tick_floor"
```

The third key makes the book charge what the backtest charged; without it the
forward test is biased in the strategy's favour by 0.23 points per trade
(finding 17).

The first is three changes at once — the exit ladder off, the holding period to 60,
the five vetoes off — because they are three faces of one problem: the bot runs
the measured-worst option on every axis that was measured.

Verify it took effect. The daily log will read `entry vetoes: ALL OFF` and
`exit profile: FORWARD_TEST`. Earlier drafts of this document gave that same
instruction while **no code printed the veto line** — `entry_settings.describe`
was called by nothing but its own tests. It is now emitted on every run, so the
check is finally performable.

Two things had to be fixed before this was safe to apply. Under `forward_test`
the max holding period is the *only* rule that closes a position, and Finding
14 was a way for that rule to silently never fire. And Finding 15 meant the key
did not actually move the entry cutoff at all — the log claimed 80, the scanner
kept buying from 60. On the v76 code this recommendation would have been
applied to a profile with a hole in its only exit and an entry rule that
ignored it.

**Expect far fewer BUY signals afterwards.** The cutoff goes from 60 to 80, and
at 80 the plain-BUY band is empty, so everything entered is labelled STRONG
BUY. That is not a data outage; it is the threshold the measurement was taken
at.

**Know what you are signing up for.** Under `forward_test` the median trade is
negative — around −4.8% — with a win rate near one third. It pays by holding a
majority of losers long enough to collect a minority of large winners. Cutting
a loser at −5%, which is what the live log shows happening, converts it into a
measurably worse strategy. That instinct is the ladder, and the ladder is what
this change turns off.

This does not create a proven edge. It removes a measured, significant loss of
**4.23 points per trade** from the vetoes alone — the largest single effect
found anywhere in this audit — and it makes the forward test comparable to a
backtest for the first time.

### 2. Re-measure, then let it run

```
python run_walkforward.py --strategy momentum --exit-profile forward_test \
  --disable-veto rsi parabolic obv thin_volume bear --apply-entry-vetoes \
  --max-tickers 615 --period 5y --tick-spread --warehouse results/warehouse.db \
  --min-price 0 --trust-short-cache --benchmark EQUAL_WEIGHT \
  --save-folds results/expectation.json
```

The daily run reads that file and prints what a BUY has been worth beneath the
recommendations. Then leave the paper account alone for several weeks. That
produces the one piece of evidence this project has never had, and no further
backtesting substitutes for it.

The holding period has already been swept (20/30/45/60/90): every setting
collapses to at most +0.25%/trade once its biggest fold is removed, so 60 is
kept — not because it won, but because nothing beat it for a reason.

### And if neither helps

Then the honest conclusion is that this system picks stocks no better than
buying the whole sharia basket — and what is needed is not a smarter signal but
a cheaper way to own the basket. That is a far more boring answer than the one
this project has been chasing, and a far easier one to act on.

---

*All figures are out-of-sample, walk-forward, on 569 tickers over fourteen
quarterly folds, with IDX tick-floored spreads and the asymmetric IDX fee and
tax model applied.*
