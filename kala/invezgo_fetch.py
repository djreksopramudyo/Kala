"""
Invezgo broker-flow adapter — the one genuinely vendor-specific piece that
turns Invezgo's API responses into the canonical columns
``kala.broker_flow_archive`` stores. See ``BROKER_FLOW_DATA_SPEC.md`` for the
vendor research that led here.

CONFIRMED (from real, live API calls against BBCA — not the docs, which
omitted two required params entirely)
--------------------------------------------------------------------------
* Base URL ``https://api.invezgo.com``; auth is a static bearer token
  (``Authorization: Bearer <token>``), read from ``KALA_INVEZGO_TOKEN`` —
  same env-var-first pattern as every other credential in this project
  (see kala/notify.py's resolve_telegram_credentials).
* ``GET /analysis/summary/stock/{code}`` REQUIRES ``market`` (one of
  ``RG``/``NG``/``TN`` — IDX board codes: Reguler/Negosiasi/Tunai; **RG**
  is the normal continuous market and what this adapter always sends) and
  ``investor`` (one of ``all``/``f``/``d`` — NOT the words "foreign"/
  "domestic"). Both 422 with a message naming the missing/invalid field if
  wrong — that's how these were found; the API console's "Test Request"
  button silently filled in defaults that never showed up in the copied URL.
* Returns a BARE JSON ARRAY, one object per broker, AGGREGATED over the
  whole from/to range. Every numeric field is a STRING. Real fields: code,
  name, buy_freq, buy_volume, buy_value, sell_freq, sell_volume,
  sell_value, buy_avg, sell_avg, net_value, net_volume, net_freq.
* ``investor=all``: net_value sums to exactly 0 across all brokers
  (market-wide every buy is someone's sell).
* ``investor=f`` returns the SAME per-broker shape (same 83 broker codes as
  investor=all for BBCA), NOT a single aggregate foreign row — most brokers
  read all-zero (no foreign flow through them that period), a handful carry
  the real foreign buy/sell/net for that broker. Summing net_value across
  every row therefore gives the stock's total foreign net flow.
* ``from == to`` (a genuine single day) works fine once ``market`` is
  present — confirmed directly, so the daily-loop design below is sound.

DAILY vs RANGE, and the API budget
----------------------------------
Because the endpoint aggregates over from/to, a DAILY point-in-time series
(what broker_flow_archive.py's schema and any honest walk-forward backtest
need) requires one call per ticker per day (from==to). At Invezgo's 30,000
req/month tier that's ~40 tickers covered daily, or the full ~600-ticker
sharia universe backfilled roughly every 15 trading days. fetch_daily_foreign_net
makes exactly that per-day loop.

STILL UNKNOWN
-------------
``/analysis/inventory-chart/stock/{code}`` (the accumulation-over-time
endpoint) additionally requires an undocumented ``scope`` param whose valid
values weren't found — lower priority than the summary endpoint above
(which is everything fetch_daily_foreign_net needs) and left for later.
"""

from __future__ import annotations

import os
import time

import pandas as pd
import requests

from .logging_util import log_swallowed

BASE_URL = "https://api.invezgo.com"
TOKEN_ENV = "KALA_INVEZGO_TOKEN"

SOURCE = "invezgo"
DEFAULT_MARKET = "RG"    # Reguler -- the normal continuous market

# Retried with backoff rather than allowed to escape. 429 is rate limiting;
# 5xx is a vendor-side blip. Both are transient, and both used to cost the
# backfill a whole day per occurrence -- a hole the archive cannot distinguish
# from "that day genuinely had no flow", because covered_range only checks the
# first and last stored date.
RETRY_STATUS_CODES = (429, 500, 502, 503, 504)
TRANSIENT_NETWORK_ERRORS = (requests.Timeout, requests.ConnectionError)
VALID_MARKETS = ("RG", "NG", "TN")
VALID_INVESTORS = ("all", "f", "d")


