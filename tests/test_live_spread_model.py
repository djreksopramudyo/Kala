"""The live book charged cheaper spreads than every measurement it is compared to.

`daily_run` runs its FRICTION REPORT at `spread_mode="tick_floor"` and books
the fills those figures describe at the default `flat`. Every validated number
in this project was measured with `--tick-spread`, i.e. tick_floor.

On this account's own nine holdings that is a round trip of 0.64% booked
against 0.87% measured — the live book is **0.23 points per trade cheaper**
than the backtest it will be compared against, every trade, always in the
direction that flatters the live result. For scale, the measured excess is
+1.71%/trade: a 13% systematic overstatement, landing squarely on the forward
test, which is the one piece of evidence this project has never had.

The default is NOT changed here — that would silently rewrite a live book's
arithmetic. It is made selectable, recorded in the measurement's provenance,
and treated as binding when the two are compared.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kala.config import (  # noqa: E402
    Config,
    CostModel,
    idx_tick_size,
    live_config,
    live_costs,
)
from kala.expectation import LiveSetup, block, mismatches  # noqa: E402


def cfg_file(tmp_path, **settings) -> Path:
    p = tmp_path / "runner_config.json"
    p.write_text(json.dumps(settings), encoding="utf-8")
    return p


def round_trip_pct(costs: CostModel, price: float) -> float:
    return (1 - costs.sell_multiplier(price) / costs.buy_multiplier(price)) * 100


# ---------------------------------------------------------------------------
# the gap is real, and it points one way
# ---------------------------------------------------------------------------

def test_the_two_models_differ_and_flat_is_always_the_cheaper_one():
    """If flat were ever the dearer one this would be a wash, not a bias."""
    flat, tick = CostModel(), CostModel(spread_mode="tick_floor")
    prices = [67, 150, 323, 519, 800, 1104, 1721, 2794, 7061, 9064]
    gaps = [round_trip_pct(tick, p) - round_trip_pct(flat, p) for p in prices]
    assert all(g >= 0 for g in gaps), dict(zip(prices, gaps))
    assert any(g > 0.2 for g in gaps), "no material gap — the finding is moot"


def test_the_gap_is_worst_on_cheap_stocks():
    """A 67-rupiah name cannot have a spread tighter than its 1-rupiah tick."""
    flat, tick = CostModel(), CostModel(spread_mode="tick_floor")
    assert idx_tick_size(67) == 1.0
    cheap = round_trip_pct(tick, 67) - round_trip_pct(flat, 67)
    rich = round_trip_pct(tick, 9064) - round_trip_pct(flat, 9064)
    assert cheap > rich
    assert cheap > 1.0, f"expected a big gap on a 67 IDR name, got {cheap:.2f}"


# ---------------------------------------------------------------------------
# the setting, and the default that must not move
# ---------------------------------------------------------------------------

def test_no_setting_keeps_the_historical_flat_model(tmp_path):
    """Changing this default would rewrite a live book's arithmetic silently."""
    assert live_costs({}).spread_mode == "flat"
    assert live_costs(None).spread_mode == "flat"
    assert live_config(cfg_file(tmp_path)).costs.spread_mode == "flat"
    assert live_costs({}) == Config().costs


def test_the_setting_selects_the_measured_model(tmp_path):
    assert live_costs({"costs_spread_mode": "tick_floor"}).spread_mode == "tick_floor"
    p = cfg_file(tmp_path, costs_spread_mode="tick_floor")
    assert live_config(p).costs.spread_mode == "tick_floor"


def test_the_setting_survives_an_exit_profile(tmp_path):
    """Both keys are read; one must not overwrite the other."""
    p = cfg_file(tmp_path, exit_profile="forward_test",
                 costs_spread_mode="tick_floor")
    cfg = live_config(p)
    assert cfg.costs.spread_mode == "tick_floor"
    assert cfg.backtest.holding_max_days == 60
    assert cfg.backtest.score_entry_threshold == 80.0


