"""A FAILED benchmark fetch must not read as a benign regime.

check_market_health used to return status 'UNKNOWN' when the ^JKSE download
raised or came back short. 'UNKNOWN' is also what regime.classify_market_regime
emits for benchmark warm-up bars, and the entry veto deliberately lets those
through — so a network blip was indistinguishable from "nothing to worry about"
and silently disabled block_buys_in_bear, the only hard regime protection the
live scanner still has (the soft score multiplier was retired in favour of it).

The two cases are now distinct strings: warm-up stays 'UNKNOWN' (fails open),
fetch failure is regime.UNAVAILABLE (fails closed).
"""

import numpy as np
import pandas as pd
import pytest

from kala import regime
from kala.config import EntryConfig
from kala.entries import evaluate_entry
from kala.exits import evaluate_exit


def make_df(closes, vols=None):
    closes = np.asarray(closes, dtype=float)
    n = len(closes)
    vols = np.asarray(vols, dtype=float) if vols is not None else np.full(n, 1_000_000.0)
    return pd.DataFrame(
        {"Open": closes, "High": closes * 1.005, "Low": closes * 0.995,
         "Close": closes, "Volume": vols},
        index=pd.bdate_range("2024-01-02", periods=n),
    )


def clean_candidate():
    """A BUY that trips no veto other than a regime one."""
    t = np.arange(45)
    return make_df(1000 * (1 + 0.0018 * t + 0.025 * np.sin(t / 2.0)),
                   np.linspace(1_000_000, 1_300_000, 45))


def test_clean_candidate_is_allowed_in_a_known_calm_tape():
    # Guards the tests below: this frame is otherwise veto-free, so any veto
    # they observe is attributable to the regime status alone.
    assert evaluate_entry(clean_candidate(), market_status="NEUTRAL").allowed


@pytest.mark.parametrize("status", ["BEARISH", "MODERATE_BEAR"])
def test_bear_tape_still_blocks_buys(status):
    d = evaluate_entry(clean_candidate(), market_status=status)
    assert not d.allowed
    assert any("market regime" in v for v in d.vetoes)


def test_unavailable_regime_blocks_buys():
    """The regression: a failed IHSG fetch must NOT open the bear gate."""
    d = evaluate_entry(clean_candidate(), market_status=regime.UNAVAILABLE)
    assert not d.allowed, "IHSG fetch failure silently permitted a BUY"
    assert any("unavailable" in v.lower() for v in d.vetoes), d.vetoes


@pytest.mark.parametrize("status", ["UNKNOWN", None])
def test_warmup_and_no_benchmark_still_fail_open(status):
    """Not-yet-knowable is not a failure — backtest numbers must not move."""
    assert evaluate_entry(clean_candidate(), market_status=status).allowed


def test_unavailable_block_is_configurable():
    cfg = EntryConfig(block_buys_when_regime_unavailable=False)
    assert evaluate_entry(clean_candidate(), market_status=regime.UNAVAILABLE,
                          cfg=cfg).allowed


def test_classify_market_regime_never_emits_unavailable():
    """UNAVAILABLE is a live-path sentinel only, so no backtest bar can carry it."""
    close = pd.Series(np.linspace(100.0, 200.0, 120),
                      index=pd.bdate_range("2024-01-02", periods=120))
    status = regime.classify_market_regime(pd.DataFrame({"Close": close}))
    assert regime.UNAVAILABLE not in set(status)
    assert set(status) <= set(regime.STATUSES) | {"UNKNOWN"}
    assert (status.iloc[:49] == "UNKNOWN").all()  # warm-up still UNKNOWN


def test_unavailable_regime_flags_a_losing_position_on_the_exit_side():
    """exits.py had the same hardcoded bear list; being blind must not make us
    more patient with a loser than a visible bear tape would."""
    closes = np.linspace(1000.0, 900.0, 60)  # holding a loser
    feats_df = make_df(closes)
    from kala.scoring import compute_features
    feats = compute_features(feats_df)

    d = evaluate_exit(ticker="TEST", entry_price=1000.0, features=feats,
                      peak_price=1000.0, entry_atr=None,
                      market_status=regime.UNAVAILABLE, score=None)
    assert any("unavailable" in r.lower() for r in d.reasons), d.reasons


# --- producer side --------------------------------------------------------
# The tests above pin the CONSUMERS (entries/exits react to UNAVAILABLE). These
# pin the PRODUCER: check_market_health must actually emit that sentinel on a
# failed fetch. Without them, reverting check_market_health to 'UNKNOWN' would
# restore the bug with every test above still green.

import kala_daily_trader as dt


@pytest.fixture
def clear_market_health_cache():
    # _market_health is a module-level cache: one transient failure at the top
    # of a scan is otherwise reused for the whole run.
    dt._market_health = None
    yield
    dt._market_health = None


@pytest.mark.parametrize("fake_download,label", [
    (lambda *a, **k: (_ for _ in ()).throw(ConnectionError("boom")), "network error"),
    (lambda *a, **k: pd.DataFrame(), "empty frame"),
    (lambda *a, **k: pd.DataFrame({"Close": np.arange(30.0)}), "short history"),
])
def test_failed_ihsg_fetch_reports_unavailable(monkeypatch, clear_market_health_cache,
                                               fake_download, label):
    monkeypatch.setattr(dt.yf, "download", fake_download)
    mkt = dt.check_market_health()
    assert mkt["status"] == regime.UNAVAILABLE, (
        f"{label}: fetch failure reported as {mkt['status']!r}")


def test_failed_ihsg_fetch_blocks_a_buy_end_to_end(monkeypatch, clear_market_health_cache):
    """The whole chain: fetch dies -> status -> evaluate_entry -> BUY refused."""
    monkeypatch.setattr(dt.yf, "download",
                        lambda *a, **k: (_ for _ in ()).throw(ConnectionError("boom")))
    status = dt.check_market_health().get("status")
    assert not evaluate_entry(clean_candidate(), market_status=status).allowed
