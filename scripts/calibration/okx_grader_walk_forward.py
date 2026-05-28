#!/usr/bin/env python3
"""Sprint 14 #1 — Validate the validator: does our grader's pick hold over time?

Same logic that exposed OKX's selection bias, applied to ourselves: if a
trader we grade A in window-1 (e.g. day 1-30 of their history) is C/D in
window-2 (day 31-60) and window-3 (day 61-90), our grader has the same
period-dependence we accused OKX of.

Uses the 91-day rates series each trader exposes via OKX smartmoney
(saved to analysis/data/okx_leaderboard/raw_90d.json). For each trader:
  - Window A: days 1-30 → grade
  - Window B: days 31-60 → grade
  - Window C: days 61-90 → grade
Then count A→A transitions, A→D degradations, A→C-or-B (one-grade drift), etc.

PRE-COMMIT INTERPRETATION (Op-1, written before running):
  Grader SHIPS clean if all of:
    - ≥ 60% of Window-A "A or B" traders stay "A or B" in Window B
    - ≥ 60% of Window-A "A or B" traders stay "A or B" in Window C
    - ≤ 20% of Window-A "A" traders fall to D in Window B or C
  Otherwise we have a calibration problem and need to fix it BEFORE
  scaling distribution or monetization.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

# Import the grader (clone of the OKX scoring logic)
sys.path.insert(0, "scripts/calibration")
from okx_leaderboard_grader import grade_okx_trader

DATA_DIR = Path("analysis/data/okx_leaderboard")


def slice_trader(trader: dict, start_day: int, end_day: int) -> dict | None:
    """Return a synthetic trader payload covering only rates[start_day:end_day].

    The grader downstream computes daily-PnL deltas from the cumulative series;
    to slice honestly we keep the cumulative shape but rebase to zero at the
    window start (so DD/Sharpe are computed within the window only).
    """
    rates = trader.get("rates") or []
    if len(rates) < end_day:
        return None
    window = rates[start_day:end_day]
    if len(window) < 10:  # need at least 10 days for the grader to run
        return None
    # Rebase so first day of window is the baseline
    base = float(window[0]["value"])
    rebased_rates = [
        {"statTime": r["statTime"], "value": str(float(r["value"]) - base)}
        for r in window
    ]
    return {
        **trader,
        "rates": rebased_rates,
    }


def main() -> int:
    path = DATA_DIR / "raw_90d.json"
    if not path.exists():
        print(f"ERROR: {path} not found. Re-fetch via okx-cex-smartmoney MCP.")
        return 1
    raw = json.loads(path.read_text())
    traders = raw.get("data", [])

    print("=" * 110)
    print("VALIDATE-THE-VALIDATOR — walk-forward on the grader's own picks")
    print("=" * 110)
    print(f"Universe: {len(traders)} traders × 90 days (rates series) each")
    print(f"Windows:  A=days 1-30  B=days 31-60  C=days 61-90  (each ~30 days)")
    print()

    # Define windows
    WINDOWS = [("A", 0, 30), ("B", 30, 60), ("C", 60, 90)]

    # For each trader, grade in each window
    per_trader: dict[str, dict[str, str]] = {}  # nickname → {window_label: grade}
    nicknames: dict[str, str] = {}
    for t in traders:
        aid = t.get("authorId")
        if not aid:
            continue
        nicknames[aid] = t.get("nickName", "?")
        per_trader[aid] = {}
        for label, s, e in WINDOWS:
            sliced = slice_trader(t, s, e)
            if not sliced:
                per_trader[aid][label] = "?"
                continue
            try:
                g = grade_okx_trader(sliced)
                per_trader[aid][label] = g.get("grade", "?")
            except Exception:
                per_trader[aid][label] = "?"

    # Per-trader transition table
    print(f"{'nickname':<24s} | {'A':>3s} | {'B':>3s} | {'C':>3s} | A→B | A→C | trajectory")
    print("-" * 95)

    grade_rank = {"A": 4, "B": 3, "C": 2, "D": 1, "?": 0}
    flows_a_to_b: Counter[str] = Counter()
    flows_a_to_c: Counter[str] = Counter()
    stable_high = 0  # A/B in all 3 windows
    stable_low = 0   # C/D in all 3
    flipped = 0      # ≥ 2 grades apart
    catastrophic_drops = 0  # A → D anywhere
    n_graded = 0

    for aid, grades in per_trader.items():
        ga, gb, gc = grades.get("A", "?"), grades.get("B", "?"), grades.get("C", "?")
        if "?" in (ga, gb, gc):
            continue
        n_graded += 1
        # Transitions
        flows_a_to_b[f"{ga}→{gb}"] += 1
        flows_a_to_c[f"{ga}→{gc}"] += 1
        # Classification
        ranks = [grade_rank[ga], grade_rank[gb], grade_rank[gc]]
        if all(r >= 3 for r in ranks):
            stable_high += 1
            traj = "STABLE A/B"
        elif all(r <= 2 for r in ranks):
            stable_low += 1
            traj = "stable C/D"
        elif max(ranks) - min(ranks) >= 2:
            flipped += 1
            traj = "FLIP"
        else:
            traj = "adjacent"
        if "A" in (ga,) and "D" in (gb, gc):
            catastrophic_drops += 1
            traj += " [A→D]"
        nick = nicknames.get(aid, "?")[:23]
        # Only print non-? rows; show all 50 for transparency
        d_ab = grade_rank[gb] - grade_rank[ga]
        d_ac = grade_rank[gc] - grade_rank[ga]
        print(f"{nick:<24s} | {ga:>3s} | {gb:>3s} | {gc:>3s} | "
              f"{d_ab:>+3d} | {d_ac:>+3d} | {traj}")

    print(f"\nGraded {n_graded} of {len(per_trader)} traders across all 3 windows")
    print()

    # Aggregate
    print("=" * 110)
    print("AGGREGATE TRANSITIONS")
    print("=" * 110)
    print("\nWindow A → Window B:")
    for k in sorted(flows_a_to_b.keys()):
        print(f"  {k:<6s}  {flows_a_to_b[k]:>3d}")
    print("\nWindow A → Window C:")
    for k in sorted(flows_a_to_c.keys()):
        print(f"  {k:<6s}  {flows_a_to_c[k]:>3d}")
    print()

    # Per pre-commit gates
    print("=" * 110)
    print("STABILITY GATES")
    print("=" * 110)
    a_or_b_in_A = [aid for aid, g in per_trader.items()
                   if g.get("A") in ("A", "B")]
    a_or_b_in_A_stay_in_B = [aid for aid in a_or_b_in_A
                              if per_trader[aid].get("B") in ("A", "B")]
    a_or_b_in_A_stay_in_C = [aid for aid in a_or_b_in_A
                              if per_trader[aid].get("C") in ("A", "B")]
    a_in_A = [aid for aid, g in per_trader.items() if g.get("A") == "A"]
    a_drop_to_D = [aid for aid in a_in_A
                    if per_trader[aid].get("B") == "D" or per_trader[aid].get("C") == "D"]

    if a_or_b_in_A:
        pct_keep_AB_in_B = 100 * len(a_or_b_in_A_stay_in_B) / len(a_or_b_in_A)
        pct_keep_AB_in_C = 100 * len(a_or_b_in_A_stay_in_C) / len(a_or_b_in_A)
    else:
        pct_keep_AB_in_B = pct_keep_AB_in_C = 0
    pct_a_to_d = 100 * len(a_drop_to_D) / max(len(a_in_A), 1) if a_in_A else 0

    gates = [
        (f"≥ 60% of Window-A A/B stay A/B in B (got {pct_keep_AB_in_B:.0f}%, n={len(a_or_b_in_A)})", pct_keep_AB_in_B >= 60),
        (f"≥ 60% of Window-A A/B stay A/B in C (got {pct_keep_AB_in_C:.0f}%, n={len(a_or_b_in_A)})", pct_keep_AB_in_C >= 60),
        (f"≤ 20% of Window-A A's fall to D in B or C (got {pct_a_to_d:.0f}%, n={len(a_in_A)})", pct_a_to_d <= 20),
    ]
    for desc, ok in gates:
        print(f"  [{('PASS' if ok else 'FAIL')}]  {desc}")
    n_pass = sum(1 for _, ok in gates if ok)
    print()
    if n_pass == 3:
        verdict = "GRADER VALIDATED — ship with confidence; A/B picks hold across periods"
    elif n_pass == 2:
        verdict = "MOSTLY STABLE — one gate misses; document the limitation"
    elif n_pass == 1:
        verdict = "WEAK — grader has period-dependence (same as OKX); refine before scaling"
    else:
        verdict = "REJECT — grader is selection-biased; we'd be doing what we accused OKX of"
    print(f"  → VERDICT: {verdict}")

    print(f"\n  STABLE A/B (all 3 windows): {stable_high} / {n_graded}")
    print(f"  STABLE C/D (all 3 windows): {stable_low} / {n_graded}")
    print(f"  FLIP (≥2 grades apart):     {flipped} / {n_graded}")
    print(f"  Catastrophic drops (A→D):   {catastrophic_drops} / {len(a_in_A)} starting-A traders")

    # Save
    out_dir = DATA_DIR
    out = out_dir / "validator_walk_forward.json"
    out.write_text(json.dumps({
        "windows": {label: {"start_day": s, "end_day": e} for label, s, e in WINDOWS},
        "n_traders_graded_all_windows": n_graded,
        "stable_high": stable_high,
        "stable_low": stable_low,
        "flipped": flipped,
        "catastrophic_drops": catastrophic_drops,
        "transitions_a_to_b": dict(flows_a_to_b),
        "transitions_a_to_c": dict(flows_a_to_c),
        "pct_AB_keep_AB_in_B": pct_keep_AB_in_B,
        "pct_AB_keep_AB_in_C": pct_keep_AB_in_C,
        "pct_a_to_d": pct_a_to_d,
        "per_trader": {nicknames.get(aid, aid): g for aid, g in per_trader.items()},
    }, indent=2, ensure_ascii=False, default=str))
    print(f"\nSaved → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
