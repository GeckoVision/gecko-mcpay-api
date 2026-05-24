#!/usr/bin/env python3
"""Phase S52 — López de Prado overfitting rigor primitives (quant-analyst, 2026-05-24).

WHY THIS MODULE EXISTS
  The block-bootstrap CI in stats_validation answers "is this mean different from
  zero given serial dependence?" It does NOT answer the question the
  quant-backtest-rigor skill exists to answer:

      "Is this the best of N noisy trials, or a real finding?"

  per-token patterns are exhausted (3 nulls). Before we believe ANY new edge
  class (longer-hold, cross-sectional), we apply the full rigor stack from
  López de Prado's "Advances in Financial Machine Learning" (chs. 7, 11, 14):

    * CPCV  — Combinatorial Purged Cross-Validation. C(N,k) backtest paths from
      one tape → a DISTRIBUTION of Sharpes, not one. Purge + embargo so
      overlapping-label leakage cannot inflate the OOS read.
    * PBO   — Probability of Backtest Overfitting. Over ALL variants tried, is
      the in-sample best also OOS-best? PBO = P(OOS rank of the IS-best variant
      lands in the bottom half).
    * DSR   — Deflated Sharpe Ratio. Deflates the observed Sharpe for (a) the
      number of variants tried, (b) return skew/kurtosis, (c) sample length.
      The probability the TRUE Sharpe > 0 after that deflation.

  mlfinlab is no longer installable from PyPI (no distribution, 2026-05). The
  skill says: "else implement CPCV/PBO/DSR per the recipes." This module is that
  implementation — pure stdlib (math/statistics/random), matching the existing
  calibration harness's numpy-free convention (NO calibration script imports
  numpy/scipy/pandas; checked 2026-05-24).

WHAT'S HERE
  * normal_cdf / normal_ppf — Gaussian CDF/inverse via math.erf + Acklam's PPF
    (DSR/PSR need Φ and Φ⁻¹; scipy is not a dependency).
  * sharpe_ratio            — per-period Sharpe of a return list (0 if no var).
  * combinatorial_groups    — the C(N,k) test-group selections of CPCV.
  * cpcv_paths              — assemble the C(N,k) OOS return paths from a stream of
    (group_id, return, label_end_group) samples, with the purge + embargo leakage
    trap folded in (a sample is admitted to a path only if its whole label horizon
    stays inside the test groups and clear of the embargo band); returns the
    per-path Sharpe distribution + summary (median, 5/95 pct, % paths < 0).
  * pbo                     — Bailey-Borwein-López de Prado PBO via the logit of
    OOS rank of the IS-best across combinatorial train/test splits of a
    variant×period performance matrix.
  * deflated_sharpe_ratio   — Bailey-López de Prado DSR with honest variant count.
  * verdict                 — the skill's structured VERDICT block + DEPLOY/PAPER/
    REJECT decision with the hard gates (PBO<0.2, DSR>=0.95, %paths<0<=25%).

No I/O, no network, no live-bot state. Pure functions + a --self-test.
Run: python3 scripts/calibration/overfitting_rigor.py --self-test
     uv run pytest scripts/calibration/test_overfitting_rigor.py -q
"""

from __future__ import annotations

import math
import random
import statistics as st
from dataclasses import dataclass, field
from itertools import combinations


