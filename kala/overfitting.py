"""
Overfitting diagnostics: Deflated Sharpe Ratio (DSR) and Probability of
Backtest Overfitting (PBO), via Combinatorially Symmetric Cross-Validation.

WHY THIS EXISTS
---------------
This project's own history is the textbook case these metrics exist to
catch: several price-tier / cost-model cuts were tried in the 2026-07
re-validation, one of them (>= IDR 1,000, ticker-level filter) looked like
a real edge (t=3.38), and it was later retracted once a point-in-time-
correct re-test came back flat. That is EXACTLY what "testing N trials and
reporting the best one" does to a Sharpe ratio, even with zero fraud and
good intentions -- the best of N noisy trials looks better than any single
trial's true expectation, purely from selection. These two numbers make
that risk explicit instead of something you have to re-derive by hand
each time, the way the min-price incident was caught.

DEFLATED SHARPE RATIO (Bailey & Lopez de Prado, 2014)
-------------------------------------------------------
Answers: "given that this Sharpe ratio was the BEST of N trials, each with
`trial_variance` variance in their own Sharpe estimates, what's the
probability the TRUE Sharpe is actually > 0?" A high raw Sharpe from a wide
trial search deflates hard; the same Sharpe from one single planned test
barely deflates at all. This is a probability (0-1), not a ratio -- "deflated
Sharpe ratio" is the field's name for it, not a re-scaled Sharpe.

PROBABILITY OF BACKTEST OVERFITTING (Bailey, Borwein, Lopez de Prado, Zhu,
2015), via CSCV
----------------------------------------------------------------------
Answers a complementary question directly from DATA, no distributional
assumption needed: given a T-period x N-configuration performance matrix
(e.g. fold x threshold EV from a walk-forward sweep), how often does the
configuration that looks best in-sample fall at or below the OOS MEDIAN
once you split the data every possible symmetric way? PBO near 0.5 means
in-sample selection carries no OOS information (pure overfitting); PBO
near 0 means the in-sample winner reliably keeps winning out-of-sample.

Neither number ever creates an edge. Both only ever LOWER your confidence
in one — same spirit as everything else in this project's validation
tooling.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass

import numpy as np

# Euler-Mascheroni constant, used by the expected-max-Sharpe-under-the-null term.
_GAMMA = 0.5772156649015329


def _norm_cdf(x: float) -> float:
    """Standard normal CDF without a scipy dependency."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_ppf(p: float) -> float:
    """Standard normal inverse CDF (quantile function), no scipy dependency.
    Acklam's rational approximation -- accurate to ~1e-9, ample for this use."""
    if not (0.0 < p < 1.0):
        raise ValueError("p must be in (0, 1)")
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
        1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
        6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
        -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
        3.754408661907416e+00]
    p_low, p_high = 0.02425, 1 - 0.02425
    if p < p_low:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
               ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p <= p_high:
        q = p - 0.5
        r = q*q
        return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / \
               (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)
    q = math.sqrt(-2 * math.log(1 - p))
    return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
            ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)


def expected_max_sharpe_under_null(n_trials: int, trial_variance: float) -> float:
    """The Sharpe ratio you'd expect the BEST of ``n_trials`` independent,
    genuinely-zero-edge strategies to show, purely from noise (their Sharpe
    estimates have variance ``trial_variance``). This is SR_0 in Bailey &
    Lopez de Prado (2014) eq. 10 — the deflation benchmark."""
    if n_trials < 1:
        raise ValueError("n_trials must be >= 1")
    if trial_variance < 0:
        raise ValueError("trial_variance must be >= 0")
    if n_trials == 1:
        return 0.0
    return math.sqrt(trial_variance) * (
        (1 - _GAMMA) * _norm_ppf(1 - 1.0 / n_trials)
        + _GAMMA * _norm_ppf(1 - 1.0 / (n_trials * math.e))
    )


