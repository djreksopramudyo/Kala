"""
Buy-side guardrails.

The scanner scores momentum, so it naturally rewards stocks that have ALREADY
surged — which is how it made PTPW (+46% in 20 days, RSI 78.6, OBV in
distribution, volume only 1.13x, market BEARISH) its single top pick the day
before it rolled over. The old code computed those red flags but only subtracted
a few points, so a big enough momentum score bulldozed every warning.

``evaluate_entry`` turns the worst of them into hard VETOES: a BUY that trips any
enabled rule is rejected (the caller downgrades it to HOLD). Everything is
derived from the price history itself, so it's self-contained and testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import indicators as ind
from .config import EntryConfig


@dataclass
class EntryDecision:
    allowed: bool
    vetoes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)


def evaluate_entry(features, market_status: str | None = None, cfg: EntryConfig | None = None) -> EntryDecision:
    """Decide whether a BUY candidate clears the guardrails.

    ``features`` is an OHLCV frame (capitalised columns). Returns an
    ``EntryDecision``; ``allowed=False`` means at least one veto fired.
    """
    cfg = cfg or EntryConfig()

    close = features["Close"]
    volume = features["Volume"]
    n = len(close)

    last_price = float(close.iloc[-1]) if n else float("nan")
    rsi_last = float(ind.rsi(close, 14).iloc[-1]) if n >= 15 else float("nan")
    roc20 = float((close.iloc[-1] / close.iloc[-21] - 1.0) * 100.0) if n >= 21 else 0.0

    adx_last = float("nan")
    if cfg.veto_ranging_stock and n >= 30 and "High" in features and "Low" in features:
        adx_last = float(ind.adx(features["High"], features["Low"], close, 14)["adx"].iloc[-1])

    # OBV distribution: price up over the window while OBV is down (divergence)
    obv = ind.obv(close, volume)
    lb = cfg.distribution_lookback
    if n > lb:
        obv_change = obv.iloc[-1] - obv.iloc[-(lb + 1)]
        price_change = close.iloc[-1] - close.iloc[-(lb + 1)]
        distribution = (obv_change < 0) and (price_change > 0)
    else:
        distribution = False

    # Volume confirmation: recent (5-bar) vs baseline (20-bar) average
    if n >= 20:
        recent_vol = float(volume.iloc[-5:].mean())
        base_vol = float(volume.iloc[-20:].mean())
        vol_ratio = recent_vol / base_vol if base_vol > 0 else 0.0
    else:
        vol_ratio = float("nan")

    vetoes: list[str] = []
    warnings: list[str] = []

    if cfg.veto_overbought and rsi_last == rsi_last and rsi_last >= cfg.rsi_overbought:
        vetoes.append(f"overbought (RSI {rsi_last:.0f} >= {cfg.rsi_overbought:.0f})")

    if cfg.veto_parabolic and roc20 >= cfg.roc20_parabolic:
        vetoes.append(f"already extended (+{roc20:.0f}% in 20d >= +{cfg.roc20_parabolic:.0f}%)")

    if cfg.veto_distribution and distribution:
        vetoes.append("OBV distribution (price up while volume distributes — smart money selling into strength)")

    if (cfg.veto_thin_volume and roc20 >= cfg.surge_roc_threshold
            and vol_ratio == vol_ratio and vol_ratio < cfg.min_volume_ratio):
        vetoes.append(f"surge not confirmed by volume ({vol_ratio:.2f}x < {cfg.min_volume_ratio:.2f}x — thin/illiquid)")

    if cfg.block_buys_in_bear and market_status in cfg.bear_statuses:
        vetoes.append(f"market regime is {market_status}")

    # Fail closed when the regime could not be fetched at all (see
    # regime.UNAVAILABLE): "we couldn't read the tape" must not be quieter than
    # "the tape is bearish". Benchmark warm-up ('UNKNOWN') and no-benchmark
    # (None) still fall through untouched — those are not failures.
    if (cfg.block_buys_when_regime_unavailable
            and market_status in cfg.regime_unavailable_statuses):
        vetoes.append("market regime unavailable (IHSG fetch failed — "
                      "cannot rule out a bear tape)")

    if (cfg.veto_ranging_stock and adx_last == adx_last
            and adx_last < cfg.range_adx_threshold):
        vetoes.append(f"stock is range-bound (ADX {adx_last:.0f} < "
                      f"{cfg.range_adx_threshold:.0f} — trend entries whipsaw here)")

    if (cfg.veto_cheap_stock and last_price == last_price
            and last_price < cfg.min_price_idr):
        vetoes.append(f"price too low (Rp{last_price:,.0f} < Rp{cfg.min_price_idr:,.0f} "
                      "-- no out-of-sample edge below this tier under honest "
                      "tick-floor spread costs)")

    # A non-vetoing-but-notable condition: overbought-ish without being a hard veto
    if not vetoes and rsi_last == rsi_last and rsi_last >= cfg.rsi_overbought - 10:
        warnings.append(f"RSI elevated ({rsi_last:.0f})")

    metrics = {"price": last_price, "rsi": rsi_last, "roc20": roc20,
              "obv_distribution": distribution, "volume_ratio": vol_ratio,
              "adx": adx_last}
    return EntryDecision(allowed=(len(vetoes) == 0), vetoes=vetoes, warnings=warnings, metrics=metrics)