@pytest.mark.parametrize("bad", ["tickfloor", "TICK-FLOOR", "cheap", "", "none"])
def test_an_unknown_spread_mode_raises(bad):
    """A typo must not leave the optimistic model quietly in place."""
    with pytest.raises(ValueError, match="unknown costs_spread_mode"):
        live_costs({"costs_spread_mode": bad})


@pytest.mark.parametrize("ok", ["tick_floor", "TICK_FLOOR", " flat ", "Flat"])
def test_case_and_whitespace_are_tolerated(ok):
    assert live_costs({"costs_spread_mode": ok}).spread_mode in ("flat", "tick_floor")


# ---------------------------------------------------------------------------
# a measurement taken under one model does not describe a book kept under the other
# ---------------------------------------------------------------------------

MEASURED = {
    "strategy": "momentum", "exit_profile": "forward_test",
    "baseline_threshold": 80.0, "holding_max_days": 60,
    "benchmark": "EQUAL_WEIGHT", "apply_entry_vetoes": False,
    "disabled_vetoes": [], "n_tickers": 615, "measured_at": "2026-08-21",
    "threshold_grid_size": 6, "spread_mode": "tick_floor",
    "folds": [{"fold": 0, "n_baseline": 100, "excess_baseline_pct": 1.0},
              {"fold": 1, "n_baseline": 100, "excess_baseline_pct": 2.0}],
    "pooled_excess_baseline": {"n": 5241, "ev_pct": 1.71, "t_stat": 2.02},
    "pooled_excess_baseline_clustered_t": 1.92,
    "pooled_excess_baseline_dsr": 0.766,
}

ALL_OFF = ("bear", "obv", "parabolic", "rsi", "thin_volume")


def live(spread_mode: str) -> LiveSetup:
    return LiveSetup(holding_max_days=60, baseline_threshold=80.0,
                     disabled_vetoes=ALL_OFF, exit_profile="forward_test",
                     spread_mode=spread_mode)


def saved(tmp_path, **over) -> Path:
    p = tmp_path / "expectation.json"
    p.write_text(json.dumps({**MEASURED, **over}), encoding="utf-8")
    return p


def test_a_flat_book_cannot_quote_a_tick_floored_measurement(tmp_path):
    lines = block(live("flat"), path=saved(tmp_path), today=None)
    text = "\n".join(lines)
    assert "NOT APPLICABLE" in text
    assert "spread_mode" in text
    assert "%/trade" not in text, (
        "the excess was printed beside a book charging cheaper costs")


def test_aligning_the_book_makes_the_measurement_applicable(tmp_path):
    """Non-vacuity: the check must not refuse everything."""
    text = "\n".join(block(live("tick_floor"), path=saved(tmp_path), today=None))
    assert "NOT APPLICABLE" not in text
    assert "+1.71%/trade" in text


def test_a_table_without_the_field_is_not_assumed_to_be_flat(tmp_path):
    """Assuming the cheaper model is assuming the flattering answer."""
    t = dict(MEASURED)
    del t["spread_mode"]
    p = tmp_path / "expectation.json"
    p.write_text(json.dumps(t), encoding="utf-8")
    text = "\n".join(block(live("flat"), path=p, today=None))
    assert "not recorded" in text
    assert "%/trade" not in text


def test_the_mismatch_names_both_sides(tmp_path):
    from kala.expectation import load
    rows = mismatches(load(saved(tmp_path)), live("flat"))
    assert ("spread_mode", "tick_floor", "flat") in rows


# ---------------------------------------------------------------------------
# the dead registry entry
# ---------------------------------------------------------------------------