@dataclass
class DeflatedSharpeResult:
    observed_sharpe: float
    n_trials: int
    n_observations: int
    sharpe_benchmark: float          # SR_0: expected max under the null
    dsr: float                       # P(true Sharpe > 0), 0-1
    verdict: str

    def summary_text(self) -> str:
        return (f"Deflated Sharpe: observed SR={self.observed_sharpe:.2f} "
               f"(best of {self.n_trials} trial(s), n={self.n_observations} obs) "
               f"vs a noise benchmark of {self.sharpe_benchmark:.2f} -> "
               f"DSR={self.dsr:.1%} probability the TRUE Sharpe is > 0.\n"
               f"VERDICT: {self.verdict}")


def deflated_sharpe_ratio(observed_sharpe: float, n_trials: int, n_observations: int,
                          trial_variance: float | None = None,
                          skew: float = 0.0, kurtosis: float = 3.0) -> DeflatedSharpeResult:
    """Probability the strategy's TRUE Sharpe ratio is > 0, after deflating
    for having picked the best of ``n_trials`` attempts.

    ``trial_variance``: variance of the Sharpe ratio ACROSS the trials tried
    (not within one trial's returns). None defaults to 1/n_observations, the
    textbook single-trial estimator variance — a reasonable default when you
    don't have the other trials' own Sharpes handy, but passing the real
    cross-trial variance (e.g. np.var of each threshold's pooled EV/std) is
    more honest when you have it.

    ``skew``/``kurtosis`` of the return distribution — the DSR formula
    corrects for non-normal returns (fat tails inflate apparent Sharpe
    precision). Defaults are the normal-distribution values (0, 3), i.e. no
    correction; pass real sample skew/kurtosis for a tighter estimate.
    """
    if n_observations < 2:
        raise ValueError("n_observations must be >= 2")
    if trial_variance is None:
        trial_variance = 1.0 / n_observations
    sr0 = expected_max_sharpe_under_null(n_trials, trial_variance)

    denom = math.sqrt(max(1e-12,
        1.0 - skew * observed_sharpe + (kurtosis - 1.0) / 4.0 * observed_sharpe ** 2))
    z = (observed_sharpe - sr0) * math.sqrt(n_observations - 1) / denom
    dsr = _norm_cdf(z)

    if n_trials <= 1:
        verdict = ("Single trial — no deflation needed, but this number alone "
                  "still doesn't confirm an edge (see t-stat / OOS walk-forward).")
    elif dsr >= 0.95:
        verdict = "Clears deflation at a high bar — worth taking seriously, still not proof."
    elif dsr >= 0.5:
        verdict = ("Positive but weak after deflation — plausibly noise dressed up by "
                  "trying multiple configurations. Treat like the min-price retraction: "
                  "confirm independently before trusting it.")
    else:
        verdict = ("Below 50% — the observed Sharpe is CONSISTENT WITH pure noise once "
                  "the number of trials is accounted for. Do not trust this result.")

    return DeflatedSharpeResult(observed_sharpe=observed_sharpe, n_trials=n_trials,
                                n_observations=n_observations, sharpe_benchmark=sr0,
                                dsr=dsr, verdict=verdict)


@dataclass
class PBOResult:
    pbo: float                       # fraction of CSCV splits where IS-best underperformed OOS median
    n_splits_tested: int
    n_configs: int
    n_periods: int
    verdict: str

    def summary_text(self) -> str:
        return (f"PBO: {self.pbo:.1%} (from {self.n_splits_tested} symmetric train/test "
               f"splits across {self.n_configs} configuration(s), {self.n_periods} period(s) "
               f"each).\nVERDICT: {self.verdict}")


def _pbo_verdict(pbo: float) -> str:
    if pbo >= 0.5:
        return (">= 50% — the in-sample 'best' configuration is no better than a coin "
               "flip at beating the OOS median. Classic overfitting signature — this is "
               "what picking the best of several price-tier/cost-model cuts looked like.")
    if pbo >= 0.3:
        return ("Elevated (30-50%) — meaningful overfitting risk. Don't act on the "
               "in-sample-best configuration without independent OOS confirmation.")
    return ("< 30% — the in-sample-best configuration tends to actually hold up "
           "out-of-sample. Still not proof of a real edge on its own; confirm with the "
           "usual walk-forward + alpha check.")


