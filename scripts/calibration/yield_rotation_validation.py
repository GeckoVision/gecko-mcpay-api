#!/usr/bin/env python3
"""Phase E.2' — multi-chain USDC yield rotation validation (pre-registered).

See private/strategy/2026-05-27-phase-e-ev-hunt-plan.md (E.2 section + E.2' pivot).

Hypothesis (trading-strategist's HIGHEST-prior proposal, adapted to free
DefiLlama data substrate since Marginfi + Drift aren't in DefiLlama):

Rotate USDC notional across major lending pools (Kamino-Solana, Aave-Base,
Aave-Ethereum, Compound-Ethereum, Aave-Arbitrum) by trailing-7d APY rank,
gated by an APY-spread hurdle above the static Kamino baseline. Default lane
= 100% Kamino if hurdle not met.

This is a STRUCTURAL test: does cross-pool/cross-chain APY rotation beat
the validated single-pool Kamino baseline NET OF rebalance costs?

Variants tested:
- BASELINE: weekly rebalance, top-3 weighted [0.5, 0.3, 0.2], 1.5%/yr hurdle
- Ablations vary: hurdle, frequency, top-K, lookback, cost-stress

Run baseline:
    uv run python scripts/calibration/yield_rotation_validation.py
Run ablations:
    uv run python scripts/calibration/yield_rotation_validation.py --ablations
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics as st
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import overfitting_rigor as ofr  # noqa: E402

CACHE_DIR = Path(_HERE) / "data" / "yield_pools"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# 5 candidate pools (discovered via DefiLlama free yields API, 2026-05-27).
# (pool_id, label, chain, protocol).
POOLS = [
    ("d2141a59-c199-4be7-8d4b-c8223954836b", "Kamino-Sol",   "Solana",   "kamino-lend"),
    ("7e0661bf-8cf3-45e6-9424-31916d4c7b84", "Aave-Base",    "Base",     "aave-v3"),
    ("aa70268e-4b52-42bf-a116-608b370f9501", "Aave-ETH",     "Ethereum", "aave-v3"),
    ("7da72d09-56ca-4ec5-a45f-59114353e487", "Compound-ETH", "Ethereum", "compound-v3"),
    ("d9fa8e14-0447-4207-9ae8-7810199dfa1f", "Aave-ARB",     "Arbitrum", "aave-v3"),
]

# Rebalance costs (one-way; backtest applies on every rotation, prorated by
# weight changed). Cross-chain via Wormhole/Allbridge/Mayan ≈ 0.5%/leg in 2026;
# same-chain swap (Jupiter / Uniswap) ≈ 0.05%/leg.
COST_CROSS_CHAIN_PCT = 0.50
COST_SAME_CHAIN_PCT = 0.05


def chain_of(label: str) -> str:
    """Resolve chain from label — used to decide bridge vs same-chain cost."""
    for _pid, lbl, chain, _proto in POOLS:
        if lbl == label:
            return chain
    return "?"


# ── BASELINE configuration (per agent proposal)
BASELINE = {
    "name": "baseline",
    "hurdle_pct_yr": 1.5,         # top-K mean must exceed Kamino baseline + this
    "rebalance_period_days": 7,   # weekly
    "lookback_days": 7,           # trailing 7d APY for ranking
    "top_k": 3,                   # rotate to top-K pools, weights [0.5, 0.3, 0.2]
    "cost_stress_factor": 1.0,    # 1.0 = realistic, 2.0 = stress test
}

ABLATIONS = [
    BASELINE,
    {**BASELINE, "name": "tight_hurdle", "hurdle_pct_yr": 0.5},
    {**BASELINE, "name": "loose_hurdle", "hurdle_pct_yr": 3.0},
    {**BASELINE, "name": "biweekly", "rebalance_period_days": 14},
    {**BASELINE, "name": "monthly", "rebalance_period_days": 28},
    {**BASELINE, "name": "lookback_14d", "lookback_days": 14},
    {**BASELINE, "name": "lookback_28d", "lookback_days": 28},
    {**BASELINE, "name": "topk_1", "top_k": 1},
    {**BASELINE, "name": "topk_5", "top_k": 5},
    {**BASELINE, "name": "cost_stress_2x", "cost_stress_factor": 2.0},
]


def fetch_pool_chart(pool_id: str, label: str, force_refresh: bool = False) -> list[dict]:
    """Fetch historical APY for a pool. Cache to disk to avoid re-querying."""
    cache_file = CACHE_DIR / f"{label.replace('/', '_')}_apy.json"
    if cache_file.exists() and not force_refresh:
        # Check age — refresh if > 12h
        age_hours = (time.time() - cache_file.stat().st_mtime) / 3600
        if age_hours < 12:
            return json.loads(cache_file.read_text())

    print(f"  fetching {label} ({pool_id}) from DefiLlama ...", flush=True)
    try:
        r = httpx.get(f"https://yields.llama.fi/chart/{pool_id}", timeout=30)
        rows = r.json().get("data") or []
        cache_file.write_text(json.dumps(rows))
        return rows
    except Exception as e:
        print(f"    FAILED: {type(e).__name__}: {e}")
        if cache_file.exists():
            return json.loads(cache_file.read_text())
        return []


def load_all_pool_charts() -> dict[str, list[dict]]:
    """Pull historical APY for all 5 pools (cached)."""
    out: dict[str, list[dict]] = {}
    for pid, label, _chain, _proto in POOLS:
        rows = fetch_pool_chart(pid, label)
        if rows:
            out[label] = rows
        else:
            print(f"  WARNING: no data for {label}")
    return out


def parse_ts(ts_str: str) -> int:
    """Parse ISO ts string → unix ms."""
    from datetime import datetime
    try:
        # Handle both 'Z' suffix and '+00:00'
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        return int(dt.timestamp() * 1000)
    except Exception:
        return 0


def align_to_daily(charts: dict[str, list[dict]]) -> tuple[list[int], dict[str, dict[int, float]]]:
    """Align all charts to a common DAILY timestamp grid.

    Returns (sorted_daily_ts_list, {label → {ts_day → apy_pct}}).
    """
    aligned: dict[str, dict[int, float]] = {label: {} for label in charts}
    all_days: set[int] = set()
    for label, rows in charts.items():
        for r in rows:
            ts_ms = parse_ts(r.get("timestamp", ""))
            if ts_ms <= 0:
                continue
            # Round to day (UTC midnight)
            day_ts = ts_ms - (ts_ms % (24 * 3600 * 1000))
            apy = r.get("apy")
            if apy is None or not isinstance(apy, (int, float)):
                continue
            aligned[label][day_ts] = float(apy)
            all_days.add(day_ts)
    return sorted(all_days), aligned


def simulate_variant(
    config: dict,
    common_days: list[int],
    pool_apy: dict[str, dict[int, float]],
) -> list[dict]:
    """Run one variant. Returns list of weekly allocation snapshots with realized yield.

    Each snapshot: {
        ts: day_start_ms,
        allocation: {label: weight, ...},   # weights sum to 1
        realized_apy_pct: weighted current APY,
        rebalance_cost_pct: cost paid this rebalance,
        net_apy_pct: realized - cost amortized over hold,
    }
    """
    hurdle = config["hurdle_pct_yr"]
    period = config["rebalance_period_days"]
    lookback = config["lookback_days"]
    top_k = config["top_k"]
    cost_factor = config["cost_stress_factor"]

    # Kamino is the baseline (default lane)
    snapshots = []
    last_alloc: dict[str, float] = {"Kamino-Sol": 1.0}  # start in 100% Kamino
    # Iterate days; rebalance every `period` days
    if not common_days:
        return []
    first_day = common_days[0] + lookback * 24 * 3600 * 1000  # need lookback warmup
    rebalance_days = [d for d in common_days if d >= first_day]
    next_rebalance = 0

    for i, day in enumerate(rebalance_days):
        if i != 0 and (day - rebalance_days[next_rebalance]) < period * 24 * 3600 * 1000:
            continue  # not yet time to rebalance
        next_rebalance = i

        # Compute trailing-lookback mean APY per pool
        trailing_means: dict[str, float] = {}
        for label, day_apy in pool_apy.items():
            window_apys = []
            for d in common_days:
                if d > day:
                    break
                if d > day - lookback * 24 * 3600 * 1000 and d in day_apy:
                    window_apys.append(day_apy[d])
            if len(window_apys) >= max(2, lookback // 2):
                trailing_means[label] = sum(window_apys) / len(window_apys)

        kamino_apy = trailing_means.get("Kamino-Sol")
        if kamino_apy is None:
            continue

        # Decide allocation: rotation OR default-to-Kamino
        # Rotation: top-K by trailing APY; weights = decay 0.5, 0.3, 0.2 (for K=3),
        # equal-weight for other K
        ranked = sorted(trailing_means.items(), key=lambda kv: -kv[1])[:top_k]
        top_k_mean = sum(apy for _, apy in ranked) / len(ranked) if ranked else 0
        # Hurdle: top-K-mean APY must exceed Kamino baseline by hurdle (in %/yr)
        if top_k_mean >= kamino_apy + hurdle:
            # Rotate
            if top_k == 3:
                weights = [0.5, 0.3, 0.2]
            elif top_k == 1:
                weights = [1.0]
            else:
                weights = [1.0 / top_k] * top_k
            new_alloc = {ranked[i][0]: weights[i] for i in range(min(len(ranked), len(weights)))}
        else:
            # Default lane: 100% Kamino
            new_alloc = {"Kamino-Sol": 1.0}

        # Compute rebalance cost = sum of |weight_change| × per-pool cost
        # Per-pool cost depends on chain transition (Solana ↔ EVM = bridge)
        rebalance_cost = 0.0
        all_pools = set(last_alloc) | set(new_alloc)
        for pool in all_pools:
            old_w = last_alloc.get(pool, 0.0)
            new_w = new_alloc.get(pool, 0.0)
            delta = abs(new_w - old_w)
            if delta < 1e-6:
                continue
            # Cost depends on whether this is cross-chain
            pool_chain = chain_of(pool)
            # If the pool's chain != where the "outgoing" weight is going, it's cross-chain
            # Simplification: assume all rotations incur cross-chain cost if old or new is on different chain
            # Conservative: any non-Kamino-Sol vs Kamino-Sol movement = cross-chain
            old_chains = {chain_of(p) for p, w in last_alloc.items() if w > 0}
            new_chains = {chain_of(p) for p, w in new_alloc.items() if w > 0}
            is_cross_chain = (
                ("Solana" in old_chains and "Solana" not in new_chains)
                or ("Solana" in new_chains and "Solana" not in old_chains)
                or (old_chains != new_chains and pool_chain != "Solana")
            )
            cost_pct = (COST_CROSS_CHAIN_PCT if is_cross_chain else COST_SAME_CHAIN_PCT) * cost_factor
            rebalance_cost += delta * cost_pct / 2  # /2 because each delta represents one side of the flow

        # Realized APY = weighted current-day APY of new allocation
        realized_apy = sum(
            w * pool_apy[lbl].get(day, trailing_means.get(lbl, 0))
            for lbl, w in new_alloc.items()
        )

        # Net APY over the period (in %/yr): realized minus amortized cost
        # Amortize cost over the period: cost / (period/365)
        cost_amortized_apy = rebalance_cost * (365 / period) if period > 0 else rebalance_cost

        snapshots.append({
            "ts": day,
            "allocation": new_alloc,
            "kamino_apy": kamino_apy,
            "top_k_mean_apy": top_k_mean,
            "rotated": new_alloc != {"Kamino-Sol": 1.0},
            "realized_apy_pct": realized_apy,
            "rebalance_cost_pct": rebalance_cost,
            "net_apy_pct": realized_apy - cost_amortized_apy,
        })

        last_alloc = new_alloc

    return snapshots


def baseline_kamino_only(common_days: list[int], pool_apy: dict[str, dict[int, float]], rebalance_period_days: int) -> list[dict]:
    """Comparator: always 100% Kamino. Daily APY series, no rotation cost."""
    out = []
    for d in common_days:
        apy = pool_apy.get("Kamino-Sol", {}).get(d)
        if apy is None:
            continue
        out.append({"ts": d, "kamino_apy": apy, "net_apy_pct": apy, "rotated": False})
    return out


def annualized_realized(snapshots: list[dict], days_per_rebalance: int) -> float:
    """Convert per-snapshot net APY into ANNUALIZED realized return.

    Each snapshot represents `days_per_rebalance` of yield at that APY rate.
    """
    if not snapshots:
        return 0.0
    # Per-snapshot return = APY × (days_per_rebalance / 365)
    period_returns = [s["net_apy_pct"] * days_per_rebalance / 365 for s in snapshots]
    total_period_return = sum(period_returns)
    total_days = len(snapshots) * days_per_rebalance
    if total_days <= 0:
        return 0.0
    annualized = total_period_return * (365 / total_days)
    return annualized


def run_variant(config: dict, common_days: list[int], pool_apy: dict[str, dict[int, float]]) -> dict:
    snapshots = simulate_variant(config, common_days, pool_apy)
    if not snapshots:
        return {
            "name": config["name"], "n_snapshots": 0,
            "rotated_count": 0, "rotation_rate": 0,
            "annualized_pct": 0, "vs_kamino_static_pct": 0,
            "kamino_static_annualized_pct": 0,
            "rebalance_cost_total_pct": 0,
        }

    annualized = annualized_realized(snapshots, config["rebalance_period_days"])
    rotated = sum(1 for s in snapshots if s["rotated"])
    # Total rebalance cost paid
    total_cost = sum(s["rebalance_cost_pct"] for s in snapshots)
    # Kamino-only comparator (use the same period for fair comparison)
    kamino_apys = [pool_apy["Kamino-Sol"].get(s["ts"]) for s in snapshots]
    kamino_apys = [a for a in kamino_apys if a is not None]
    if kamino_apys:
        kamino_static_period_returns = [a * config["rebalance_period_days"] / 365 for a in kamino_apys]
        kamino_static_annualized = sum(kamino_static_period_returns) * (365 / (len(kamino_apys) * config["rebalance_period_days"]))
    else:
        kamino_static_annualized = 0

    return {
        "name": config["name"],
        "config": config,
        "n_snapshots": len(snapshots),
        "rotated_count": rotated,
        "rotation_rate": rotated / len(snapshots),
        "annualized_pct": annualized,
        "kamino_static_annualized_pct": kamino_static_annualized,
        "vs_kamino_static_pct": annualized - kamino_static_annualized,
        "rebalance_cost_total_pct": total_cost,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ablations", action="store_true")
    ap.add_argument("--refresh", action="store_true", help="bypass cache + re-fetch DefiLlama")
    args = ap.parse_args()

    print("=" * 100)
    print("Phase E.2' — multi-chain USDC yield rotation (pre-registered)")
    print(f"  pools: {[p[1] for p in POOLS]}")
    print(f"  cross-chain cost: {COST_CROSS_CHAIN_PCT}%/leg  same-chain: {COST_SAME_CHAIN_PCT}%/leg")
    print("=" * 100)

    print("Loading pool APY history (DefiLlama free)...")
    charts = load_all_pool_charts()
    print(f"  pools loaded: {len(charts)} / {len(POOLS)}")
    if len(charts) < 2:
        print("ABORT: need >= 2 pools")
        return 1

    common_days, pool_apy = align_to_daily(charts)
    print(f"  aligned days: {len(common_days)}  span: {common_days[0]/86400000:.0f} → {common_days[-1]/86400000:.0f} (unix days)")
    print()

    configs = ABLATIONS if args.ablations else [BASELINE]
    results = []
    for cfg in configs:
        print(f"[RUN] {cfg['name']}", flush=True)
        r = run_variant(cfg, common_days, pool_apy)
        results.append(r)
        if r["n_snapshots"] > 0:
            print(
                f"  n_snapshots={r['n_snapshots']}  rotated={r['rotated_count']} ({r['rotation_rate']:.1%})  "
                f"annualized={r['annualized_pct']:+.2f}%  kamino_static={r['kamino_static_annualized_pct']:+.2f}%  "
                f"delta={r['vs_kamino_static_pct']:+.2f}%  total_cost={r['rebalance_cost_total_pct']:+.2f}%"
            )
        else:
            print("  TOO_FEW_SNAPSHOTS")

    print()
    print("=" * 100)
    print("SUMMARY (sorted by delta vs Kamino-static)")
    print("=" * 100)
    print(f"  {'name':<18s}  {'n_snap':>7s}  {'rotated':>8s}  {'rotation_rate':>14s}  {'annualized':>10s}  {'kamino_static':>14s}  {'delta':>8s}")
    print("-" * 100)
    for r in sorted(results, key=lambda r: -r["vs_kamino_static_pct"] if r["n_snapshots"] else 999):
        if r["n_snapshots"] == 0:
            print(f"  {r['name']:<18s}  TOO_FEW_SNAPSHOTS")
            continue
        print(
            f"  {r['name']:<18s}  {r['n_snapshots']:>7d}  {r['rotated_count']:>8d}  {r['rotation_rate']:>13.1%}  "
            f"{r['annualized_pct']:>+9.2f}%  {r['kamino_static_annualized_pct']:>+13.2f}%  {r['vs_kamino_static_pct']:>+7.2f}%"
        )

    # Branch verdict per pre-commit
    print()
    print("=" * 100)
    print("BRANCH ANALYSIS:")
    print("=" * 100)
    baseline = results[0] if results else None
    if baseline and baseline["n_snapshots"] > 0:
        delta = baseline["vs_kamino_static_pct"]
        print(f"  Baseline delta vs Kamino-static: {delta:+.2f}%/yr")
        if delta > 0.5:
            print("  → BRANCH A: ROTATION ADDS VALUE — proceed to deeper rigor + paper pilot")
        elif delta > 0:
            print("  → BRANCH B: MARGINAL — rotation barely beats static; need stress + larger pool universe")
        else:
            print("  → BRANCH C: NULL #11 — rotation does NOT beat static Kamino baseline")
            if args.ablations:
                any_positive = sum(1 for r in results if r["vs_kamino_static_pct"] > 0)
                print(f"  Of {len(results)} ablations, {any_positive} have positive delta")
                if any_positive >= len(results) * 0.5:
                    print("  → consider: maybe BASELINE config is suboptimal; some variants do beat")
                else:
                    print("  → broadly null: most variants underperform Kamino-static")

    # Persist
    out = Path(_HERE).parent.parent / "analysis" / "data" / "phase_e" / "yield_rotation"
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps(results, indent=2, default=str))
    print(f"\nResults → {(out / 'summary.json').relative_to(Path(_HERE).parent.parent)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
