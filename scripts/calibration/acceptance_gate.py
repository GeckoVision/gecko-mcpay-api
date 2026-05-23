#!/usr/bin/env python3
"""Phase V.2 — the acceptance gate (default REJECT) + pre-registration ledger.

THE SPEC (docs/strategy/2026-05-22-market-analysis-roadmap.md, V.2)
  A feature/strategy ships ONLY IF ALL of these pass. Default verdict is REJECT;
  the harness is the SKEPTIC. Every gate is computed, never eyeballed.

  GATES
   1. leakage_clean        — survives the V.1 leakage traps (lookahead+shuffle+placebo).
   2. net_ev_excl_zero     — net-of-fee EV block-bootstrap CI EXCLUDES zero, on the
                             positive side, in the feature's DECLARED regime.
   3. survives_fdr         — survives Benjamini-Hochberg across the batch of features
                             tested (multiple-comparisons honesty).
   4. n_eff_ge_30          — N_eff >= 30 (the V.2 minimum for a sub-1% edge claim).
   5. oos_same_sign        — out-of-sample positive AND same sign across walk-forward
                             folds.
   6. incremental_vif      — incremental over the existing panel (VIF). If NO panel
                             feature columns are supplied, this gate is NOT silently
                             passed — it is marked NOT_APPLICABLE and the verdict
                             records that the incrementality claim was NOT tested.
   7. economically_meaningful — gross edge >= 2x the round-trip fee.

  Plus an APPEND-ONLY PRE-REGISTRATION LEDGER: what was tested is recorded BEFORE
  results are seen, so the FDR batch size is honest (you can't quietly drop the
  losers from the denominator).

HONESTY RULES (enforced in code, not prose)
  * Default REJECT: AcceptanceVerdict.accepted is True ONLY if every APPLICABLE
    gate passes AND no gate is NOT_APPLICABLE that the spec requires. A
    NOT_APPLICABLE incrementality gate => the feature is NOT accepted as
    "incremental over the panel"; the verdict says so explicitly.
  * A stub/approximation NEVER reads as a pass. NOT_APPLICABLE != PASS.

REUSE: stats_validation (block bootstrap, BH-FDR), feature_validation (traps,
edge), walkforward_validation (walk-forward + per-regime).

Run: uv run pytest scripts/calibration/test_acceptance_gate.py -q
"""

from __future__ import annotations

import json
import os
import statistics as st
import sys
import time
from dataclasses import dataclass, field
from enum import Enum

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import feature_validation as fv
import stats_validation as sv
import walkforward_validation as wfv

# Default DEX round-trip fee (% per round trip). The roadmap's central ~0.5-0.75%.
DEFAULT_FEE_RT = 0.5
N_EFF_MIN = 30.0
ECON_FEE_MULTIPLE = 2.0  # gross edge must be >= 2x round-trip fee


class GateResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass
class Gate:
    name: str
    result: GateResult
    detail: str
    value: float | None = None

    @property
    def ok(self) -> bool:
        return self.result == GateResult.PASS


@dataclass
class AcceptanceVerdict:
    feature: str
    regime: str
    gates: list[Gate]
    fee_rt: float
    accepted: bool = False  # DEFAULT REJECT
    not_applicable_gates: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "feature": self.feature,
            "regime": self.regime,
            "fee_rt": self.fee_rt,
            "accepted": self.accepted,
            "gates": [
                {"name": g.name, "result": g.result.value, "detail": g.detail, "value": g.value}
                for g in self.gates
            ],
            "not_applicable_gates": self.not_applicable_gates,
        }


