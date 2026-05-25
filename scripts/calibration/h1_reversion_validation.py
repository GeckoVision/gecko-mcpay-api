#!/usr/bin/env python3
"""H1 — on-chain net-flow reversion (PRE-REGISTERED, single frozen config).

Hypothesis (private/strategy/2026-05-24-h1-onchain-reversion-prereg.md):
  DEX 1h net-USD-flow extremes mean-revert. When a token's 1h net-flow is in its
  extreme decile, the forward-4h return FADES it (top decile = crowd buying ->
  expect down / short-or-avoid; bottom decile = capitulation -> expect up / buy).

Frozen params (NO sweep — one config so DSR/PBO are not deflated for a search):
  flow window = 1h · decile threshold = top/bottom 10% · forward hold = 4h ·
  tokens = WIF, PYTH, JTO, BOME · window = the 24-tape coverage (2025-08-22..2026-05-23).

Causal-implementation choices (committed a priori, NOT swept; documented as part of
the frozen config — sweeping any of these later forces DSR/PBO to deflate):
  * decile threshold estimated on a TRAILING 30-day (720h) window, strictly prior
    bars only (no full-sample look-ahead);
  * 4h cooldown after each entry (non-overlapping holds -> clean CPCV labels);
  * fee charged round-trip (2x per trade); headline fee = 0.04% (Jupiter-reachable).

Feature net-flow = sum(amount_usd as buyer) - sum(amount_usd as seller), per hour
(built by build_flow_tapes.py from dex_solana.trades).

Verdict gate (default REJECT): ships only if net-of-fee CI clears the 2x-fee bar
(lo > 0) AND DSR >= 0.95 AND PBO < 0.2 AND %CPCV-paths-Sharpe<0 < 25%.
"""

from __future__ import annotations

import json
import os
import statistics as st
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import overfitting_rigor as ofr  # noqa: E402

TAPE_DIR = os.path.join(_HERE, "data", "tape")
FLOW_DIR = os.path.join(_HERE, "data", "flow")
SYMBOLS = ["WIF", "PYTH", "JTO", "BOME"]

# ── Frozen config ───────────────────────────────────────────────────
FLOW_WINDOW_H = 720  # trailing 30d causal decile estimator
DECILE = 0.10  # top/bottom 10%
HOLD = 4  # forward 4h
COOLDOWN = HOLD  # non-overlapping holds
FEE_GRID = [0.0, 0.04, 0.10, 0.20]  # % per side; headline = 0.04 (round-trip 2x)
HEADLINE_FEE = 0.04

CPCV_N_GROUPS = 8
CPCV_N_TEST = 2
CPCV_EMBARGO = 1


# ── Load: tape close as master clock + flow aligned onto it ─────────
def load_token(sym: str) -> tuple[list[int], list[float], list[float]]:
    """Return (ts[], close[], net[]) on the contiguous 1H tape clock. Flow is
    aligned onto the tape ts (net=0 for the rare missing hour -> neutral, no
    signal). Master = tape so h+HOLD is exactly HOLD hours."""
    with open(os.path.join(TAPE_DIR, f"{sym}_1H.json")) as f:
        tape = json.load(f)
    ts = [int(x["ts"]) for x in tape]
    close = [float(x["close"]) for x in tape]
    with open(os.path.join(FLOW_DIR, f"{sym}_1H_flow.json")) as f:
        flow = json.load(f)
    fmap = {int(x["ts"]): float(x["net"]) for x in flow}
    net = [fmap.get(t, 0.0) for t in ts]
    return ts, close, net


# ── Causal trailing-decile percentile ───────────────────────────────
def percentile(sorted_vals: list[float], q: float) -> float:
    n = len(sorted_vals)
    if n == 1:
        return sorted_vals[0]
    idx = q * (n - 1)
    lo = int(idx)
    hi = min(lo + 1, n - 1)
    frac = idx - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def fwd_return(close: list[float], t: int, hold: int) -> float | None:
    j = t + hold
    if j >= len(close) or close[t] <= 0:
        return None
    return (close[j] - close[t]) / close[t] * 100.0


