#!/usr/bin/env python3
"""Flow-CONTINUATION gate vs flow-reversion null — pre-registered, single config.

See private/strategy/2026-05-25-flow-continuation-prereg.md. Tests whether breakout/
vol-spike entries taken when PRIOR-HOUR on-chain net-USD-flow is positive AND rising
(continuation) are net-of-fee +EV and beat the rejected entries. Opposite sign of the
on-chain-flow reversion null. The only orthogonal (non-price) feature on disk.

Leakage-clean: tape & flow are on the :00 hourly grid (verified); flow at
`entry_ts − 1h` / `− 2h` are STRICTLY-prior fully-closed hours. Label = the real exit
stack (exit_reconciliation.simulate_exit_real_close), exit params held constant (only
the flow gate varies). Default-REJECT gate.

Run: uv run python scripts/calibration/flow_continuation_validation.py [--fee 0.08]
"""

from __future__ import annotations

import argparse
import json
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
FLOW_DIR = os.path.join(_HERE, "data", "flow")
SYMBOLS = ["WIF", "PYTH", "JTO", "BOME"]
HOUR_MS = 3_600_000
STEP = 6
DEFAULT_FEE_RT = 0.08
CPCV_N_GROUPS, CPCV_N_TEST, CPCV_EMBARGO = 8, 2, 1
BLOCK, REPS, SEED = 3, 5000, 1729


def load(sym: str) -> tuple[dict, dict] | None:
    tp = os.path.join(TAPE_DIR, f"{sym}_1H.json")
    fp = os.path.join(FLOW_DIR, f"{sym}_1H_flow.json")
    if not (os.path.exists(tp) and os.path.exists(fp)):
        return None
    with open(tp) as f:
        c = base.enrich(json.load(f))
    with open(fp) as f:
        flow = {int(x["ts"]): float(x["net"]) for x in json.load(f)}
    return c, flow


def collect() -> list[dict]:
    """[{ts, sym, ret_gross, kept}] — kept = prior-hr flow positive AND rising."""
    out: list[dict] = []
    n_skip_gap = 0
    for sym in SYMBOLS:
        loaded = load(sym)
        if not loaded:
            continue
        c, flow = loaded
        n = len(c["close"])
        i = base.WARMUP
        while i < n:
            if (
                base.breakout_fires(c, i) or base.volume_spike_fires(c, i)
            ) and base.has_full_horizon(c, i):
                ets = int(c["ts"][i])
                net_prev = flow.get(ets - HOUR_MS)
                net_prev2 = flow.get(ets - 2 * HOUR_MS)
                if net_prev is None or net_prev2 is None:
                    n_skip_gap += 1
                    i += 1
                    continue
                kept = net_prev > 0 and net_prev > net_prev2  # positive AND rising
                out.append(
                    {
                        "ts": ets,
                        "sym": sym,
                        "ret_gross": recon.simulate_exit_real_close(c, i),
                        "kept": kept,
                    }
                )
                i += STEP
            else:
                i += 1
    if n_skip_gap:
        print(f"  (skipped {n_skip_gap} entries missing prior-hour flow)")
    out.sort(key=lambda d: d["ts"])
    return out


def arm(rets: list[float]) -> dict:
    if not rets:
        return {"n": 0}
    return {
        "n": len(rets),
        "ev": st.mean(rets),
        "win": sum(1 for r in rets if r > 0) / len(rets),
        "sharpe": ofr.sharpe_ratio(rets),
        "max_dd": ofr.max_drawdown(rets),
    }


def _boot_mean(xs: list[float], rng: random.Random) -> float:
    n = len(xs)
    acc, cnt = 0.0, 0
    while cnt < n:
        s = rng.randrange(n)
        for k in range(BLOCK):
            acc += xs[(s + k) % n]
            cnt += 1
            if cnt >= n:
                break
    return acc / n


def block_ci(xs: list[float]) -> tuple[float, float, float]:
    if len(xs) < 2:
        return float("nan"), float("nan"), float("nan")
    rng = random.Random(SEED)
    ms = sorted(_boot_mean(xs, rng) for _ in range(REPS))
    return st.mean(xs), ms[int(0.05 * REPS)], ms[int(0.95 * REPS)]


def block_diff_ci(a: list[float], b: list[float]) -> tuple[float, float, float, bool]:
    if len(a) < 2 or len(b) < 2:
        return float("nan"), float("nan"), float("nan"), False
    rng = random.Random(SEED)
    diffs = sorted(_boot_mean(a, rng) - _boot_mean(b, rng) for _ in range(REPS))
    lo, hi = diffs[int(0.05 * REPS)], diffs[int(0.95 * REPS)]
    return st.mean(a) - st.mean(b), lo, hi, (lo > 0 or hi < 0)


