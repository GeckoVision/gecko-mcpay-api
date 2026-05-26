#!/usr/bin/env python3
"""Delta-neutral funding-carry harvest (Hyperliquid) — pre-registered, single config.

See private/strategy/2026-05-25-carry-harvest-prereg.md. Each hour, per coin, hold the
funding-RECEIVING side (side = sign of trailing-24h mean funding) and harvest
side x fundingRate (delta-hedged -> price PnL ~0). Subtract a flip cost when the side
changes. Headline = equal-weight carry PORTFOLIO (correctly treats cross-coin
correlation); per-coin for PBO. Default-REJECT gate + the TAIL (max DD / Calmar).

OPTIMISTIC by construction (ideal hedge, no liquidation/de-peg) -> a REJECT is
decisive; a PASS is necessary-not-sufficient.

Run: uv run python scripts/calibration/carry_harvest_validation.py [--flip-cost 0.002]
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
W = 24  # trailing window (hours) for the side signal
DEFAULT_FLIP_COST = 0.002  # 0.20% per side-flip (round-trip, 2 hedge legs), as a fraction
HOURS_YR = 24 * 365
CPCV_N_GROUPS, CPCV_N_TEST, CPCV_EMBARGO = 8, 2, 1
BLOCK, REPS, SEED = 6, 5000, 1729


def load_funding(coin: str) -> list[dict] | None:
    p = os.path.join(FUND_DIR, f"{coin}_funding.json")
    if not os.path.exists(p):
        return None
    with open(p) as f:
        recs = json.load(f)
    recs.sort(key=lambda x: x["ts"])
    return recs


def carry_series(recs: list[dict], flip_cost: float) -> list[tuple[int, float]]:
    """[(ts, net_carry)] — side=sign(trailing-W mean), harvest side*funding, minus
    flip_cost when the side changes. Leakage-clean (trailing window strictly prior)."""
    out: list[tuple[int, float]] = []
    fr = [r["fundingRate"] for r in recs]
    ts = [int(r["ts"]) for r in recs]
    prev_side = 0
    for t in range(W, len(fr)):
        trailing = sum(fr[t - W : t]) / W
        side = 1 if trailing > 0 else (-1 if trailing < 0 else 0)
        net = side * fr[t]
        if side != prev_side and side != 0:
            net -= flip_cost
        prev_side = side
        out.append((ts[t], net))
    return out


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
            for k in range(BLOCK):
                acc += xs[(s + k) % n]
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


def run(flip_cost: float) -> None:
    per_coin: dict[str, list[tuple[int, float]]] = {}
    ceiling: dict[str, float] = {}
    for coin in COINS:
        recs = load_funding(coin)
        if not recs:
            continue
        per_coin[coin] = carry_series(recs, flip_cost)
        fr = [r["fundingRate"] for r in recs]
        ceiling[coin] = (
            st.mean([abs(x) for x in fr]) * HOURS_YR * 100
        )  # perfect-foresight |funding|

    # equal-weight portfolio: mean net-carry across coins present each hour
    by_ts: dict[int, list[float]] = {}
    for series in per_coin.values():
        for t, v in series:
            by_ts.setdefault(t, []).append(v)
    port = [st.mean(by_ts[t]) for t in sorted(by_ts)]  # hourly portfolio return (fraction)

    print("=" * 96)
    print(
        f"FUNDING-CARRY HARVEST (delta-neutral, side=sign(trailing-{W}h), flip_cost={flip_cost * 100:.2f}%)"
    )
    print(f"  {len(per_coin)} coins, portfolio hours={len(port)}")
    print("=" * 96)
    # per-coin descriptive
    for coin, series in per_coin.items():
        vs = [v for _, v in series]
        ann = st.mean(vs) * HOURS_YR * 100
        shp = (st.mean(vs) / st.pstdev(vs) * math.sqrt(HOURS_YR)) if st.pstdev(vs) > 0 else 0.0
        print(
            f"  {coin:5} net-carry ann={ann:>+7.2f}%  Sharpe={shp:>+5.2f}  (|funding| ceiling={ceiling[coin]:>+6.1f}%)"
        )

    mean_h, lo_h, hi_h = block_ci(port)
    ann = mean_h * HOURS_YR * 100
    ann_lo, ann_hi = lo_h * HOURS_YR * 100, hi_h * HOURS_YR * 100
    shp = (mean_h / st.pstdev(port) * math.sqrt(HOURS_YR)) if st.pstdev(port) > 0 else 0.0
    mdd = ofr.max_drawdown(port)
    calmar = (sum(port) / abs(mdd)) if mdd < 0 else float("inf")
    cpcv = cpcv_on(port)
    dsr = ofr.deflated_sharpe_ratio(port, [ofr.sharpe_ratio(port)], n_trials=1)
    pbo = pbo_by_coin(per_coin)

    print(
        f"\n  PORTFOLIO net-carry: annualized {ann:+.2f}%  95% CI [{ann_lo:+.2f}%, {ann_hi:+.2f}%]  excl0+: {lo_h > 0}"
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
    for k, v in gates.items():
        print(f"    [{'PASS' if v else 'FAIL'}] {k}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--flip-cost", type=float, default=DEFAULT_FLIP_COST, help="fraction per side-flip"
    )
    a = ap.parse_args()
    run(a.flip_cost)
