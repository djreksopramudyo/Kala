"""
Configuration objects for the kala engine.

Everything that used to be a scattered magic-number (``-7.0`` here, ``0.0019``
there, ``15.0`` in three different files) lives here in one typed, documented
place. Construct a ``Config()`` for defaults, or override any field.

    >>> cfg = Config(risk=RiskConfig(hard_stop_pct=-8.0))
    >>> cfg.risk.hard_stop_pct
    -8.0
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace


@dataclass
class CostModel:
    """Transaction costs for the Indonesian market (IDX).

    IDX costs are ASYMMETRIC — the sell side carries an extra transaction tax
    (PPh final 0.1%) on top of the broker fee, and you always cross the
    bid/ask spread on both legs. Modelling a single flat commission (as the
    original scripts did) understates real round-trip drag by ~0.3-0.4% and
    makes a losing strategy look profitable in backtests.
    """

    buy_commission: float = 0.0019   # broker fee, buy leg (~0.19%)
    sell_commission: float = 0.0015  # broker fee, sell leg (~0.15%)
    sell_tax: float = 0.0010         # PPh final transaction tax, sell only (0.1%)
    half_spread: float = 0.0010      # half the bid/ask spread, paid on each leg

    # "flat": half_spread is a constant fraction regardless of price — the
    #   historical assumption every validated number was computed under.
    # "tick_floor": half_spread is FLOORED at half of one IDX price tick at
    #   the fill price. A 67-rupiah stock cannot have a spread tighter than
    #   its 1-rupiah tick (~1.5%), so the flat 0.10% assumption understates
    #   real costs by ~7x there — and by ~2-3x for most of the 200-2,000
    #   tier. Flat stays the default so existing backtests/tests are
    #   unchanged; flip this on (e.g. --tick-spread on run_walkforward.py /
    #   compare_exit_engines.py) to MEASURE how much edge survives honest
    #   spreads before deciding whether cheap stocks need an entry veto.
    spread_mode: str = "flat"        # "flat" | "tick_floor"

    @property
    def sell_total(self) -> float:
        """Total proportional cost on the sell leg (fee + tax)."""
        return self.sell_commission + self.sell_tax

    @property
    def buy_total(self) -> float:
        """Total proportional cost on the buy leg."""
        return self.buy_commission

    @property
    def round_trip(self) -> float:
        """Total proportional drag for a full in-and-out trade incl. spread
        (flat-mode figure; tick_floor makes the spread legs price-aware)."""
        return self.buy_commission + self.sell_total + 2 * self.half_spread

    def half_spread_at(self, price: float) -> float:
        """Half-spread as a fraction of ``price``. In flat mode this is just
        the constant. In tick_floor mode it is floored at half of one tick:
        the quoted spread can never be tighter than 1 tick, and a market-ish
        fill pays about half of it per leg."""
        if self.spread_mode != "tick_floor" or price <= 0:
            return self.half_spread
        return max(self.half_spread, idx_tick_size(price) / price / 2.0)

    def buy_multiplier(self, price: float) -> float:
        """Multiply a raw fill price by this to get the cost-inclusive buy
        price. Price-aware in tick_floor mode; identical to the historical
        ``1 + buy_commission + half_spread`` scalar in flat mode."""
        return 1.0 + self.buy_commission + self.half_spread_at(price)

    def sell_multiplier(self, price: float) -> float:
        """Multiply a raw fill price by this to get net sell proceeds per
        share. Identical to ``1 - sell_total - half_spread`` in flat mode."""
        return 1.0 - self.sell_total - self.half_spread_at(price)


def idx_tick_size(price: float) -> float:
    """IDX price-fraction (tick) for the regular market, by price tier:
    < 200: 1 | 200-<500: 2 | 500-<2,000: 5 | 2,000-<5,000: 10 | >= 5,000: 25.
    The tick sets a hard floor on the bid-ask spread — central to why a flat
    percentage spread assumption is too optimistic for cheap stocks."""
    if price < 200:
        return 1.0
    if price < 500:
        return 2.0
    if price < 2000:
        return 5.0
    if price < 5000:
        return 10.0
    return 25.0


def us_equity_costs() -> CostModel:
    """CostModel preset for liquid US large-cap equities — NOT the IDX
    defaults above. Two things are structurally different in the US, not
    just scaled by currency:

      * No per-trade transaction TAX like IDX's sell-side PPh — US equity
        trades carry only a tiny SEC Section 31 fee on the sell leg
        (a few dollars per million traded; modelled here, though at this
        size it's closer to noise than a real drag).
      * Commission is realistically ZERO — most modern US retail brokers
        (Fidelity, Schwab, Robinhood etc.) charge no per-trade commission
        on equities, unlike IDX's ~0.15-0.19% broker fees.

    ``half_spread`` (5bps) reflects a LIQUID mega/large-cap US name, which
    trades far tighter than a mid/small-cap IDX stock — but is still a real
    cost, not zero; do not assume it's negligible for anything less liquid
    than this project's US_SHARIA_STOCKS starter list.

    ``spread_mode`` stays "flat": ``idx_tick_size``'s price tiers are an
    IDX-specific rule (rupiah-denominated bands) and would be MEANINGLESS
    applied to a $50-$900 US stock quoted in cents — "tick_floor" mode must
    not be used with this preset.
    """
    return CostModel(
        buy_commission=0.0,
        sell_commission=0.0,
        sell_tax=0.0000221,   # SEC Section 31 fee, sell leg only
        half_spread=0.0005,
        spread_mode="flat",
    )


@dataclass
class RiskConfig:
    """Stop-loss, take-profit and trailing-stop behaviour.

    The trailing stop ratchets through four phases as the position's PEAK
    profit grows (it never loosens):

        Phase 1  peak < breakeven_trigger      -> ATR stop, floored at hard_stop
        Phase 2  peak >= breakeven_trigger      -> stop at entry (breakeven)
        Phase 3  peak >= trail_start            -> trail trailing_distance below peak
        Phase 4  peak >= tight_trigger          -> trail tight_distance below peak

    *** MEASURED 2026-08-13: THIS LADDER SUBTRACTS VALUE ON THIS UNIVERSE. ***
    An out-of-sample sweep (diagnose_exit_param_sweep.py) found every one of 48
    stop/target/breakeven combinations negative, and a control with all
    price-based exits switched off — only holding_max_days closing positions —
    beat all of them by roughly half a point per trade.

    The mechanism: managing the exit RAISES win rate and LOWERS payoff, and the
    payoff loss dominates. The median trade is negative even in the control, so
    expectancy lives in a thin right tail, and target_profit_pct is the rule
    that cuts it off. breakeven_trigger_pct compounds it by converting pullbacks
    into scratches.

    These defaults are KEPT for continuity with existing backtest numbers, NOT
    because they are validated — they are measured as harmful. Read
    PROJECT_STATUS.md "Exit-ladder result" before treating any value here as a
    considered choice.

    A second consequence, found later: because every earlier walk-forward
    evaluated the ENTRY score through this ladder, the standing "unvalidated"
    verdict on the composite score may be a property of these exits rather than
    of the signal. With exits off, the score shows a clean monotone
    dose-response — see PROJECT_STATUS.md "Signal-contribution control". What is NOT established is that holding longer is
    profitable: the holding-period sweep never reached |t| = 2 and was run on a
    fraction of the universe, so it is undecided rather than negative.
    """

    trailing_enabled: bool = True

    hard_stop_pct: float = -5.0      # absolute floor; stop is never wider than this
    atr_stop_multiple: float = 2.0   # phase-1 stop = entry - multiple * ATR
    target_profit_pct: float = 8.0   # take-profit level (realistic for IDX swing)

    breakeven_trigger_pct: float = 4.0   # peak gain that moves stop to breakeven
    trail_start_pct: float = 8.0         # peak gain that starts trailing
    trailing_distance_pct: float = 3.0   # phase-3 trail distance below peak
    tight_trigger_pct: float = 12.0      # peak gain that tightens the trail
    tight_distance_pct: float = 2.5      # phase-4 trail distance below peak


def forward_test_config(score_threshold: float = 80.0,
                        holding_days: int = 60) -> "Config":
    """The configuration the 2026-08 out-of-sample work actually validated.

    Everything the sweeps established points the same way and NONE of it is the
    default: the exit ladder subtracts roughly 1.6 points per trade, the entry
    score selects in proportion to how hard it is asked, and expectancy lives in
    a right tail that a take-profit amputates. So:

      * every price-based exit is OFF — no stop, no target, no trailing. A
        position is closed by ``holding_max_days`` and nothing else.
      * ``score_entry_threshold`` is high (80 by default; the surface plateaus
        between 80 and 95, so the exact value inside that band matters little).
      * ``holding_max_days`` is 60.

    KNOW WHAT YOU ARE SIGNING UP FOR. The median trade under this profile is
    NEGATIVE — about -4.8% at threshold 80 — with a win rate near one third. It
    pays by holding a majority of losing positions long enough to collect a
    minority of large winners. Cutting a loser at -5%, which is the instinct the
    live log shows, converts this into a different and measurably worse
    strategy; the ladder results are what that looks like.

    Deliberately NOT the default. Existing backtest and walk-forward numbers
    were computed under the standard Config, and silently moving the default
    would invalidate the comparison this whole result rests on. Opt in via
    runner_config.json: ``"exit_profile": "forward_test"``.

    See PROJECT_STATUS.md, "Survivorship discriminator + benchmark corrections".
    """
    return Config(
        risk=RiskConfig(
            trailing_enabled=False,
            hard_stop_pct=-99.0,      # inert: never reached in practice
            target_profit_pct=999.0,  # inert: the tail is the point
            breakeven_trigger_pct=999.0,
        ),
        backtest=BacktestConfig(
            score_entry_threshold=score_threshold,
            holding_max_days=holding_days,
        ),
    )


def config_for_profile(profile: str | None) -> "Config":
    """Resolve a runner_config.json ``exit_profile`` to a Config.

    Unknown names raise rather than silently falling back: a typo in a config
    file must not quietly run the profile you were trying to move away from.
    """
    name = (profile or "legacy").strip().lower()
    if name in ("legacy", "default", ""):
        return Config()
    if name == "forward_test":
        return forward_test_config()
    raise ValueError(
        f"unknown exit_profile {profile!r} — use 'legacy' or 'forward_test'")


def live_config(config_path=None) -> "Config":
    """The Config the LIVE path should be deciding with, read from disk.

    WHY THIS EXISTS
    ---------------
    ``kala_daily_trader`` decided its BUY cutoff with a bare
    ``Config().backtest.score_entry_threshold`` — the LEGACY default, 60,
    always, regardless of what ``runner_config.json`` said. Meanwhile
    ``daily_run`` logged, on every single run::

        exit profile: FORWARD_TEST — no stop/target/trailing,
        entry score >= 80, hold 60d.

    off the profile-resolved config. So under ``forward_test`` the log stated
    a threshold of 80 while the scanner that emits the BUY signals used 60,
    and the paper trader buys everything the scanner labels BUY or STRONG BUY.
    Every trade scoring 60-79 is one the profile says should not be taken —
    and the +1.71%/trade measurement that justifies the profile was made at
    baseline 80 (5,241 trades). Those entries are not in it.

    The comment above ``config_for_profile``'s caller says a strategy change
    this large must never be something you have to read the source to
    discover. It was printed, and it was not what ran.

    A missing or unreadable config yields the LEGACY defaults — the historical
    behaviour, and identical to what the hardcoded ``Config()`` produced — so
    this changes nothing for anyone who has not opted into a profile. An
    unknown profile name still raises, via ``config_for_profile``.
    """
    import json
    from pathlib import Path

    path = (Path(config_path) if config_path
            else Path(__file__).resolve().parent.parent / "runner_config.json")
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Config()
    # No isinstance guard here: config_from_settings owns that check, and two
    # copies of it meant deleting either one changed nothing — an untestable
    # branch, which is the same as dead code.
    return config_from_settings(settings)


def config_from_settings(settings: dict | None) -> "Config":
    """Resolve an ALREADY-PARSED runner_config dict into the live Config.

    Split out because ``daily_run`` has the dict in hand and used to build its
    trading config with ``config_for_profile(cfg.get("exit_profile"))`` alone —
    which resolves the profile and drops the cost model on the floor. The paper
    trader books its fills through that config, so a ``costs_spread_mode``
    setting would have been read by ``live_config`` for the scanner and ignored
    by the thing that actually charges the fills. One function, both callers.
    """
    settings = settings if isinstance(settings, dict) else {}
    return replace(config_for_profile(settings.get("exit_profile")),
                   costs=live_costs(settings))


VALID_SPREAD_MODES = ("flat", "tick_floor")


def live_costs(settings: dict | None) -> CostModel:
    """The cost model the live book charges, from ``costs_spread_mode``.

    WHY THIS IS CONFIGURABLE RATHER THAN JUST CORRECTED
    ---------------------------------------------------
    The paper trader books fills through ``cfg.costs``, which was always the
    default ``CostModel()`` — ``spread_mode="flat"``, a constant 0.10%
    half-spread. Every validated number in this project was measured with
    ``--tick-spread``, i.e. ``tick_floor``, where the half-spread is floored at
    half an IDX tick. On this account's own nine holdings that is a round-trip
    of 0.64% booked against 0.87% measured — the live book is 0.23 points per
    trade CHEAPER than the backtest it will be compared against, every trade,
    always in the flattering direction. On a 519-rupiah name the gap is 0.76.

    For scale: the measured excess is +1.71%/trade. A systematic 0.23-point
    overstatement is 13% of that, and it lands squarely on the forward test —
    the one piece of evidence this project has never had.

    Meanwhile ``daily_run`` already runs its FRICTION REPORT at
    ``spread_mode="tick_floor"``. The same run tells you what your trading
    costs under the honest model and books it under the optimistic one.

    Changing the default would silently rewrite a live book's arithmetic, so
    it stays ``flat`` and this reads the setting. ``"costs_spread_mode":
    "tick_floor"`` in runner_config.json aligns the book with every
    measurement; an unknown value RAISES rather than quietly leaving the
    optimistic model in place.
    """
    mode = (settings or {}).get("costs_spread_mode")
    if mode is None:
        return CostModel()
    mode = str(mode).strip().lower()
    if mode not in VALID_SPREAD_MODES:
        raise ValueError(
            f"unknown costs_spread_mode {mode!r} — use "
            f"{' or '.join(repr(m) for m in VALID_SPREAD_MODES)}. Refusing to "
            f"run rather than silently booking fills at the optimistic flat "
            f"spread you were trying to move away from.")
    return CostModel(spread_mode=mode)


@dataclass
class BacktestConfig:
    """Backtest execution realism knobs."""

    score_entry_threshold: float = 60.0  # composite score >= this -> long
    holding_max_days: int = 20           # force exit after N bars in a position
    arb_limit_pct: float = 25.0          # IDX auto-rejection band (varies by tier)
    arb_lock_tol_pct: float = 1.0        # tolerance: bar counts as locked if the
                                         # down-move is within this of the limit

    # OFF by default so existing backtest/walk-forward numbers and tests are
    # unchanged. The live bot and papertrade paths already run every BUY
    # candidate through entries.evaluate_entry; the backtest historically did
    # not. Set True to make the backtest apply the same guardrails (RSI
    # overbought, parabolic ROC20, OBV distribution, thin-volume surge, and
    # — when a benchmark is supplied — the bear-regime block) so its numbers
    # reflect what the live system would actually have done.
    apply_entry_vetoes: bool = False


@dataclass
class EntryConfig:
    """Buy-side guardrails — the veto rules that stop the scanner from chasing
    an already-blown-up move (the PTPW case: +46% in 20 days, RSI 78, OBV
    distribution, thin volume, bearish market — and it was still the top pick).

    A BUY that trips any enabled veto is downgraded to HOLD.
    """

    veto_overbought: bool = True
    rsi_overbought: float = 75.0          # RSI at/above this -> too late

    veto_parabolic: bool = True
    roc20_parabolic: float = 25.0         # +25% in 20 sessions -> already extended

    veto_distribution: bool = True        # price rising while OBV falls = smart money out
    distribution_lookback: int = 10

    veto_thin_volume: bool = True         # a big move must be confirmed by volume
    surge_roc_threshold: float = 15.0     # only demand confirmation above this 20d move
    min_volume_ratio: float = 1.5         # recent vs baseline volume must clear this

    block_buys_in_bear: bool = True
    bear_statuses: tuple = ("BEARISH", "MODERATE_BEAR")

    # A regime we failed to FETCH is not a benign regime. check_market_health
    # returns UNAVAILABLE when the IHSG/^JKSE download raises or comes back
    # with too little history; the tape it could not see may be the very bear
    # tape bear_statuses exists to block. Fail closed rather than treating a
    # network blip as permission to buy. This does NOT cover regime.UNKNOWN
    # (benchmark warm-up) or None (no benchmark configured) — those are
    # genuinely-not-yet-knowable and still fail open, so backtest and
    # walk-forward numbers are unchanged.
    block_buys_when_regime_unavailable: bool = True
    regime_unavailable_statuses: tuple = ("UNAVAILABLE",)

    # 2026-07 tick-cost re-validation (see kala/edge.py): sub-2,000-
    # rupiah stocks can't trade tighter than their IDX tick, so a flat 0.10%
    # spread assumption understates their real cost 2-7x -- objectively
    # worse cost economics regardless of any edge finding. An EARLIER
    # (now-retracted) walk-forward run appeared to show a real >= IDR 1,000
    # edge, but that measurement had a look-ahead flaw (ticker-level
    # latest-close filter, not point-in-time); a point-in-time re-test came
    # back negative instead. Kept ON as a cost-hygiene default -- NOT as a
    # claim that this tier has a demonstrated edge. See edge.py's module
    # docstring for the full sequence and what would settle it.
    veto_cheap_stock: bool = True
    min_price_idr: float = 1000.0

    # OFF by default (existing backtest/walk-forward numbers unchanged).
    # A momentum entry into a RANGING stock (ADX < range_adx, per this
    # ticker's OWN price action -- see kala/regime_filter.py) is a
    # different failure mode from the benchmark-level bear-regime block
    # above: a choppy stock whipsaws a trend-following entry regardless of
    # which way the broader index is pointed. UNVALIDATED -- set True and
    # re-run walk_forward to test whether it actually helps.
    veto_ranging_stock: bool = False
    range_adx_threshold: float = 20.0


@dataclass
class Config:
    """Top-level config bundling the sub-configs."""

    risk: RiskConfig = field(default_factory=RiskConfig)
    backtest: BacktestConfig = field(default_factory=BacktestConfig)
    costs: CostModel = field(default_factory=CostModel)
    entries: EntryConfig = field(default_factory=EntryConfig)