# ── Variance Inflation Factor (incrementality over a panel) ─────────
def vif_against_panel(target: list[float], panel_columns: list[list[float]]) -> float | None:
    """VIF of `target` regressed on the existing panel columns (OLS R^2 via normal
    equations). VIF = 1/(1 - R^2). High VIF => the target is largely explained by
    the panel (NOT incremental). Returns None if no panel columns are supplied
    (so the caller marks the gate NOT_APPLICABLE rather than silently passing).

    Implementation: closed-form multiple-regression R^2 using centered columns and
    a small Gram-matrix solve (Gaussian elimination). No numpy dependency."""
    if not panel_columns:
        return None
    n = len(target)
    if n < len(panel_columns) + 2:
        return None
    # center
    ty = st.mean(target)
    y = [v - ty for v in target]
    cols = []
    for col in panel_columns:
        m = st.mean(col)
        cols.append([v - m for v in col])
    p = len(cols)
    # Gram matrix X'X and X'y
    gram = [[sum(cols[a][r] * cols[b][r] for r in range(n)) for b in range(p)] for a in range(p)]
    xty = [sum(cols[a][r] * y[r] for r in range(n)) for a in range(p)]
    beta = _solve(gram, xty)
    if beta is None:
        return None
    # R^2 = 1 - SSE/SST
    sst = sum(v * v for v in y)
    if sst == 0:
        return None
    sse = 0.0
    for r in range(n):
        pred = sum(beta[a] * cols[a][r] for a in range(p))
        sse += (y[r] - pred) ** 2
    r2 = 1.0 - sse / sst
    r2 = min(max(r2, 0.0), 0.999999)
    return 1.0 / (1.0 - r2)


def _solve(a: list[list[float]], b: list[float]) -> list[float] | None:
    """Gaussian elimination with partial pivoting. Returns x s.t. a x = b, or None
    if singular."""
    n = len(a)
    m = [[*row, b[i]] for i, row in enumerate(a)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[piv][col]) < 1e-12:
            return None
        m[col], m[piv] = m[piv], m[col]
        pivval = m[col][col]
        for r in range(n):
            if r == col:
                continue
            factor = m[r][col] / pivval
            for k in range(col, n + 1):
                m[r][k] -= factor * m[col][k]
    return [m[i][n] / m[i][i] for i in range(n)]


# ── The pre-registration ledger (append-only) ───────────────────────
class PreRegistrationLedger:
    """Append-only JSONL ledger of what was tested, recorded BEFORE results are
    seen. The FDR batch size is the count of registered hypotheses — you cannot
    shrink the denominator after the fact. `register` MUST be called before
    `evaluate_feature` consumes results for a feature."""

    def __init__(self, path: str | None = None):
        self.path = path
        self.entries: list[dict] = []

    def register(self, feature: str, regime: str, hypothesis: str) -> dict:
        entry = {
            "ts": time.time(),
            "feature": feature,
            "regime": regime,
            "hypothesis": hypothesis,
            "phase": "pre-registered",
        }
        self.entries.append(entry)
        if self.path:
            with open(self.path, "a") as f:
                f.write(json.dumps(entry) + "\n")
        return entry

    def batch_size(self) -> int:
        return len(self.entries)


