# Extracting the validation harness as a standalone library — notes

**Status: notes and a plan, not a completed extraction.** No package was
split out, published, or renamed here — this document maps what's already
market-agnostic, what's genuinely IDX-specific, and what a real extraction
would need to change, so the decision to actually do it (or not) can be made
with the real scope in front of it instead of a guess.

## Why this is worth doing at all

The validation harness (walk-forward, cost-sensitivity sweep, PBO/Deflated
Sharpe, the strategy-zoo interface) has nothing to do with Indonesia or
sharia screening — it's "does this trading rule have an out-of-sample edge,
net of costs, and how much of that edge is p-hacked." That question is the
same for a US equity swing strategy, a crypto momentum system, or an FX
carry trade. The only reason it currently lives inside `kala/` is that
it was built to answer one specific question about one specific market.

## Module-by-module: generic vs market-specific

| Module | Generic? | Notes |
|---|---|---|
| `walkforward.py` | **Yes, nearly as-is.** | Folds, threshold sweep, `trade_stats`, the alpha-vs-beta diagnostic — all pure pandas/stdlib math over an OHLCV DataFrame. Its only market-specific dependency is `backtest.backtest_ticker`, which is itself mostly generic (see below). |
| `overfitting.py` | **Yes, fully.** | PBO (CSCV) and Deflated Sharpe operate on a plain (periods × configs) return matrix — no market assumptions anywhere. Already has zero IDX-specific code. Could be copy-pasted into a new package today unchanged. |
| `strategies.py` | **Yes, fully.** | The `Strategy` dataclass + registry pattern is a generic plugin interface. `momentum` is the only IDX-*flavored* thing registered, and even that's just composite_score with no exchange-specific logic in the scoring math itself. |
| `cost_sensitivity.py` | **Yes, fully.** | Scales whatever `CostModel` it's given; doesn't know what currency or exchange the numbers are in. |
| `regime.py` / `regime_filter.py` | **Yes, the mechanism.** | SMA-crossover and ADX-based classification are generic technical constructs. The specific choice of benchmark (`^JKSE`) is a caller decision, not something baked into the module. |
| `backtest.py` | **Mostly, with one real exception.** | Next-open fills, ATR stops, trailing stops, max-holding-period exits — all generic. The one genuinely exchange-specific mechanic is **limit-lock ("ARB") carry**: a position can't fill on a bar that's locked at the daily price-move limit. This is already parameterized (`BacktestConfig.arb_limit_pct`, `arb_lock_tol_pct`), so it ports to any market with circuit-breaker bands (several Asian exchanges have this; US equities effectively don't) by changing the config value — or setting `arb_limit_pct` high enough that it never fires, for markets without daily limits at all. |
| `config.py` (`CostModel`) | **Structure yes, defaults no.** | The shape (buy fee, sell fee, sell-only tax, spread, tick-floor mode) generalizes to most markets' cost stacks. The *numbers* (`buy_commission=0.0019`, `sell_tax=0.0010` — Indonesia's PPh final transaction tax) are IDX-specific and would need new defaults per market; not every market has an asymmetric sell-side tax. |
| `entries.py` (guardrails) | **Mostly generic, one IDX-specific veto.** | RSI-overbought, parabolic-ROC, OBV-distribution, thin-volume vetoes are all generic technical rules. `veto_cheap_stock`/`min_price_idr` is IDX-specific — it exists because of IDX's per-tick spread floor at low rupiah prices, a real mechanic in *some* markets (tick-size-constrained spreads) but not universal. |
| `papertrade.py` | **No — this is the IDX-specific layer.** | `LOT_SIZE = 100` (IDX trades in lots), WIB-timezone daily cycle assumptions, and the corporate-action guard's price-magnitude heuristics are all tuned to this market. This module is closer to "a working example of USING the generic harness for one market" than something to extract. |
| `universe.py` | **No.** | The ISSI sharia-compliant ticker list is Indonesia-specific by definition. In an extracted library this becomes "bring your own universe" — a plain `list[str]` the caller supplies, exactly as `walkforward.py` already expects (it never imports `universe.py`). |
| `dataclasses (Trade, FoldResult, WalkForwardReport, ...)` | **Yes.** | Plain data containers; nothing market-specific in their shape. |

**The short version:** the actual validation math (`walkforward.py`,
`overfitting.py`, `strategies.py`, `cost_sensitivity.py`) is already
decoupled from IDX specifics almost by accident, because it was written
against `{ticker: OHLCV DataFrame}` + a `Config` object rather than against
this project's universe or currency directly. The IDX-specific surface area
is concentrated in exactly the three places you'd expect — the live
paper-trading layer (`papertrade.py`), the entry guardrails tuned to IDX
tick economics (one line in `entries.py`), and the universe list itself.

## What a real extraction would need to do

1. **New package**, e.g. `wf-validate` or similar, containing (verbatim or
   near-verbatim): `walkforward.py`, `overfitting.py`, `strategies.py`,
   `cost_sensitivity.py`, `regime.py`/`regime_filter.py`, the relevant
   dataclasses from `backtest.py` (`Trade`, `BacktestResult`), and a trimmed
   `backtest_ticker` with the ARB mechanic made fully optional (default
   `arb_limit_pct=None` = disabled, since most markets don't have daily
   limit locks).
2. **Rename the IDX-flavored config defaults** to neutral ones and document
   them as "IDX example values, override for your market" rather than
   defaults that quietly assume Jakarta.
3. **Drop the hard dependency on `universe.py`** — already true today for
   the validation modules; just needs the import removed from any example
   code that currently pulls in `ALL_SHARIA_STOCKS` for convenience.
4. **Decide what happens to `entries.py`'s guardrails.** These are useful
   generic building blocks (overbought/parabolic/thin-volume/distribution
   vetoes) bundled with one IDX-specific one (`min_price_idr`). Cleanest
   split: ship the generic vetoes in the library, leave `min_price_idr` and
   any other tick-economics veto as an example extension in this repo, not
   in the extracted package.
5. **Tests port almost directly.** `tests/test_walkforward.py`,
   `tests/test_overfitting.py`, `tests/test_strategies.py`, and
   `tests/test_cost_sensitivity.py` already use synthetic OHLCV data with
   no IDX-specific fixtures — they were written to test the generic
   mechanism, so they'd need only an import-path change, not a rewrite.

## What this project gets from writing this down instead of just doing it

Actually publishing a package is a maintenance commitment (versioning,
issue triage, a README that has to stay honest about what's validated and
what isn't) this project doesn't currently have the ongoing attention to
support well. Writing down *where the seams already are* costs little and
means the extraction is a mechanical afternoon's work if it's ever actually
needed — by this project's own author, or by someone reading this repo who
wants the walk-forward + PBO/DSR harness for a market that isn't IDX.