def _to_float(value) -> float | None:
    """Invezgo returns every number as a string (or null). Parse to float,
    or None for null / empty / unparseable — never 0, so a genuinely absent
    figure is stored NULL by the archive, not silently claimed as measured
    zero (the NaN-vs-0 discipline the archive schema is built on)."""
    if value is None:
        return None
    try:
        s = str(value).strip()
        return float(s) if s else None
    except (TypeError, ValueError):
        return None


class InvezgoClient:
    """Thin authenticated GET wrapper. One requests call per request, same
    stateless pattern as the rest of this project's network code. Retries
    on 429 (rate limit) with exponential backoff -- without this, a big
    backfill run silently drops whichever days happen to land on a
    throttled request, leaving gaps in the archive that LOOK complete
    (get_or_fetch/covered_range have no way to tell "never fetched" apart
    from "fetched and empty") but aren't."""

    def __init__(self, token: str | None = None, base_url: str = BASE_URL,
                 timeout: int = 30, max_retries: int = 4, backoff_base: float = 2.0):
        self.token = (token if token is not None
                      else os.environ.get(TOKEN_ENV, "")).strip()
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_base = backoff_base

    def _get(self, path: str, params: dict | None = None):
        if not self.token:
            raise RuntimeError(
                f"No Invezgo token: set the {TOKEN_ENV} environment variable "
                "(a root-owned secrets file / systemd drop-in on a server, "
                "never runner_config.json).")

        attempt = 0
        while True:
            try:
                r = requests.get(
                    f"{self.base_url}{path}",
                    params=params or {},
                    headers={"Authorization": f"Bearer {self.token}"},
                    timeout=self.timeout,
                )
            except TRANSIENT_NETWORK_ERRORS:
                # A timeout or dropped connection is the same KIND of event as
                # a 429 -- transient, and retrying fixes it. Letting it escape
                # here is what silently costs a backfill whole days (the
                # caller's per-day handler just logs and skips), leaving a hole
                # that covered_range still reports as covered.
                if attempt >= self.max_retries:
                    raise
                time.sleep(self.backoff_base ** (attempt + 1))
                attempt += 1
                continue

            status = getattr(r, "status_code", 200)
            if status in RETRY_STATUS_CODES and attempt < self.max_retries:
                # Retry-After header wins if present; otherwise exponential
                # backoff (2s, 4s, 8s, 16s by default) -- either way, sleeping
                # here (not raising) is what makes a big sequential backfill
                # loop self-heal instead of quietly losing days to throttling.
                # 5xx is included for the same reason: a vendor blip that is
                # not retried becomes a permanent gap in the archive.
                wait = r.headers.get("Retry-After")
                delay = float(wait) if wait else self.backoff_base ** (attempt + 1)
                time.sleep(delay)
                attempt += 1
                continue
            r.raise_for_status()
            return r.json()

    def broker_summary(self, code: str, from_date: str, to_date: str,
                       investor: str = "all", market: str = DEFAULT_MARKET) -> list[dict]:
        """Per-broker buy/sell/net breakdown for ``code`` aggregated over
        [from_date, to_date] (ISO strings). ``code`` is the bare IDX code
        (``BBCA``), not the yfinance ``BBCA.JK`` form — call sites that hold
        a ``.JK`` ticker should strip it first (fetch_daily_foreign_net does).
        ``investor`` must be one of VALID_INVESTORS (``"f"`` for foreign, NOT
        the word "foreign" — the API 422s on anything else); ``market`` must
        be one of VALID_MARKETS (default ``"RG"``, the normal continuous
        market). Returns the raw list of broker dicts (values still strings,
        as the API sends them); [] if the API returns nothing."""
        data = self._get(
            f"/analysis/summary/stock/{code}",
            params={"from": from_date, "to": to_date,
                   "investor": investor, "market": market},
        )
        return data if isinstance(data, list) else []

    def financial_statement(self, code: str, statement: str = "IS",
                            type_: str = "FY", limit: int = 8) -> dict:
        """Multi-period financial-statement matrix for ``code`` (bare IDX
        code, no ``.JK``). ``statement`` in VALID_STATEMENTS (BS/IS/CF);
        ``type_`` in VALID_STATEMENT_TYPES (FY annual, Q quarterly, Q1-Q4 a
        specific quarter); ``limit`` = periods requested. Unlike the
        broker-flow endpoint this needs no market/investor/from/to — just
        statement/type/limit (confirmed against the real OpenAPI spec and
        live probe calls). Returns the raw ``{"rows": [...], "columns":
        [...]}`` dict; ``{}`` if the API returns a non-dict. Feed it to
        ``normalize_financial_statement`` to get archive-ready rows."""
        data = self._get(
            f"/analysis/financial-statement/{code}",
            params={"statement": statement, "type": type_, "limit": limit},
        )
        return data if isinstance(data, dict) else {}