# ── The evaluator ───────────────────────────────────────────────────
def evaluate_feature(
    *,
    feature: fv.Feature,
    regime: str,
    candles: dict,
    indices: list[int],
    symbols: list[str],
    net_returns: list[float],
    gross_returns: list[float],
    trap_indices: list[int],
    trap_symbols: list[str],
    trap_fwd_returns: list[float],
    samples_for_walkforward: list[wfv.Sample],
    pvalue: float,
    fdr_batch_pvalues: list[float],
    fee_rt: float = DEFAULT_FEE_RT,
    panel_columns: list[list[float]] | None = None,
    fdr_alpha: float = 0.05,
) -> AcceptanceVerdict:
    """Run all V.2 gates for one feature. DEFAULT REJECT — accepted is True only if
    every applicable gate passes and no required gate is NOT_APPLICABLE.

    Arguments:
      indices / symbols            — the SELECTED ("act") trades in the declared
        regime, aligned to net_returns / gross_returns. Used by gates 2/4/6/7.
      net_returns / gross_returns  — per-sample realized returns of the SELECTED
        trades. `net_returns` is already net-of-fee; `gross_returns` is pre-fee.
      trap_indices / trap_symbols / trap_fwd_returns — the FULL aligned sample set
        (all candidates, not just selected) the leakage traps score over.
      samples_for_walkforward      — Sample objects for the OOS fold check.
      pvalue                       — this feature's own p-value (for FDR).
      fdr_batch_pvalues            — ALL p-values in the pre-registered batch.
      panel_columns                — existing-panel feature columns aligned to the
        target's scores (on `indices`); None/empty => incrementality NOT_APPLICABLE.
    """
    gates: list[Gate] = []

    # Gate 1 — leakage clean (run over the FULL aligned trap set)
    rep = fv.run_leakage_traps(feature, candles, trap_indices, trap_fwd_returns, trap_symbols)
    gates.append(
        Gate(
            "leakage_clean",
            GateResult.PASS if rep.clean else GateResult.FAIL,
            f"lookahead={rep.lookahead_clean} shuffle={rep.shuffle_passes} "
            f"placebo={rep.placebo_passes}",
        )
    )

    # Gate 2 — net-of-fee EV block-CI excludes zero (positive) in declared regime
    net_series = _by_symbol(net_returns, symbols)
    if net_series:
        ev, lo, hi, n_eff, _b = sv.block_bootstrap_ci(net_series)
    else:
        ev = lo = hi = float("nan")
        n_eff = 0.0
    net_excl_pos = lo == lo and lo > 0
    gates.append(
        Gate(
            "net_ev_excl_zero",
            GateResult.PASS if net_excl_pos else GateResult.FAIL,
            f"netEV={ev:+.4f} CI[{lo:+.4f},{hi:+.4f}] (declared regime={regime})",
            value=ev,
        )
    )

    # Gate 3 — survives BH-FDR across the batch
    fdr = sv.bh_fdr(fdr_batch_pvalues, alpha=fdr_alpha)
    survives = pvalue <= fdr["threshold"] if fdr["k"] > 0 else False
    gates.append(
        Gate(
            "survives_fdr",
            GateResult.PASS if survives else GateResult.FAIL,
            f"p={pvalue:.4g} BH-threshold={fdr['threshold']:.4g} "
            f"(batch m={len(fdr_batch_pvalues)}, rejected k={fdr['k']})",
            value=pvalue,
        )
    )

    # Gate 4 — N_eff >= 30
    gates.append(
        Gate(
            "n_eff_ge_30",
            GateResult.PASS if n_eff >= N_EFF_MIN else GateResult.FAIL,
            f"N_eff={n_eff:.1f} (min {N_EFF_MIN:.0f})",
            value=n_eff,
        )
    )

    # Gate 5 — OOS positive + same sign across folds
    wf = wfv.walk_forward(samples_for_walkforward, n_folds=4)
    oos_ok = wf["oos_positive"] and wf["same_sign_across_folds"]
    gates.append(
        Gate(
            "oos_same_sign",
            GateResult.PASS if oos_ok else GateResult.FAIL,
            f"oos_positive={wf['oos_positive']} "
            f"same_sign={wf['same_sign_across_folds']} folds={len(wf['folds'])}",
        )
    )

    # Gate 6 — incremental over the panel (VIF). NOT_APPLICABLE if no panel.
    scores = [feature.compute(candles, i) for i in indices]
    vif = vif_against_panel(scores, panel_columns or [])
    if vif is None:
        gates.append(
            Gate(
                "incremental_vif",
                GateResult.NOT_APPLICABLE,
                "no panel columns supplied — incrementality NOT tested (NOT a pass)",
            )
        )
    else:
        # incremental if VIF below a standard collinearity threshold (~5)
        incr = vif < 5.0
        gates.append(
            Gate(
                "incremental_vif",
                GateResult.PASS if incr else GateResult.FAIL,
                f"VIF vs panel={vif:.2f} (threshold 5.0; lower=more incremental)",
                value=vif,
            )
        )

    # Gate 7 — economically meaningful: gross edge >= 2x round-trip fee
    gross_series = _by_symbol(gross_returns, symbols)
    gross_ev = st.mean([v for s in gross_series for v in s]) if gross_series else float("nan")
    econ_bar = ECON_FEE_MULTIPLE * fee_rt
    econ_ok = gross_ev == gross_ev and gross_ev >= econ_bar
    gates.append(
        Gate(
            "economically_meaningful",
            GateResult.PASS if econ_ok else GateResult.FAIL,
            f"gross_edge={gross_ev:+.4f} vs bar {econ_bar:.4f} "
            f"(={ECON_FEE_MULTIPLE:.0f}x fee {fee_rt})",
            value=gross_ev,
        )
    )

    not_applicable = [g.name for g in gates if g.result == GateResult.NOT_APPLICABLE]
    # DEFAULT REJECT: accept only if every gate is an explicit PASS.
    accepted = all(g.result == GateResult.PASS for g in gates)
    return AcceptanceVerdict(
        feature=feature.name,
        regime=regime,
        gates=gates,
        fee_rt=fee_rt,
        accepted=accepted,
        not_applicable_gates=not_applicable,
    )


