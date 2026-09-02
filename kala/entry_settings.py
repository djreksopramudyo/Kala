"""Make the live bot's entry vetoes configurable — they were hardcoded.

WHY THIS EXISTS
---------------
Measured on the full universe, walk-forward, against an equal-weighted
benchmark built from the traded universe itself (fixed-baseline arm):

    no vetoes                +1.71%/trade   clustered t +1.92
    only bear                -0.50%         clustered t -0.31
    only obv                 -0.80%         clustered t -0.52
    only thin_volume         -1.25%         clustered t -0.82
    only rsi                 -2.10%         clustered t -1.75
    only parabolic           -2.30%         clustered t -2.98
    ALL FIVE (live setting)  -2.52%         clustered t -3.10

Every configuration containing a veto is worse than none, and the ordering is
monotone. The live bot ran the bottom row.

It ran it with no way to change it. ``kala_daily_trader`` and
``kala_engine`` both called ``evaluate_entry(data, market_status=...)``
with no ``cfg``, so ``EntryConfig()``'s defaults applied — all five vetoes ON,
hardcoded, unreachable from ``runner_config.json``. The measured-best setting
could not be selected without editing source.

WHAT THIS DOES NOT DO
---------------------
It does NOT change the default. Absent configuration the behaviour is byte-for-
byte what it was: every veto on. Flipping a live trading bot's entry logic as a
side effect of a refactor is exactly the kind of silent change this audit
exists to find. The measured-better setting is opt-in and the config line is in
the docstring below.

USAGE
-----
In ``runner_config.json``::

    "disabled_entry_vetoes": ["rsi", "parabolic", "obv", "thin_volume", "bear"]

An unknown name is an ERROR, not a no-op: a typo that silently disables nothing
would leave the bot running the configuration the user believed they had turned
off — and nothing on screen would differ.
"""

from __future__ import annotations

import json
from pathlib import Path

from .config import EntryConfig

CONFIG_KEY = "disabled_entry_vetoes"

# Same names the walk-forward's --disable-veto accepts, so a configuration and
# the experiment that justified it are written the same way.
VETO_FLAGS = {
    "rsi": "veto_overbought",
    "parabolic": "veto_parabolic",
    "obv": "veto_distribution",
    "thin_volume": "veto_thin_volume",
    "bear": "block_buys_in_bear",
}


class UnknownVetoName(ValueError):
    """A name in the config matches no veto. Never treated as 'disable nothing'."""


def entry_config_from(settings: dict | None, **overrides) -> EntryConfig:
    """Build an EntryConfig from a parsed runner_config dict.

    ``settings`` is the whole config dict (or None). Missing key -> defaults,
    i.e. every veto enabled, unchanged from before this module existed.

    Raises UnknownVetoName for a name that matches nothing, and TypeError if
    the value is not a list of strings. Both are configuration mistakes that
    would otherwise present as "the setting had no effect".
    """
    names = (settings or {}).get(CONFIG_KEY, [])
    if names is None:
        names = []
    if isinstance(names, str):
        raise TypeError(
            f'{CONFIG_KEY} must be a LIST of names, not the string {names!r} — '
            f'e.g. ["rsi", "parabolic"]')
    if not isinstance(names, (list, tuple)):
        raise TypeError(f"{CONFIG_KEY} must be a list of names, got {type(names).__name__}")

    unknown = [n for n in names if n not in VETO_FLAGS]
    if unknown:
        raise UnknownVetoName(
            f"{CONFIG_KEY} contains unknown veto name(s): {', '.join(map(str, unknown))}. "
            f"Valid names: {', '.join(sorted(VETO_FLAGS))}. Refusing to run rather "
            f"than silently leaving those vetoes ENABLED.")

    off = {VETO_FLAGS[n]: False for n in names}
    return EntryConfig(**{**off, **overrides})


def load_entry_config(config_path: str | Path | None = None) -> tuple[EntryConfig, list[str]]:
    """(EntryConfig, disabled names) read from runner_config.json.

    A missing or unreadable config file yields the DEFAULTS — the historical
    behaviour — because the live scanner must not stop scanning over a config
    problem. A config file that exists but names a veto wrongly still raises:
    that is a statement the user made and got wrong, not an absence.
    """
    path = Path(config_path) if config_path else Path(__file__).resolve().parent.parent / "runner_config.json"
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return EntryConfig(), []
    cfg = entry_config_from(settings)
    return cfg, sorted(settings.get(CONFIG_KEY) or [])


def describe(cfg: EntryConfig) -> str:
    """One line naming which vetoes are live, for the daily log.

    A setting that cannot be seen from the output is a setting nobody can
    verify took effect.
    """
    on = sorted(n for n, f in VETO_FLAGS.items() if getattr(cfg, f))
    off = sorted(n for n, f in VETO_FLAGS.items() if not getattr(cfg, f))
    if not off:
        return f"entry vetoes: ALL ON ({', '.join(on)}) — the measured-worst setting"
    if not on:
        return ("entry vetoes: ALL OFF — the measured-best setting "
                "(+1.71%/trade vs -2.52% with all five)")
    return f"entry vetoes: ON {', '.join(on)}  |  OFF {', '.join(off)}"


def veto_check_failed_note(exc: BaseException) -> str:
    """The note a scanner puts in `entry_vetoes` when the check itself crashed.

    Both scanners wrap `evaluate_entry` in a try/except. Both used to
    `pass`, leaving the BUY standing with an EMPTY veto list — and an empty
    list means "nothing fired", which is a different fact from "nothing ran".
    A downstream reader cannot tell them apart, and the second one is a BUY
    recommendation with no guardrails applied.

    One function so the two scanners cannot drift into wording the same
    failure differently, and so a test can assert on the message by CALLING
    it rather than grepping for a string that happens to be split across two
    source literals — which is how the first version of this test failed.
    """
    return (f"VETO CHECK FAILED ({type(exc).__name__}: {exc}) — "
            f"entry guardrails did NOT run on this name")
