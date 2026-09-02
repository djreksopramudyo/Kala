#!/usr/bin/env python3
"""How much of a pooled walk-forward result comes from how few folds?

A pooled EV averages every trade together and hides whether the edge was
earned steadily or in one quarter. Pooling is right for the t-statistic and
wrong for deciding whether to trade it: an edge concentrated in 2-3 windows is
a regime bet, and the next regime is not in the sample.

Numbers below are read off the fold table printed by run_walkforward.py.
"""

FOLDS = {
    "forward_test": [
        # (n_trades, EV_pct, IHSG_pct)
        (348, -5.46, -2.4), (307, 2.30, -3.8), (370, -0.08, 5.4),
        (471, -3.50, 1.4), (530, -3.93, 4.0), (323, 0.53, -6.1),
        (558, 10.03, 9.6), (375, -1.08, -8.8), (346, 3.11, -11.1),
        (558, 15.28, 18.1), (542, 36.49, 10.1), (607, 3.58, 9.2),
        (428, -9.29, -22.3), (182, -11.56, -12.6),
    ],
    "legacy": [
        (806, -1.50, -2.4), (760, -1.04, -3.8), (1169, -0.07, 5.4),
        (907, -2.08, 1.4), (838, -1.65, 4.0), (886, -0.88, -6.1),
        (1845, -0.68, 9.6), (1383, -1.27, -8.8), (1199, -1.95, -11.1),
        (1864, -0.05, 18.1), (2840, 1.82, 10.1), (2312, 1.33, 9.2),
        (1259, -3.23, -22.3), (863, -1.97, -12.6),
    ],
}


def report(name: str, folds: list) -> None:
    n_tot = sum(f[0] for f in folds)
    rows = [(i, n, ev, n * ev) for i, (n, ev, _) in enumerate(folds)]
    total = sum(r[3] for r in rows)
    neg = [r for r in rows if r[2] < 0]

    print(f"\n{'=' * 68}\n{name.upper()}\n{'=' * 68}")
    print(f"  trades {n_tot}   pooled EV {total / n_tot:+.2f}%/trade")
    print(f"  folds with NEGATIVE EV: {len(neg)} of {len(folds)}")

    ranked = sorted(rows, key=lambda r: -r[3])
    print(f"\n  {'fold':>5}{'n':>7}{'EV%':>9}{'P&L contrib':>13}{'share':>9}")
    for i, n, ev, c in ranked:
        print(f"  {i:>5}{n:>7}{ev:>+9.2f}{c:>+13.0f}{c / total * 100:>+8.1f}%")

    top1 = ranked[0][3] / total * 100
    top3 = sum(r[3] for r in ranked[:3]) / total * 100
    rest = sum(r[3] for r in ranked[3:]) / total * 100
    print(f"\n  best fold alone      {top1:+.1f}% of all pooled P&L")
    print(f"  best 3 folds         {top3:+.1f}%")
    print(f"  the other {len(folds) - 3} folds     {rest:+.1f}%")
    if top3 > 90:
        print("\n  READ: the edge lives in three windows. Pooled significance is")
        print("  real but it is not evidence of a steady process — it is a bet")
        print("  that windows like those recur.")


for name, folds in FOLDS.items():
    report(name, folds)

print(f"\n{'=' * 68}\nWHAT THE COMPARISON ISOLATES\n{'=' * 68}")
print("""  Both runs use the SAME universe (569 usable tickers), the same 14 folds
  and the same signal. They differ in the exit rules AND in the fixed
  baseline threshold (60 vs 80).

  So compare the "walk-forward threshold" lines, not the "fixed baseline"
  lines: the walk-forward threshold is chosen per fold from TRAIN data in
  both runs, and both mostly chose 75. That makes the exit rules the
  substantive difference between them.""")