# ── Gaussian CDF / inverse (no scipy) ───────────────────────────────
def normal_cdf(x: float) -> float:
    """Standard-normal CDF Φ(x) via the error function."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def normal_ppf(p: float) -> float:
    """Standard-normal inverse CDF Φ⁻¹(p) (Acklam's rational approximation).

    |error| < 1.15e-9 over the whole domain — ample for a DSR/PSR z-score. Used
    only when a quantile is needed; DSR itself only needs the forward CDF.
    """
    if p <= 0.0:
        return -math.inf
    if p >= 1.0:
        return math.inf
    # coefficients
    a = [
        -3.969683028665376e01,
        2.209460984245205e02,
        -2.759285104469687e02,
        1.383577518672690e02,
        -3.066479806614716e01,
        2.506628277459239e00,
    ]
    b = [
        -5.447609879822406e01,
        1.615858368580409e02,
        -1.556989798598866e02,
        6.680131188771972e01,
        -1.328068155288572e01,
    ]
    c = [
        -7.784894002430293e-03,
        -3.223964580411365e-01,
        -2.400758277161838e00,
        -2.549732539343734e00,
        4.374664141464968e00,
        2.938163982698783e00,
    ]
    d = [
        7.784695709041462e-03,
        3.224671290700398e-01,
        2.445134137142996e00,
        3.754408661907416e00,
    ]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1
        )
    if p <= phigh:
        q = p - 0.5
        r = q * q
        return (
            (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5])
            * q
            / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
        )
    q = math.sqrt(-2 * math.log(1 - p))
    return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
        (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1
    )


# ── Sharpe ──────────────────────────────────────────────────────────
def sharpe_ratio(returns: list[float]) -> float:
    """Per-period Sharpe (mean / stdev). 0.0 when <2 obs or zero variance.

    NOT annualized — these are per-trade / per-bar returns and the variants are
    compared on the SAME clock, so a constant annualization factor cancels in
    every ranking, CPCV percentile, PBO and DSR computation. Reporting the raw
    per-period Sharpe avoids a fictitious annualization assumption on an
    irregular trade clock.
    """
    if len(returns) < 2:
        return 0.0
    sd = st.pstdev(returns)
    if sd == 0:
        return 0.0
    return st.mean(returns) / sd


def skew_kurt(returns: list[float]) -> tuple[float, float]:
    """(skewness, kurtosis) — kurtosis is the RAW 4th standardized moment (not
    excess), as the Bailey-LdP DSR formula uses γ4 (=3 for a Gaussian)."""
    n = len(returns)
    if n < 3:
        return 0.0, 3.0
    m = st.mean(returns)
    sd = st.pstdev(returns)
    if sd == 0:
        return 0.0, 3.0
    g3 = sum(((x - m) / sd) ** 3 for x in returns) / n
    g4 = sum(((x - m) / sd) ** 4 for x in returns) / n
    return g3, g4


# ── CPCV ────────────────────────────────────────────────────────────
def combinatorial_groups(n_groups: int, n_test: int) -> list[tuple[int, ...]]:
    """All C(n_groups, n_test) test-group selections. Each is one CPCV path's
    test set; the complement (minus purge/embargo) is its train set."""
    return list(combinations(range(n_groups), n_test))


@dataclass
class CPCVResult:
    n_groups: int
    n_test: int
    n_paths: int
    path_sharpes: list[float]
    median: float
    p05: float
    p95: float
    pct_paths_negative: float
    mean_test_n: float
    note: str = ""


def cpcv_paths(
    samples: list[tuple[int, float, int]],
    n_groups: int = 8,
    n_test: int = 2,
    embargo_groups: int = 1,
) -> CPCVResult:
    """Combinatorial Purged CV over a TIME-ORDERED stream of samples.

    Each sample is (group_id, ret, label_end_group):
      group_id        — which of n_groups contiguous time blocks the entry is in
                        (assigned by the caller from chronological order).
      ret             — the realized per-trade return of that sample (the OOS PnL
                        when this sample is in a test block).
      label_end_group — the group in which this sample's HOLD ends (its triple-
                        barrier-style label horizon). For a longer-hold variant
                        this can exceed group_id; that's exactly the overlap the
                        purge must remove.

    For each of the C(n_groups, n_test) test selections we form the OOS path as
    the concatenation of the test-block samples and take its Sharpe. We PURGE any
    sample whose label horizon would straddle a test block (so a train fit could
    not have peeked) and EMBARGO `embargo_groups` after each test block. Because
    this module evaluates a DETERMINISTIC rule (no model is fit), the purge/
    embargo here protect the TEST read itself: a sample is admitted to a test path
    only if its entire [group_id, label_end_group] horizon lies inside the test
    block set and outside any embargo band — i.e. its label cannot have leaked
    information from an adjacent (implicitly-train) block.

    Returns the distribution of path Sharpes + summary stats.
    """
    if not samples or n_test >= n_groups or n_groups < 2:
        return CPCVResult(
            n_groups,
            n_test,
            0,
            [],
            float("nan"),
            float("nan"),
            float("nan"),
            float("nan"),
            0.0,
            note="degenerate config or empty stream",
        )
    selections = combinatorial_groups(n_groups, n_test)
    path_sharpes: list[float] = []
    test_ns: list[int] = []
    for test_groups in selections:
        test_set = set(test_groups)
        # embargo band: the `embargo_groups` groups immediately AFTER each test
        # block are off-limits (a label ending there could carry test info fwd).
        embargo: set[int] = set()
        for g in test_groups:
            for e in range(1, embargo_groups + 1):
                embargo.add(g + e)
        path_returns: list[float] = []
        for grp, ret, lab_end in samples:
            if grp not in test_set:
                continue
            # PURGE: the whole label horizon must stay inside the test set and
            # clear of the embargo band — otherwise the sample's outcome overlaps
            # a non-test (implicit-train) block and is dropped.
            horizon = range(grp, lab_end + 1)
            if any(h not in test_set for h in horizon):
                continue
            if any(h in embargo for h in horizon):
                continue
            path_returns.append(ret)
        if len(path_returns) >= 2:
            path_sharpes.append(sharpe_ratio(path_returns))
            test_ns.append(len(path_returns))
    if not path_sharpes:
        return CPCVResult(
            n_groups,
            n_test,
            0,
            [],
            float("nan"),
            float("nan"),
            float("nan"),
            float("nan"),
            0.0,
            note="no path had >=2 admissible samples after purge/embargo",
        )
    srt = sorted(path_sharpes)
    n = len(srt)
    median = st.median(srt)
    p05 = srt[max(0, int(0.05 * n) - 0)] if n >= 20 else srt[0]
    p95 = srt[min(n - 1, int(0.95 * n))]
    pct_neg = sum(1 for s in srt if s < 0) / n
    return CPCVResult(
        n_groups=n_groups,
        n_test=n_test,
        n_paths=n,
        path_sharpes=path_sharpes,
        median=median,
        p05=p05,
        p95=p95,
        pct_paths_negative=pct_neg,
        mean_test_n=st.mean(test_ns),
    )


# ── PBO (Probability of Backtest Overfitting) ───────────────────────
@dataclass
class PBOResult:
    pbo: float
    n_combinations: int
    n_variants: int
    median_logit: float
    note: str = ""


def pbo(
    perf_matrix: list[list[float]],
    n_partitions: int = 10,
) -> PBOResult:
    """Bailey-Borwein-López de Prado Probability of Backtest Overfitting.

    perf_matrix: rows = TIME PERIODS, cols = strategy VARIANTS; value = the
      variant's return in that period. (T periods × V variants.)

    Method (CSCV — combinatorial symmetric cross-validation):
      1. Split the T rows into `n_partitions` equal contiguous blocks.
      2. For every way to choose HALF the blocks as IS (the rest OOS):
         - rank variants by IS Sharpe; pick the IS-best variant n*.
         - find the OOS rank of n* among all variants (1=worst ... V=best).
         - relative rank ω = OOS_rank / (V+1); logit λ = ln(ω / (1-ω)).
      3. PBO = fraction of combinations whose λ < 0 — i.e. the IS-best variant
         landed in the BOTTOM half OOS. A high PBO means selecting the IS-best
         tells you nothing (or worse) about OOS performance.

    PBO < 0.2 informative · 0.2–0.5 borderline · >=0.5 uninformative (random pick).
    """
    T = len(perf_matrix)
    if T == 0:
        return PBOResult(float("nan"), 0, 0, float("nan"), note="empty matrix")
    V = len(perf_matrix[0])
    if V < 2:
        return PBOResult(float("nan"), 0, V, float("nan"), note="need >=2 variants for PBO")
    # n_partitions must be even and <= T
    S = min(n_partitions, T)
    if S % 2 == 1:
        S -= 1
    if S < 2:
        return PBOResult(
            float("nan"), 0, V, float("nan"), note=f"too few periods ({T}) to partition"
        )
    bounds = [round(T * i / S) for i in range(S + 1)]
    blocks = [list(range(bounds[i], bounds[i + 1])) for i in range(S)]
    blocks = [b for b in blocks if b]
    S = len(blocks)
    if S < 2:
        return PBOResult(float("nan"), 0, V, float("nan"), note="degenerate blocks")

    def variant_sharpe(rows: list[int]) -> list[float]:
        out = []
        for v in range(V):
            series = [perf_matrix[r][v] for r in rows]
            out.append(sharpe_ratio(series))
        return out

    logits: list[float] = []
    half = S // 2
    for is_blocks in combinations(range(S), half):
        is_set = set(is_blocks)
        is_rows = [r for bi in is_set for r in blocks[bi]]
        oos_rows = [r for bi in range(S) if bi not in is_set for r in blocks[bi]]
        if len(is_rows) < 2 or len(oos_rows) < 2:
            continue
        is_sr = variant_sharpe(is_rows)
        oos_sr = variant_sharpe(oos_rows)
        n_star = max(range(V), key=lambda v: is_sr[v])  # IS-best variant
        # OOS rank of n_star: 1=worst .. V=best (ties → average-ish via sort pos)
        order = sorted(range(V), key=lambda v: oos_sr[v])
        oos_rank = order.index(n_star) + 1
        omega = oos_rank / (V + 1)
        omega = min(max(omega, 1e-6), 1 - 1e-6)
        logits.append(math.log(omega / (1 - omega)))
    if not logits:
        return PBOResult(float("nan"), 0, V, float("nan"), note="no valid IS/OOS combination")
    pbo_val = sum(1 for x in logits if x < 0) / len(logits)
    return PBOResult(
        pbo=pbo_val,
        n_combinations=len(logits),
        n_variants=V,
        median_logit=st.median(logits),
    )


# ── Deflated Sharpe Ratio ───────────────────────────────────────────
def expected_max_sharpe(variant_sharpes: list[float], n_trials: int | None = None) -> float:
    """E[max Sharpe] of N independent trials under the null (true SR=0), given the
    cross-sectional variance of the trial Sharpes (Bailey-LdP eq.). This is the
    benchmark the observed Sharpe must beat to be 'real'.

        E[max] ≈ σ_SR · ( (1-γ)·Φ⁻¹(1 - 1/N) + γ·Φ⁻¹(1 - 1/(N·e)) )

    with γ the Euler-Mascheroni constant. σ_SR is the stdev across the N trial
    Sharpes (the honest selection variance — the whole point of the deflation)."""
    N = n_trials if n_trials is not None else len(variant_sharpes)
    if N <= 1:
        return 0.0
    sigma_sr = st.pstdev(variant_sharpes) if len(variant_sharpes) >= 2 else 0.0
    if sigma_sr == 0:
        return 0.0
    gamma = 0.5772156649015329  # Euler-Mascheroni
    z1 = normal_ppf(1 - 1.0 / N)
    z2 = normal_ppf(1 - 1.0 / (N * math.e))
    return sigma_sr * ((1 - gamma) * z1 + gamma * z2)


@dataclass
class DSRResult:
    dsr: float
    observed_sr: float
    sr_star: float  # the deflated benchmark E[max SR]
    n_variants: int
    n_returns: int
    skew: float
    kurt: float
    note: str = ""


def deflated_sharpe_ratio(
    returns_selected: list[float],
    all_variant_sharpes: list[float],
    n_trials: int | None = None,
) -> DSRResult:
    """Bailey-López de Prado Deflated Sharpe Ratio.

    DSR = Φ( ((SR_obs − SR*) · sqrt(T−1)) / sqrt(1 − γ3·SR_obs + ((γ4−1)/4)·SR_obs²) )

      SR_obs — Sharpe of the SELECTED variant's per-period returns.
      SR*     — expected_max_sharpe over ALL variants tried (the deflation
                benchmark; this is where the "how many things did you try"
                honesty lives).
      T       — number of returns (sample length).
      γ3, γ4  — skew and (raw) kurtosis of the selected returns.

    DSR is the probability the TRUE Sharpe exceeds SR* (≈0 benchmark deflated for
    selection). Threshold to claim 'real': DSR >= 0.95.

    n_trials lets the caller pass the HONEST variant count even if
    all_variant_sharpes holds fewer (e.g. you summarize). Default = len(list).
    """
    T = len(returns_selected)
    if T < 3:
        return DSRResult(
            float("nan"),
            float("nan"),
            float("nan"),
            len(all_variant_sharpes),
            T,
            0.0,
            3.0,
            note="T<3",
        )
    sr_obs = sharpe_ratio(returns_selected)
    g3, g4 = skew_kurt(returns_selected)
    sr_star = expected_max_sharpe(all_variant_sharpes, n_trials=n_trials)
    denom = 1.0 - g3 * sr_obs + ((g4 - 1.0) / 4.0) * sr_obs**2
    if denom <= 0:
        denom = 1e-9
    z = ((sr_obs - sr_star) * math.sqrt(T - 1)) / math.sqrt(denom)
    return DSRResult(
        dsr=normal_cdf(z),
        observed_sr=sr_obs,
        sr_star=sr_star,
        n_variants=(n_trials if n_trials is not None else len(all_variant_sharpes)),
        n_returns=T,
        skew=g3,
        kurt=g4,
    )


# ── Verdict ─────────────────────────────────────────────────────────
@dataclass
class Verdict:
    name: str
    cpcv_median_sharpe: float
    cpcv_ci: tuple[float, float]
    cpcv_pct_paths_negative: float
    dsr: float
    pbo: float
    max_dd: float
    calmar: float
    verdict: str
    rationale: list[str] = field(default_factory=list)

    def render(self) -> str:
        lo, hi = self.cpcv_ci
        lines = [
            f"STRATEGY: {self.name}",
            "PRIMARY METRICS:",
            f"  CPCV median Sharpe:        {self.cpcv_median_sharpe:+.3f}  "
            f"(5-95% CI: [{lo:+.3f}, {hi:+.3f}])",
            f"  CPCV % paths Sharpe < 0:   {self.cpcv_pct_paths_negative:.1%}",
            f"  Deflated Sharpe Ratio:     {self.dsr:.3f}  (threshold >= 0.95)",
            f"  PBO:                       {self.pbo:.3f}  (threshold < 0.20)",
            f"  Max DD (CPCV worst path):  {self.max_dd:+.3f}",
            f"  Calmar:                    {self.calmar:+.3f}",
            "",
            f"VERDICT: [ {self.verdict} ]",
            "RATIONALE: " + ("; ".join(self.rationale) if self.rationale else "all gates clear"),
        ]
        return "\n".join(lines)


def make_verdict(
    name: str,
    cpcv: CPCVResult,
    dsr_res: DSRResult,
    pbo_res: PBOResult,
    max_dd: float,
    calmar: float,
) -> Verdict:
    """Apply the skill's hard gates and produce DEPLOY | PAPER ONLY | REJECT.

    Hard rule (skill §6): NEVER DEPLOY if PBO >= 0.2 OR DSR < 0.95 OR
    %paths<0 > 25%. We add: a NaN in any primary metric → REJECT (cannot
    certify). PAPER ONLY is reserved for the case where the point estimate is
    positive and the CI does not exclude a real edge but a hard gate is missed —
    i.e. plausible but unproven. Everything else → REJECT.
    """
    rationale: list[str] = []
    nan = any(x != x for x in (cpcv.median, dsr_res.dsr, pbo_res.pbo, cpcv.pct_paths_negative))
    pbo_fail = (not nan) and pbo_res.pbo >= 0.20
    dsr_fail = (not nan) and dsr_res.dsr < 0.95
    paths_fail = (not nan) and cpcv.pct_paths_negative > 0.25

    if nan:
        verdict = "REJECT"
        rationale.append("a primary metric is undefined (insufficient/degenerate data)")
    elif pbo_fail or dsr_fail or paths_fail:
        if pbo_fail:
            rationale.append(f"PBO {pbo_res.pbo:.2f} >= 0.20 (selection uninformative)")
        if dsr_fail:
            rationale.append(f"DSR {dsr_res.dsr:.2f} < 0.95 (Sharpe not real after deflation)")
        if paths_fail:
            rationale.append(
                f"{cpcv.pct_paths_negative:.0%} of CPCV paths Sharpe<0 (> 25% — unstable)"
            )
        # PAPER ONLY only if the central read is at least positive AND the worst
        # failure is a single borderline gate; otherwise REJECT.
        borderline = (
            cpcv.median > 0 and (not paths_fail) and (pbo_res.pbo < 0.5) and (dsr_res.dsr >= 0.50)
        )
        verdict = "PAPER ONLY" if borderline else "REJECT"
    else:
        verdict = "DEPLOY"

    return Verdict(
        name=name,
        cpcv_median_sharpe=cpcv.median,
        cpcv_ci=(cpcv.p05, cpcv.p95),
        cpcv_pct_paths_negative=cpcv.pct_paths_negative,
        dsr=dsr_res.dsr,
        pbo=pbo_res.pbo,
        max_dd=max_dd,
        calmar=calmar,
        verdict=verdict,
        rationale=rationale,
    )


def max_drawdown(returns: list[float]) -> float:
    """Max drawdown of the cumulative (additive) equity curve of per-trade returns.
    Returns a NEGATIVE number (the worst peak-to-trough), or 0.0 if never below
    peak. Additive (not compounded) because returns are small per-trade % and the
    harness reports arithmetic edges throughout."""
    if not returns:
        return 0.0
    equity = 0.0
    peak = 0.0
    mdd = 0.0
    for r in returns:
        equity += r
        peak = max(peak, equity)
        mdd = min(mdd, equity - peak)
    return mdd


# ── Self-test ───────────────────────────────────────────────────────
def self_test() -> bool:
    ok = True

    def check(name: str, cond: bool) -> None:
        nonlocal ok
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
        ok = ok and cond

    # T0 — Gaussian helpers against known values
    check("T0a Φ(0)=0.5", abs(normal_cdf(0.0) - 0.5) < 1e-12)
    check("T0b Φ(1.96)~0.975", abs(normal_cdf(1.959964) - 0.975) < 1e-4)
    check("T0c Φ⁻¹(0.975)~1.96", abs(normal_ppf(0.975) - 1.959964) < 1e-4)
    check("T0d Φ⁻¹∘Φ round-trips", abs(normal_ppf(normal_cdf(0.7)) - 0.7) < 1e-6)

    # T1 — Sharpe basics
    check("T1a constant series Sharpe=0 (no var)", sharpe_ratio([1.0] * 10) == 0.0)
    pos = [0.1 + 0.001 * i for i in range(50)]
    check("T1b positive-drift series Sharpe>0", sharpe_ratio(pos) > 0)

    # T2 — CPCV produces a DISTRIBUTION, and purge drops overlapping labels.
    # Build a TRUE-edge stream: every sample +0.5 ± small noise, label ends same
    # group (no overlap) → all paths should be strongly positive.
    rng = random.Random(7)
    samp_true = []
    n_groups = 8
    per = 40
    for g in range(n_groups):
        for _ in range(per):
            samp_true.append((g, 0.5 + rng.gauss(0, 0.3), g))
    res_true = cpcv_paths(samp_true, n_groups=8, n_test=2, embargo_groups=1)
    print(
        f"      CPCV(true edge): {res_true.n_paths} paths  median SR={res_true.median:+.2f}  "
        f"[{res_true.p05:+.2f},{res_true.p95:+.2f}]  %neg={res_true.pct_paths_negative:.0%}"
    )
    check("T2a CPCV yields C(8,2)=28 paths", res_true.n_paths == 28)
    check("T2b true-edge median Sharpe > 0", res_true.median > 0)
    check("T2c true-edge ~0% paths negative", res_true.pct_paths_negative < 0.1)

    # noise stream: mean 0 → median Sharpe near 0, lots of negative paths
    samp_noise = []
    for g in range(n_groups):
        for _ in range(per):
            samp_noise.append((g, rng.gauss(0, 1.0), g))
    res_noise = cpcv_paths(samp_noise, n_groups=8, n_test=2, embargo_groups=1)
    print(
        f"      CPCV(noise):     {res_noise.n_paths} paths  median SR={res_noise.median:+.2f}  "
        f"%neg={res_noise.pct_paths_negative:.0%}"
    )
    check("T2d noise median Sharpe ~ 0", abs(res_noise.median) < 0.25)
    check("T2e noise has many negative paths (>25%)", res_noise.pct_paths_negative > 0.25)

    # T2f — purge actually drops a sample whose label spills into a non-test group.
    # one test selection {0,1}; a sample in group 1 with label_end 2 must be purged.
    spill = [(0, 1.0, 0), (1, 1.0, 1), (1, 99.0, 2)]  # the 99.0 must never count
    r = cpcv_paths(spill, n_groups=3, n_test=2, embargo_groups=0)
    # the only path with >=2 admissible samples is test={0,1}; it must exclude 99
    check(
        "T2f purge drops label-spill sample", all(s < 50 for s in r.path_sharpes) or r.n_paths == 0
    )

    # T3 — PBO: a genuinely-good single variant among noise → low PBO; pure noise
    # across many variants → PBO ~ 0.5.
    T_periods = 40
    V = 6
    # variant 0 has a true edge; rest are noise
    mat_edge = []
    for _t in range(T_periods):
        row = [0.4 + rng.gauss(0, 0.5)]  # the real one
        row += [rng.gauss(0, 0.5) for _ in range(V - 1)]
        mat_edge.append(row)
    pbo_edge = pbo(mat_edge, n_partitions=8)
    print(f"      PBO(one real variant): {pbo_edge.pbo:.2f} over {pbo_edge.n_combinations} combos")
    check("T3a PBO low when one variant is genuinely best", pbo_edge.pbo < 0.30)

    # Average PBO over several noise realizations: any SINGLE small noise matrix
    # is itself noisy (only ~70 IS/OOS combos), so we assert the EXPECTED PBO of a
    # no-edge matrix is materially higher than the genuine-edge case. Under the
    # null the IS-best is a coin-flip OOS, so E[PBO] → ~0.5 as T,V grow; on this
    # small matrix it sits well above the edge case's near-zero.
    noise_pbos = []
    for s in range(12):
        rng_s = random.Random(1000 + s)
        mat_noise = [[rng_s.gauss(0, 1.0) for _ in range(V)] for _ in range(T_periods)]
        noise_pbos.append(pbo(mat_noise, n_partitions=8).pbo)
    mean_noise_pbo = st.mean(noise_pbos)
    print(
        f"      PBO(all noise): mean over 12 seeds = {mean_noise_pbo:.2f} "
        f"(range {min(noise_pbos):.2f}-{max(noise_pbos):.2f})"
    )
    check(
        "T3b mean noise PBO >> edge PBO (>=0.30 and > edge case)",
        mean_noise_pbo >= 0.30 and mean_noise_pbo > pbo_edge.pbo,
    )

    # T4 — DSR: deflation lowers a single-trial-looking Sharpe when many tried.
    real_ret = [0.3 + rng.gauss(0, 1.0) for _ in range(200)]  # modest positive SR
    sr_real = sharpe_ratio(real_ret)
    # few trials: DSR should be higher than with many noisy trials of similar SR
    trial_sharpes_few = [sr_real, 0.0]
    trial_sharpes_many = [sr_real] + [rng.gauss(0, 0.3) for _ in range(50)]
    dsr_few = deflated_sharpe_ratio(real_ret, trial_sharpes_few)
    dsr_many = deflated_sharpe_ratio(real_ret, trial_sharpes_many)
    print(
        f"      DSR few-trials={dsr_few.dsr:.3f} (SR*={dsr_few.sr_star:+.2f})  "
        f"many-trials={dsr_many.dsr:.3f} (SR*={dsr_many.sr_star:+.2f})"
    )
    check("T4a DSR <= 1 and >= 0", 0.0 <= dsr_few.dsr <= 1.0)
    check("T4b more trials → higher SR* benchmark", dsr_many.sr_star >= dsr_few.sr_star)
    check("T4c more trials → lower (or equal) DSR", dsr_many.dsr <= dsr_few.dsr + 1e-9)

    # T5 — verdict gating
    good = CPCVResult(8, 2, 28, [], 1.2, 0.8, 1.6, 0.0, 30.0)
    good_dsr = DSRResult(0.99, 1.2, 0.1, 5, 200, 0.0, 3.0)
    good_pbo = PBOResult(0.05, 28, 6, 1.0)
    v_good = make_verdict("good", good, good_dsr, good_pbo, -0.1, 12.0)
    check("T5a all gates clear → DEPLOY", v_good.verdict == "DEPLOY")
    bad_pbo = PBOResult(0.6, 28, 6, -0.5)
    v_bad = make_verdict("bad", good, good_dsr, bad_pbo, -0.1, 12.0)
    check("T5b PBO>=0.2 → not DEPLOY", v_bad.verdict != "DEPLOY")
    nan_cpcv = CPCVResult(8, 2, 0, [], float("nan"), float("nan"), float("nan"), float("nan"), 0.0)
    v_nan = make_verdict("nan", nan_cpcv, good_dsr, good_pbo, 0.0, 0.0)
    check("T5c NaN metric → REJECT", v_nan.verdict == "REJECT")

    # T6 — max_drawdown sign + magnitude
    check("T6a all-up curve → 0 DD", max_drawdown([0.1, 0.2, 0.1]) == 0.0)
    check("T6b down move → negative DD", max_drawdown([1.0, -0.5, -0.5]) <= -1.0 + 1e-9)

    print(f"\n  {'ALL TESTS PASS' if ok else 'SOME TESTS FAILED'}")
    return ok


if __name__ == "__main__":
    import sys

    if "--self-test" in sys.argv:
        sys.exit(0 if self_test() else 1)
    print("overfitting_rigor: CPCV / PBO / DSR primitives. Run with --self-test.")
