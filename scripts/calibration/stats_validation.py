#!/usr/bin/env python3
"""Phase V.1 — shared statistical-validation primitives (quant-analyst, 2026-05-23).

WHY THIS MODULE EXISTS
  The calibration scripts (exit_reconciliation, fee_sensitivity_gating_delta,
  structure_gating_delta) each carry a near-identical block-bootstrap + an IID
  bootstrap kept only for the "how much wider" side-by-side. Phase V.1 of the
  market-analysis roadmap (docs/strategy/2026-05-22-market-analysis-roadmap.md)
  says to REPLACE the IID bootstrap as the canonical CI, because trade returns
  are serially autocorrelated within a symbol and the IID bootstrap therefore
  UNDERSTATES the variance (its N_eff equals N; the real N_eff is much smaller).

  This module is the SINGLE importable home for the corrected primitives so the
  other scripts CAN migrate to it later. It deliberately does NOT migrate them
  now (out of scope) — it just gives them somewhere to migrate TO.

WHAT'S HERE
  * block_bootstrap_ci  — moving/circular block bootstrap of the mean over a set
    of per-symbol ordered series. Returns mean, 95% CI, and an N_eff estimate.
    Block length is chosen from the data's autocorrelation (Politis–White-style
    rule, floored at the cube-root heuristic) — documented in the function.
  * iid_bootstrap_ci    — the OLD method, kept ONLY so callers/tests can show the
    block CI is materially wider on autocorrelated data. NOT the canonical CI.
  * effective_n / variance_inflation — Bartlett-weighted VIF → N_eff = N / VIF.
  * bh_fdr              — Benjamini–Hochberg false-discovery-rate control.

No I/O, no network, no live-bot state. Pure functions + unit tests (run with
`python3 scripts/calibration/stats_validation.py --self-test`, or via pytest:
`uv run pytest scripts/calibration/test_stats_validation.py -q`).
"""

from __future__ import annotations

import math
import random
import statistics as st

# Shared bootstrap config (kept consistent with the existing harness so a future
# migration is a drop-in; callers may override).
N_BOOTSTRAP = 5000
RNG_SEED = 1729


# ── Autocorrelation + effective-N ───────────────────────────────────
def autocorr(x: list[float], lag: int) -> float:
    """Sample autocorrelation of a single series at `lag` (biased estimator,
    var in the denominator → consistent with the existing harness)."""
    n = len(x)
    if n <= lag + 2:
        return 0.0
    m = st.mean(x)
    var = sum((v - m) ** 2 for v in x)
    if var == 0:
        return 0.0
    return sum((x[t] - m) * (x[t - lag] - m) for t in range(lag, n)) / var


def variance_inflation(series_list: list[list[float]], k_max: int = 4) -> float:
    """Bartlett-weighted variance-inflation factor (VIF) from within-symbol
    autocorrelation, averaged across symbols (n-weighted):

        VIF = 1 + 2 * Σ_{k=1..K} (1 − k/(K+1)) · ρ_k

    N_eff = N / VIF. For an IID series ρ_k ≈ 0 → VIF ≈ 1 → N_eff ≈ N. For an
    AR(1) with φ>0 the positive ρ_k inflate VIF → N_eff < N. Floored at 1.0 so
    N_eff never exceeds N (negative autocorrelation is not credited as extra
    information here — a conservative choice for a skeptic harness)."""
    vif = 1.0
    for k in range(1, k_max + 1):
        num = den = 0.0
        for s in series_list:
            if len(s) > k + 2:
                num += autocorr(s, k) * len(s)
                den += len(s)
        rho = num / den if den else 0.0
        vif += 2 * (1 - k / (k_max + 1)) * rho
    return max(vif, 1.0)


def effective_n(series_list: list[list[float]], k_max: int = 4) -> float:
    """N_eff = N / VIF over a set of per-symbol ordered series."""
    n = sum(len(s) for s in series_list)
    if n == 0:
        return 0.0
    return n / variance_inflation(series_list, k_max=k_max)