def _top_broker_share(brokers: list[dict]) -> float | None:
    """What fraction of the day's total |net_value| across ``brokers`` came
    from the single most active broker (0-1) -- a concentration/conviction
    signal: is this day's flow dominated by one broker (often read as more
    "informed"/institutional) or spread thin across many (more diffuse,
    retail-like). None (not 0) when every broker read zero activity --
    concentration is undefined on a no-activity day, not minimal."""
    abs_nets = [abs(_to_float(b.get("net_value")) or 0.0) for b in brokers]
    total = sum(abs_nets)
    if total <= 0:
        return None
    return max(abs_nets) / total


def fetch_daily_foreign_net(ticker: str, start: str, end: str,
                            client: InvezgoClient | None = None,
                            investor: str = "f",
                            market: str = DEFAULT_MARKET) -> pd.DataFrame | None:
    """A ``fetch_fn`` for ``BrokerFlowArchive.get_or_fetch``: return one row
    per trading day in [start, end] with the canonical broker-flow columns,
    or None if nothing came back for any day.

    For each business day it calls broker_summary(code, day, day, investor,
    market) and SUMS net_value / buy_value / sell_value / net_volume across
    the returned per-broker rows — confirmed correct: investor="f" returns
    one row per broker (most zero, some carrying real foreign flow), not a
    single aggregate, so the sum IS the stock's total foreign net for that
    day. Per-day failures are logged and skipped, never fatal, so a partial
    history still lands in the archive — same degrade-gracefully spirit as
    warehouse.get_or_fetch.

    WARNING: one API call PER DAY (from==to) — see the module docstring on
    the 30,000-req/month budget before pointing this at the full universe.
    """
    client = client or InvezgoClient()
    code = ticker.replace(".JK", "")
    rows: dict[str, dict] = {}
    failed_days: list[str] = []

    for day in pd.bdate_range(start, end):
        ds = day.strftime("%Y-%m-%d")
        try:
            brokers = client.broker_summary(code, ds, ds, investor=investor, market=market)
        except Exception as e:
            # A day lost here is indistinguishable downstream from a day that
            # genuinely had no flow: both are simply absent, and covered_range
            # reports the span as covered either way. Count them so a holey
            # backfill cannot pass for a complete one.
            log_swallowed(f"invezgo.fetch_daily_foreign_net({ticker}, {ds})", e)
            failed_days.append(ds)
            continue
        if not brokers:
            continue
        net = sum(_to_float(b.get("net_value")) or 0.0 for b in brokers)
        buy = sum(_to_float(b.get("buy_value")) or 0.0 for b in brokers)
        sell = sum(_to_float(b.get("sell_value")) or 0.0 for b in brokers)
        vol = sum(_to_float(b.get("net_volume")) or 0.0 for b in brokers)
        rows[ds] = {"foreign_net_value": net, "foreign_buy_value": buy,
                    "foreign_sell_value": sell, "foreign_net_volume": vol,
                    "foreign_top_broker_share": _top_broker_share(brokers)}

    if failed_days:
        print(f"  [invezgo] WARNING: {ticker} lost {len(failed_days)} day(s) to "
              f"fetch failures after retries ({failed_days[0]}"
              f"{'...' + failed_days[-1] if len(failed_days) > 1 else ''}). "
              "These are GAPS, not zero-flow days — covered_range cannot tell "
              "the difference, so re-run this range before trusting it.")

    if not rows:
        return None
    df = pd.DataFrame.from_dict(rows, orient="index")
    df.index = pd.DatetimeIndex(df.index)
    df.attrs["failed_days"] = failed_days
    return df.sort_index()


