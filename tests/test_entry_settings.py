"""The live bot's entry vetoes must be configurable, and the default unchanged.

The vetoes were hardcoded: both live call sites invoked
``evaluate_entry(data, market_status=...)`` with no ``cfg``, so
``EntryConfig()``'s defaults applied. Measured against an equal-weighted
benchmark built from the traded universe, that setting — all five on — is the
WORST of the seven configurations tested (-2.52%/trade, clustered t -3.10,
versus +1.71% with none). It was also the only one reachable.

Two things this file pins:

  1. absent configuration, behaviour is EXACTLY what it was. Flipping a live
     trading bot's entry logic as a side effect of adding a config hook would
     be a silent change to real money.
  2. a configuration mistake is an ERROR, never a no-op. A typo that quietly
     disabled nothing would leave the bot running the setting the user
     believed they had switched off, with nothing on screen to show it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kala.config import EntryConfig  # noqa: E402
from kala.entry_settings import (  # noqa: E402
    CONFIG_KEY,
    VETO_FLAGS,
    UnknownVetoName,
    describe,
    entry_config_from,
    load_entry_config,
)

# ---- the default must not move -------------------------------------------

def test_no_config_reproduces_the_previous_behaviour_exactly():
    """The historical call was evaluate_entry(...) with no cfg."""
    for settings in (None, {}, {"daily_capital_idr": 5_000_000}):
        cfg = entry_config_from(settings)
        default = EntryConfig()
        for name, field in VETO_FLAGS.items():
            assert getattr(cfg, field) == getattr(default, field), (
                f"{name} changed without being configured")


def test_an_empty_list_also_leaves_everything_on():
    cfg = entry_config_from({CONFIG_KEY: []})
    for field in VETO_FLAGS.values():
        assert getattr(cfg, field) is True


def test_a_missing_config_file_yields_defaults_rather_than_crashing(tmp_path):
    """The scanner must not stop scanning because a file is absent."""
    cfg, off = load_entry_config(tmp_path / "nope.json")
    assert off == []
    for field in VETO_FLAGS.values():
        assert getattr(cfg, field) is True


def test_an_unparseable_config_file_yields_defaults(tmp_path):
    bad = tmp_path / "runner_config.json"
    bad.write_text("{not json", encoding="utf-8")
    cfg, off = load_entry_config(bad)
    assert off == []
    assert cfg.veto_overbought is True


# ---- configuration must actually take effect -----------------------------

@pytest.mark.parametrize("name", sorted(VETO_FLAGS))
def test_disabling_one_veto_turns_off_exactly_that_one(name):
    cfg = entry_config_from({CONFIG_KEY: [name]})
    assert getattr(cfg, VETO_FLAGS[name]) is False
    for other, field in VETO_FLAGS.items():
        if other != name:
            assert getattr(cfg, field) is True, f"{name} also disabled {other}"


def test_disabling_all_five_is_the_measured_best_setting():
    cfg = entry_config_from({CONFIG_KEY: sorted(VETO_FLAGS)})
    for field in VETO_FLAGS.values():
        assert getattr(cfg, field) is False


def test_it_reads_the_real_config_file(tmp_path):
    p = tmp_path / "runner_config.json"
    p.write_text(json.dumps({"daily_capital_idr": 1, CONFIG_KEY: ["rsi", "bear"]}),
                 encoding="utf-8")
    cfg, off = load_entry_config(p)
    assert off == ["bear", "rsi"]
    assert cfg.veto_overbought is False
    assert cfg.block_buys_in_bear is False
    assert cfg.veto_parabolic is True


# ---- a mistake must be loud ----------------------------------------------

def test_an_unknown_name_raises_rather_than_disabling_nothing():
    """The failure this project keeps finding: a setting that silently no-ops.

    Left permissive, `"rsii"` would leave the RSI veto ENABLED while the user
    believed it was off, and no output would differ.
    """
    with pytest.raises(UnknownVetoName) as e:
        entry_config_from({CONFIG_KEY: ["rsii"]})
    assert "rsii" in str(e.value)
    assert "Refusing to run" in str(e.value)
    # It must also list what IS valid, or the user cannot fix it.
    for name in VETO_FLAGS:
        assert name in str(e.value)


def test_one_bad_name_among_good_ones_still_raises():
    with pytest.raises(UnknownVetoName):
        entry_config_from({CONFIG_KEY: ["rsi", "parabolik"]})


def test_a_bare_string_is_rejected_not_iterated_as_characters():
    '"rsi" would otherwise iterate to r, s, i and match nothing.'
    with pytest.raises(TypeError) as e:
        entry_config_from({CONFIG_KEY: "rsi"})
    assert "LIST" in str(e.value)


def test_a_wrong_type_is_rejected():
    with pytest.raises(TypeError):
        entry_config_from({CONFIG_KEY: {"rsi": True}})


def test_an_explicit_null_is_treated_as_no_configuration():
    cfg = entry_config_from({CONFIG_KEY: None})
    assert cfg.veto_overbought is True


# ---- the setting has to be visible ---------------------------------------

def test_describe_names_the_live_setting():
    assert "ALL ON" in describe(EntryConfig())
    assert "ALL OFF" in describe(entry_config_from({CONFIG_KEY: sorted(VETO_FLAGS)}))
    mixed = describe(entry_config_from({CONFIG_KEY: ["rsi", "obv"]}))
    assert "OFF obv, rsi" in mixed
    assert "parabolic" in mixed.split("|")[0], "the ON list must name what is on"


def test_describe_says_which_setting_was_measured_better():
    """A reader should not have to remember the study to read the line."""
    assert "measured-worst" in describe(EntryConfig())
    assert "measured-best" in describe(entry_config_from({CONFIG_KEY: sorted(VETO_FLAGS)}))


# ---- the live call sites must actually pass the cfg ----------------------

@pytest.mark.parametrize("script", ["kala_daily_trader.py", "kala_engine.py"])
def test_the_live_scanner_passes_a_cfg_to_evaluate_entry(script):
    """Without cfg=, EntryConfig() defaults apply and the config is inert."""
    src = (ROOT / script).read_text(encoding="utf-8")
    assert "load_entry_config()" in src, f"{script} does not load the config"
    assert "evaluate_entry(data, market_status=None)" not in src
    assert "evaluate_entry(data, market_status=mkt.get('status'))" not in src


def test_a_failed_veto_check_is_reported_not_swallowed():
    """It used to `except Exception: pass`, leaving the BUY and an empty list.

    An empty veto list means "nothing fired". A crashed check means "nothing
    ran". Those must not render identically on a buy recommendation.

    Asserted on the shared helper's OUTPUT. An earlier version grepped
    kala_daily_trader.py for the message and broke the moment the message
    moved into a function — which is exactly the signal that it was testing the
    location of a string rather than the behaviour.
    """
    from kala.entry_settings import veto_check_failed_note

    note = veto_check_failed_note(KeyError("Close"))
    assert "VETO CHECK FAILED" in note
    assert "entry guardrails did NOT run" in note
    assert "KeyError" in note

    src = (ROOT / "kala_daily_trader.py").read_text(encoding="utf-8")
    assert "veto_check_failed_note(_e)" in src, "the scanner does not use it"
    assert "except Exception:\n                pass" not in src