# ── Block-length selection ──────────────────────────────────────────
def choose_block_length(series_list: list[list[float]]) -> int:
    """Data-driven block length for the block bootstrap.

    Rule (documented choice): we take the MAX of two heuristics and clamp:
      * cube-root rule  b ≈ N^(1/3)  (the textbook default growth rate),
      * an autocorrelation-aware bump: the first lag at which the n-weighted
        autocorrelation drops below 1/e (≈0.37), a cheap Politis–White-flavoured
        proxy for the dependence length (NOT the full spectral PW estimator —
        documented as an approximation).
    Clamped to [2, max(2, min_series_len)] so a block always fits the shortest
    usable series and is never degenerate (block=1 would be the IID bootstrap).

    Returns at least 2.
    """
    usable = [s for s in series_list if len(s) >= 2]
    if not usable:
        return 2
    n = sum(len(s) for s in usable)
    cube = max(2, round(n ** (1.0 / 3.0)))
    # autocorrelation length: first lag where n-weighted |ρ| < 1/e
    thresh = 1.0 / math.e
    ac_len = 1
    for k in range(1, 11):
        num = den = 0.0
        for s in usable:
            if len(s) > k + 2:
                num += autocorr(s, k) * len(s)
                den += len(s)
        rho = (num / den) if den else 0.0
        if abs(rho) < thresh:
            ac_len = k
            break
        ac_len = k + 1
    shortest = min(len(s) for s in usable)
    return max(2, min(max(cube, ac_len), shortest))


# ── Block bootstrap (the canonical CI) ──────────────────────────────
def block_bootstrap_ci(
    series_list: list[list[float]],
    block: int | None = None,
    n_boot: int = N_BOOTSTRAP,
    alpha: float = 0.05,
    seed: int = RNG_SEED,
) -> tuple[float, float, float, float, int]:
    """Moving-block bootstrap of the MEAN over a set of per-symbol ordered series.

    Each resample draws overlapping blocks of length `block` (random start within
    a symbol's series, symbols chosen proportional to length) until it reaches the
    original total count, then truncates. Preserves within-symbol serial
    dependence, so the resulting CI WIDENS relative to IID when the data is
    autocorrelated — that widening is the entire point of V.1.

    `block=None` → choose_block_length(series_list) (data-driven).

    Returns (mean, ci_lo, ci_hi, n_eff, block_used).
    """
    flat = [v for s in series_list for v in s]
    if not flat:
        return (float("nan"), float("nan"), float("nan"), 0.0, 0)
    point = st.mean(flat)
    n_eff = effective_n(series_list)
    if len(flat) == 1:
        return (point, point, point, n_eff, 1)
    b = block if block is not None else choose_block_length(series_list)
    usable = [s for s in series_list if len(s) >= 1]
    weights = [len(s) for s in usable]
    total = len(flat)
    rng = random.Random(seed)
    boots: list[float] = []
    for _ in range(n_boot):
        sample: list[float] = []
        while len(sample) < total:
            s = rng.choices(usable, weights=weights, k=1)[0]
            bb = min(b, len(s))
            start = rng.randrange(0, len(s) - bb + 1)
            sample.extend(s[start : start + bb])
        boots.append(st.mean(sample[:total]))
    boots.sort()
    lo = boots[int((alpha / 2) * n_boot)]
    hi = boots[int((1 - alpha / 2) * n_boot)]
    return (point, lo, hi, n_eff, b)


