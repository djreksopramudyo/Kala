# Kala

A quantitative research and paper-trading system for the Indonesian Stock
Exchange (IDX), built to answer one question honestly: **does any of this
actually beat buying the index?**

Sixteen signal hypotheses were tested. None survived. Then the system that
produced that answer was audited against itself, and twenty-one defects were found
— every one of them a case of the code reporting something the code
contradicts.

Both halves are the point. The nulls are only worth something if the machinery
that produced them can be trusted, and the only way to find out was to attack
it.

---

## Part one — the research

| | |
|---|---|
| Signal hypotheses tested | **16** |
| Surviving a benchmark-excess ("alpha") check | **0** |
| Where the real answers turned up | portfolio *construction*, not signals |

Momentum, mean-reversion, 12-1 long-horizon momentum, low volatility,
turn-of-month, Ramadan seasonality, 52-week-high proximity, dividend yield,
support/resistance, multi-horizon trend, ML re-weighting, order flow — all
tested walk-forward, all null or negative once measured against the right
benchmark. Several were *confidently* negative on real statistical power, not
just underpowered nulls.

**The recurring lesson:** every US raw result looked spectacular and died under
the alpha check. The largest raw t-statistic in the study was **10.54**; its
alpha t was **0.78**. Raw returns alone would have "found" several strategies
here.

### The one positive result, stated honestly

Portfolio construction is where something worked. A core-satellite allocation —
an index core plus a small satellite sleeve — beat the index-only portfolio in
**90% of rolling windows** over the full 8-year sample.

Then the survivorship check was run on it, and it is the most interesting
number in the project: **100% of randomly chosen baskets also beat the core**,
with the hand-picked eight at the **1st percentile** of that random
distribution.

The sleeve earned its risk. The stock *picking* inside it did worse than
chance. The asset-class tilt paid; the skill did not.

Canonical status: [`PROJECT_STATUS.md`](PROJECT_STATUS.md). Narrative version:
[`CASE_STUDY.md`](CASE_STUDY.md).

---

## Why the nulls are trustworthy

A null result is only worth anything if the test could have found an edge.

**Walk-forward, out-of-sample.** Thresholds are chosen on a training window and
evaluated on the untouched test window that follows (`kala/walkforward.py`).

**Benchmark excess, not raw return.** Each trade is measured against the
benchmark's move *over that trade's own holding window*, looked up as-of the
entry date. A strategy that makes money in a rising market scores zero.

**Clustered t-statistics.** Trades opened on the same day share that day's
move, so the plain t over-rejects — 4.4% false-positive when nothing is shared,
31.5% at 40% shared variance. `clustered_t_stat` clusters by entry date.

**Deflated Sharpe.** `deflated_sharpe_ratio` (Bailey & López de Prado) discounts
for having picked the best of N attempts — the multiple-testing correction that
sixteen hypotheses demand.

**Honest costs.** IDX charges a sell-side transaction tax on top of the broker
fee, and the spread cannot be tighter than one price tick. `kala/config.py`
carries both, with the tick floor by price tier and the auto-rejection band.

**Execution realism.** Signals fill at the *next* bar's open. A position locked
limit-down ("ARB") is carried, not fantasy-filled at a stop that could not have
traded.

**Survivorship checks.** Any result found on a hand-picked basket is re-run
against random baskets from the same universe — which is what turned the
core-satellite result from a success story into an honest one.

---

## Part two — auditing the system against itself

Twenty-one defects, found under one rule: *a failure must never be able to look
like a normal outcome.* None was an arithmetic error. Every one was a number
the system reported that the system's own behaviour contradicted.

A representative few:

| | reported | actually did |
|---|---|---|
| a confident BUY | score 82/100, R:R 2.4:1 | no measured expectation stated at all |
| position aged, exit rule live | — | rule silently skipped for an off-bar entry date |
| `entry score >= 80` in the log | 80 | bought from 60 |
| "this setting has no effect" | — | it worked, and was the best change available |
| friction report at tick-floored spreads | — | fills booked 0.23 pts/trade cheaper |
| "to measure it, run this command" | — | the command's own output was then refused |
| "`--period` is not a valid flag" | ×17 | the script never got as far as its flags |