def cpcv_on(rets: list[float], bar_index: list[int]) -> ofr.CPCVResult:
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
            note="too few trades",
        )
    order = sorted(range(len(rets)), key=lambda i: bar_index[i])
    rs = [rets[i] for i in order]
    nn = len(rs)
    bounds = [round(nn * g / CPCV_N_GROUPS) for g in range(CPCV_N_GROUPS + 1)]
    samples = [(g, rs[p], g) for g in range(CPCV_N_GROUPS) for p in range(bounds[g], bounds[g + 1])]
    return ofr.cpcv_paths(samples, CPCV_N_GROUPS, CPCV_N_TEST, CPCV_EMBARGO)


def pbo_by_symbol(cands: list[dict], fee_rt: float) -> ofr.PBOResult:
    kept = [d for d in cands if d["kept"]]
    names = sorted({d["sym"] for d in kept})
    if len(names) < 2:
        return ofr.PBOResult(float("nan"), 0, len(names), float("nan"), note="need >=2 symbols")
    bars = sorted(d["ts"] for d in kept)
    lo_b, span, nb = bars[0], max(1, bars[-1] - bars[0]), 10
    matrix = []
    for b in range(nb):
        row = []
        for nm in names:
            vals = [
                d["ret_gross"] - fee_rt
                for d in kept
                if d["sym"] == nm and min(nb - 1, int((d["ts"] - lo_b) / span * nb)) == b
            ]
            row.append(st.mean(vals) if vals else 0.0)
        matrix.append(row)
    return ofr.pbo(matrix, n_partitions=nb)


def run(fee_rt: float) -> None:
    cands = collect()
    keep = [d for d in cands if d["kept"]]
    rej = [d for d in cands if not d["kept"]]
    all_net = [d["ret_gross"] - fee_rt for d in cands]
    keep_net = [d["ret_gross"] - fee_rt for d in keep]
    rej_net = [d["ret_gross"] - fee_rt for d in rej]

    print("=" * 96)
    print(
        f"FLOW-CONTINUATION GATE (prior-hr net-flow >0 AND rising)  "
        f"(N={len(cands)}, kept={len(keep)}, fee_rt={fee_rt}%, {SYMBOLS})"
    )
    print("=" * 96)
    for label, a in (
        ("ALL (baseline)", arm(all_net)),
        ("KEPT (continuation)", arm(keep_net)),
        ("REJECTED", arm(rej_net)),
    ):
        if a.get("n"):
            print(
                f"  {label:<20} n={a['n']:>4}  EV_net={a['ev']:>+7.4f}%  win={a['win']:>5.1%}  "
                f"Sharpe={a['sharpe']:>+5.2f}  maxDD={a['max_dd']:>+7.2f}"
            )

    ev, lo, hi = block_ci(keep_net)
    dmean, dlo, dhi, dclean = block_diff_ci(keep_net, rej_net)
    cpcv = cpcv_on(keep_net, [d["ts"] for d in keep])
    dsr = ofr.deflated_sharpe_ratio(keep_net, [ofr.sharpe_ratio(keep_net)], n_trials=1)
    pbo = pbo_by_symbol(cands, fee_rt)
    mdd = ofr.max_drawdown(keep_net)

    print(f"\n  KEPT net-EV 95% CI : [{lo:+.4f}, {hi:+.4f}]  clears 2xfee (lo>0): {lo > 0}")
    print(
        f"  gating delta (kept-rej): {dmean:+.4f}%  95% CI [{dlo:+.4f}, {dhi:+.4f}]  beats: {dclean and dmean > 0}"
    )
    print(
        f"  CPCV median Sharpe={cpcv.median:+.3f}  %paths<0={cpcv.pct_paths_negative:.1%}  paths={cpcv.n_paths}"
    )
    print(f"  DSR={dsr.dsr:.3f} (>=0.95)   PBO={pbo.pbo:.3f} (<0.20)   maxDD={mdd:+.2f}")

    gates = {
        "KEPT clears 2xfee (lo>0)": lo > 0,
        "beats rejected (delta lo>0)": dclean and dmean > 0,
        "DSR>=0.95": dsr.dsr >= 0.95,
        "PBO<0.20": (pbo.pbo == pbo.pbo) and pbo.pbo < 0.20,
        "%paths<0<25%": cpcv.pct_paths_negative < 0.25,
    }
    verdict = (
        "DEPLOY" if all(gates.values()) else ("PAPER ONLY" if (ev > 0 and dmean > 0) else "REJECT")
    )
    print(f"\n  VERDICT: {verdict}")
    for k, v in gates.items():
        print(f"    [{'PASS' if v else 'FAIL'}] {k}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fee", type=float, default=DEFAULT_FEE_RT, help="round-trip fee %")
    a = ap.parse_args()
    run(a.fee)