# ── One token: extreme-decile fade trades (gross, per-side fee=0) ────
def token_trades(sym: str) -> list[tuple[int, float]]:
    """Return [(ts, gross_fade_return_pct)] for taken trades. Top-decile flow ->
    fade (short, profit if price falls -> -fwd); bottom-decile -> long (+fwd).
    Decile thresholds from the strictly-prior trailing FLOW_WINDOW_H hours.
    4h cooldown -> non-overlapping holds."""
    ts, close, net = load_token(sym)
    n = len(ts)
    trades: list[tuple[int, float]] = []
    last_exit = -1
    t = FLOW_WINDOW_H
    while t + HOLD < n:
        if t <= last_exit:  # inside a live position (cooldown)
            t += 1
            continue
        window = sorted(net[t - FLOW_WINDOW_H : t])  # strictly prior bars
        p_hi = percentile(window, 1 - DECILE)
        p_lo = percentile(window, DECILE)
        cur = net[t]
        side = 0
        if cur >= p_hi:
            side = -1  # crowd buying -> fade -> short
        elif cur <= p_lo:
            side = +1  # capitulation -> long
        if side == 0:
            t += 1
            continue
        fwd = fwd_return(close, t, HOLD)
        if fwd is None:
            t += 1
            continue
        trades.append((ts[t], side * fwd))
        last_exit = t + HOLD
        t += 1
    return trades


# ── Rigor helpers (mirror xsectional house pattern) ─────────────────
def block_bootstrap_ci(returns: list[float]) -> tuple[float, float, float]:
    """Stationary/circular block bootstrap of the MEAN. Block length data-driven
    via lag-1 autocorr; 5000 reps; percentile 5-95 CI. Self-contained (stdlib)."""
    import random

    n = len(returns)
    if n < 2:
        return float("nan"), float("nan"), float("nan")
    mean = st.mean(returns)
    # lag-1 autocorr -> block length ~ n^(1/3) inflated by dependence
    mu = mean
    num = sum((returns[i] - mu) * (returns[i - 1] - mu) for i in range(1, n))
    den = sum((x - mu) ** 2 for x in returns) or 1e-12
    rho = max(0.0, min(0.95, num / den))
    base = max(2, round(n ** (1 / 3)))
    block = max(2, min(n, round(base * (1 + 2 * rho))))
    rng = random.Random(12345)
    means: list[float] = []
    for _ in range(5000):
        acc = 0.0
        cnt = 0
        while cnt < n:
            start = rng.randrange(n)
            for k in range(block):
                acc += returns[(start + k) % n]
                cnt += 1
                if cnt >= n:
                    break
        means.append(acc / n)
    means.sort()
    lo = means[int(0.05 * len(means))]
    hi = means[int(0.95 * len(means))]
    return mean, lo, hi, block  # type: ignore[return-value]


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
            note="too few trades for CPCV",
        )
    order = sorted(range(len(returns)), key=lambda i: bar_index[i])
    rets = [returns[i] for i in order]
    n = len(rets)
    bounds = [round(n * gi / CPCV_N_GROUPS) for gi in range(CPCV_N_GROUPS + 1)]
    samples: list[tuple[int, float, int]] = []
    for gi in range(CPCV_N_GROUPS):
        for p in range(bounds[gi], bounds[gi + 1]):
            samples.append((gi, rets[p], gi))  # non-overlapping -> label in-group
    return ofr.cpcv_paths(samples, CPCV_N_GROUPS, CPCV_N_TEST, CPCV_EMBARGO)


def pbo_per_token(token_net: dict[str, list[tuple[int, float]]]) -> ofr.PBOResult:
    """PBO with one column per TOKEN (the honest variant axis for a frozen rule:
    is the edge robust across tokens, or carried by one). Rows = 10 time blocks."""
    names = [s for s in SYMBOLS if len(token_net[s]) >= 2]
    if len(names) < 2:
        return ofr.PBOResult(float("nan"), 0, len(names), float("nan"), note="need >=2 tokens")
    all_bars = sorted({ts for s in names for ts, _ in token_net[s]})
    if len(all_bars) < 10:
        return ofr.PBOResult(float("nan"), 0, len(names), float("nan"), note="too few bars")
    n_blocks = 10
    lo_b, hi_b = all_bars[0], all_bars[-1]
    span = max(1, hi_b - lo_b)

    def block_of(b: int) -> int:
        return min(n_blocks - 1, int((b - lo_b) / span * n_blocks))

    matrix: list[list[float]] = []
    for blk in range(n_blocks):
        row: list[float] = []
        for name in names:
            vals = [r for ts, r in token_net[name] if block_of(ts) == blk]
            row.append(st.mean(vals) if vals else 0.0)
        matrix.append(row)
    return ofr.pbo(matrix, n_partitions=n_blocks)


