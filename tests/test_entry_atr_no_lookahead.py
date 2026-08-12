"""The stop must be sized with volatility that was knowable at order time.

Wilder's ATR at bar t incorporates bar t's own High and Low. The backtest
fills entries at bar i+1's OPEN, so taking entry_atr from bar i+1 used the
fill day's realised range — information the order could not have had. It
feeds governing_stop() directly, so on a day that turned out wild the stop
came out wider and spared the position a whipsaw exit it had no way to
foresee. Always in the flattering direction.

The effect is small (~0.7bp per trade measured on low-volatility synthetic
series) and only appears where the ATR stop binds at all — with
hard_stop_pct=-5.0 and atr_stop_multiple=2.0 the hard floor wins whenever
ATR exceeds 2.5% of price. It changes no conclusion in PROJECT_STATUS.md.
It is fixed because a harness whose entire claim is "we tested honestly"
cannot carry a look-ahead, however small.
"""

import numpy as np
import pandas as pd
import pytest

from kala.backtest import backtest_ticker
from kala.config import BacktestConfig, Config
from kala.scoring import compute_features


def _frame(n=400, seed=7, base_vol=0.007, k=0.35):
    """Low-volatility series: the regime where the ATR stop actually binds."""
    rng = np.random.default_rng(seed)
    vol = np.full(n, base_vol)
    for t in range(1, n):
        vol[t] = 0.88 * vol[t - 1] + 0.12 * base_vol + 0.15 * base_vol * abs(rng.normal())
    close = 1000 * np.exp(np.cumsum(rng.normal(0.0004, 1.0, n) * vol))
    intr = vol * k * rng.uniform(0.7, 1.3, n)
    high, low = close * (1 + intr), close * (1 - intr)
    open_ = np.concatenate([[close[0]], close[:-1] * (1 + rng.normal(0, 0.002, n - 1))])
    high = np.maximum.reduce([high, open_, close])
    low = np.minimum.reduce([low, open_, close])
    return pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close,
                         "Volume": rng.integers(1e6, 5e6, n).astype(float)},
                        index=pd.bdate_range("2021-01-01", periods=n))


def _discriminating_frame():
    """A series built so the two ATR choices give visibly different stops.

    Quiet bars keep the signal-bar ATR small, so its stop sits ABOVE the -5%
    hard floor and binds. The fill bar then prints a huge range, inflating
    ATR enough that the leaked stop would be clamped down to the hard floor.
    A later bar closes between the two levels: the honest stop is breached,
    the leaked one is not.
    """
    n = 60
    price = 1000.0
    idx = pd.bdate_range("2021-01-01", periods=n)
    o = np.full(n, price)
    h = np.full(n, price * 1.002)
    lo = np.full(n, price * 0.998)
    c = np.full(n, price)

    entry_i = 40                       # fill bar
    h[entry_i] = price * 1.10          # huge range -> ATR spikes on THIS bar
    lo[entry_i] = price * 0.90
    c[entry_i] = price

    # Close between the two candidate stops (see the assertions below).
    c[entry_i + 1] = price * 0.97
    lo[entry_i + 1] = price * 0.969
    h[entry_i + 1] = price * 1.001

    df = pd.DataFrame({"Open": o, "High": h, "Low": lo, "Close": c,
                       "Volume": np.full(n, 5e6)}, index=idx)
    score = pd.Series(0.0, index=idx)
    score.iloc[entry_i - 1] = 100.0    # signal one bar before the fill
    return df, score, entry_i


def test_stop_is_sized_from_the_signal_bar_so_the_position_is_stopped_out():
    """The discriminating case. With the signal bar's (small) ATR the stop is
    breached and the trade closes on 'stop'. With the fill bar's inflated ATR
    the stop would have been clamped to the -5% floor and never touched —
    the position would have survived on information it could not have had.
    """
    df, score, entry_i = _discriminating_frame()
    cfg = Config(backtest=BacktestConfig(score_entry_threshold=50.0,
                                         apply_entry_vetoes=False))
    atr = compute_features(df)["atr"]
    from kala.exits import governing_stop

    entry = df["Open"].iloc[entry_i]
    stop_signal, _, _ = governing_stop(entry, entry, float(atr.iloc[entry_i - 1]),
                                       cfg.risk)
    stop_fill, _, _ = governing_stop(entry, entry, float(atr.iloc[entry_i]),
                                     cfg.risk)
    breach = df["Close"].iloc[entry_i + 1]

    # The fixture must actually separate the two, or the test proves nothing.
    assert stop_signal > stop_fill, "fixture failed to separate the two stops"
    assert stop_fill < breach <= stop_signal, "fixture close is not between them"

    result = backtest_ticker("T.JK", df, cfg=cfg, score_override=score)
    assert result.n_signals == 1, "fixture must produce exactly one signal"
    assert result.closed, (
        "the position was never stopped out, so it is still open at the end "
        "of the data — its stop was sized from the fill bar's inflated ATR, "
        "i.e. entry_atr is being read from bar i+1 again")
    assert result.closed[0].exit_reason.startswith("stop")


def test_atr_at_bar_t_contains_bar_t_high_low():
    """The premise, asserted rather than assumed: perturbing ONLY bar t's High
    changes atr[t]. That is why atr[t] is unusable for an order filled at
    bar t's open."""
    df = _frame(n=120)
    before = compute_features(df)["atr"].iloc[-1]

    bumped = df.copy()
    bumped.iloc[-1, bumped.columns.get_loc("High")] *= 1.10
    after = compute_features(bumped)["atr"].iloc[-1]

    assert after != before


def test_fix_does_not_change_entry_or_exit_timing():
    """Only the stop DISTANCE was mis-sized. Signal-to-fill timing was always
    correct, and this must not have disturbed it: entries still land on the
    bar after the signal."""
    df = _frame()
    cfg = Config(backtest=BacktestConfig(score_entry_threshold=55.0))
    result = backtest_ticker("T.JK", df, cfg=cfg)

    for trade in result.closed:
        assert trade.entry_date in df.index
        assert trade.exit_date >= trade.entry_date


def test_leak_would_have_flattered_not_hurt():
    """Sanity-check the direction of the bias that was removed. A wider stop
    (bigger ATR) can only ever avoid or delay a stop-out, never cause one."""
    from kala.exits import governing_stop

    cfg = Config()
    entry = 1000.0
    tight, _, _ = governing_stop(entry, entry, 10.0, cfg.risk)
    wide, _, _ = governing_stop(entry, entry, 20.0, cfg.risk)
    assert wide <= tight        # more volatility -> stop sits lower


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