def iid_bootstrap_ci(
    vals: list[float],
    n_boot: int = N_BOOTSTRAP,
    alpha: float = 0.05,
    seed: int = RNG_SEED,
) -> tuple[float, float, float]:
    """IID bootstrap of the mean (the OLD method). Kept ONLY for the side-by-side
    'block CI is wider' check — NOT the canonical CI. Assumes exchangeable rows,
    which is FALSE for serially correlated trade returns → it understates width."""
    if not vals:
        return (float("nan"), float("nan"), float("nan"))
    point = st.mean(vals)
    if len(vals) == 1:
        return (point, point, point)
    rng = random.Random(seed)
    m = len(vals)
    boots = [st.mean([vals[rng.randrange(m)] for _ in range(m)]) for _ in range(n_boot)]
    boots.sort()
    return (point, boots[int((alpha / 2) * n_boot)], boots[int((1 - alpha / 2) * n_boot)])


# ── Benjamini–Hochberg FDR ──────────────────────────────────────────
def bh_fdr(pvalues: list[float], alpha: float = 0.05) -> dict:
    """Benjamini–Hochberg step-up FDR control.

    Sort p-values ascending p_(1) ≤ … ≤ p_(m); find the largest rank k with
    p_(k) ≤ (k/m)·alpha; reject all hypotheses with rank ≤ k. Controls the
    expected false-discovery proportion at `alpha` under independence / PRDS.

    Returns:
      rejected      — set of ORIGINAL indices rejected (discoveries),
      threshold     — the largest p-value that passes (the BH cutoff), or 0.0
                      if nothing is rejected,
      adjusted      — BH-adjusted p-values (q-values) in ORIGINAL order,
      k             — number of rejections.
    """
    m = len(pvalues)
    if m == 0:
        return {"rejected": set(), "threshold": 0.0, "adjusted": [], "k": 0}
    order = sorted(range(m), key=lambda i: pvalues[i])
    sorted_p = [pvalues[i] for i in order]
    # largest k where p_(k) <= (k/m)*alpha   (k is 1-based rank)
    k_max = 0
    for rank in range(1, m + 1):
        if sorted_p[rank - 1] <= (rank / m) * alpha:
            k_max = rank
    rejected_sorted_ranks = set(range(1, k_max + 1))
    rejected = {order[r - 1] for r in rejected_sorted_ranks}
    threshold = sorted_p[k_max - 1] if k_max > 0 else 0.0
    # BH-adjusted q-values: q_(i) = min_{j>=i} ( m/j * p_(j) ), monotone, capped 1
    adj_sorted = [0.0] * m
    running_min = 1.0
    for rank in range(m, 0, -1):
        q = min(1.0, (m / rank) * sorted_p[rank - 1])
        running_min = min(running_min, q)
        adj_sorted[rank - 1] = running_min
    adjusted = [0.0] * m
    for sorted_pos, orig_idx in enumerate(order):
        adjusted[orig_idx] = adj_sorted[sorted_pos]
    return {
        "rejected": rejected,
        "threshold": threshold,
        "adjusted": adjusted,
        "k": k_max,
    }


# ── Synthetic-series generators (for tests / demos) ─────────────────
def ar1_series(n: int, phi: float, sigma: float = 1.0, mean: float = 0.0, seed: int = 0):
    """AR(1): x_t = mean + phi*(x_{t-1}-mean) + eps. Strong positive phi → strong
    serial dependence → the case where block CI must beat IID CI."""
    rng = random.Random(seed)
    out: list[float] = []
    prev = mean
    for _ in range(n):
        eps = rng.gauss(0.0, sigma)
        cur = mean + phi * (prev - mean) + eps
        out.append(cur)
        prev = cur
    return out


def iid_series(n: int, sigma: float = 1.0, mean: float = 0.0, seed: int = 0):
    rng = random.Random(seed)
    return [rng.gauss(mean, sigma) for _ in range(n)]


