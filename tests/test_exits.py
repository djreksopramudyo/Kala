"""Exit-engine tests — regression tests for the three original bugs."""

import numpy as np
import pandas as pd
import pytest

from kala.config import RiskConfig
from kala.exits import Urgency, evaluate_exit, governing_stop
from kala.scoring import compute_features


def make_df(closes, vols=None):
    closes = np.asarray(closes, dtype=float)
    n = len(closes)
    vols = np.asarray(vols, dtype=float) if vols is not None else np.full(n, 1_000_000.0)
    return pd.DataFrame(
        {
            "Open": closes,
            "High": closes * 1.005,
            "Low": closes * 0.995,
            "Close": closes,
            "Volume": vols,
        },
        index=pd.bdate_range("2024-01-02", periods=n),
    )


@pytest.fixture
def downtrend_features():
    """A stock in an established downtrend that crossed below long ago, then
    keeps drifting down — death-cross EVENT is in the past, STATE persists."""
    up = np.linspace(1000, 1300, 60)
    down = np.linspace(1300, 900, 80)
    df = make_df(np.concatenate([up, down]))
    return compute_features(df)


def test_urgency_never_downgrades(downtrend_features):
    """Original bug: a later weaker rule overwrote an earlier URGENT (e.g.
    stop-loss). With a losing position deep below its stop, the final urgency
    must be URGENT no matter how many weaker rules also fire. (Since v3.3 the
    weaker rules here — MACD, bearish-market, score-weak — fire ADVISORY, but
    the invariant is the same: they must never demote the stop's URGENT.)"""
    d = evaluate_exit(
        ticker="TEST.JK",
        entry_price=1300.0,          # bought the top -> stop long since hit
        features=downtrend_features,
        peak_price=1300.0,
        entry_atr=20.0,
        market_status="BEARISH",     # fires advisory extras after the stop
        score=30.0,                  # fires advisory 'score weak' after the stop
    )
    assert d.exit_signal
    assert d.urgency == Urgency.URGENT
    # multiple weaker reasons fired and none demoted the urgency
    assert any("ADVISORY" in r for r in d.reasons)
    assert any("URGENT" in r for r in d.reasons)


def test_unvalidated_rules_are_advisory_only(downtrend_features):
    """v3.3: MACD-bearish, bearish-market-while-losing and score-collapse
    were never validated out-of-sample, and the exit-engine A/B measured them
    net-harmful when allowed to auto-sell (-0.21%/trade vs +0.37%). They must
    inform without ever setting exit_signal. Entry priced so the position is
    down ~-3%: enough for rule 7, nowhere near the -5% stop."""
    price_now = float(downtrend_features["Close"].iloc[-1])
    d = evaluate_exit(
        ticker="TEST.JK",
        entry_price=price_now / 0.97,        # ~-3% loss: rule 7 territory
        features=downtrend_features,          # bleeding tape: MACD bearish
        peak_price=price_now / 0.97,
        entry_atr=None,
        market_status="BEARISH",
        score=30.0,                           # score-collapse territory
        cfg=RiskConfig(trailing_enabled=False, hard_stop_pct=-50.0,
                       target_profit_pct=999.0),
    )
    assert any("MACD" in r or "bearish market" in r or "score weak" in r
               for r in d.reasons), "the advisories must still inform"
    assert not d.exit_signal, "advisory rules must never force a sale"
    assert d.urgency <= Urgency.ADVISORY


def test_death_cross_state_is_advisory_not_exit(downtrend_features):
    """Bars after the crossover must NOT report 'DEATH CROSS today'. The
    below-trend state alone (profitable position, no other triggers) must not
    force an exit."""
    # entry far below market so profit is positive and stops don't trigger
    d = evaluate_exit(
        ticker="TEST.JK",
        entry_price=500.0,
        features=downtrend_features,
        peak_price=910.0,            # just above current -> trail not hit
        entry_atr=5.0,
        cfg=RiskConfig(trailing_enabled=False, target_profit_pct=999.0),
    )
    assert not any("DEATH CROSS today" in r for r in d.reasons)
    assert any("Below trend" in r for r in d.reasons)


