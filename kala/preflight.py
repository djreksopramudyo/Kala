"""
Pre-deployment checks — the boring list in DEPLOY_CHECKLIST.md, automated.

WHY THIS EXISTS
---------------
`DEPLOY_CHECKLIST.md` is a manual checklist, and the two things on it that
hurt most are exactly the two a human skips: a Telegram token left sitting in
plaintext in `runner_config.json`, and a timer that was *written* but never
*installed*. Both fail silently. A token leaks quietly; an uninstalled timer
just means the daily message never arrives and you assume the market was
quiet.

A third silent failure is not on the checklist at all because nobody thought
to look for it: a **mistyped config key**. `runner_config.json` is read with
``cfg.get(key, default)`` everywhere, so a typo — `scorecard_weekday` instead
of `scorecard_report_weekday` — does not raise. It silently keeps the default
forever, and the setting you thought you changed never took effect.

WHAT THIS IS NOT
----------------
It does not check that your *strategy* is sound; ~20 studies in
`PROJECT_STATUS.md` already answered that (it isn't, beyond the structural
choices). This only checks that the machine is wired up the way you think.

Every check is read-only. Nothing here writes, sends, or spends.
"""

from __future__ import annotations

import datetime as _dt
import difflib
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

OK, WARN, FAIL, SKIP = "OK", "WARN", "FAIL", "SKIP"


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    message: str

    @property
    def failed(self) -> bool:
        return self.status == FAIL


from .entry_settings import CONFIG_KEY as _ENTRY_VETO_KEY

# Config keys the code actually reads. Kept explicit rather than imported from
# daily_run so this module stays inside the package (daily_run imports kala,
# not the reverse). test_preflight.py asserts this stays in sync with
# daily_run.DEFAULT_CONFIG, so adding a key without registering it fails CI
# rather than silently weakening the typo check.
#
# That guard covered DEFAULT_CONFIG only. Two keys read elsewhere were missing
# — see the notes below — and for each of them this file confidently told the
# user the setting was doing nothing. A registry that is wrong in that
# direction is worse than no registry: it argues the user out of a correct
# configuration. test_config_keys_are_registered.py now scans the source for
# every literal key read off a config dict.
KNOWN_CONFIG_KEYS = frozenset({
    # daily_run.DEFAULT_CONFIG
    "auto_paper_trade", "breaker_enabled", "breaker_halt_drawdown_pct",
    "breaker_resume_drawdown_pct", "daily_capital_idr",
    "friction_report_weekday", "max_pct_of_adv", "max_positions",
    "news_check_enabled", "news_max_tickers", "risk_pct_per_trade",
    "scorecard_benchmark", "scorecard_report_enabled",
    "scorecard_report_weekday", "start_capital_idr", "telegram_chat_id",
    "telegram_token", "walkforward_max_tickers", "walkforward_period",
    "watchlist_min_discount_pct", "weekly_fundamental_weekday",
    # read elsewhere (telegram_bot, rebalance, papertrade, intraday_watch)
    # "costs" used to sit here. Nothing read it — the mirror image of the
    # missing keys below: a registered key that does nothing, blessed by the
    # very check that exists to catch settings that do nothing. Removed, and
    # the registry is now checked in BOTH directions.
    "target_allocation", "charge_manual_costs",
    # Which spread model books live fills. Absent means "flat", the historical
    # behaviour; "tick_floor" matches every measurement in this project. See
    # config.live_costs for why the default is not simply corrected.
    "costs_spread_mode",
    "intraday_pulse_minutes",
    # which exit geometry the live loop trades — see config.config_for_profile.
    # "legacy" keeps the historical stop/target/trailing ladder; "forward_test"
    # runs the configuration the 2026-08 sweeps validated. Absent means legacy,
    # so an untouched config never changes strategy on its own.
    "exit_profile",
    # monthly "who closed these positions" check — see kala/discipline.py
    "discipline_report_enabled", "discipline_report_weekday",
    # Circuit-breaker option read at daily_run.py's BreakerConfig. It was
    # missing here, so preflight told the user a live SAFETY toggle "is not
    # read by any code" and was "having no effect" — about a setting that
    # governs whether a halt survives an unreadable state file.
    "breaker_preserve_halt_when_unreadable",
    # IMPORTED, not spelled out. This is the setting the audit's headline
    # recommendation asks for (+4.23 points/trade), and preflight was telling
    # anyone who applied it that it "is not read by any code. It is silently
    # ignored, so whatever you set it to is having no effect." — the exact
    # opposite of the truth, about the single most valuable change available.
    # Importing the constant from the module that reads it makes that
    # particular drift impossible rather than merely tested.
    _ENTRY_VETO_KEY,
})