VALID_STATEMENTS = ("BS", "IS", "CF")   # balance sheet / income / cash flow
VALID_STATEMENT_TYPES = ("FY", "Q", "Q1", "Q2", "Q3", "Q4")


def normalize_financial_statement(response: dict) -> pd.DataFrame:
    """Turn Invezgo's ``/analysis/financial-statement/{code}`` response into
    the long-format frame ``kala.fundamental_archive`` stores: one row per
    (line item x reporting period) cell.

    The response is a matrix ``{"rows": [...], "columns": [...]}`` — rows are
    line items (each with a stable ``id``, a human ``name``, and a ``values``
    array of ``{col, year, amount, period}`` per period), columns name the
    periods (``{year, label, period}``, e.g. FY 2020 or Q2 2025). This
    flattens it to columns: fiscal_year (int), period (FY/Q1..Q4),
    line_item_id, line_item, amount (float or None). ``amount`` uses the
    adapter's ``_to_float`` discipline — a genuinely absent value becomes
    None (stored NULL by the archive), while a vendor-reported 0 stays 0.0.

    Note there is deliberately NO observed/filing date here: the response
    carries none (confirmed — see kala/fundamental_archive.py's docstring on
    why that matters), so the pull date is supplied by the caller/archive at
    record time, not parsed from the payload."""
    if not isinstance(response, dict):
        return pd.DataFrame(columns=["fiscal_year", "period", "line_item_id",
                                     "line_item", "amount"])
    recs = []
    for row in response.get("rows", []):
        # skip abstract/header rows: they're section labels, not figures.
        if row.get("is_abstract"):
            continue
        item_id = row.get("id")
        name = row.get("name")
        for cell in row.get("values", []):
            year = cell.get("year")
            period = cell.get("period")
            if year is None or period is None:
                continue
            recs.append({
                "fiscal_year": int(year),
                "period": str(period),
                "line_item_id": item_id,
                "line_item": name,
                "amount": _to_float(cell.get("amount")),
            })
    return pd.DataFrame(recs, columns=["fiscal_year", "period", "line_item_id",
                                       "line_item", "amount"])


def fetch_financial_statement(ticker: str, statement: str = "IS",
                              client: InvezgoClient | None = None,
                              type_: str = "FY", limit: int = 8) -> pd.DataFrame | None:
    """A ``fetch_fn``-shaped helper for ``FundamentalArchive.get_or_snapshot``
    (which calls it as ``fetch_fn(ticker, statement)``): pull ``ticker``'s
    ``statement`` history and return it normalized, or None if nothing came
    back. Costs ONE API call. ``type_`` selects annual (``FY``) vs quarterly
    (``Q``); ``limit`` is how many periods to request (vendor returns up to
    that many, newest first). ``ticker`` may be the yfinance ``BBCA.JK`` form
    — the ``.JK`` is stripped for the bare IDX code the endpoint expects."""
    client = client or InvezgoClient()
    code = ticker.replace(".JK", "")
    try:
        data = client.financial_statement(code, statement=statement, type_=type_, limit=limit)
    except Exception as e:
        log_swallowed(f"invezgo.fetch_financial_statement({ticker}, {statement})", e)
        return None
    df = normalize_financial_statement(data)
    return df if len(df) else None


def broker_net_frame(brokers: list[dict]) -> pd.DataFrame:
    """Turn one broker_summary() response into a tidy, numeric DataFrame
    (index = broker code) for the bandarmology-concentration signal —
    which broker is accumulating, straight from investor=all data. Columns:
    name, buy_value, sell_value, net_value, net_volume."""
    recs = []
    for b in brokers:
        recs.append({
            "code": b.get("code"),
            "name": b.get("name"),
            "buy_value": _to_float(b.get("buy_value")),
            "sell_value": _to_float(b.get("sell_value")),
            "net_value": _to_float(b.get("net_value")),
            "net_volume": _to_float(b.get("net_volume")),
        })
    df = pd.DataFrame(recs)
    if not df.empty:
        df = df.set_index("code")
    return df
