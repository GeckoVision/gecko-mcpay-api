#!/usr/bin/env python3
"""Decompose: how much of the loss is entries (SL fires) vs exits (give-back)?

Companion to shadow_exit_counterfactual.py.

Hypothesis: 3 stop_loss closes lose -9.24% combined; they're the immovable floor
that exit-side improvements can't touch. Decompose:
  - Strategy A: keep all 20 closes, apply tight_trail_03 (exit-only fix)
  - Strategy B: assume 3 SL trades NEVER OPENED (i.e., entry filter caught them)
  - Strategy C: A + B combined
"""
from __future__ import annotations

import random
import statistics as st

import sys
sys.path.insert(0, "scripts/analysis")
from shadow_exit_counterfactual import (
    load_closes,
    policy_tight_trail_03,
    policy_baseline,
    bootstrap_ci,
)


def main() -> int:
    closes = load_closes()
    n = len(closes)
    print(f"N = {n} closes\n")

    # Counts by reason
    sl = [c for c in closes if c.reason == "stop_loss"]
    non_sl = [c for c in closes if c.reason != "stop_loss"]
    print(f"  stop_loss: {len(sl)} closes, sum {sum(c.pnl_actual for c in sl):+.2f}%, mean {st.mean([c.pnl_actual for c in sl]):+.2f}%")
    print(f"  non-SL:    {len(non_sl)} closes, sum {sum(c.pnl_actual for c in non_sl):+.2f}%, mean {st.mean([c.pnl_actual for c in non_sl]):+.2f}%")
    print()

    # Strategies
    strategies = {
        "A. baseline (current)": [policy_baseline(c)[1] * 100 for c in closes],
        "B. baseline, SL trades filtered out": [policy_baseline(c)[1] * 100 for c in non_sl],
        "C. tight_trail_03 (exit-only fix)": [policy_tight_trail_03(c)[1] * 100 for c in closes],
        "D. C + SL trades filtered (exit + entry fix)": [policy_tight_trail_03(c)[1] * 100 for c in non_sl],
        "E. tight_trail_03 + force-TP-at-0.5%": [
            min(policy_tight_trail_03(c)[1], 0.005) * 100 if c.peak / c.entry - 1 >= 0.005 else policy_tight_trail_03(c)[1] * 100
            for c in closes
        ],
    }

    print(f"{'strategy':<50s} {'N':>3s} {'mean':>8s} {'sum':>8s} {'95% CI':>20s} {'win%':>6s}")
    print("-" * 110)
    for name, vs in strategies.items():
        if not vs:
            continue
        m = st.mean(vs)
        s = sum(vs)
        ci_lo, ci_hi = bootstrap_ci(vs)
        wr = 100 * sum(1 for v in vs if v >= 0.5) / len(vs)
        print(f"{name:<50s} {len(vs):>3d} {m:>+7.2f}% {s:>+7.2f}% [{ci_lo:>+6.2f}, {ci_hi:>+6.2f}] {wr:>5.0f}%")
    print()

    # Per-symbol SL incidence — entry-side question
    from collections import Counter
    sl_by_sym = Counter(c.symbol for c in sl)
    all_by_sym = Counter(c.symbol for c in closes)
    print("SL incidence per symbol (entry-quality lens):")
    for sym, total in sorted(all_by_sym.items(), key=lambda x: -x[1]):
        sl_count = sl_by_sym.get(sym, 0)
        print(f"  {sym:<12s} {sl_count}/{total} = {100*sl_count/total:.0f}% catastrophic")
    print()

    # Key takeaway
    print("=" * 100)
    print("DECOMPOSITION")
    print("=" * 100)
    base_sum = sum(c.pnl_actual for c in closes)
    sl_sum = sum(c.pnl_actual for c in sl)
    a_sum = base_sum  # current
    c_strat = [policy_tight_trail_03(c)[1] * 100 for c in closes]
    c_sum = sum(c_strat)
    d_strat = [policy_tight_trail_03(c)[1] * 100 for c in non_sl]
    d_sum = sum(d_strat)
    print(f"  Total current loss:               {a_sum:+.2f}%")
    print(f"  → Loss from 3 stop_loss closes:   {sl_sum:+.2f}%  ({100*sl_sum/a_sum:.0f}% of total damage)")
    print(f"  → Loss from 17 non-SL closes:     {base_sum - sl_sum:+.2f}%")
    print()
    print(f"  EXIT-side fix only (tight_trail_03):     {c_sum:+.2f}%  (Δ {c_sum-a_sum:+.2f}pp from baseline)")
    print(f"  ENTRY+EXIT fix (filter SL + tight trail): {d_sum:+.2f}%  (Δ {d_sum-a_sum:+.2f}pp from baseline)")
    print()
    print("CONCLUSION:")
    if abs(sl_sum) > abs(base_sum - sl_sum):
        print("  Entry-quality (avoiding the 3 SL trades) is the LARGER lever than exit hygiene.")
        print("  The 3 SL closes are -3% catastrophic single events that exit-side cannot reach.")
        print("  Entry filter > exit retune.")
    else:
        print("  Exit hygiene is the larger lever.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