# ── Self-test ────────────────────────────────────────────────────────
def self_test() -> bool:
    ok = True

    def check(name: str, cond: bool) -> None:
        nonlocal ok
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
        ok = ok and cond

    # T1 — BH-FDR against a known textbook vector (Benjamini-Hochberg 1995 style).
    pv = [0.001, 0.008, 0.039, 0.041, 0.042, 0.06, 0.074, 0.205, 0.212, 0.216]
    res = bh_fdr(pv, alpha=0.05)
    # By hand: m=10; (k/m)*0.05 thresholds = .005,.010,.015,.020,.025,.030,.035,...
    # p_(1)=.001<=.005 ✓ ; p_(2)=.008<=.010 ✓ ; p_(3)=.039<=.015 ✗ ... none after
    # pass until... largest k with p_(k)<=(k/m)*alpha is k=2.
    check("T1a BH rejects exactly k=2", res["k"] == 2)
    check("T1b BH rejects indices {0,1}", res["rejected"] == {0, 1})
    check("T1c BH threshold = 0.008", abs(res["threshold"] - 0.008) < 1e-9)
    # adjusted q for the smallest p = 10/1*0.001 = 0.01 (after monotone min)
    check("T1d adjusted q[0] ~ 0.01", abs(res["adjusted"][0] - 0.01) < 1e-9)
    # all-null guard
    check("T1e empty -> no rejections", bh_fdr([], 0.05)["k"] == 0)

    # T2 — block CI ≈ IID CI on an IID series (no autocorrelation to preserve).
    iid = iid_series(400, sigma=1.0, mean=0.0, seed=11)
    _p_i, ilo, ihi = iid_bootstrap_ci(iid)
    _p_b, blo, bhi, neff_iid, _bk = block_bootstrap_ci([iid])
    iid_w = ihi - ilo
    blk_w_iid = bhi - blo
    ratio_iid = blk_w_iid / iid_w
    check(
        f"T2a IID: block/IID width ratio ~1 (got {ratio_iid:.2f})",
        0.80 <= ratio_iid <= 1.25,
    )
    check(
        f"T2b IID: N_eff ~ N (got {neff_iid:.0f} of {len(iid)})",
        neff_iid >= 0.80 * len(iid),
    )

    # T3 — THE DISCRIMINATING PROPERTY: on AR(1) phi=0.7 the block CI is
    # MATERIALLY WIDER than the IID CI, and N_eff << N. This is the whole reason
    # V.1 replaces the IID bootstrap.
    ar = ar1_series(400, phi=0.7, sigma=1.0, mean=0.0, seed=7)
    _pa_i, alo, ahi = iid_bootstrap_ci(ar)
    _pa_b, ablo, abhi, neff_ar, bk_ar = block_bootstrap_ci([ar])
    iid_w_ar = ahi - alo
    blk_w_ar = abhi - ablo
    ratio_ar = blk_w_ar / iid_w_ar
    print(
        f"      AR(1) phi=0.7: IID width={iid_w_ar:.3f}  block width={blk_w_ar:.3f}  "
        f"ratio={ratio_ar:.2f}x  N_eff={neff_ar:.0f}/{len(ar)}  block_len={bk_ar}"
    )
    check(
        f"T3a AR(1): block CI MATERIALLY wider than IID (ratio {ratio_ar:.2f} > 1.3)",
        ratio_ar > 1.3,
    )
    check(
        f"T3b AR(1): N_eff << N (got {neff_ar:.0f}, need < {0.6 * len(ar):.0f})",
        neff_ar < 0.6 * len(ar),
    )
    check(
        f"T3c AR(1) widening ({ratio_ar:.2f}x) > IID widening ({ratio_iid:.2f}x)",
        ratio_ar > ratio_iid + 0.2,
    )

    # T4 — choose_block_length is data-driven and >= 2.
    bl_iid = choose_block_length([iid])
    bl_ar = choose_block_length([ar])
    check("T4a block length >= 2 on both", bl_iid >= 2 and bl_ar >= 2)
    check(
        f"T4b AR(1) block length >= IID block length ({bl_ar} >= {bl_iid})",
        bl_ar >= bl_iid,
    )

    print(f"\n  {'ALL TESTS PASS' if ok else 'SOME TESTS FAILED'}")
    return ok


if __name__ == "__main__":
    import sys

    sys.exit(0 if self_test() else 1)
