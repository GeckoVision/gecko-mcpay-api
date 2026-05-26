#!/usr/bin/env python3
"""Adaptive (volatility-scaled) TP vs fixed-2% TP — pre-registered, single config.

See private/strategy/2026-05-25-adaptive-tp-prereg.md. Tests the founder's variable-TP
idea: TP% = clamp(1.5 x ATR%(entry), 0.5, 3.0) vs fixed 2.0%, on the SAME breakout/
volume-spike candidates, reusing the bot's REAL exit stack
(exit_reconciliation.simulate_exit_real_close) with LIVE_TP_PCT overridden per-trade —
all other rules (trail/SL/stall/flat-stall) identical, so ONLY the TP varies.

Default-REJECT gate: adaptive ships only if its net-EV CI clears the 2xfee bar AND it
beats baseline (paired delta CI > 0) AND DSR>=0.95 AND PBO<0.2 AND %paths<0<25%.

Run: uv run python scripts/calibration/adaptive_tp_validation.py
"""

from __future__ import annotations

import os
import random
import statistics as st
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import chart_floor_calibration as base  # noqa: E402
import exit_reconciliation as recon  # noqa: E402
import overfitting_rigor as ofr  # noqa: E402

TAPE_DIR = os.path.join(_HERE, "data", "tape")
SYMBOLS = ["WIF", "PYTH", "JTO", "BOME"]
TF = "5m"
ATR_PERIOD = 14
ATR_MULT = 1.5
TP_LO, TP_HI = 0.5, 3.0
BASELINE_TP = 2.0
FEE_RT = 0.08  # round-trip (Jupiter 0.04%/side)
STEP = 6  # non-overlap stepping (matches the eval)
CPCV_N_GROUPS, CPCV_N_TEST, CPCV_EMBARGO = 8, 2, 1
BLOCK, REPS, SEED = 3, 5000, 1729


def load(sym: str) -> dict | None:
    import json

    path = os.path.join(TAPE_DIR, f"{sym}_{TF}.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return base.enrich(json.load(f))


def atr_pct_at(c: dict, i: int) -> float | None:
    """14-period ATR / close * 100 at bar i (causal — bars <= i)."""
    if i < ATR_PERIOD:
        return None
    h, low, cl = c["high"], c["low"], c["close"]
    trs = [
        max(h[j] - low[j], abs(h[j] - cl[j - 1]), abs(low[j] - cl[j - 1]))
        for j in range(i - ATR_PERIOD + 1, i + 1)
    ]
    atr = sum(trs) / len(trs)
    return atr / cl[i] * 100.0 if cl[i] > 0 else None


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def collect() -> list[dict]:
    """Per candidate: ts, sym, baseline_net, adaptive_net (paired, same entry)."""
    out: list[dict] = []
    saved_tp = recon.LIVE_TP_PCT
    try:
        for sym in SYMBOLS:
            c = load(sym)
            if not c:
                continue
            n = len(c["close"])
            i = base.WARMUP
            while i < n:
                if (
                    base.breakout_fires(c, i) or base.volume_spike_fires(c, i)
                ) and base.has_full_horizon(c, i):
                    atrp = atr_pct_at(c, i)
                    if atrp is None:
                        i += 1
                        continue
                    recon.LIVE_TP_PCT = BASELINE_TP
                    base_ret = recon.simulate_exit_real_close(c, i) - FEE_RT
                    recon.LIVE_TP_PCT = _clamp(ATR_MULT * atrp, TP_LO, TP_HI)
                    adap_ret = recon.simulate_exit_real_close(c, i) - FEE_RT
                    out.append({"ts": c["ts"][i], "sym": sym, "base": base_ret, "adap": adap_ret})
                    i += STEP
                else:
                    i += 1
    finally:
        recon.LIVE_TP_PCT = saved_tp
    out.sort(key=lambda d: d["ts"])
    return out


def arm(returns: list[float]) -> dict:
    if not returns:
        return {"n": 0}
    return {
        "n": len(returns),
        "ev": st.mean(returns),
        "win": sum(1 for r in returns if r > 0) / len(returns),
        "sharpe": ofr.sharpe_ratio(returns),
        "max_dd": ofr.max_drawdown(returns),
    }


def block_ci(xs: list[float], paired: bool = False) -> tuple[float, float, float]:
    """Block-bootstrap 5-95% CI of the mean (paired=just pass the differences)."""
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


def cpcv_on(returns: list[float], bar_index: list[int]) -> ofr.CPCVResult:
    if len(returns) < CPCV_N_GROUPS * 2:
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
            note="too few trades",
        )
    order = sorted(range(len(returns)), key=lambda i: bar_index[i])
    rets = [returns[i] for i in order]
    nn = len(rets)
    bounds = [round(nn * g / CPCV_N_GROUPS) for g in range(CPCV_N_GROUPS + 1)]
    samples = [
        (g, rets[p], g) for g in range(CPCV_N_GROUPS) for p in range(bounds[g], bounds[g + 1])
    ]
    return ofr.cpcv_paths(samples, CPCV_N_GROUPS, CPCV_N_TEST, CPCV_EMBARGO)


