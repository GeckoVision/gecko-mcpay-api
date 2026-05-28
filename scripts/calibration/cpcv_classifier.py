#!/usr/bin/env python3
"""Sprint 10 #8 — Combinatorial Purged Cross-Validation classifier.

Per López de Prado: instead of one train/test split (which gave one estimate
with unknown variance — and the swing-window REJECTED on it), use CPCV:
  N folds (e.g. 6 monthly slices over 180d)
  k_test held-out per split (e.g. 2 folds)
  C(N, k_test) combinations of train/test → multiple paths through same data
  Per-symbol pattern selection happens on the TRAIN slice; evaluated on TEST.

Outputs distribution of router-EV across all paths + per-symbol stability
matrix. PBO computed from variant rankings across paths.

PRE-COMMIT INTERPRETATION (Op-1, written BEFORE running):
  - Router SHIP-WORTHY iff:
    * median test-path EV ≥ 0 AND
    * 5th-percentile test-path EV ≥ -5% (downside controlled) AND
    * % paths with positive router-EV ≥ 60% AND
    * PBO (variant selection) < 0.20
  - Router PROMISING iff 2-3 of 4 gates pass
  - Router REJECT if ≤ 1 gate passes

Embargo: 2 bars (8 hours) between train and test slices to prevent label
overlap leakage (our trades hold ~12 bars / 2 days, so 2-bar embargo is the
minimum honest spec; ideally we'd embargo the full label horizon).
"""
from __future__ import annotations

import itertools
import json
import os
import statistics as st
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, "scripts/calibration")
from swing_window_validation import (
    ConfluenceParams,
    Trade,
    backtest_symbol,
    load_universe as load_60d_universe,
)

DATA_DIR_180D = Path("scripts/calibration/data/solana_4h_180d")
N_FOLDS = 6
K_TEST = 2
EMBARGO_BARS = 2


def load_180d_universe() -> dict[str, list[dict]]:
    out = {}
    if not DATA_DIR_180D.exists():
        return out
    for f in sorted(DATA_DIR_180D.glob("*_4h.json")):
        sym = f.stem.replace("_4h", "")
        try:
            rows = json.loads(f.read_text())
            if len(rows) >= 200:
                out[sym] = rows
        except Exception:
            pass
    return out


def split_into_folds(rows: list[dict], n_folds: int) -> list[list[dict]]:
    """Sequential folds (preserves time order)."""
    n = len(rows)
    fold_size = n // n_folds
    folds = []
    for i in range(n_folds):
        start = i * fold_size
        end = n if i == n_folds - 1 else (i + 1) * fold_size
        folds.append(rows[start:end])
    return folds


def assemble_train_test(folds: list[list[dict]], test_fold_indices: set[int]) -> tuple[list[dict], list[dict]]:
    """Return (train_rows, test_rows). Test = concat of test folds (NOT contiguous).

    Embargo: drop the first EMBARGO_BARS of any train fold that immediately
    follows a test fold (prevents test→train leakage at fold boundaries).
    """
    train, test = [], []
    for i, fold in enumerate(folds):
        if i in test_fold_indices:
            test.extend(fold)
        else:
            # If prior fold was test, embargo the first few bars of this train fold
            if (i - 1) in test_fold_indices:
                train.extend(fold[EMBARGO_BARS:])
            else:
                train.extend(fold)
    return train, test


@dataclass
class PathResult:
    test_fold_ids: tuple[int, ...]
    router_train_sum: float
    router_test_sum: float
    flat_test_sum: float
    n_traded_syms: int
    per_sym_picks: dict[str, str]  # sym -> pattern picked on train
    per_sym_test_sum: dict[str, float]


