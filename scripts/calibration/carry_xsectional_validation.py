#!/usr/bin/env python3
"""Cross-sectional weekly-rebalance funding carry (Hyperliquid) — pre-registered.

See private/strategy/2026-05-25-carry-xsectional-prereg.md. Each week: rank 10 HL coins
by trailing-168h mean funding; SHORT the top-K positive-funding coins (mult +1, receive
positive funding) + LONG the bottom-K negative-funding coins (mult -1, receive negative
funding). Hold the week, delta-neutral (price PnL ~0). Harvest = mult*funding hourly;
0.20% cost on a leg when it enters/flips at a week-open. Weekly rebalance => ~7x less
churn than the naive hourly carry. Default-REJECT gate + the TAIL.

OPTIMISTIC (ideal hedge) -> PASS is necessary-not-sufficient (needs price ingestion for
the real hedge cost/tail).

Run: uv run python scripts/calibration/carry_xsectional_validation.py [--k 3] [--flip-cost 0.002]
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import statistics as st
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import overfitting_rigor as ofr  # noqa: E402

FUND_DIR = os.path.join(_HERE, "data", "funding")
COINS = ["BTC", "ETH", "SOL", "BNB", "AVAX", "DOGE", "WIF", "ARB", "OP", "LINK"]
W = 168  # trailing window + rebalance period (1 week, hourly)
DEFAULT_K = 3
DEFAULT_FLIP_COST = 0.002
HOURS_YR = 24 * 365
CPCV_N_GROUPS, CPCV_N_TEST, CPCV_EMBARGO = 8, 2, 1
BLOCK, REPS, SEED = 6, 5000, 1729


def load_funding() -> dict[str, dict[int, float]]:
    out: dict[str, dict[int, float]] = {}
    for c in COINS:
        p = os.path.join(FUND_DIR, f"{c}_funding.json")
        if os.path.exists(p):
            with open(p) as f:
                out[c] = {int(r["ts"]): float(r["fundingRate"]) for r in json.load(f)}
    return out


def build(fund: dict[str, dict[int, float]], k: int, flip_cost: float):
    """Return (portfolio_hourly_returns, per_coin_contrib). Cross-sectional weekly book."""
    all_ts = sorted({t for d in fund.values() for t in d})
    port: list[float] = []
    per_coin: dict[str, list[tuple[int, float]]] = {c: [] for c in fund}
    prev_book: dict[str, int] = {}
    # iterate week-aligned: rebalance every W hours, starting after one W warmup
    i = W
    while i < len(all_ts):
        wk_ts = all_ts[i : i + W]  # week starts at all_ts[i]; rank uses strictly-prior W hours
        prior = list(all_ts[max(0, i - W) : i])
        means = {}
        for c, d in fund.items():
            vals = [d[t] for t in prior if t in d]
            if len(vals) >= W // 2:
                means[c] = st.mean(vals)
        ranked = sorted(means.items(), key=lambda kv: kv[1])
        if len(ranked) < 2 * k:
            i += W
            continue
        book: dict[str, int] = {}
        for c, _ in ranked[-k:]:  # top-k positive funding -> short -> mult +1
            book[c] = +1
        for c, _ in ranked[:k]:  # bottom-k negative funding -> long -> mult -1
            book[c] = -1
        for h_idx, t in enumerate(wk_ts):
            legs = []
            for c, mult in book.items():
                if t not in fund[c]:
                    continue
                harvest = mult * fund[c][t]
                if h_idx == 0 and (c not in prev_book or prev_book[c] != mult):
                    harvest -= flip_cost
                legs.append(harvest)
                per_coin[c].append((t, harvest))
            if legs:
                port.append(st.mean(legs))
        prev_book = book
        i += W
    return port, per_coin


def block_ci(xs: list[float]) -> tuple[float, float, float]:
    n = len(xs)
    if n < 2:
        return float("nan"), float("nan"), float("nan")
    rng = random.Random(SEED)
    means = []
    for _ in range(REPS):
        acc, cnt = 0.0, 0
        while cnt < n:
            s = rng.randrange(n)
            for kk in range(BLOCK):
                acc += xs[(s + kk) % n]
                cnt += 1
                if cnt >= n:
                    break
        means.append(acc / n)
    means.sort()
    return st.mean(xs), means[int(0.05 * REPS)], means[int(0.95 * REPS)]


def cpcv_on(rets: list[float]) -> ofr.CPCVResult:
    if len(rets) < CPCV_N_GROUPS * 2:
        return ofr.CPCVResult(
            CPCV_N_GROUPS,
            CPCV_N_TEST,
            0,
            [],
            float("nan"),
            float("nan"),
            float("nan"),
            float("nan"),
            0.0,
            note="too few",
        )
    n = len(rets)
    bounds = [round(n * g / CPCV_N_GROUPS) for g in range(CPCV_N_GROUPS + 1)]
    samples = [
        (g, rets[p], g) for g in range(CPCV_N_GROUPS) for p in range(bounds[g], bounds[g + 1])
    ]
    return ofr.cpcv_paths(samples, CPCV_N_GROUPS, CPCV_N_TEST, CPCV_EMBARGO)


def pbo_by_coin(per_coin: dict[str, list[tuple[int, float]]]) -> ofr.PBOResult:
    names = [c for c in per_coin if len(per_coin[c]) >= 10]
    if len(names) < 2:
        return ofr.PBOResult(float("nan"), 0, len(names), float("nan"), note="need >=2 coins")
    all_ts = sorted({t for c in names for t, _ in per_coin[c]})
    lo, span, nb = all_ts[0], max(1, all_ts[-1] - all_ts[0]), 10
    matrix = []
    for b in range(nb):
        row = []
        for c in names:
            vals = [v for t, v in per_coin[c] if min(nb - 1, int((t - lo) / span * nb)) == b]
            row.append(st.mean(vals) if vals else 0.0)
        matrix.append(row)
    return ofr.pbo(matrix, n_partitions=nb)


def run(k: int, flip_cost: float) -> None:
    fund = load_funding()
    port, per_coin = build(fund, k, flip_cost)
    print("=" * 96)
    print(
        f"CROSS-SECTIONAL WEEKLY CARRY (K={k} short-top/long-bottom, weekly rebal, flip={flip_cost * 100:.2f}%)"
    )
    print(f"  {len(fund)} coins, portfolio hours={len(port)}")
    print("=" * 96)
    if len(port) < 2:
        print("  insufficient data")
        return
    mean_h, lo_h, hi_h = block_ci(port)
    ann, ann_lo, ann_hi = mean_h * HOURS_YR * 100, lo_h * HOURS_YR * 100, hi_h * HOURS_YR * 100
    shp = (mean_h / st.pstdev(port) * math.sqrt(HOURS_YR)) if st.pstdev(port) > 0 else 0.0
    mdd = ofr.max_drawdown(port)
    calmar = (sum(port) / abs(mdd)) if mdd < 0 else float("inf")
    cpcv = cpcv_on(port)
    dsr = ofr.deflated_sharpe_ratio(port, [ofr.sharpe_ratio(port)], n_trials=1)
    pbo = pbo_by_coin(per_coin)

    print(
        f"  net carry annualized {ann:+.2f}%  95% CI [{ann_lo:+.2f}%, {ann_hi:+.2f}%]  excl0+: {lo_h > 0}"
    )
    print(f"  annualized Sharpe={shp:+.2f}  maxDD(cum)={mdd * 100:+.3f}%  Calmar={calmar:+.2f}")
    print(
        f"  CPCV median Sharpe={cpcv.median:+.3f}  %paths<0={cpcv.pct_paths_negative:.1%}  DSR={dsr.dsr:.3f}  PBO={pbo.pbo:.3f}"
    )

    gates = {
        "net-carry CI excl 0 (+)": lo_h > 0,
        "DSR>=0.95": dsr.dsr >= 0.95,
        "PBO<0.20": (pbo.pbo == pbo.pbo) and pbo.pbo < 0.20,
        "%paths<0<25%": cpcv.pct_paths_negative < 0.25,
        "tail ok (Calmar>0)": mdd < 0 and calmar > 0,
    }
    verdict = (
        "DEPLOY" if all(gates.values()) else ("PAPER ONLY" if ann > 0 and lo_h > 0 else "REJECT")
    )
    print(f"\n  VERDICT: {verdict}   (OPTIMISTIC — ideal hedge; PASS = necessary-not-sufficient)")
    for kk, v in gates.items():
        print(f"    [{'PASS' if v else 'FAIL'}] {kk}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=DEFAULT_K)
    ap.add_argument("--flip-cost", type=float, default=DEFAULT_FLIP_COST)
    a = ap.parse_args()
    run(a.k, a.flip_cost)