def test_the_costs_key_is_no_longer_advertised_as_real():
    """`"costs"` was registered as a known key and read by nothing.

    The mirror image of finding 16: a setting preflight blesses that does
    nothing at all. `costs_spread_mode` replaces it and is actually read.
    """
    from kala.preflight import KNOWN_CONFIG_KEYS, check_config_keys
    assert "costs" not in KNOWN_CONFIG_KEYS
    assert "costs_spread_mode" in KNOWN_CONFIG_KEYS
    (warn,) = [c for c in check_config_keys({"costs": {"buy_commission": 0.001}})
               if c.status == "WARN"]
    assert "no effect" in warn.message
    assert all(c.status == "OK"
               for c in check_config_keys({"costs_spread_mode": "tick_floor"}))


# ---------------------------------------------------------------------------
# the thing that books the fills must get the setting too
# ---------------------------------------------------------------------------

def test_the_trading_config_daily_run_builds_carries_the_cost_model():
    """`daily_run` used `config_for_profile(...)` alone, which resolves the
    profile and drops the cost model. The paper trader books through that
    config, so the setting would have reached the scanner and not the fills.
    """
    from kala.config import config_from_settings
    assert config_from_settings(
        {"costs_spread_mode": "tick_floor"}).costs.spread_mode == "tick_floor"
    assert config_from_settings({}).costs.spread_mode == "flat"
    assert config_from_settings(None).costs.spread_mode == "flat"


def test_daily_run_resolves_its_trading_config_through_that_function():
    """co_names off the compiled function — cannot pass on a deleted call."""
    import daily_run
    names = daily_run.main.__code__.co_names
    assert "config_from_settings" in names
    assert "config_for_profile" not in names, (
        "the profile-only resolver is back, and it drops the cost model")


def test_a_paper_trader_on_the_aligned_config_charges_more(tmp_path):
    """End to end: the setting has to change what a fill costs."""
    from kala.config import config_from_settings
    from kala.papertrade import PaperTrader

    flat = PaperTrader.load(tmp_path / "a.json", start_capital=10_000_000,
                            cfg=config_from_settings({}))
    tick = PaperTrader.load(tmp_path / "b.json", start_capital=10_000_000,
                            cfg=config_from_settings(
                                {"costs_spread_mode": "tick_floor"}))
    flat.manual_buy("BSML.JK", shares=100, price=519)
    tick.manual_buy("BSML.JK", shares=100, price=519)
    assert tick.positions["BSML.JK"].entry_price > \
        flat.positions["BSML.JK"].entry_price
    assert tick.cash < flat.cash, "the dearer model must actually cost more"


def test_the_measurement_records_which_model_it_charged():
    """Without this the saved table cannot be checked against the book at all.

    Found by mutation: deleting the field survived, because every test here
    supplied it by hand in a fixture rather than asking the writer for it.
    """
    import argparse

    from run_walkforward import VETO_FLAGS, build_run_config, run_provenance

    class _Strategy:
        name = "momentum"

    ap = argparse.ArgumentParser()
    ap.add_argument("--apply-entry-vetoes", action="store_true")
    ap.add_argument("--disable-veto", nargs="*", default=[],
                    choices=sorted(VETO_FLAGS))
    ap.add_argument("--exit-profile", default="forward_test")
    ap.add_argument("--benchmark", default="EQUAL_WEIGHT")
    args = ap.parse_args([])

    for mode in ("flat", "tick_floor"):
        cfg = build_run_config("forward_test", CostModel(spread_mode=mode),
                               False, False)
        prov = run_provenance(args, _Strategy(), cfg, 10, measured_at="2026-01-01")
        assert prov["spread_mode"] == mode, (
            "the saved table cannot say which cost model it charged")


def test_live_setup_reads_the_cost_model_off_the_config():
    """Found by mutation: hardcoding "flat" in from_config survived.

    Every test here built a LiveSetup by hand, so nothing exercised the path
    the daily run actually takes.
    """
    from kala.config import config_from_settings

    for mode in ("flat", "tick_floor"):
        cfg = config_from_settings({"costs_spread_mode": mode})
        assert LiveSetup.from_config(cfg).spread_mode == mode
