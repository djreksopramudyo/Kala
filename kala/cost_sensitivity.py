"""
Transaction-cost sensitivity sweep — edge vs. cost-assumption grid.

PROJECT_STATUS.md's finding (no OOS edge survives honest costs) was reached
by comparing exactly TWO cost assumptions (flat 0.10% spread vs. tick-
floored). This module generalizes that into a full grid: scale every cost
component (both commissions, the sell tax, the half-spread) by a range of
multipliers and re-run the SAME walk-forward harness at each one, so you can
see exactly where (if anywhere) the edge would have to sit for costs to stop
being the deciding factor -- a Break-even cost multiplier, not just a
before/after snapshot.

Every scenario reuses ``walk_forward``/``walk_forward_strategy`` unchanged;
this module only builds the cost-model grid and collects results.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

import pandas as pd

from .config import Config, CostModel
from .walkforward import DEFAULT_THRESHOLDS, WalkForwardReport, walk_forward

DEFAULT_MULTIPLIERS = (0.0, 0.5, 1.0, 1.5, 2.0, 3.0)


def scaled_cost_model(base: CostModel, multiplier: float) -> CostModel:
    """A CostModel with every cost component scaled by ``multiplier``.
    0.0 = frictionless (upper bound on any possible edge); 1.0 = the base
    assumption unchanged; >1.0 = costs worse than assumed."""
    return replace(
        base,
        buy_commission=base.buy_commission * multiplier,
        sell_commission=base.sell_commission * multiplier,
        sell_tax=base.sell_tax * multiplier,
        half_spread=base.half_spread * multiplier,
    )


@dataclass
class CostSweepPoint:
    multiplier: float
    cost_model: CostModel
    report: WalkForwardReport

    @property
    def pooled_baseline(self) -> dict:
        return self.report.pooled_baseline

    @property
    def t_stat(self) -> float:
        return self.pooled_baseline.get("t_stat", 0.0)

    @property
    def ev_pct(self) -> float:
        return self.pooled_baseline.get("ev_pct", 0.0)


@dataclass
class CostSweepResult:
    points: list[CostSweepPoint] = field(default_factory=list)

    def breakeven_multiplier(self) -> float | None:
        """The smallest tested multiplier at which pooled EV/trade drops to
        <= 0 -- i.e. the point costs alone erase the edge. None if EV never
        crosses zero across the tested grid (either always positive, or
        already negative at the lowest multiplier tested)."""
        for pt in sorted(self.points, key=lambda p: p.multiplier):
            if pt.ev_pct <= 0:
                return pt.multiplier
        return None

    def summary_text(self) -> str:
        lines = ["TRANSACTION-COST SENSITIVITY SWEEP", "=" * 56,
                f"{'cost x':>8}{'trades':>9}{'EV/trade':>11}{'t-stat':>9}{'verdict':>14}"]
        for pt in sorted(self.points, key=lambda p: p.multiplier):
            s = pt.pooled_baseline
            verdict = "edge" if (s.get("ev_pct", 0.0) > 0 and s.get("t_stat", 0.0) >= 2.0) else "no edge"
            lines.append(f"{pt.multiplier:>7.1f}x{s.get('n', 0):>9}"
                         f"{s.get('ev_pct', 0.0):>+10.2f}%{s.get('t_stat', 0.0):>9.2f}{verdict:>14}")
        breakeven = self.breakeven_multiplier()
        lines.append("-" * 56)
        if breakeven is not None:
            lines.append(f"Breakeven: EV/trade hits zero at ~{breakeven:.1f}x the base cost assumption.")
        else:
            lines.append("EV/trade never crosses zero across the tested multiplier grid.")
        return "\n".join(lines)


def sweep_costs(dfs: dict[str, pd.DataFrame],
                base_cfg: Config | None = None,
                benchmark: pd.DataFrame | None = None,
                multipliers=DEFAULT_MULTIPLIERS,
                thresholds=DEFAULT_THRESHOLDS,
                strategy=None,
                **wf_kwargs) -> CostSweepResult:
    """Run walk_forward once per cost multiplier, holding everything else
    (folds, thresholds, strategy) fixed -- isolates cost assumption as the
    ONLY variable changing between runs."""
    base_cfg = base_cfg or Config()
    points: list[CostSweepPoint] = []
    for m in multipliers:
        cfg = replace(base_cfg, costs=scaled_cost_model(base_cfg.costs, m))
        if strategy is not None:
            from .strategies import walk_forward_strategy
            report = walk_forward_strategy(strategy, dfs, benchmark=benchmark,
                                           thresholds=thresholds, cfg=cfg, **wf_kwargs)
        else:
            report = walk_forward(dfs, cfg=cfg, benchmark=benchmark,
                                  thresholds=thresholds, **wf_kwargs)
        points.append(CostSweepPoint(multiplier=m, cost_model=cfg.costs, report=report))
    return CostSweepResult(points=points)
