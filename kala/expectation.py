"""What a BUY from this system has actually been worth, attached to the signal.

WHY THIS EXISTS
---------------
The daily scan ends like this::

    TOP PICK: XXXX (Score: 82/100 | ADX: 31 | R:R: 2.4:1)
    v2.1 FEATURES ACTIVE:
      [x] Time Series Analysis ...
      [x] Relative Strength vs IHSG ...
      ... nine checkmarks ...

Nine ticks, a score out of 100, a risk/reward ratio to one decimal place — and
nowhere on that screen does it say what a BUY from this system has been
MEASURED to be worth out of sample. The reader is given precision about the
signal and silence about the payoff, which reads as confidence.

The measured payoff is on disk. Against an equal-weighted benchmark built from
the traded universe itself, the fixed-baseline arm returned +1.71%/trade excess
at a clustered t of 1.92 and a deflated Sharpe of 0.766 — below both of the
report's own stated bars — and -0.44%/trade once its single biggest fold is
removed. That is not a secret; it is in a JSON file the daily run never opens.

This module opens it and puts it on the same screen as the recommendation.

THE ZERO-VS-MISSING RULE, STATED TO THE USER
--------------------------------------------
When no measurement exists, this prints NOT MEASURED and says in as many words
that an absent expectation is not an expectation of zero. Rendering a missing
measurement as ``+0.00%`` is the single defect this audit has found most often;
the live path is the last place it would be noticed.

WHY A MISMATCHED MEASUREMENT IS REFUSED
---------------------------------------
A walk-forward run made with ``--holding-days 90`` and every veto disabled does
not measure a live bot holding 60 days with every veto on. Printing its number
beside today's signals would be worse than printing nothing: it would be a
specific, sourced, wrong figure. So the provenance the saved table now carries
is compared against the live configuration, and any difference in the fields
that change what gets traded suppresses the number and names the difference.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .entry_settings import VETO_FLAGS
from .walkforward import DSR_CONFIDENT, T_CONFIDENT, edge_verdict

# Where the daily run looks unless told otherwise. A single conventional path
# means "re-run the walk-forward and the daily scan picks it up" is true
# without another config knob.
DEFAULT_PATH = "results/expectation.json"

# Older than this and the measurement is reported as stale. Two quarters is
# roughly one fold of the walk-forward: past that, the run predates market
# conditions the live bot is now trading in.
STALE_DAYS = 180

# Provenance fields that change WHICH trades happen. A difference in any of
# these means the saved table measured a different system.
BINDING_FIELDS = ("exit_profile", "holding_max_days", "baseline_threshold",
                  "spread_mode", "vetoes disabled")

# Imported rather than restated: if a sixth veto is ever added, a hardcoded
# five here would quietly report a no-veto run as "all five off" and match it
# against a live setup that has six off.
VETO_NAMES = tuple(sorted(VETO_FLAGS))


@dataclass(frozen=True)
class LiveSetup:
    """The configuration the daily run is about to trade with.

    Deliberately a value object rather than the live Config: the comparison is
    between two records of what was run, and taking a Config here would invite
    reaching into it for fields the saved table does not carry.
    """

    holding_max_days: int
    baseline_threshold: float
    disabled_vetoes: tuple[str, ...] = ()
    exit_profile: str = "legacy"
    spread_mode: str = "flat"

    @classmethod
    def from_config(cls, cfg, disabled_vetoes=(), exit_profile="legacy") -> "LiveSetup":
        return cls(
            holding_max_days=int(cfg.backtest.holding_max_days),
            baseline_threshold=float(cfg.backtest.score_entry_threshold),
            disabled_vetoes=tuple(sorted(disabled_vetoes or ())),
            exit_profile=(exit_profile or "legacy").strip().lower(),
            spread_mode=getattr(cfg.costs, "spread_mode", "flat"),
        )


@dataclass(frozen=True)
class Measurement:
    """A saved walk-forward fold table, read back.

    ``raw`` is kept whole so a field added to the table later is readable here
    without a schema migration; the named attributes are the ones this module
    reasons about.
    """

    path: Path
    raw: dict = field(repr=False)

    # -- provenance ---------------------------------------------------------
    @property
    def strategy(self) -> str | None:
        return self.raw.get("strategy")

    @property
    def exit_profile(self) -> str | None:
        return self.raw.get("exit_profile")

    @property
    def benchmark(self) -> str | None:
        return self.raw.get("benchmark")

    @property
    def holding_max_days(self):
        return self.raw.get("holding_max_days")

    @property
    def baseline_threshold(self):
        return self.raw.get("baseline_threshold")

    @property
    def disabled_vetoes(self) -> tuple[str, ...]:
        return tuple(self.raw.get("disabled_vetoes") or ())

    @property
    def applies_vetoes(self):
        """True/False as recorded, or None for a table written before the field.

        None matters: a table that never recorded the veto arm cannot be
        checked against the live veto setting, and saying so is different from
        saying the arms match.
        """
        return self.raw.get("apply_entry_vetoes")

    @property
    def n_tickers(self):
        return self.raw.get("n_tickers")

    @property
    def spread_mode(self):
        """Which spread model the measurement charged, or None if unrecorded.

        None is not "flat". Tables written before this field cannot say which
        model they used, and assuming the cheaper one is assuming the answer
        that flatters the live book.
        """
        return self.raw.get("spread_mode")

    @property
    def measured_at(self) -> str | None:
        return self.raw.get("measured_at")

    @property
    def grid_size(self) -> int:
        return int(self.raw.get("threshold_grid_size") or 0)

    # -- statistics ---------------------------------------------------------
    @property
    def folds(self) -> list[dict]:
        return list(self.raw.get("folds") or [])

    @property
    def excess(self) -> dict:
        return self.raw.get("pooled_excess_baseline") or {}

    @property
    def n_trades(self) -> int:
        return int(self.excess.get("n") or 0)

    @property
    def excess_pct(self):
        """EV per trade in excess of the benchmark, or None when unmeasured.

        None, never 0.0. A run made without ``--benchmark`` has no excess
        column at all, and the difference between "the edge is zero" and "the
        edge was never measured" is the whole point of this module.
        """
        if not self.n_trades:
            return None
        return self.excess.get("ev_pct")

    @property
    def clustered_t(self):
        return self.raw.get("pooled_excess_baseline_clustered_t")

    @property
    def dsr(self):
        return self.raw.get("pooled_excess_baseline_dsr")

    @property
    def has_baseline_folds(self) -> bool:
        """Does the table carry the BASELINE arm's per-fold excess?

        Tables written before this column existed do not. They cannot be
        decomposed against the baseline headline at all, and substituting the
        chosen arm's folds — which is what every consumer of this data did
        until now — subtracts one arm's quarter from another arm's total.
        """
        return any(f.get("excess_baseline_pct") is not None for f in self.folds)

    @property
    def concentration(self) -> tuple[float | None, int | None, str]:
        """(excess without the biggest fold, that fold's id, which arm).

        The arm is returned, not assumed. When the table carries the baseline
        column the decomposition matches the headline and the arm is
        "baseline". Otherwise it falls back to the chosen arm and SAYS SO, and
        ``chosen_excess_pct`` gives the pooled figure that fallback belongs
        beside — because a decomposition is only readable next to the total it
        decomposes.
        """
        if self.has_baseline_folds:
            value, fold_id = excess_excluding_largest_fold(
                self.folds, "n_baseline", "excess_baseline_pct")
            return value, fold_id, "baseline"
        value, fold_id = excess_excluding_largest_fold(self.folds)
        return value, fold_id, "chosen"

    @property
    def chosen_excess_pct(self):
        """Pooled excess of the walk-forward-chosen arm, or None if unsaved."""
        stats = self.raw.get("pooled_excess_chosen") or {}
        if not stats.get("n"):
            return None
        return stats.get("ev_pct")

    @property
    def negative_folds(self) -> tuple[int, int, str]:
        """(negative, total, arm) — counted on the same arm as ``concentration``."""
        key = "excess_baseline_pct" if self.has_baseline_folds else "excess_pct"
        arm = "baseline" if self.has_baseline_folds else "chosen"
        rows = [f for f in self.folds if f.get(key) is not None]
        return sum(1 for f in rows if f[key] < 0), len(rows), arm


def load(path: str | Path | None = None) -> Measurement | None:
    """Read a saved fold table, or None if there isn't a usable one.

    None covers missing, unreadable and malformed alike. The caller renders all
    three as NOT MEASURED, because for the reader they are the same situation:
    no evidence. What must never happen is a partial read presenting as a
    measurement, so a table that is not a JSON object is rejected outright.
    """
    p = Path(path or DEFAULT_PATH)
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    return Measurement(path=p, raw=raw)


def excess_excluding_largest_fold(folds, n_key: str = "n",
                                  excess_key: str = "excess_pct"
                                  ) -> tuple[float | None, int | None]:
    """Pooled excess with the single largest-CONTRIBUTING fold removed.

    ``n_key``/``excess_key`` name WHICH ARM's columns to read, and there is no
    default that silently mixes them: a decomposition of one arm's pooled
    figure has to be built from that same arm's folds. See
    ``Measurement.concentration`` for why this argument exists at all.

    Concentration is the failure this project keeps rediscovering: a pooled
    number that is really one quarter. The holding-period sweep climbed
    monotonically from -0.05% to +2.08% across 20/30/45/60/90 days and every
    one of those columns collapsed to at most +0.25% once its biggest fold came
    out — the ramp was one fold growing, not the strategy improving.

    Largest by CONTRIBUTION (n * excess), not by percentage. By percentage the
    winner is routinely a three-trade fold whose removal changes nothing, which
    would make this check pass while measuring the wrong thing.

    Deliberately NOT reported as "fold N is X% of the total": when the total is
    near zero that share explodes and flips sign, which reads as a dramatic
    finding about nothing. The re-pooled average is stable.

    Returns (excess, fold_id), or (None, None) when there is nothing to remove.
    """
    rows = [(f.get(n_key) or 0, f.get(excess_key), f.get("fold")) for f in folds]
    rows = [(n, e, i) for n, e, i in rows if e is not None and n]
    if len(rows) < 2:
        return None, None
    biggest = max(rows, key=lambda r: r[0] * r[1])
    rest = [r for r in rows if r is not biggest]
    denom = sum(n for n, _, _ in rest)
    if not denom:
        return None, None
    return sum(n * e for n, e, _ in rest) / denom, biggest[2]


def _fmt(value) -> str:
    if isinstance(value, (list, tuple)):
        return ", ".join(map(str, value)) if value else "(none)"
    return "(none)" if value in (None, "") else str(value)


def measured_vetoes_off(m: Measurement) -> tuple[str, ...] | None:
    """Which vetoes were OFF in the measured run, or None when unrecorded.

    NOT simply ``disabled_vetoes``. A run made without ``--apply-entry-vetoes``
    applied no vetoes at all, and records ``disabled_vetoes: []`` — the same
    empty list a full-veto run records. Compared naively, the no-veto arm and
    the all-veto arm agree, and the two arms differ by 4.23%/trade. Every one
    of the fifteen fold tables on disk is in exactly that state, so this is the
    comparison that would have gone wrong first.
    """
    applied = m.applies_vetoes
    if applied is None:
        return None
    if not applied:
        return tuple(sorted(VETO_NAMES))
    return tuple(sorted(m.disabled_vetoes))


def mismatches(m: Measurement, live: LiveSetup) -> list[tuple[str, str, str]]:
    """(field, measured, live) for every binding difference. Empty means applies.

    Only the fields that change which trades happen are checked. Strategy name
    and ticker count are shown to the reader but do not suppress the number:
    a universe that grew by a few names is still a measurement of this system,
    while a different holding period is a measurement of a different one.
    """
    out: list[tuple[str, str, str]] = []
    want_off = tuple(sorted(live.disabled_vetoes or ()))
    profile = m.exit_profile
    pairs = (
        # The exit profile decides whether a position is closed by a trailing
        # ladder or only by elapsed days. Two configurations that differ here
        # are not the same strategy holding for different lengths — they are
        # different strategies, and the ladder was measured at about -1.6
        # points per trade.
        ("exit_profile", profile.strip().lower() if profile else None,
         (live.exit_profile or "legacy").strip().lower()),
        ("holding_max_days", m.holding_max_days, live.holding_max_days),
        ("baseline_threshold", m.baseline_threshold, live.baseline_threshold),
        # A flat-spread book compared against a tick-floored measurement is
        # biased by ~0.23 points per trade on this account's holdings — 13% of
        # the measured excess, always in the flattering direction.
        ("spread_mode", m.spread_mode, live.spread_mode),
        ("vetoes disabled", measured_vetoes_off(m), want_off),
    )
    for key, got, want in pairs:
        if got is None:
            # A field the table never recorded cannot be shown to agree with
            # anything. "Not recorded" suppresses the number the same as a
            # difference does, because it is one — an unknown one.
            out.append((key, "not recorded", _fmt(want)))
        elif key == "baseline_threshold":
            if abs(float(got) - float(want)) > 1e-9:
                out.append((key, f"{float(got):g}", f"{float(want):g}"))
        elif isinstance(got, tuple):
            if tuple(got) != tuple(want):
                out.append((key, _fmt(got), _fmt(want)))
        elif got != want:
            out.append((key, _fmt(got), _fmt(want)))
    return out


def age_days(m: Measurement, today: date) -> int | None:
    """Days since the run, or None when the table carries no timestamp.

    Not derived from the file's mtime. Copying a fold table between machines
    rewrites mtime and would report a two-year-old measurement as fresh — a
    staleness check that lies in the reassuring direction is worse than none.
    """
    stamp = m.measured_at
    if not stamp:
        return None
    try:
        return (today - date.fromisoformat(str(stamp)[:10])).days
    except ValueError:
        return None


def verdict_lines(m: Measurement) -> list[str]:
    """The same verdict vocabulary the walk-forward report prints, plus the
    deflation the saved table may not be able to express.

    ``edge_verdict`` gates its deflated-Sharpe clause on knowing how many
    thresholds were tried, and tables written before ``threshold_grid_size``
    existed do not say. Left alone, such a table would render EDGE CONFIRMED
    with a sub-bar deflated Sharpe sitting two lines above it — precisely the
    contradiction between a headline and its own evidence that put that
    argument into ``edge_verdict`` in the first place. So when the count is
    unknown and the DSR is below the bar, the deflation is stated separately
    rather than silently skipped or invented as a number.
    """
    stats = dict(m.excess)
    lines = ["VERDICT: " + edge_verdict(stats, clustered_t=m.clustered_t,
                                        dsr=m.dsr, n_trials=m.grid_size)]
    if (m.dsr is not None and m.dsr < DSR_CONFIDENT and not m.grid_size
            and m.n_trades >= 30 and (m.excess_pct or 0) > 0
            and (m.clustered_t or stats.get("t_stat") or 0) >= T_CONFIDENT):
        lines.append(
            f"  ...but the deflated Sharpe is {m.dsr:.3f}, below {DSR_CONFIDENT}. "
            f"This table predates the")
        lines.append(
            "  grid-size field, so the verdict above could not deflate for the "
            "number of")
        lines.append(
            "  thresholds tried. Read the deflated Sharpe as governing.")
    return lines


def measure_command(live: LiveSetup | None, path: str | Path | None = None,
                    strategy: str = "momentum",
                    benchmark: str = "EQUAL_WEIGHT") -> list[str]:
    """The command that produces a table THIS setup would accept.

    Derived from the live configuration, not a fixed string. The fixed string
    this replaces read::

        python run_walkforward.py --strategy momentum --exit-profile
        forward_test --benchmark EQUAL_WEIGHT --save-folds ...

    Follow it with a tick-floored book and the resulting table records
    ``spread_mode: flat``, so the block that printed the instruction then
    REFUSES the table it asked for. An instruction that cannot be followed to a
    working result is the same defect as a warning that is wrong — and this one
    was mine.

    Returned as wrapped lines, ready to print.
    """
    p = Path(path or DEFAULT_PATH)
    args = ["python run_walkforward.py",
            f"--strategy {strategy}"]
    if live is not None:
        args.append(f"--exit-profile {live.exit_profile}")
        # --disable-veto requires --apply-entry-vetoes; with every name listed
        # this is the no-veto arm, recorded explicitly rather than by absence.
        args.append("--apply-entry-vetoes")
        if live.disabled_vetoes:
            args.append("--disable-veto " + " ".join(live.disabled_vetoes))
        if live.spread_mode == "tick_floor":
            args.append("--tick-spread")
        args.append(f"--holding-days {live.holding_max_days}")
        args.append(f"--baseline-threshold {live.baseline_threshold:g}")
    else:
        args.append("--exit-profile forward_test")
    args.append(f"--benchmark {benchmark}")
    args.append(f"--save-folds {p}")

    out, line = [], "  " + args[0]
    for a in args[1:]:
        if len(line) + len(a) + 1 > 76:
            out.append(line + " \\")
            line = "      " + a
        else:
            line += " " + a
    out.append(line)
    return out


def not_measured_lines(path: str | Path | None = None,
                       live: LiveSetup | None = None) -> list[str]:
    p = Path(path or DEFAULT_PATH)
    return [
        "MEASURED EXPECTATION: NOT MEASURED",
        f"  No usable walk-forward table at {p}.",
        "  The signals above carry no measured out-of-sample expectation.",
        "  That is NOT the same as an expectation of zero — it is an absence of",
        "  evidence, and it should be read as one.",
        "  To measure THIS configuration:",
        *measure_command(live, p),
    ]


def describe(m: Measurement | None, live: LiveSetup, today: date | None = None,
             path: str | Path | None = None) -> list[str]:
    """The block the daily run prints under its recommendations."""
    if m is None:
        return not_measured_lines(path, live)

    today = today or date.today()
    bad = mismatches(m, live)
    head = ["MEASURED EXPECTATION (what a BUY from this system has been worth, OOS)"]

    stamp = m.measured_at or "date not recorded"
    age = age_days(m, today)
    if age is None:
        when = f"measured {stamp}"
    elif age < 0:
        # A table stamped in the future is a clock or a hand-edit, not a fresh
        # measurement. Say so rather than quietly rendering "-4 days ago".
        when = f"measured {stamp} (stamped in the FUTURE — check the clock)"
    else:
        when = f"measured {stamp} ({age}d ago)"
        if age > STALE_DAYS:
            when += f" — STALE, older than {STALE_DAYS}d"
    head.append(
        f"  {when} · {_fmt(m.strategy)} · {_fmt(m.exit_profile)} · "
        f"hold {_fmt(m.holding_max_days)}d · vs {_fmt(m.benchmark)}")
    head.append(
        f"  {_fmt(m.n_tickers)} tickers · {len(m.folds)} folds · "
        f"{m.n_trades} pooled OOS trades")

    if bad:
        head.append("")
        head.append("  NOT APPLICABLE to the configuration about to trade:")
        for key, was, now in bad:
            # Two lines when either side is long. A veto list overflowing its
            # column pushed "live (none)" off the visual grid and made the two
            # halves of the comparison hard to tell apart — the one thing this
            # table exists to make obvious.
            if len(was) > 22 or len(now) > 22:
                head.append(f"    {key}")
                head.append(f"      measured: {was}")
                head.append(f"      live:     {now}")
            else:
                head.append(f"    {key:<20} measured {was:<24} live {now}")
        head.append("  A measurement of a different configuration is not a")
        head.append("  measurement of this one. The number is withheld rather than")
        head.append("  printed beside signals it does not describe.")
        head.append("  Re-measure with the live settings:")
        head.extend(measure_command(live, m.path))
        return head

    if m.excess_pct is None:
        head.append("")
        head.append("  excess over benchmark: NOT MEASURED in this run — it was")
        head.append("    made without a benchmark, so there is no excess column.")
        head.append("    Re-run with --benchmark EQUAL_WEIGHT to get one.")
        return head

    ct = f"{m.clustered_t:+.2f}" if m.clustered_t is not None else "n/a"
    dsr = f"{m.dsr:.3f}" if m.dsr is not None else "n/a"
    head.append(
        f"  excess over benchmark: {m.excess_pct:+.2f}%/trade   "
        f"clustered t {ct}   deflated Sharpe {dsr}")

    xb, fold_id, arm = m.concentration
    if xb is not None and arm == "baseline":
        head.append(
            f"  excluding the biggest single fold (#{fold_id}): {xb:+.2f}%/trade")
    elif xb is not None:
        # Fallback arm. Printed WITH its own pooled figure so the two numbers
        # being compared are from the same measurement — the headline above is
        # a different arm and subtracting this fold from it is meaningless.
        chosen = m.chosen_excess_pct
        head.append("  concentration is only available for the WALK-FORWARD-CHOSEN")
        head.append("  arm in this table — it predates the per-fold baseline column:")
        if chosen is not None:
            head.append(f"    chosen arm pooled: {chosen:+.2f}%/trade")
        head.append(
            f"    chosen arm excluding its biggest fold (#{fold_id}): "
            f"{xb:+.2f}%/trade")
        head.append("  Re-run to get this decomposition for the arm above.")
    neg, total, neg_arm = m.negative_folds
    if total:
        label = "" if neg_arm == "baseline" else " (chosen arm)"
        head.append(f"  {neg} of {total} folds negative{label}.")
    head.extend("  " + ln for ln in verdict_lines(m))
    return head


def block(live: LiveSetup, path: str | Path | None = None,
          today: date | None = None) -> list[str]:
    """Load and describe in one call — what the daily run actually uses."""
    return describe(load(path), live, today=today, path=path)


def live_lines(cfg: dict, trade_cfg, path: str | Path | None = None,
               today: date | None = None) -> list[str]:
    """The whole block the daily run logs: settings first, then their payoff.

    ``entry_settings.describe`` is called here because until now it was called
    NOWHERE. It exists with tests and a docstring reading "a setting that
    cannot be seen from the output is a setting nobody can verify took effect"
    — and it was not in any output. This audit told the user in writing to
    apply ``disabled_entry_vetoes`` and then "verify the log reads entry
    vetoes: ALL OFF", which no code was capable of printing. The instruction
    was unfollowable and nothing would have said so.

    ``cfg`` is the parsed runner_config dict and ``trade_cfg`` the Config
    already resolved from its ``exit_profile``, both passed in rather than
    re-read, so this block reports the settings the run is actually using and
    not a second, independently loaded copy that could disagree.
    """
    from .entry_settings import describe as describe_vetoes
    from .entry_settings import entry_config_from

    ecfg = entry_config_from(cfg or {})
    disabled = sorted((cfg or {}).get("disabled_entry_vetoes") or [])
    live = LiveSetup.from_config(trade_cfg, disabled,
                                 exit_profile=(cfg or {}).get("exit_profile"))
    return [describe_vetoes(ecfg), ""] + block(live, path=path, today=today)
