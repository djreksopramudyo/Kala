"""Preflight told the user a working setting was doing nothing.

`check_config_keys` compares `runner_config.json` against a hand-maintained
`KNOWN_CONFIG_KEYS` and warns:

    'disabled_entry_vetoes' is not read by any code. It is silently ignored,
    so whatever you set it to is having no effect.

That setting IS read — by `entry_settings.entry_config_from` — and it is the
audit's headline recommendation, worth +4.23 points per trade. A user who
applied it and then ran preflight was told, in those words, to take it out.
`breaker_preserve_halt_when_unreadable` was in the same state: a live SAFETY
toggle, read at `daily_run.py`, reported as inert.

A registry that is wrong in this direction is worse than no registry, because
it argues the user out of a correct configuration.

The existing guard only checked `daily_run.DEFAULT_CONFIG ⊆ KNOWN_CONFIG_KEYS`.
Both missing keys are read elsewhere, so nothing covered them. These tests scan
the source instead.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kala.entry_settings import CONFIG_KEY as ENTRY_VETO_KEY  # noqa: E402
from kala.preflight import KNOWN_CONFIG_KEYS, check_config_keys  # noqa: E402

# `cfg.get("literal")` and friends. Deliberately narrow: it sees the common
# spelling and nothing else. A key read through a variable — which is exactly
# how `disabled_entry_vetoes` hid — is invisible here, which is why the
# CONFIG_KEY test below exists as a separate net.
KEY_READ = re.compile(
    r"""(?:cfg|settings|config|conf)\.get\(\s*["']([a-z_][a-z0-9_]*)["']""")

# Used ONLY by the reverse check. Deliberately loose — `cfg["x"]`, and any
# `.get("x")` at all, including `(settings or {}).get("x")` which the strict
# pattern above cannot see past the parenthesis. Looseness is safe in this
# direction: at worst it lets a dead key hide, whereas a loose FORWARD pattern
# would accuse a live one.
ANY_READ = re.compile(
    r"""(?:\.get\(|\[)\s*["']([a-z_][a-z0-9_]*)["']""")


def source_files() -> list[Path]:
    files = sorted(ROOT.glob("*.py")) + sorted((ROOT / "kala").glob("*.py"))
    return [p for p in files if not p.name.startswith("test_")]


def keys_read_in_source() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for p in source_files():
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            for m in KEY_READ.finditer(line):
                found.setdefault(m.group(1), []).append(
                    f"{p.relative_to(ROOT)}:{i}")
    return found


def test_the_scanner_finds_something():
    """Guard the guard: a broken regex would make every test below vacuous."""
    found = keys_read_in_source()
    assert len(found) >= 20, f"only found {sorted(found)}"
    assert "exit_profile" in found


# Keys read through a variable rather than a literal, so the scan above cannot
# see them. Each needs a reason, because this list is the escape hatch that
# would otherwise let a dead entry hide.
READ_INDIRECTLY = {
    # entry_settings reads it as CONFIG_KEY; preflight imports that constant.
    ENTRY_VETO_KEY: "kala/entry_settings.py, via CONFIG_KEY",
}


def test_every_key_read_from_a_config_dict_is_registered():
    unregistered = {k: v for k, v in keys_read_in_source().items()
                    if k not in KNOWN_CONFIG_KEYS}
    assert not unregistered, (
        "these keys are read by the code but missing from KNOWN_CONFIG_KEYS, "
        "so preflight tells the user they have no effect: "
        + "; ".join(f"{k} ({v[0]})" for k, v in sorted(unregistered.items())))


def test_the_registry_tracks_the_constant_the_reader_uses():
    """The constant and the registry cannot drift if there is only one of them.

    Asserted by RENAMING the constant and reloading preflight: a registry that
    tracks it follows the rename, a registry with its own copy of the string
    does not. Grepping preflight's source for the import would pass on a file
    that also carried a stale literal — and duplicating that literal is what
    let the two disagree in the first place.
    """
    import importlib

    import kala.entry_settings as es
    import kala.preflight as pf

    original = es.CONFIG_KEY
    try:
        es.CONFIG_KEY = "zzz_renamed_for_this_test"
        reloaded = importlib.reload(pf)
        assert "zzz_renamed_for_this_test" in reloaded.KNOWN_CONFIG_KEYS, (
            "preflight carries its own copy of the key rather than the "
            "constant the reader uses")
        assert original not in reloaded.KNOWN_CONFIG_KEYS, (
            "the old spelling survived the rename — there is a stale literal")
    finally:
        es.CONFIG_KEY = original
        importlib.reload(pf)

    assert ENTRY_VETO_KEY in pf.KNOWN_CONFIG_KEYS


def dead_keys(registry) -> list[str]:
    """Registered keys that appear nowhere in the source as a read."""
    seen = set(keys_read_in_source()) | set(READ_INDIRECTLY)
    for p in source_files():
        seen |= set(ANY_READ.findall(p.read_text(encoding="utf-8")))
    return sorted(set(registry) - seen)


def test_no_registered_key_is_read_by_nothing():
    """The mirror of the test above, and the case that got past it.

    `"costs"` sat in the registry, read by no code at all. preflight — whose
    entire job is catching settings that do nothing — blessed it. A user
    could put a whole cost model in runner_config.json, be told the config
    was fine, and have it ignored.

    A key legitimately read through a variable goes in READ_INDIRECTLY with a
    reason. Everything else has to appear in the source as a literal.
    """
    assert not dead_keys(KNOWN_CONFIG_KEYS), (
        "these keys are registered as real but nothing reads them, so "
        "preflight tells the user they are fine while they do nothing: "
        + ", ".join(dead_keys(KNOWN_CONFIG_KEYS)))


def test_the_dead_key_check_would_catch_one():
    """Non-vacuity. A check that can only ever pass is not a check.

    `"costs"` is the real example: registered, read by nothing, blessed by
    preflight for as long as it sat there.
    """
    assert dead_keys(set(KNOWN_CONFIG_KEYS) | {"costs"}) == ["costs"]
    assert dead_keys(set(KNOWN_CONFIG_KEYS) | {"zzz_never_read"}) == [
        "zzz_never_read"]


# ---------------------------------------------------------------------------
# what the user actually does
# ---------------------------------------------------------------------------

RECOMMENDED = {
    "exit_profile": "forward_test",
    "disabled_entry_vetoes": ["rsi", "parabolic", "obv", "thin_volume", "bear"],
}


def test_the_configuration_this_audit_recommends_passes_clean():
    """The whole point. If this warns, the advice contradicts the tooling."""
    checks = check_config_keys(RECOMMENDED)
    assert all(c.status == "OK" for c in checks), [c.message for c in checks]


def test_the_circuit_breaker_option_is_not_called_inert():
    """A safety toggle reported as having no effect is the worst polarity."""
    checks = check_config_keys({"breaker_preserve_halt_when_unreadable": True})
    assert all(c.status == "OK" for c in checks), [c.message for c in checks]


@pytest.mark.parametrize("typo", [
    "disabled_entry_veto", "disabled_entry_vetos", "exit_profiles",
    "breaker_enable",
])
def test_a_real_typo_is_still_caught(typo):
    """Non-vacuity: widening the registry must not blunt the detector."""
    checks = check_config_keys({typo: "x"})
    assert any(c.status == "WARN" and typo in c.message for c in checks), (
        f"{typo} was accepted as a real key")


def test_the_warning_still_says_the_setting_has_no_effect():
    """The wording is the useful part — a bare 'unknown key' is ignorable."""
    (warn,) = [c for c in check_config_keys({"nonsense_key": 1})
               if c.status == "WARN"]
    assert "no effect" in warn.message