def test_death_cross_event_fires_on_cross_bar():
    up = np.linspace(1000, 1400, 70)
    crash = np.linspace(1400, 1050, 12)
    df = make_df(np.concatenate([up, crash]))
    f_all = compute_features(df)
    # locate the crossover bar and slice so it is the LAST bar
    cross = (f_all["sma_fast"].shift(1) >= f_all["sma_slow"].shift(1)) & (
        f_all["sma_fast"] < f_all["sma_slow"])
    cross_i = int(np.where(cross.fillna(False))[0][0])
    f = compute_features(df.iloc[: cross_i + 1])
    # confirm geometry: crossed on the LAST bar
    assert f["sma_fast"].iloc[-2] >= f["sma_slow"].iloc[-2]
    assert f["sma_fast"].iloc[-1] < f["sma_slow"].iloc[-1]
    d = evaluate_exit("TEST.JK", entry_price=1000.0, features=f,
                      peak_price=1400.0, entry_atr=10.0)
    assert any("DEATH CROSS today" in r for r in d.reasons)
    assert d.exit_signal


# ----------------------------------------------------------------------------
# Governing stop
# ----------------------------------------------------------------------------

def test_governing_stop_ratchets_and_floors():
    cfg = RiskConfig()
    entry, atr_val = 1000.0, 15.0
    # Phase 1: ATR stop = 1000 - 30 = 970
    s1, p1, _ = governing_stop(entry, peak_price=1000.0, entry_atr=atr_val, cfg=cfg)
    assert p1 == 1 and s1 == pytest.approx(970.0)
    # Phase 2: peak +5% -> breakeven
    s2, p2, _ = governing_stop(entry, peak_price=1050.0, entry_atr=atr_val, cfg=cfg)
    assert p2 == 2 and s2 == pytest.approx(1000.0)
    # Phase 3: peak +9% -> trail 3% below peak
    s3, p3, _ = governing_stop(entry, peak_price=1090.0, entry_atr=atr_val, cfg=cfg)
    assert p3 == 3 and s3 == pytest.approx(1090.0 * 0.97)
    # Phase 4: peak +15% -> tight trail
    s4, p4, _ = governing_stop(entry, peak_price=1150.0, entry_atr=atr_val, cfg=cfg)
    assert p4 == 4 and s4 == pytest.approx(1150.0 * 0.975)
    # Monotone: stop never moves down as peak rises
    assert s1 <= s2 <= s3 <= s4


def test_governing_stop_never_wider_than_hard_floor():
    cfg = RiskConfig(hard_stop_pct=-8.0, atr_stop_multiple=2.0)
    # huge ATR would imply a -20% stop; floor must cap it at -8%
    s, _, _ = governing_stop(1000.0, peak_price=1000.0, entry_atr=100.0, cfg=cfg)
    assert s == pytest.approx(920.0)


def test_no_atr_falls_back_to_hard_stop():
    cfg = RiskConfig(hard_stop_pct=-8.0)
    s, _, _ = governing_stop(1000.0, peak_price=1000.0, entry_atr=None, cfg=cfg)
    assert s == pytest.approx(920.0)


def test_rsi_panic_is_advisory_not_urgent():
    """Original rule 'RSI < 25 -> URGENT SELL' must now be advisory-only."""
    crash = np.concatenate([np.full(60, 1000.0), np.linspace(1000, 700, 30)])
    f = compute_features(make_df(crash))
    assert float(f["rsi"].iloc[-1]) < 25
    d = evaluate_exit("TEST.JK", entry_price=690.0, features=f,  # in profit, stops clear
                      peak_price=705.0, entry_atr=5.0,
                      cfg=RiskConfig(trailing_enabled=False, target_profit_pct=999.0))
    rsi_reasons = [r for r in d.reasons if "oversold" in r]
    assert rsi_reasons and all(r.startswith("[ADVISORY]") for r in rsi_reasons)