def check_secrets(cfg: dict, env: dict | None = None) -> list[Check]:
    """The irreversible-if-skipped one: credentials in plaintext.

    A token in ``runner_config.json`` has already leaked every time that file
    was copied, zipped or shared — which in this project's history is several
    times. Env vars are the supported path (see kala/notify.py).
    """
    import os

    from kala.notify import CHAT_ID_ENV, TOKEN_ENV, _is_placeholder

    env = os.environ if env is None else env
    out: list[Check] = []

    cfg_token = str(cfg.get("telegram_token", "") or "")
    cfg_chat = str(cfg.get("telegram_chat_id", "") or "")
    has_cfg_token = bool(cfg_token) and not _is_placeholder(cfg_token)
    has_cfg_chat = bool(cfg_chat) and not _is_placeholder(cfg_chat)
    has_env_token = bool(str(env.get(TOKEN_ENV, "") or "").strip())
    has_env_chat = bool(str(env.get(CHAT_ID_ENV, "") or "").strip())

    if has_cfg_token:
        out.append(Check(
            "secrets/token", FAIL,
            f"telegram_token is stored in plaintext in the config. Move it to "
            f"the {TOKEN_ENV} env var and blank the config field. If this file "
            f"has ever been shared or zipped, revoke the token via @BotFather "
            f"first — it is already compromised."))
    elif has_env_token:
        out.append(Check("secrets/token", OK, f"token read from {TOKEN_ENV}"))
    else:
        out.append(Check(
            "secrets/token", FAIL,
            f"no Telegram token anywhere — not in {TOKEN_ENV}, not in the "
            f"config. The bot cannot send you anything."))

    if has_cfg_chat:
        out.append(Check(
            "secrets/chat_id", WARN,
            f"telegram_chat_id sits in the config. Less sensitive than the "
            f"token (it identifies a chat, it does not grant access), but "
            f"{CHAT_ID_ENV} is the supported home for it."))
    elif has_env_chat:
        out.append(Check("secrets/chat_id", OK, f"chat_id read from {CHAT_ID_ENV}"))
    else:
        out.append(Check("secrets/chat_id", FAIL,
                         "no Telegram chat_id configured — messages have "
                         "nowhere to go."))
    return out


def check_config_keys(cfg: dict,
                      known: frozenset[str] = KNOWN_CONFIG_KEYS) -> list[Check]:
    """Catch mistyped keys, which otherwise fail completely silently.

    Everything is read with ``cfg.get(key, default)``, so an unrecognised key
    is not an error — it simply never takes effect. This is the only place
    that will ever tell you.
    """
    unknown = sorted(set(cfg) - set(known))
    if not unknown:
        return [Check("config/keys", OK, f"{len(cfg)} keys, all recognised")]
    out = []
    for key in unknown:
        near = difflib.get_close_matches(key, sorted(known), n=1, cutoff=0.75)
        hint = f" — did you mean '{near[0]}'?" if near else "."
        out.append(Check(
            "config/keys", WARN,
            f"'{key}' is not read by any code{hint} It is silently ignored, so "
            f"whatever you set it to is having no effect."))
    return out


def check_breaker_config(cfg: dict) -> list[Check]:
    """Hysteresis is only hysteresis while resume sits below halt.

    Inverted, the breaker flips state every day at a constant drawdown and
    permits new buys on every other one — the exact opposite of why it was
    switched on. evaluate_breaker() clamps and says so at runtime; catching
    it here means finding out before the money is in, not after.
    """
    if not cfg.get("breaker_enabled"):
        return [Check("breaker", SKIP, "disabled (breaker_enabled=false)")]
    try:
        halt = float(cfg.get("breaker_halt_drawdown_pct", 15.0))
        resume = float(cfg.get("breaker_resume_drawdown_pct", 10.0))
    except (TypeError, ValueError):
        return [Check("breaker", FAIL,
                      "breaker_halt_drawdown_pct / breaker_resume_drawdown_pct "
                      "are not numbers")]
    if resume > halt:
        return [Check(
            "breaker", FAIL,
            f"breaker_resume_drawdown_pct ({resume:.0f}%) is ABOVE "
            f"breaker_halt_drawdown_pct ({halt:.0f}%). Resume must be the "
            f"lower of the two, or the breaker flips on and off daily and "
            f"lets new buys through on alternate days.")]
    if halt <= 0:
        return [Check("breaker", FAIL,
                      f"breaker_halt_drawdown_pct is {halt:.0f}% — a "
                      f"non-positive limit can never trip.")]
    return [Check("breaker", OK,
                  f"halt at {halt:.0f}%, resume at {resume:.0f}%")]