def pbo_by_symbol(cands: list[dict]) -> ofr.PBOResult:
    names = sorted({d["sym"] for d in cands})
    if len(names) < 2:
        return ofr.PBOResult(float("nan"), 0, len(names), float("nan"), note="need >=2 symbols")
    bars = sorted(d["ts"] for d in cands)
    lo_b, span = bars[0], max(1, bars[-1] - bars[0])
    nb = 10
    matrix = []
    for b in range(nb):
        row = []
        for nm in names:
            vals = [
                d["adap"]
                for d in cands
                if d["sym"] == nm and min(nb - 1, int((d["ts"] - lo_b) / span * nb)) == b
            ]
            row.append(st.mean(vals) if vals else 0.0)
        matrix.append(row)
    return ofr.pbo(matrix, n_partitions=nb)


def run() -> None:
    cands = collect()
    base_net = [d["base"] for d in cands]
    adap_net = [d["adap"] for d in cands]
    diff = [d["adap"] - d["base"] for d in cands]
    bar_index = [d["ts"] for d in cands]

    print("=" * 96)
    print(
        f"ADAPTIVE-TP (1.5xATR, clamp[{TP_LO},{TP_HI}]) vs FIXED-{BASELINE_TP}% TP  "
        f"(N={len(cands)}, fee_rt={FEE_RT}%, {SYMBOLS})"
    )
    print("=" * 96)
    for label, a in (("FIXED-2% baseline", arm(base_net)), ("ADAPTIVE-TP", arm(adap_net))):
        if a.get("n"):
            print(
                f"  {label:<18} n={a['n']:>4}  EV_net={a['ev']:>+7.4f}%  win={a['win']:>5.1%}  "
                f"Sharpe={a['sharpe']:>+5.2f}  maxDD={a['max_dd']:>+7.2f}"
            )

    ev, lo, hi = block_ci(adap_net)
    dmean, dlo, dhi = block_ci(diff, paired=True)
    cpcv = cpcv_on(adap_net, bar_index)
    dsr = ofr.deflated_sharpe_ratio(adap_net, [ofr.sharpe_ratio(adap_net)], n_trials=1)
    pbo = pbo_by_symbol(cands)
    mdd = ofr.max_drawdown(adap_net)
    calmar = (sum(adap_net) / abs(mdd)) if mdd < 0 else float("inf")

    print(f"\n  adaptive net-EV 95% CI : [{lo:+.4f}, {hi:+.4f}]  clears 2xfee bar (lo>0): {lo > 0}")
    print(
        f"  paired delta (adap-base): {dmean:+.4f}%  95% CI [{dlo:+.4f}, {dhi:+.4f}]  "
        f"beats baseline: {dlo > 0}"
    )
    print(
        f"  CPCV median Sharpe={cpcv.median:+.3f}  %paths<0={cpcv.pct_paths_negative:.1%}  "
        f"paths={cpcv.n_paths}"
    )
    print(
        f"  DSR={dsr.dsr:.3f} (>=0.95)   PBO={pbo.pbo:.3f} (<0.20)   maxDD={mdd:+.2f}  Calmar={calmar:+.2f}"
    )

    gates = {
        "net-EV clears 2xfee (lo>0)": lo > 0,
        "beats baseline (delta lo>0)": dlo > 0,
        "DSR>=0.95": dsr.dsr >= 0.95,
        "PBO<0.20": (pbo.pbo == pbo.pbo) and pbo.pbo < 0.20,
        "%paths<0<25%": cpcv.pct_paths_negative < 0.25,
    }
    verdict = (
        "DEPLOY" if all(gates.values()) else ("PAPER ONLY" if (dmean > 0 and ev > 0) else "REJECT")
    )
    print(f"\n  VERDICT: {verdict}")
    for k, v in gates.items():
        print(f"    [{'PASS' if v else 'FAIL'}] {k}")


if __name__ == "__main__":
    run()
