# Case study: building a trading system, then proving it doesn't work

**Status: validated negative.** This is the honest write-up of that outcome —
not a post-mortem written after giving up, but the intended final product of
the validation process this project was built around from the start.

If you came here hoping for a strategy to copy, stop: `PROJECT_STATUS.md` has
the one-line verdict, and it's "no." What follows is *why* that's the answer,
told in the order the evidence actually arrived — including the part where
the evidence briefly said the opposite, and why that turned out to be wrong.

---

## The setup

Kala is an EOD swing-trading system for the Indonesian Stock Exchange
(IDX), restricted to the ISSI sharia-compliant universe, with a Telegram bot
front end for paper trading. The trading idea itself is unremarkable —
a composite momentum score (trend position, RSI, rate of change) ranks
candidates; a rule-based exit engine (ATR stop, trailing stop, take-profit,
max holding period) manages them. Nothing exotic. The interesting part isn't
the signal; it's what it took to find out the signal doesn't survive contact
with real trading frictions, and how easy it turned out to be to fool
yourself into believing otherwise along the way.

## Building the harness before trusting the score

Before asking "does this make money," the project spent most of its early
effort making sure a "yes" answer, if one ever came, would actually mean
something:

- **No look-ahead.** Every indicator is computed causally — a value at bar
  *t* only ever depends on bars up to and including *t*. Features are
  recomputed fresh on each backtest window rather than sliced from a
  precomputed full-history series, because EMA-based indicators (MACD) carry
  exponentially-decaying memory of everything before the calculation started
  — slicing a precomputed score is *not* equivalent to computing it fresh on
  the same window, and this project caught that bug the hard way once the
  strategy interface was generalized beyond the original score (see
  `kala/strategies.py`'s module docstring for the full story).
- **Real execution frictions.** Next-open fills, not same-bar fills. IDX
  limit-lock ("ARB") handling — a position can't exit into a locked limit-down
  bar just because the backtest wants it to; it carries forward, same as a
  real order would. Asymmetric costs: buy commission, sell commission, a
  sell-only transaction tax (PPh final), and a spread — not one flat
  round-trip number.
- **Walk-forward, not in-sample fitting.** History is split into rolling
  train/test folds. The entry threshold is chosen on train data only, then
  frozen and evaluated on test data the choice never saw. Pooled
  out-of-sample trades get a one-sample t-test against zero, because a 45%
  win rate with fat winners can beat a 60% win rate with fat losers and win
  rate alone doesn't tell you that.
- **An alpha-vs-beta check.** Every trade's return is also measured against
  what the benchmark (IHSG) did over that same entry-to-exit window. A
  positive raw return that evaporates against this baseline was market
  exposure, not stock-picking skill.

This is the boring, load-bearing 80% of the project. It's also the part that
mattered most, because without it the next section would have shipped a lie.

## The number that looked real

The first honest walk-forward run, at a flat 0.10% spread assumption, showed
a weak positive edge (t≈1.65) — encouraging, not conclusive. Then the cost
model got more honest: IDX stocks below roughly 2,000 rupiah can't trade at
a spread tighter than their exchange-mandated price tick, so a flat spread
assumption understates their real cost by 2–7x. Re-running with tick-floored
spreads flipped the full-universe result negative (t=-1.35).

The natural next question: is the whole universe dead, or is it just the
cheap tier dragging it down? Filtering to stocks priced ≥ IDR 1,000 and
re-running produced a strong, well-powered result — n=2,338 trades, t=3.38,
and (this is the part that made it credible) the alpha-vs-benchmark version
of the same test came back *stronger*, t=4.79, which argued against pure
market-beta capture. This got shipped internally as a validated finding.

It was wrong, and the reason it was wrong is the most useful part of this
whole write-up.

## The bug: filtering on the future

The ≥ IDR 1,000 filter selected tickers by their **latest close** — the most
recent price in the downloaded history, not the price at each historical
trade. A stock trading at 400 rupiah in 2022 and 1,400 rupiah today passes
that filter and keeps every one of its 2022 trades in the "validated ≥1,000"
bucket, even though at the time of those trades it was a sub-1,000-rupiah
stock with sub-1,000-rupiah execution costs. Today's price is partly a
record of *which stocks already went up* — filtering on it retroactively
selects for winners and back-dates that selection onto history that didn't
have it available. It's a look-ahead bug wearing a cost-hygiene costume.

This is worth sitting with, because it's not a sloppy mistake — the code
that produced it was already tick-cost-aware, already walk-forward, already
alpha-checked. It survived three layers of honest methodology and still got
through, because the leak was in a filter that *looked* like a simple data
hygiene step ("only trade liquid, non-penny stocks") rather than a modeling
choice that needed the same point-in-time discipline as everything else. The
lesson generalizes past this project: any filter applied to backtest data
needs to be checked for whether it uses information that wouldn't have been
available at each historical decision point — universe selection is exposed
to look-ahead exactly like entry signals are, and it's easier to miss
because it doesn't feel like "the strategy."

## Retraction, confirmed two independent ways

Two separate follow-up tests, both re-run with the filter fixed to use
point-in-time price instead of latest close:

1. **`compare_exit_engines.py`**, an A/B script that applies entry vetoes
   (including the price floor) per-bar as trading actually happens, on the
   full 519-ticker universe at 5 years of history: **-0.43%/trade, t=-3.06,
   n=3,433.**
2. **A re-run of the walk-forward harness** with the look-ahead ticker
   filter removed and only the point-in-time veto left in place: **t=0.00 to
   -0.09** — flat.

Both independent measurements agree: no demonstrated edge, at any price
tier, once the selection is honest. The gap between the two negative numbers
(-0.43% vs ~0.00%) is a power difference (n=3,433 vs ~1,070), not a
disagreement.

## What actually held up

- **The infrastructure.** No-look-ahead backtesting, ARB-aware exits,
  asymmetric IDX costs, tick-floored spreads, a real walk-forward harness
  with anti-overfitting guards (train-only threshold selection, minimum
  trade counts before a threshold is trusted), and an alpha-vs-beta
  diagnostic. All of it is reusable for testing a *different* hypothesis —
  which is exactly what happened next: a strategy-zoo interface
  (`kala/strategies.py`) now lets a new idea (mean-reversion, a
  fundamental-value tilt) run through the identical harness instead of
  needing its own bespoke validation code, and a Combinatorially-Symmetric
  Cross-Validation / Deflated-Sharpe module (`kala/overfitting.py`)
  quantifies exactly the kind of multiple-testing risk that produced the
  false positive above.

  An audit on 2026-08-05 found that module had **zero callers outside its
  own tests** — the safeguard existed as code, and this paragraph claimed it
  was in force, but not one of the sixteen hypotheses had actually been run
  through it. The Deflated Sharpe is now computed inside `walk_forward`
  itself (deflating for the number of entry thresholds swept) and printed in
  every report, so the claim is true rather than aspirational. The PBO/CSCV
  half is still opt-in: `overfitting.pbo_from_walkforward_sweep` has to be
  invoked deliberately, and has not been run on the existing results.
- **The paper trader and Telegram bot.** Both work as built and are a
  reasonable low-stakes way to keep testing ideas — a corporate-action guard
  auto-adjusts split-distorted positions instead of silently misreading
  them as catastrophic losses, a live-vs-backtest edge tracker
  (`kala/edge.py`) flags if reality ever drifts from expectation in
  either direction, and a regime-conditional breakdown can show whether any
  future "edge" is concentrated in a couple of rally quarters (the way the
  *original* pre-tick-cost result turned out to be, in hindsight) instead of
  broad-based.

## Epilogue: what happened when the search was pushed much further

The write-up above ended where the *signal* research ended. It was then
pushed considerably further, on the entirely reasonable grounds that "I looked
and found nothing" is not the same claim as "there is nothing." Roughly twenty
studies later, the shape of the answer changed in a way worth recording,
because the interesting part is *which kind* of question kept failing.

**Signals kept failing, and the failures got more informative.** The count
reached fourteen hypotheses: three flavours of momentum, mean-reversion, order
flow (twice), low-volatility, two calendar effects (turn-of-month and a
Ramadan effect built from an officially-sourced date table), 52-week-high
proximity, ML re-weighting, and trailing dividend yield. Tested across two
markets where applicable. The pattern was consistent enough to become a
finding in itself: **raw results on US data looked spectacular and collapsed
to noise under the alpha check every single time** — the largest raw t-stat
recorded anywhere in the project was 10.54, and its alpha check came back
0.78. A reader who only ever reported raw numbers would have "found" several
strategies here.

**Then the category of question changed, and so did the results.** Signals ask
*which stock* and *when*. Nobody had asked *how much of each*, *how many*, or
*when to deploy*. Those turned out to be where the honest answers lived:

- **Weighting** (equal vs inverse-vol vs min-variance, four runs): naive 1/N
  was not reliably beaten — the DeMiguel result, reproduced.
- **Volatility targeting**: negative on both clean IDX windows. Plausibly
  because it re-prices exposure monthly against IDX costs ~6× the US
  equivalent — the same cost mechanism that killed the very first signal.
- **Holdings count**: risk was *still falling* at 16 names. Real,
  prediction-free risk reduction — but unbuyable at a 30M IDR account size,
  where 16 satellite positions fall below one IDX lot each.
- **Lump sum vs DCA**: lump sum won 62% of start dates, dropping to 54% once
  idle cash earns a realistic Indonesian ~4%/yr. Close to a coin flip —
  materially different from the ~2/3 US textbook figure, for the mechanical
  reason that low equity drift plus a high risk-free rate shrinks the penalty
  for holding cash. A case where the standard advice genuinely does not
  transfer.
- **Core-satellite**: the one strongly positive result — an 8-name sleeve beat
  holding the sharia index ETF alone in 90% of rolling windows. Which
  immediately raised the question below.

**The result that required arguing against ourselves.** That core-satellite
finding had an obvious way of being fake: the eight names were chosen *today*,
from companies that are *still* well-known — a filter that quietly selects for
"did not collapse over the test window." So a survivorship check was built
specifically to try to destroy it: draw hundreds of random baskets from the
same universe, and see whether they beat the core too. If most do, the edge is
the core's weakness rather than any stock-picking skill, and the finding
stands. If few do while the hand-picked eight sit near the top, it was
hindsight and must not be acted on. That test also states, in its own output,
the bias it *cannot* remove — the random pool is today's index membership, so
delisted companies are missing from every arm, and the residual bias flatters
everything including the comparison it is trying to validate.

**Two bugs found late, both of the kind that produce confident wrong answers.**
A test failure dismissed four times as "pre-existing and unrelated" turned out
to be a live cache bug: freshness was judged against the calendar date, so on
weekends and holidays the check demanded a bar that could not exist, silently
re-downloading the entire universe and burning the API quota that had already
broken one study mid-run. Alongside it, a cached ticker with too-little history
matched neither branch of the coverage logic and *vanished from the study
without a word* — quietly shrinking the universe rather than erroring. Neither
would have announced itself.

**The revised conclusion.** Not "no edge exists" but something more specific
and more useful: *in this corner of the market, the levers that survive honest
testing are structural rather than predictive.* Allocation across asset
classes, cost control, staying invested, and deployment discipline all showed
measurable effects. Every attempt to forecast which stock, or when, did not —
across fourteen hypotheses and two markets.

## What this project is not

It's not a live *trading* strategy, and the signal research shouldn't be
funded with money anyone needs to grow. The investment decision it produced
was to stop hunting an edge in EOD swing trading on sharia-screened IDX names
and hold a diversified, low-cost, multi-asset allocation instead — informed by
this project's own negative results, which remains arguably its most useful
output. What changed in the epilogue is only that the *portfolio-construction*
questions turned out to be worth asking properly, and to have answers that a
generic "just buy the index" recommendation would have gotten wrong for this
specific market.

## Why publish a negative result at all

Most public trading-strategy write-ups only exist because the strategy
looked good enough to write up — which is exactly the selection bias this
project spent most of its engineering effort trying to route around
internally, and would be hypocritical to then reproduce externally by only
publishing if the number had come out positive. The methodology is the
product here, not the signal. If it saves someone else the time this project
spent finding (and then un-finding) a look-ahead-inflated 3.38 t-stat, that's
a better return than the strategy itself ever produced.
