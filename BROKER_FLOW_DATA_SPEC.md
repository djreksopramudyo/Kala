# Broker-flow / bandarmology data — vendor checklist and integration spec

**Status: adapter BUILT and confirmed against the real API (2026-07-22).**
`kala/broker_flow_archive.py` (storage) and `kala/invezgo_fetch.py` (the
Invezgo-specific fetch/normalize layer) both exist and are tested. Two
required params — `market` and the exact `investor` enum values — are
**undocumented on the "Test Request" console page** (it silently fills in
defaults that don't show up in the copied URL) but ARE in the real OpenAPI
spec once you have it; see "Confirmed params" below.

## Invezgo — confirmed from their OpenAPI docs (2026-07-22)

- **Base URL**: `https://api.invezgo.com`
- **Auth**: static bearer token — `Authorization: Bearer YOUR_SECRET_TOKEN`
  header on every request. Simple to wire via an env var, same pattern as
  every other credential in this project (Telegram token, Reddit OAuth).
- **Historical depth: capped at 2 years back, on every endpoint, on every
  paid retail tier (Advance/Prime/Max).** Deeper history needs their
  unpriced "Enterprise" plan (contact admin@invezgo.com). This is
  confirmed from their own disclaimer text, not inferred. Practical
  effect: walk-forward runs against this data get ~3-4 folds instead of
  the 14 folds a 5-year OHLCV run gets — real, but statistically weaker
  than momentum/mean-reversion's tests. One endpoint's doc page (`/analysis/top/change`)
  separately claims "Data Awal: 2010-01-01" ("initial data from
  2010-01-01"), which reads like it contradicts the 2-year cap — probably
  means "the underlying dataset starts there" vs. "what your plan can
  actually query," but this is worth asking Invezgo support to confirm
  rather than assuming either way.
- **Rate limits at the tiers actually worth considering**: Advance (Rp
  499,900/mo discounted) — 250 req/min, 30,000 req/month. Prime (Rp
  999,000/mo) — 500 req/min, 65,000 req/month. **Confirmed**: a single
  call CAN return a range of dates (`from`/`to`), but the response is
  aggregated over that whole range, not one row per day — so a daily
  point-in-time archive still costs one call per ticker per day. At
  30,000 req/month that's ~40 tickers/day covered daily, or the full
  ~600-ticker sharia universe backfilled roughly every 15 trading days.
- **Real endpoint paths** (nav labels differ from actual paths):
  - `/analysis/top/foreign` — "Top Foreign Flow"
  - `/analysis/top/accumulation` — "Top BDM Flow" (BDM = bandar/broker accumulation)
  - `/analysis/top/ritel` — "Top Ritel Flow"
  - `/analysis/summary/stock/{code}` — "Stock Broker Summary" (per-broker breakdown)
  - `/analysis/summary/broker/{code}` — "Broker Broker Summary" (reverse lookup)
  - `/analysis/inventory-chart/stock/{code}` — "Stock Inventory Chart" (cumulative broker position over time — the actual "accumulation zone" data real bandarmology uses)
  - `/analysis/shareholder-insider`, `/analysis/insider-chart/{code}` — insider transactions
  - `/analysis/financial-statement/{code}` — params: `statement` (BS/IS/CF), `type` (FY/Q/Q1-4), `limit` (example value 8 in the OpenAPI spec). A `limit` defaulting to 8 strongly suggests this returns MULTIPLE historical periods, not just the latest — **if confirmed, this unblocks the fundamental-value strategy too**, which `kala/fundamental_screen.py` marked permanently stuck specifically for lack of point-in-time fundamentals. Worth a probe call independently of the bandarmology work, same pattern as `probe_invezgo.py`.
  - `/analysis/calendar` — corporate action calendar, filterable by code/date/type (IPO, REVERSE split, RIGHT issue, RUPS_RESULT, etc.), paginated. Bonus use: could make `papertrade.py`'s corporate-action guard **proactive** (look up a scheduled split ahead of time) instead of only reactive (detecting one after the fact via price-magnitude heuristics, see `apply_corporate_action_adjustment`).
  - `/analysis/list/index` and `/analysis/information/{code}` both carry Invezgo's own sharia tagging (`category: ["SYARIAH", ...]`, and an index category literally named `"sharia"` covering JII/JII70/ISSI) — worth cross-checking against `kala.universe.ALL_SHARIA_STOCKS` for drift, not necessarily replacing it.

## Confirmed params (live API calls + the real OpenAPI spec, 2026-07-22)

`GET /analysis/summary/stock/{code}` — the endpoint `kala/invezgo_fetch.py`
actually uses:

| Param | Required | Values | Notes |
|---|---|---|---|
| `code` | yes | e.g. `BBCA` | bare code, no `.JK` |
| `from`, `to` | yes | `YYYY-MM-DD` | `from == to` (a genuine single day) works fine — confirmed live |
| `investor` | yes | `all`, `f`, `d` | **not** the words "foreign"/"domestic" — a wrong value 422s |
| `market` | yes | `RG`, `NG`, `TN` | IDX board: Reguler/Negosiasi/Tunai. **Undocumented on the interactive "Test Request" console** (it silently defaults this, which is why the first real calls all 422'd with "market should be string, but got undefined") but present in the actual OpenAPI spec. Use `RG` — the normal continuous market. |

Response: a bare JSON array, one object per broker, **aggregated over the
whole from/to range** (not a daily series baked into one call — daily needs
one call per day, from==to). Every number is a string. Confirmed live:
`investor=f` returns the SAME per-broker shape as `investor=all` (same
broker codes), not a single pre-aggregated foreign row — most brokers read
all-zero, a handful carry real foreign buy/sell/net. Summing `net_value`
across every row in the response gives the stock's total foreign net for
that period — that's what `fetch_daily_foreign_net` does, and it's now
confirmed correct rather than assumed.

**Daily point-in-time cadence is confirmed feasible**: `from == to` works,
so the archive's one-row-per-day schema is achievable as originally
designed. At 30,000 req/month that's ~1,000 calls/day, i.e. ~40 tickers
covered daily, or the full ~600-ticker sharia universe backfilled roughly
every 15 trading days.

`GET /analysis/inventory-chart/stock/{code}` (accumulation-over-time,
lower priority, not yet called): also needs `market` (here `ALL`/`RG`/`NG`/`TN`
— `ALL` is valid on this endpoint, unlike summary/stock) and additionally
`scope` (`vol`/`val`/`freq`) and `investor` (`all`/`f`/`d`); `limit`,
`filter`, `filter_operator`, `filter_value` are optional. Full param list
now known from the OpenAPI spec; response shape still unprobed.

`GET /analysis/financial-statement/{code}`: `statement` (`BS`/`IS`/`CF`),
`type` (`FY`/`Q`/`Q1`-`Q4`), `limit` (example value `8`) — **CONFIRMED
real multiple historical periods** via `probe_financial_statement.py`
(2026-07-23, saved as `tests/fixtures/invezgo_financial_statement_bbca_is_*.json`):
an 8-quarter pull and a 7-year annual pull both returned genuinely
different values per period, not a repeated snapshot. This is the
biggest unconfirmed-to-confirmed jump of the week — see
`kala/fundamental_screen.py`'s updated module docstring for what it
actually means and the one real blocker left (point-in-time integrity —
unconfirmed whether historical periods get revised/restated on later
queries). Adapter/strategy not built yet on purpose, to preserve this
session's remaining Invezgo budget for the bandarmology backfill; sized
similarly to the broker-flow adapter when someone does pick it up.

## Why this exists

Both `PROJECT_STATUS.md`-tested hypotheses so far (momentum, mean-
reversion) use only price/volume. Broker-flow data — who's net buying or
selling a stock — is a mechanically different kind of signal: order-flow
/ "follow the smart money" rather than price-pattern-based. Worth testing
as a third, genuinely independent hypothesis once real data exists.

## General vendor checklist (kept for reference — Invezgo is chosen, this was the process that got us there)

Ask these questions of both Invezgo and Sectors.app's docs/sales before
committing. I couldn't get definitive answers myself — every pricing page
I tried (both vendors, plus a third-party Invezgo review) returned a 403
from automated fetching, so this needs a human clicking through their
signup flow.

1. **Historical depth of the broker-flow / foreign-flow data specifically**
   (not their general financials history, which may go back further than
   the flow data does). Need at least 2-3 years to build real walk-forward
   folds the same way `run_walkforward.py` does for OHLCV; 5 years would
   match this project's usual `--period 5y` runs.
2. **Point-in-time integrity**: does a query for "broker summary on
   2024-03-15" return exactly what would have been visible on that date,
   or can historical values be revised/restated later? (Same discipline
   this project already applies to OHLCV and fundamentals — see
   `kala/edge.py`'s look-ahead retraction story for why this matters
   more than it sounds like it should.)
3. **Bulk historical pull vs. single-day query**: can you request e.g.
   "5 years of daily foreign-flow for these 600 tickers" in a reasonable
   number of API calls, or is it one ticker/one day per call? The second
   shape makes backfilling the archive impractical (600 tickers x 1,250
   trading days = 750,000 calls) — worth knowing before paying, not after.
4. **Universe coverage**: does it cover the ISSI/sharia-screened universe
   this project trades (`kala.universe.ALL_SHARIA_STOCKS`, ~600
   tickers), or just large-caps/LQ45?
5. **Granularity available at your price tier**: net foreign flow only
   (cheaper, more common), or full per-broker buy/sell breakdown
   (bandarmology proper — which broker codes are accumulating). The
   schema below supports both; only net flow is required.
6. **Rate limits** at whatever tier you'd actually pay for — matters for
   how long a full-universe backfill would take to run.

## Canonical data shape (what `broker_flow_archive.py` stores)

One row per `(ticker, date, source)`:

| Column | Required? | Meaning |
|---|---|---|
| `foreign_net_value` | **Yes** | Net foreign buy value, IDR. Positive = net foreign buying. The one figure expected from any vendor/tier. |
| `foreign_buy_value` | No | Gross foreign buy value, IDR — only if the vendor's tier breaks it out. |
| `foreign_sell_value` | No | Gross foreign sell value, IDR — same. |
| `foreign_net_volume` | No | Net foreign flow in shares rather than IDR value. |

Optional fields are stored as **NULL**, never 0, when a vendor doesn't
report them — 0 would silently claim "measured, no activity" when the
truth is "not available." (This project already got bitten once by
exactly this NaN-vs-0 confusion, in the `/checkstop` false-alarm bug —
see `kala/intraday.py`'s NaN-guard history if you want the story.)

`source` (`"invezgo"` / `"sectors"` / etc.) is tracked per row, so
switching vendors later — or running both side by side to cross-check —
doesn't mean silently overwriting one vendor's numbers with another's.

## What's already built (`kala/broker_flow_archive.py`)

```python
from kala.broker_flow_archive import BrokerFlowArchive

archive = BrokerFlowArchive("results/broker_flow.db")
archive.upsert("ANTM.JK", "invezgo", df)          # df: DatetimeIndex, columns above
cached = archive.read("ANTM.JK", source="invezgo", start="2023-01-01", end="2024-01-01")

# or, once a fetch adapter exists, gap-aware like kala.warehouse:
df = archive.get_or_fetch("ANTM.JK", "invezgo", "2023-01-01", "2024-06-01",
                          fetch_fn=lambda t, s, e: my_vendor_adapter(t, s, e))
```

18 tests cover upsert/read round-trips, NULL-vs-0 handling, multi-vendor
separation, date-range filtering, and the gap-aware `get_or_fetch` path —
same rigor as `kala.warehouse` and `kala.sentiment_archive`.

## BUILT (`kala/invezgo_fetch.py`, 15 tests) — confirmed against the LIVE API

- `InvezgoClient` — authenticated GET, token from `KALA_INVEZGO_TOKEN`
  (env-var-first, same pattern as the Telegram/Reddit creds; never
  `runner_config.json`). Sends `market` (default `RG`) on every call.
- `broker_summary(code, from, to, investor="all", market="RG")` — the raw
  per-broker call, params matching the confirmed table above exactly.
- `_to_float` — parses Invezgo's stringified numbers, returns None (not 0)
  for null/empty, feeding the archive's NULL-vs-0 discipline.
- `fetch_daily_foreign_net(ticker, start, end, investor="f", market="RG")`
  — a drop-in `fetch_fn` for `BrokerFlowArchive.get_or_fetch`: loops
  business days (one call each, from==to — confirmed to work) and SUMS
  `net_value` across returned rows. Confirmed (not assumed): `investor="f"`
  returns per-broker rows, not one aggregate, so summing is correct.
- `broker_net_frame(rows)` — tidy per-broker DataFrame for the
  bandarmology-concentration signal (who's accumulating), straight from
  `investor=all` data.

## Two strategy-zoo entries, same backfill, zero extra API cost

**`kala/strategy_foreign_flow.py`** — registered as `"foreign_flow"` (10
tests). Scores on a rolling z-score of cumulative foreign net flow vs. the
ticker's OWN recent norm (not a raw IDR threshold, which would just rank
by market cap).

**`kala/strategy_broker_concentration.py`** — registered as
`"broker_concentration"` (7 tests). A refinement, not a separate data
pull: `fetch_daily_foreign_net` already sees the full per-broker breakdown
before summing it into `foreign_net_value` — `foreign_top_broker_share`
(what fraction of the day's total foreign activity came from the single
most active broker) is computed from that SAME response and stored
alongside, at zero extra API cost. Scores high only when foreign buying is
BOTH strong AND concentrated in relatively few brokers (a conviction
signal) — concentrated *selling*, or diffuse buying spread across many
brokers, scores low. `BrokerFlowArchive` migrates existing databases in
place (`ALTER TABLE ... ADD COLUMN`) — an already-backfilled
`broker_flow.db` gains this column automatically, old rows just read NULL
for it, no re-fetch needed.

Both merge via `attach_foreign_flow()` (generic over which archive column
it merges — called twice, chained, to get both columns onto the same
frame) and are wired into `run_walkforward.py` via `--broker-flow-db`. A
ticker with no archive coverage scores NaN on either and simply never
trades. UNTESTED ON REAL DATA — both signals are proven against synthetic
flow; the actual money question needs the archive backfilled first.

## What's left

1. **Backfill the archive** (`backfill_broker_flow.py`) — budget-aware,
   resumable, now with 429 retry/backoff for a big run. Both strategies'
   columns land from the same calls; no separate backfill needed for
   `broker_concentration`.
2. **Run the actual walk-forward verdict** on each:
   `python run_walkforward.py --strategy foreign_flow --broker-flow-db results/broker_flow.db --period <however far back the archive reaches>`
   (swap `foreign_flow` for `broker_concentration` for the second) — same
   honest treatment momentum and mean-reversion got. No claim of edge
   until that run produces a number.
3. **(bonus, lower priority)** inventory-chart's response shape (params
   now known, never called); `/analysis/financial-statement/{code}`'s
   `limit` param suggests real history — worth a probe for
   `fundamental_screen.py`; `--corporate-calendar` for a proactive
   split/rights guard.