The last five were found by turning the same question on the audit's *own*
output — its recommendation, its printed instructions, its documents, and
finally its tooling: caught first leaving a live trading file mutated after
being killed mid-run, and then, on a machine missing an optional dependency,
reading a script's import traceback as that script's list of accepted flags and
reporting seventeen working commands as documentation errors.

Full register with reproductions: [`AUDIT_SUMMARY.md`](AUDIT_SUMMARY.md).

### How the fixes are verified

Every fix carries a test that was **verified to fail when the bug is put
back** — not assumed to. `repro/mutate_*.py` are seven mutation harnesses that
re-insert each defect and assert the suite goes red. They distinguish three
outcomes, which matters:

- **caught** — a test failed, the fix is real
- **SURVIVED** — the mutation applied and nothing noticed; a genuine gap
- **STALE ANCHOR** — the mutation never applied, so *nothing was measured*, which is not evidence either way

That third category caught real holes, including a boundary condition where
`>=` became `>` and the entire suite stayed green.

`repro/repro_*.py` reproduce each defect on demand, and `check_docs.py`
verifies that every count, file reference and command in the documentation
matches the repository — because six such figures had been synced by hand. It
runs each documented command's real `--help`, and reports three outcomes rather
than two: clean (exit 0), contradicted (exit 1), and **could not be checked
here** (exit 2, naming the script and the reason). Collapsing that third case
into one of the other two is finding 21.

---

## Layout

```
kala/                  74 modules — the tested engine
  scoring.py           the composite signal, in one place
  entries.py           entry vetoes (configurable; measured cost documented)
  exits.py             4-phase trailing stop (never loosens)
  backtest.py          next-open fills, ARB carry, asymmetric costs
  walkforward.py       out-of-sample harness + clustered t
  overfitting.py       deflated Sharpe
  expectation.py       what a BUY has been measured to be worth, on the live screen
  config.py            IDX cost model, tick floor, auto-rejection band
  strategy_*.py        11 hypothesis implementations
tests/                 135 files, 2,116 tests
repro/                 7 reproductions + 7 mutation harnesses
check_docs.py          documentation-vs-repository consistency
*_study.py             runnable CLI per research question
daily_run.py           the scheduled end-of-day run
```

Four-stage lifecycle — recommend, buy, manage, exit — with the exact entry
point for each in [`HOW_IT_WORKS.md`](HOW_IT_WORKS.md).

---

## Running it

```bash
pip install -r requirements.txt
pytest -q                              # 2,116 passed, 2 skipped
ruff check .
python check_docs.py                   # docs vs repository
python repro/mutate_measured_expectation.py    # re-insert 37 defects, expect all caught
```

Live operation needs a `runner_config.json` (Telegram credentials, capital,
sizing) which is gitignored and not in this repository — see
[`DEPLOY_CHECKLIST.md`](DEPLOY_CHECKLIST.md) and [`DEPLOY_VPS.md`](DEPLOY_VPS.md).

---

## Scope and status

This is a **paper-trading and research system**. It places no real orders.

The signal research phase is closed. Two things remain open and are listed as
open rather than quietly dropped: a fundamental value/quality screen blocked on
a monthly archive accumulating calendar time, and the Ramadan effect, which
needs more independent years rather than more code.

The audit's own remaining item needs elapsed time, not code — running the
measured configuration forward for several weeks, which is the one piece of
evidence this project has never had.

Nothing here is investment advice.

---

## Documentation map

| file | what it is |
|---|---|
| [`PROJECT_STATUS.md`](PROJECT_STATUS.md) | canonical validation status — the answer to "does it work" |
| [`AUDIT_SUMMARY.md`](AUDIT_SUMMARY.md) | the twenty-one findings, with reproductions |
| [`CASE_STUDY.md`](CASE_STUDY.md) | the narrative version, written for a reader |
| [`HOW_IT_WORKS.md`](HOW_IT_WORKS.md) | how the pieces fit; the daily routine |
| [`CHANGES.md`](CHANGES.md) | what changed and why |
| [`DEPLOY_CHECKLIST.md`](DEPLOY_CHECKLIST.md) | research → funded portfolio |