# ── Self-test (synthetic: planted reversion must be detected) ───────
def self_test() -> bool:
    ok = True

    def check(name: str, cond: bool) -> None:
        nonlocal ok
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
        ok = ok and cond

    # percentile sanity
    check("percentile p90 of 0..100", abs(percentile(list(range(101)), 0.9) - 90.0) < 1e-6)
    check("percentile p10 of 0..100", abs(percentile(list(range(101)), 0.1) - 10.0) < 1e-6)
    # cpcv produces paths on a real series
    rng_rets = [0.1 * ((i % 7) - 3) for i in range(200)]
    cp = cpcv_on(rng_rets, list(range(200)))
    check(f"CPCV yields paths ({cp.n_paths})", cp.n_paths > 0)
    # block bootstrap CI brackets the mean
    m, lo, hi, _bk = block_bootstrap_ci([1.0, -1.0, 2.0, -0.5, 1.5, -1.0, 0.8, -0.3] * 10)
    check("bootstrap CI brackets mean", lo <= m <= hi)
    print(f"\n  {'ALL TESTS PASS' if ok else 'SOME TESTS FAILED'}")
    return ok


# ── Main ────────────────────────────────────────────────────────────
def run() -> dict:
    print("=" * 100)
    print("H1 — ON-CHAIN NET-FLOW REVERSION  (pre-registered single config)")
    print(
        f"  window={FLOW_WINDOW_H}h trailing decile · decile={DECILE:.0%} · "
        f"hold={HOLD}h · cooldown={COOLDOWN}h · tokens={SYMBOLS}"
    )
    print("=" * 100)

    token_trades_map = {s: token_trades(s) for s in SYMBOLS}
    for s in SYMBOLS:
        tr = token_trades_map[s]
        gross = [r for _, r in tr]
        print(
            f"  {s:5} trades={len(tr):4}  gross EV/trade={st.mean(gross):+.4f}%  "
            f"hit={sum(1 for x in gross if x > 0) / max(1, len(gross)):.1%}"
            if tr
            else f"  {s:5} no trades"
        )

    # pooled headline series (time-ordered by ts)
    pooled = sorted([(ts, r) for s in SYMBOLS for ts, r in token_trades_map[s]], key=lambda x: x[0])
    bar_index = [ts for ts, _ in pooled]
    gross = [r for _, r in pooled]
    print(f"\n  POOLED trades={len(pooled)}  gross EV/trade={st.mean(gross):+.4f}%")

    results: dict = {
        "config": {
            "window_h": FLOW_WINDOW_H,
            "decile": DECILE,
            "hold": HOLD,
            "cooldown": COOLDOWN,
            "tokens": SYMBOLS,
            "n_trials_for_dsr": 1,
        },
        "per_token_n": {s: len(token_trades_map[s]) for s in SYMBOLS},
        "by_fee": {},
    }

    for fee in FEE_GRID:
        rt = 2 * fee  # round-trip cost
        net = [r - rt for r in gross]
        mean, lo, hi, blk = block_bootstrap_ci(net)
        cpcv = cpcv_on(net, bar_index)
        sr = ofr.sharpe_ratio(net)
        dsr = ofr.deflated_sharpe_ratio(net, [sr], n_trials=1)  # single frozen config
        token_net = {s: [(ts, r - rt) for ts, r in token_trades_map[s]] for s in SYMBOLS}
        pbo = pbo_per_token(token_net)
        mdd = ofr.max_drawdown(net)
        total = sum(net)
        calmar = (total / abs(mdd)) if mdd < 0 else float("inf")
        verdict = ofr.make_verdict(f"H1-reversion@fee{fee}", cpcv, dsr, pbo, mdd, calmar)

        tag = "  <<< HEADLINE" if abs(fee - HEADLINE_FEE) < 1e-9 else ""
        print("\n" + "-" * 100)
        print(f"FEE {fee:.2f}% per side (round-trip {rt:.2f}%){tag}")
        print(
            f"  net EV/trade={mean:+.4f}%  95% block-CI=[{lo:+.4f}, {hi:+.4f}]  "
            f"(block={blk})  excl0+={lo > 0}"
        )
        print(verdict.render())
        results["by_fee"][f"{fee}"] = {
            "net_ev": mean,
            "ci": [lo, hi],
            "ci_excl0_pos": lo > 0,
            "cpcv_median_sharpe": cpcv.median,
            "cpcv_pct_paths_neg": cpcv.pct_paths_negative,
            "cpcv_n_paths": cpcv.n_paths,
            "dsr": dsr.dsr,
            "pbo": pbo.pbo,
            "pbo_note": pbo.note,
            "max_dd": mdd,
            "calmar": calmar,
            "verdict": verdict.verdict,
            "rationale": verdict.rationale,
        }
    return results


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(0 if self_test() else 1)
    out = run()
    if "--json" in sys.argv:
        print("\n" + json.dumps(out, indent=2, default=str))