def check_state(state: dict, today: str | None = None) -> list[Check]:
    """Structural sanity of paper_state.json.

    DEPLOY_CHECKLIST calls an unrecorded or misrecorded fill the single most
    common failure mode, because it corrupts /report, /rebalance and TWR at
    once and does so quietly.
    """
    today = today or _dt.date.today().isoformat()
    positions = state.get("positions") or {}
    if not positions and not (state.get("log") or []):
        return [Check("state/positions", WARN,
                      "no positions and no closed trades recorded yet — "
                      "nothing to check. If you have actually bought, the "
                      "fills were never recorded with /buy.")]

    problems: list[str] = []
    for ticker, p in sorted(positions.items()):
        try:
            entry = float(p.get("entry_price") or 0)
            shares = float(p.get("shares") or 0)
        except (TypeError, ValueError):
            problems.append(f"{ticker}: entry_price/shares not numeric")
            continue
        date = str(p.get("entry_date") or "")
        if entry <= 0:
            problems.append(f"{ticker}: entry_price is {entry}")
        if shares <= 0:
            problems.append(f"{ticker}: shares is {shares}")
        if not date:
            problems.append(f"{ticker}: no entry_date (TWR will misdate it)")
        elif date > today:
            problems.append(f"{ticker}: entry_date {date} is in the future")

    if problems:
        return [Check("state/positions", FAIL,
                      f"{len(problems)} malformed position(s): "
                      + "; ".join(problems))]
    return [Check("state/positions", OK,
                  f"{len(positions)} position(s) well-formed, "
                  f"{len(state.get('log') or [])} closed trade(s) logged")]


def check_universe() -> list[Check]:
    """ISSI is revised roughly every May and November; a stale list means you
    may be holding something no longer sharia-compliant."""
    from kala.universe import staleness_warning

    warning = staleness_warning()
    if warning:
        return [Check("universe/issi", WARN, warning.strip())]
    return [Check("universe/issi", OK, "ISSI list is within its refresh window")]


def check_timers(runner=None) -> list[Check]:
    """'Written != installed' — the checklist's own words.

    systemd-specific, so it SKIPs rather than passes on Windows/macOS. A skip
    is honest; a green tick on a machine with no systemd would be a lie.
    """
    if runner is None:
        if not shutil.which("systemctl"):
            return [Check("timers", SKIP,
                          "no systemctl on this machine — if the bot runs on a "
                          "Linux VPS, run this script there instead. Nothing "
                          "about timers can be verified from here.")]

        def runner(args):
            # encoding pinned: systemctl output is decoded here, and the
            # locale default differs between the CI box and a Windows dev
            # machine. errors="replace" because a stray byte from an
            # unrelated unit must not abort a preflight CHECK.
            return subprocess.run(args, capture_output=True, text=True,
                                  encoding="utf-8", errors="replace",
                                  timeout=10).stdout

    wanted = ["kala-bot.service", "kala-daily.timer", "kala-fundamentals.timer"]
    try:
        listed = runner(["systemctl", "list-unit-files", "--no-pager"])
    except Exception as e:                       # noqa: BLE001 - reported, not raised
        return [Check("timers", WARN, f"could not query systemd: {e}")]

    out = []
    for unit in wanted:
        if unit in listed:
            out.append(Check(f"timers/{unit}", OK, "installed"))
        elif unit == "kala-fundamentals.timer":
            out.append(Check(
                f"timers/{unit}", WARN,
                "not installed. This is the time-blocked one: the fundamental "
                "value factor cannot be tested until this archive accumulates "
                "calendar time, so every month it does not run is a month that "
                "lead stays blocked. See DEPLOY_VPS.md step 7."))
        else:
            out.append(Check(f"timers/{unit}", FAIL,
                             "not installed — written but never enabled."))
    return out


def run_all(cfg: dict, state: dict, *, today: str | None = None,
            skip_timers: bool = False) -> list[Check]:
    checks: list[Check] = []
    checks += check_secrets(cfg)
    checks += check_config_keys(cfg)
    checks += check_breaker_config(cfg)
    checks += check_state(state, today=today)
    checks += check_universe()
    if not skip_timers:
        checks += check_timers()
    return checks


def format_checks(checks: list[Check]) -> str:
    icon = {OK: "✅", WARN: "⚠️ ", FAIL: "❌", SKIP: "⏭️ "}
    width = max((len(c.name) for c in checks), default=0)
    lines = ["PREFLIGHT — DEPLOY_CHECKLIST.md, automated", ""]
    for c in checks:
        lines.append(f"{icon.get(c.status, '?')} {c.name.ljust(width)}  {c.message}")
    n_fail = sum(c.status == FAIL for c in checks)
    n_warn = sum(c.status == WARN for c in checks)
    lines.append("")
    if n_fail:
        lines.append(f"{n_fail} FAILURE(S), {n_warn} warning(s). "
                     f"Fix the failures before funding anything.")
    elif n_warn:
        lines.append(f"No failures, {n_warn} warning(s) worth reading.")
    else:
        lines.append("All checks passed.")
    lines.append("")
    lines.append("This checks the plumbing, not the plan. The strategy "
                 "questions are answered in PROJECT_STATUS.md.")
    return "\n".join(lines)


def load_json(path: str | Path) -> dict:
    """Read a JSON file, returning {} when absent. Malformed JSON raises —
    a corrupt config is a finding, not something to paper over."""
    p = Path(path)
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))