def main() -> int:
    # Require ≥ 10 symbols in 180d before using it (otherwise fallback to 60d)
    n_180d = len(list(DATA_DIR_180D.glob("*_4h.json"))) if DATA_DIR_180D.exists() else 0
    use_180d = (n_180d >= 10) and not os.environ.get("FORCE_60D")
    if use_180d:
        universe = load_180d_universe()
        print(f"Using 180d universe: {len(universe)} symbols")
    else:
        universe = load_60d_universe()
        print(f"WARNING: 180d data not yet available. Falling back to 60d universe ({len(universe)} symbols).")
        print("         Re-run after ingest_coingecko_solana_180d.py completes for full rigor.")
    if not universe:
        return 1

    patterns = {
        "trend": ConfluenceParams(name="trend", pattern="trend"),
        "trend_strict": ConfluenceParams(name="trend_strict", pattern="trend", adx_cross_up=30),
        "bounce": ConfluenceParams(name="bounce", pattern="bounce"),
        "no_trade": None,
    }

    # All combinations of K_TEST folds from N_FOLDS
    test_combos = list(itertools.combinations(range(N_FOLDS), K_TEST))
    print(f"CPCV config: {N_FOLDS} folds, k_test={K_TEST}, embargo={EMBARGO_BARS} bars, "
          f"{len(test_combos)} paths × {len(universe)} symbols = {len(test_combos) * len(universe)} pattern-evals\n")

    path_results: list[PathResult] = []

    for combo_idx, test_folds in enumerate(test_combos):
        test_fold_set = set(test_folds)
        per_sym_picks = {}
        per_sym_test_sum = {}
        router_train_sum = 0.0
        router_test_sum = 0.0
        flat_test_sum = 0.0
        n_traded = 0

        for sym, rows in universe.items():
            folds = split_into_folds(rows, N_FOLDS)
            train, test = assemble_train_test(folds, test_fold_set)
            if len(train) < 30 or len(test) < 30:
                continue

            # Score every pattern on train
            train_results = {}
            for pname, p in patterns.items():
                if p is None:
                    train_results[pname] = ([], 0.0)
                    continue
                ts_list = backtest_symbol(sym, train, p)
                train_results[pname] = (ts_list, sum(t.net_ret * 100 for t in ts_list))

            best_pname = max(train_results.keys(), key=lambda k: train_results[k][1])
            all_neg = all(train_results[k][1] <= 0 for k in patterns if patterns[k] is not None)
            if all_neg:
                best_pname = "no_trade"

            per_sym_picks[sym] = best_pname
            router_train_sum += train_results[best_pname][1]

            # Apply pick on test
            if best_pname != "no_trade":
                test_trades = backtest_symbol(sym, test, patterns[best_pname])
                test_sym_sum = sum(t.net_ret * 100 for t in test_trades)
                per_sym_test_sum[sym] = test_sym_sum
                router_test_sum += test_sym_sum
                n_traded += 1
            else:
                per_sym_test_sum[sym] = 0.0

            # Flat-trend test for comparison
            flat_test_trades = backtest_symbol(sym, test, patterns["trend"])
            flat_test_sum += sum(t.net_ret * 100 for t in flat_test_trades)

        path_results.append(PathResult(
            test_fold_ids=test_folds,
            router_train_sum=router_train_sum,
            router_test_sum=router_test_sum,
            flat_test_sum=flat_test_sum,
            n_traded_syms=n_traded,
            per_sym_picks=per_sym_picks,
            per_sym_test_sum=per_sym_test_sum,
        ))

    # ── Per-path summary ──
    print(f"{'path':<18s} {'train_sum':>11s} {'test_sum':>10s} {'flat_test':>10s} {'router_edge':>12s} {'n_syms':>7s}")
    print("-" * 95)
    for r in path_results:
        edge = r.router_test_sum - r.flat_test_sum
        print(f"folds={r.test_fold_ids!r:<15s} {r.router_train_sum:>+10.2f}% {r.router_test_sum:>+9.2f}% "
              f"{r.flat_test_sum:>+9.2f}% {edge:>+11.2f}pp {r.n_traded_syms:>6d}")
    print()

    # ── Distribution stats ──
    test_sums = [r.router_test_sum for r in path_results]
    flat_sums = [r.flat_test_sum for r in path_results]
    edges = [r.router_test_sum - r.flat_test_sum for r in path_results]
    print("=" * 80)
    print("DISTRIBUTION STATISTICS (across all CPCV paths)")
    print("=" * 80)
    def stat(name, vs):
        if not vs:
            return
        srt = sorted(vs)
        n = len(srt)
        p5 = srt[max(0, int(0.05 * n))]
        p50 = srt[n // 2]
        p95 = srt[min(n - 1, int(0.95 * n))]
        pct_pos = 100 * sum(1 for v in vs if v > 0) / n
        print(f"  {name:<25s}  mean={st.mean(vs):>+6.2f}%  median={p50:>+6.2f}%  p5={p5:>+6.2f}%  p95={p95:>+6.2f}%  %pos={pct_pos:>3.0f}%")
    stat("router test_sum", test_sums)
    stat("flat-trend test_sum", flat_sums)
    stat("router edge over flat", edges)
    print()

    # ── PBO via pattern-rank stability ──
    # For each symbol, count fraction of paths where each pattern was picked
    print("=" * 80)
    print("PER-SYMBOL PICK STABILITY ACROSS PATHS")
    print("=" * 80)
    pick_counts: dict[str, Counter] = defaultdict(Counter)
    for r in path_results:
        for sym, pick in r.per_sym_picks.items():
            pick_counts[sym][pick] += 1
    n_paths = len(path_results)
    print(f"{'symbol':<10s} | {'mode':<13s} {'mode_freq':>10s} | distribution")
    print("-" * 80)
    stable_picks = 0
    flippy_picks = 0
    for sym in sorted(pick_counts.keys()):
        ctr = pick_counts[sym]
        mode, mode_n = ctr.most_common(1)[0]
        mode_freq = 100 * mode_n / n_paths
        if mode_freq >= 80:
            stable_picks += 1
            tag = " STABLE"
        elif mode_freq >= 50:
            tag = " mixed"
        else:
            flippy_picks += 1
            tag = " FLIPPY"
        dist = " ".join(f"{p}:{c}" for p, c in ctr.most_common())
        print(f"{sym:<10s} | {mode:<13s} {mode_freq:>9.0f}% | {dist}{tag}")
    print(f"\n  STABLE picks: {stable_picks}/{len(pick_counts)} | FLIPPY: {flippy_picks}/{len(pick_counts)}")
    print()

    # ── Verdict ──
    print("=" * 80)
    print("VERDICT (per pre-commit interpretation)")
    print("=" * 80)
    srt = sorted(test_sums)
    median_test = srt[len(srt) // 2]
    p5_test = srt[max(0, int(0.05 * len(srt)))]
    pct_pos = 100 * sum(1 for v in test_sums if v > 0) / len(test_sums) if test_sums else 0
    # PBO-proxy: % paths where router LOSES to flat
    pbo_proxy = 100 * sum(1 for r in path_results if r.router_test_sum <= r.flat_test_sum) / len(path_results)

    gates = [
        (f"median test_sum ≥ 0 (got {median_test:+.2f}%)", median_test >= 0),
        (f"5th-percentile test_sum ≥ -5% (got {p5_test:+.2f}%)", p5_test >= -5),
        (f"% paths with positive router-EV ≥ 60% (got {pct_pos:.0f}%)", pct_pos >= 60),
        (f"PBO-proxy (% paths router LOSES to flat) < 20% (got {pbo_proxy:.0f}%)", pbo_proxy < 20),
    ]
    for desc, ok in gates:
        print(f"  [{('PASS' if ok else 'FAIL')}]  {desc}")
    n_pass = sum(1 for _, ok in gates if ok)
    if n_pass == 4:
        verdict = "SHIP-WORTHY (CPCV-validated; proceed to paper A/B)"
    elif n_pass >= 2:
        verdict = "PROMISING — partial validation; refine before live"
    else:
        verdict = "REJECT (per default-REJECT; router is overfitting)"
    print(f"\n  → VERDICT: {verdict}")

    # Save
    out_dir = Path("analysis/data/cpcv")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "paths.json").write_text(json.dumps([
        {
            "test_folds": list(r.test_fold_ids),
            "router_train_sum": r.router_train_sum,
            "router_test_sum": r.router_test_sum,
            "flat_test_sum": r.flat_test_sum,
            "n_traded_syms": r.n_traded_syms,
            "per_sym_picks": r.per_sym_picks,
            "per_sym_test_sum": r.per_sym_test_sum,
        }
        for r in path_results
    ], indent=2))
    print(f"\nSaved → {out_dir}/paths.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
