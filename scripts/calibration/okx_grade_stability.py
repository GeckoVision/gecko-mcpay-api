#!/usr/bin/env python3
"""Sprint 12 #5 — Grade-stability cross-period analysis.

For each trader who appears in BOTH the 30d and 90d leaderboards (sortBy=pnlRatio),
compute their grade in each period independently, then measure agreement.

If a trader is Grade A on 30d but C/D on 90d → 30d grade is period-specific luck
(same selection-bias the OKX raw-PnL rank has).

If grades agree → grader is detecting persistent skill, not period noise.

Same rigor pattern as Sprint 10 walk-forward — REJECT the grader if its picks
don't hold cross-period.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, "scripts/calibration")
from okx_leaderboard_grader import grade_okx_trader

DATA_DIR = Path("analysis/data/okx_leaderboard")


def main() -> int:
    paths = {p: DATA_DIR / f"raw_{p}.json" for p in ["7d", "30d", "90d"]}
    raws = {}
    for period, path in paths.items():
        if path.exists():
            raws[period] = json.loads(path.read_text())
        else:
            print(f"  (skip period={period}: {path} not found)")
    if len(raws) < 2:
        print("Need at least 2 periods to compare. Re-run leaderboard fetches.")
        return 1

    # Per-period grading
    graded = {}  # period -> {authorId -> result}
    for period, raw in raws.items():
        traders = raw.get("data", [])
        graded[period] = {}
        for t in traders:
            try:
                r = grade_okx_trader(t)
                graded[period][r["authorId"]] = r
            except Exception:
                continue
        print(f"  graded period={period}: N={len(graded[period])}")
    print()

    # Cross-period agreement
    periods = list(graded.keys())
    print("=" * 100)
    print(f"CROSS-PERIOD GRADE STABILITY ({' vs '.join(periods)})")
    print("=" * 100)

    # Find traders that appear in ≥2 periods
    all_ids = set()
    for p in periods:
        all_ids.update(graded[p].keys())
    multi_period = [aid for aid in all_ids if sum(1 for p in periods if aid in graded[p]) >= 2]
    print(f"\nTraders in ≥2 periods: {len(multi_period)} of {len(all_ids)} total")
    print()

    # Detailed table
    grade_rank = {"A": 4, "B": 3, "C": 2, "D": 1, "?": 0}
    print(f"{'nickname':<22s} | " + " | ".join(f"{p:>10s}" for p in periods) + " | flip?")
    print("-" * (24 + 14 * len(periods) + 10))
    flips = 0
    stable_high = 0
    stable_low = 0
    for aid in multi_period:
        grades_in_periods = []
        nickname = "?"
        for p in periods:
            if aid in graded[p]:
                r = graded[p][aid]
                grades_in_periods.append((p, r["grade"]))
                nickname = r["nickname"]
        # Determine flip
        grade_set = {g for _, g in grades_in_periods}
        is_flip = len({grade_rank[g] for g in grade_set}) >= 2 and (
            max(grade_rank[g] for g in grade_set) - min(grade_rank[g] for g in grade_set) >= 2
        )
        if is_flip:
            flips += 1
            tag = "FLIP"
        elif all(grade_rank[g] >= 3 for g in grade_set):
            stable_high += 1
            tag = "stable A/B"
        elif all(grade_rank[g] <= 2 for g in grade_set):
            stable_low += 1
            tag = "stable C/D"
        else:
            tag = "adjacent"
        cells = []
        for p in periods:
            if aid in graded[p]:
                cells.append(f"{graded[p][aid]['grade']:>10s}")
            else:
                cells.append(f"{'—':>10s}")
        print(f"{nickname[:21]:<22s} | " + " | ".join(cells) + f" | {tag}")

    print()
    print("=" * 100)
    print("VERDICT")
    print("=" * 100)
    n = len(multi_period)
    print(f"  Multi-period traders: {n}")
    print(f"  STABLE high (A/B in all periods): {stable_high} ({100*stable_high/max(n,1):.0f}%)")
    print(f"  STABLE low  (C/D in all periods): {stable_low} ({100*stable_low/max(n,1):.0f}%)")
    print(f"  FLIPS (≥2 grades apart):          {flips} ({100*flips/max(n,1):.0f}%)")
    print()

    if stable_high + stable_low >= 0.7 * n:
        print("  → Grader is STABLE across periods (>70% consistent classifications)")
        print("    The Grade-A traders found in 30d ALSO grade well in 90d → real skill, not luck")
    elif flips >= 0.5 * n:
        print("  → Grader has SELECTION BIAS itself (>50% flips across periods)")
        print("    Grade in 30d does NOT predict grade in 90d → period-specific noise")
    else:
        print("  → Mixed — partial stability")

    # Save
    out = DATA_DIR / "stability.json"
    summary = {
        "periods": periods,
        "multi_period_n": n,
        "stable_high": stable_high,
        "stable_low": stable_low,
        "flips": flips,
        "per_trader": {
            aid: {p: graded[p][aid] for p in periods if aid in graded[p]}
            for aid in multi_period
        },
    }
    out.write_text(json.dumps(summary, indent=2, default=str))
    print(f"\nSaved → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