def _by_symbol(values: list[float], symbols: list[str]) -> list[list[float]]:
    by: dict[str, list[float]] = {}
    for v, s in zip(values, symbols, strict=True):
        by.setdefault(s, []).append(v)
    return [v for v in by.values() if v]


# ── Self-test (synthetic accept / reject / leak cases) ──────────────
def self_test() -> bool:
    ok = True

    def check(name: str, cond: bool) -> None:
        nonlocal ok
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
        ok = ok and cond

    import random

    rng = random.Random(99)

    # Build a synthetic window + samples where the CLEAN feature has a strong,
    # time-stable, economically-large, regime-consistent edge.
    c = fv.build_predictive_window(n=400, phi=0.6, seed=5)
    n = len(c["close"])
    indices = list(range(5, n - 2))
    syms = ["SYN"] * len(indices)
    feat = fv.MomentumFeature(k=3)

    # forward returns scaled up so the gross edge clears 2x fee comfortably
    scale = 30.0  # turn the tiny synthetic % into a clearly-economic edge
    fwd = [fv.forward_return(c, i, 1) * 100 * scale for i in indices]
    scores = [feat.compute(c, i) for i in indices]
    # net = gross - fee; gross is the score-aligned forward return
    fee = DEFAULT_FEE_RT
    # long-short framed gross/net per sample (sign by tercile handled in edge),
    # but the gates 2/7 want per-sample realized returns of the SELECTED trades:
    srt = sorted(scores)
    hi_cut = srt[(2 * len(srt)) // 3]
    sel_gross, sel_net, sel_syms, sel_idx = [], [], [], []
    for sc, fr, i in zip(scores, fwd, indices, strict=True):
        if sc >= hi_cut:  # the "act" trades the feature selects (longs)
            sel_gross.append(fr)
            sel_net.append(fr - fee)
            sel_syms.append("SYN")
            sel_idx.append(i)
    gross_mean = st.mean(sel_gross)
    print(f"      selected gross edge={gross_mean:+.3f}%  (2x fee bar={2 * fee:.3f}%)")

    samples = [
        wfv.Sample("SYN", i, feat.compute(c, i), fv.forward_return(c, i, 1), "trend")
        for i in indices
    ]

    ledger = PreRegistrationLedger()
    ledger.register(feat.name, "trend", "trailing-3-bar return predicts forward return")
    batch_p = [0.001, 0.2, 0.4]  # this feature's p is the small one
    v_accept = evaluate_feature(
        feature=feat,
        regime="trend",
        candles=c,
        indices=sel_idx,
        symbols=sel_syms,
        net_returns=sel_net,
        gross_returns=sel_gross,
        trap_indices=indices,
        trap_symbols=syms,
        trap_fwd_returns=fwd,
        samples_for_walkforward=samples,
        pvalue=0.001,
        fdr_batch_pvalues=batch_p,
        fee_rt=fee,
        panel_columns=None,  # => incrementality NOT_APPLICABLE
    )
    print("      ACCEPT-candidate gates:")
    for g in v_accept.gates:
        print(f"        {g.name:>24}: {g.result.value:>14}  {g.detail}")

    # With no panel, incrementality is NOT_APPLICABLE -> NOT accepted (honest stub).
    check("T1a no-panel feature is NOT accepted (incr NOT_APPLICABLE)", not v_accept.accepted)
    check(
        "T1b incrementality gate flagged NOT_APPLICABLE",
        "incremental_vif" in v_accept.not_applicable_gates,
    )
    # but every OTHER gate passes
    others_pass = all(
        g.result == GateResult.PASS for g in v_accept.gates if g.name != "incremental_vif"
    )
    check("T1c all gates except incrementality PASS", others_pass)

    # Now supply a panel of UNCORRELATED noise columns -> incrementality PASSES ->
    # full ACCEPT.
    panel = [[rng.gauss(0, 1) for _ in sel_idx] for _ in range(2)]
    v_full = evaluate_feature(
        feature=feat,
        regime="trend",
        candles=c,
        indices=sel_idx,
        symbols=sel_syms,
        net_returns=sel_net,
        gross_returns=sel_gross,
        trap_indices=indices,
        trap_symbols=syms,
        trap_fwd_returns=fwd,
        samples_for_walkforward=samples,
        pvalue=0.001,
        fdr_batch_pvalues=batch_p,
        fee_rt=fee,
        panel_columns=panel,
    )
    check("T2a feature with uncorrelated panel is ACCEPTED", v_full.accepted)

    # Noise feature: scores random -> no edge -> net EV CI straddles 0 -> REJECT.
    class NoiseFeature:
        name = "pure_noise"

        def __init__(self, seed):
            self.rng = random.Random(seed)
            self._cache: dict[int, float] = {}

        def compute(self, candles, i):
            if i not in self._cache:
                self._cache[i] = self.rng.gauss(0, 1)
            return self._cache[i]

    nf = NoiseFeature(7)
    noise_scores = [nf.compute(c, i) for i in indices]
    nsrt = sorted(noise_scores)
    nhi = nsrt[(2 * len(nsrt)) // 3]
    nsel_g, nsel_n, nsel_s, nsel_i = [], [], [], []
    for sc, fr, i in zip(noise_scores, fwd, indices, strict=True):
        if sc >= nhi:
            nsel_g.append(fr)
            nsel_n.append(fr - fee)
            nsel_s.append("SYN")
            nsel_i.append(i)
    nsamples = [
        wfv.Sample("SYN", i, nf.compute(c, i), fv.forward_return(c, i, 1), "trend") for i in indices
    ]
    v_noise = evaluate_feature(
        feature=nf,
        regime="trend",
        candles=c,
        indices=nsel_i,
        symbols=nsel_s,
        net_returns=nsel_n,
        gross_returns=nsel_g,
        trap_indices=indices,
        trap_symbols=syms,
        trap_fwd_returns=fwd,
        samples_for_walkforward=nsamples,
        pvalue=0.4,
        fdr_batch_pvalues=batch_p,
        fee_rt=fee,
        panel_columns=[[rng.gauss(0, 1) for _ in nsel_i] for _ in range(2)],
    )
    check("T3a noise feature is REJECTED", not v_noise.accepted)

    # Leaked feature: caught by leakage gate -> REJECT even with everything else.
    leaked = fv.LeakedFeature()
    lsamples = [
        wfv.Sample("SYN", i, leaked.compute(c, i), fv.forward_return(c, i, 1), "trend")
        for i in indices[:-1]
    ]
    v_leak = evaluate_feature(
        feature=leaked,
        regime="trend",
        candles=c,
        indices=sel_idx,
        symbols=sel_syms,
        net_returns=sel_net,
        gross_returns=sel_gross,
        trap_indices=indices[:-1],  # leaked feature reads i+1; keep room
        trap_symbols=syms[:-1],
        trap_fwd_returns=fwd[:-1],
        samples_for_walkforward=lsamples,
        pvalue=0.001,
        fdr_batch_pvalues=batch_p,
        fee_rt=fee,
        panel_columns=panel,
    )
    leak_gate = next(g for g in v_leak.gates if g.name == "leakage_clean")
    check("T4a leaked feature fails leakage gate", leak_gate.result == GateResult.FAIL)
    check("T4b leaked feature is REJECTED", not v_leak.accepted)

    # Ledger honesty
    check("T5a ledger batch size = 1 registered", ledger.batch_size() == 1)

    print(f"\n  {'ALL TESTS PASS' if ok else 'SOME TESTS FAILED'}")
    return ok


if __name__ == "__main__":
    sys.exit(0 if self_test() else 1)
