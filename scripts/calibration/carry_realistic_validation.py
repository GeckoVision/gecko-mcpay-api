#!/usr/bin/env python3
"""REALISTIC cross-sectional carry — funding harvest MINUS basis PnL (the sufficient test).

See private/strategy/2026-05-25-carry-realistic-prereg.md. Same frozen strategy as the
optimistic cross-sectional carry (K=3 short-top/long-bottom funding, weekly rebalance,
10 HL coins, 180d) but each leg now also carries the imperfect-hedge BASIS PnL:

  leg_return[t] = mult * ( funding[t] - (perp_ret[t] - spot_ret[t]) ) - cost_at_rebalance

where perp_ret from HL perp candles, spot = perp_close/(1+premium) (HL's own premium),
so perp_ret - spot_ret is the basis (~Δpremium) move against the hedge — the dominant
risk the optimistic (price-PnL~0) model assumed away. NOT a re-sweep (K/window reused
verbatim); DSR n_trials=1 (model refinement). Default-REJECT gate + the TAIL.

Run: uv run python scripts/calibration/carry_realistic_validation.py [--k 3] [--flip-cost 0.002]
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics as st
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import carry_xsectional_validation as cx  # noqa: E402  reuse block_ci/cpcv_on/pbo_by_coin
import overfitting_rigor as ofr  # noqa: E402

FUND_DIR = os.path.join(_HERE, "data", "funding")
PERP_DIR = os.path.join(_HERE, "data", "perp")
COINS = cx.COINS
W, HOURS_YR = cx.W, cx.HOURS_YR


def load_leg_inputs() -> dict[str, dict[int, tuple[float, float, float]]]:
    """Per coin: {ts: (funding, perp_ret, spot_ret)} on the common hourly grid (ts with a
    valid prior bar for the returns). spot = perp_close/(1+premium)."""
    out: dict[str, dict[int, tuple[float, float, float]]] = {}
    for c in COINS:
        fp = os.path.join(FUND_DIR, f"{c}_funding.json")
        pp = os.path.join(PERP_DIR, f"{c}_perp.json")
        if not (os.path.exists(fp) and os.path.exists(pp)):
            continue
        # HL funding ts carry a few-ms offset; perp candle ts are exact :00 -> floor both
        # to the hour so the two series join.
        def _hr(x: object) -> int:
            return (int(x) // 3_600_000) * 3_600_000

        with open(fp) as f:
            fund = {
                _hr(r["ts"]): (float(r["fundingRate"]), float(r.get("premium", 0) or 0))
                for r in json.load(f)
            }
        with open(pp) as f:
            perp = {_hr(r["ts"]): float(r["close"]) for r in json.load(f)}
        common = sorted(set(fund) & set(perp))
        rec: dict[int, tuple[float, float, float]] = {}
        for i in range(1, len(common)):
            t, tp = common[i], common[i - 1]
            pc, pp_prev = perp[t], perp[tp]
            fr_t, prem_t = fund[t]
            _, prem_prev = fund[tp]
            if pc <= 0 or pp_prev <= 0:
                continue
            spot_t = pc / (1 + prem_t)
            spot_prev = pp_prev / (1 + prem_prev)
            if spot_prev <= 0:
                continue
            perp_ret = (pc - pp_prev) / pp_prev
            spot_ret = (spot_t - spot_prev) / spot_prev
            rec[t] = (fr_t, perp_ret, spot_ret)
        out[c] = rec
    return out


def build(legs: dict[str, dict[int, tuple[float, float, float]]], k: int, flip_cost: float):
    """Cross-sectional weekly book with basis-aware leg returns. Returns (portfolio, per_coin)."""
    all_ts = sorted({t for d in legs.values() for t in d})
    port: list[float] = []
    per_coin: dict[str, list[tuple[int, float]]] = {c: [] for c in legs}
    prev_book: dict[str, int] = {}
    i = W
    while i < len(all_ts):
        wk_ts = all_ts[i : i + W]
        prior = list(all_ts[max(0, i - W) : i])
        means = {}
        for c, d in legs.items():
            vals = [d[t][0] for t in prior if t in d]  # trailing mean funding
            if len(vals) >= W // 2:
                means[c] = st.mean(vals)
        ranked = sorted(means.items(), key=lambda kv: kv[1])
        if len(ranked) < 2 * k:
            i += W
            continue
        book = {c: +1 for c, _ in ranked[-k:]}  # short top positive funding
        book.update({c: -1 for c, _ in ranked[:k]})  # long bottom negative funding
        for h_idx, t in enumerate(wk_ts):
            leg_rets = []
            for c, mult in book.items():
                if t not in legs[c]:
                    continue
                fr, perp_ret, spot_ret = legs[c][t]
                r = mult * (fr - (perp_ret - spot_ret))
                if h_idx == 0 and (c not in prev_book or prev_book[c] != mult):
                    r -= flip_cost
                leg_rets.append(r)
                per_coin[c].append((t, r))
            if leg_rets:
                port.append(st.mean(leg_rets))
        prev_book = book
        i += W
    return port, per_coin


def run(k: int, flip_cost: float) -> None:
    legs = load_leg_inputs()
    port, per_coin = build(legs, k, flip_cost)
    print("=" * 96)
    print(
        f"REALISTIC CROSS-SECTIONAL CARRY (K={k}, weekly, funding - basis, flip={flip_cost * 100:.2f}%)"
    )
    print(f"  {len(legs)} coins, portfolio hours={len(port)}")
    print("=" * 96)
    if len(port) < 2:
        print("  insufficient data")
        return
    mean_h, lo_h, hi_h = cx.block_ci(port)
    ann, ann_lo, ann_hi = mean_h * HOURS_YR * 100, lo_h * HOURS_YR * 100, hi_h * HOURS_YR * 100
    shp = (mean_h / st.pstdev(port) * math.sqrt(HOURS_YR)) if st.pstdev(port) > 0 else 0.0
    mdd = ofr.max_drawdown(port)
    calmar = (sum(port) / abs(mdd)) if mdd < 0 else float("inf")
    cpcv = cx.cpcv_on(port)
    dsr = ofr.deflated_sharpe_ratio(port, [ofr.sharpe_ratio(port)], n_trials=1)
    pbo = cx.pbo_by_coin(per_coin)

    print(
        f"  net carry annualized {ann:+.2f}%  95% CI [{ann_lo:+.2f}%, {ann_hi:+.2f}%]  excl0+: {lo_h > 0}"
    )
    print(f"  annualized Sharpe={shp:+.2f}  maxDD(cum)={mdd * 100:+.3f}%  Calmar={calmar:+.2f}")
    print(
        f"  CPCV median Sharpe={cpcv.median:+.3f}  %paths<0={cpcv.pct_paths_negative:.1%}  DSR={dsr.dsr:.3f}  PBO={pbo.pbo:.3f}"
    )

    gates = {
        "net CI excl 0 (+)": lo_h > 0,
        "DSR>=0.95": dsr.dsr >= 0.95,
        "PBO<0.20": (pbo.pbo == pbo.pbo) and pbo.pbo < 0.20,
        "%paths<0<25%": cpcv.pct_paths_negative < 0.25,
        "tail ok (Calmar>0)": mdd < 0 and calmar > 0,
    }
    verdict = (
        "DEPLOY" if all(gates.values()) else ("PAPER ONLY" if ann > 0 and lo_h > 0 else "REJECT")
    )
    print(
        f"\n  VERDICT: {verdict}   (realistic basis PnL; still excl. slippage>cost + leverage-liquidation stress)"
    )
    for kk, v in gates.items():
        print(f"    [{'PASS' if v else 'FAIL'}] {kk}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=cx.DEFAULT_K)
    ap.add_argument("--flip-cost", type=float, default=cx.DEFAULT_FLIP_COST)
    a = ap.parse_args()
    run(a.k, a.flip_cost)