def probability_backtest_overfitting(returns_matrix, n_splits: int = 8) -> PBOResult:
    """Combinatorially Symmetric Cross-Validation PBO (Bailey, Borwein,
    Lopez de Prado, Zhu 2015).

    ``returns_matrix``: array-like, shape (n_periods, n_configs) — each
    COLUMN is one configuration's return/EV in each of n_periods TIME-
    ORDERED periods (e.g. one walk-forward fold's pooled EV per threshold).
    All configs must share the same period grid; this is on the caller
    (``pbo_from_walkforward_sweep`` below builds one from real fold data).

    ``n_splits``: split the T periods into this many contiguous, equal-
    sized blocks (must divide n_periods evenly), then evaluate every
    symmetric half/half train-test combination — C(n_splits, n_splits/2)
    of them. 8 is the value used in the original paper's examples; higher
    gives more combinations (finer PBO estimate) at more compute cost.
    """
    M = np.asarray(returns_matrix, dtype=float)
    if M.ndim != 2:
        raise ValueError("returns_matrix must be 2D (periods x configs)")
    n_periods, n_configs = M.shape
    if n_configs < 2:
        raise ValueError("need >= 2 configurations to compare in-sample vs out-of-sample")
    if n_splits < 2 or n_splits % 2 != 0:
        raise ValueError("n_splits must be an even number >= 2")
    if n_periods % n_splits != 0:
        raise ValueError(f"n_periods ({n_periods}) must be evenly divisible by "
                         f"n_splits ({n_splits})")

    block_size = n_periods // n_splits
    blocks = [M[i * block_size:(i + 1) * block_size] for i in range(n_splits)]

    half = n_splits // 2
    logits = []
    for train_idx in itertools.combinations(range(n_splits), half):
        test_idx = [i for i in range(n_splits) if i not in train_idx]
        train = np.vstack([blocks[i] for i in train_idx])
        test = np.vstack([blocks[i] for i in test_idx])

        is_perf = train.mean(axis=0)          # in-sample mean return per config
        oos_perf = test.mean(axis=0)          # out-of-sample mean return per config

        best_config = int(np.argmax(is_perf))
        # relative rank of the IS-best config's OOS performance among ALL configs
        rank = int((oos_perf < oos_perf[best_config]).sum()) + 1   # 1..n_configs
        omega = rank / (n_configs + 1.0)
        omega = min(max(omega, 1e-9), 1 - 1e-9)   # guard the logit's domain
        logits.append(math.log(omega / (1 - omega)))

    pbo = float(np.mean([1 if lam <= 0 else 0 for lam in logits]))
    return PBOResult(pbo=pbo, n_splits_tested=len(logits), n_configs=n_configs,
                     n_periods=n_periods, verdict=_pbo_verdict(pbo))


def pbo_from_walkforward_sweep(dfs: dict, cfg, thresholds, train_bars: int = 252,
                               test_bars: int = 63, warmup_bars: int = 60,
                               n_splits: int = 8):
    """Build a (fold x threshold) EV matrix from REAL walk-forward folds and
    run PBO on it — the direct, honest answer to 'was picking the best
    threshold on training data actually informative, or was it noise?'

    Uses each fold's TRAIN-window EV per threshold (the same sweep
    walk_forward() itself uses to pick a threshold) as the performance
    matrix — this is asking exactly the question walk_forward's own
    threshold-picking step answers, made explicit and quantified instead of
    trusting min_train_trades alone to guard against it.
    """
    from .walkforward import make_folds, sweep_thresholds

    master = __import__("pandas").DatetimeIndex(
        sorted(set().union(*[set(df.index) for df in dfs.values()])))
    folds = make_folds(master, train_bars, test_bars, warmup_bars)
    if len(folds) < n_splits:
        raise ValueError(f"only {len(folds)} fold(s) available, need >= {n_splits} "
                         f"for n_splits={n_splits} — use more history or a smaller n_splits")
    # trim to a multiple of n_splits (CSCV needs equal-sized blocks)
    usable = (len(folds) // n_splits) * n_splits
    folds = folds[:usable]

    rows = []
    for fold in folds:
        sweep = sweep_thresholds(dfs, fold.train_start, fold.train_end,
                                 thresholds, cfg, warmup_bars)
        rows.append([sweep[thr]["ev_pct"] for thr in thresholds])

    return probability_backtest_overfitting(np.array(rows), n_splits=n_splits)
