"""Tests for acceptance_gate — the Phase V.2 gates (default REJECT).

Load-bearing assertions:
  * a strong CLEAN feature with an uncorrelated panel ACCEPTS;
  * a NOISE feature REJECTS (net-EV CI straddles zero);
  * a LEAKED feature REJECTS (leakage gate fails);
  * NO panel => incrementality is NOT_APPLICABLE and that is NOT a silent pass
    (the feature is NOT accepted).

Run: uv run pytest scripts/calibration/test_acceptance_gate.py -q
"""

from __future__ import annotations

import os
import random
import statistics as st
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import acceptance_gate as ag
import feature_validation as fv
import walkforward_validation as wfv


def _build(scale: float = 30.0, seed: int = 5):
    c = fv.build_predictive_window(n=400, phi=0.6, seed=seed)
    n = len(c["close"])
    indices = list(range(5, n - 2))
    syms = ["SYN"] * len(indices)
    fwd = [fv.forward_return(c, i, 1) * 100 * scale for i in indices]
    return c, indices, syms, fwd


def _select(feat, c, indices, syms, fwd, fee):
    scores = [feat.compute(c, i) for i in indices]
    srt = sorted(scores)
    hi_cut = srt[(2 * len(srt)) // 3]
    g, nval, s, idx = [], [], [], []
    for sc, fr, i in zip(scores, fwd, indices, strict=True):
        if sc >= hi_cut:
            g.append(fr)
            nval.append(fr - fee)
            s.append("SYN")
            idx.append(i)
    return g, nval, s, idx


def test_clean_feature_with_panel_accepts():
    fee = ag.DEFAULT_FEE_RT
    c, indices, syms, fwd = _build()
    feat = fv.MomentumFeature(k=3)
    g, nval, s, idx = _select(feat, c, indices, syms, fwd, fee)
    samples = [
        wfv.Sample("SYN", i, feat.compute(c, i), fv.forward_return(c, i, 1), "trend")
        for i in indices
    ]
    rng = random.Random(1)
    panel = [[rng.gauss(0, 1) for _ in idx] for _ in range(2)]
    v = ag.evaluate_feature(
        feature=feat,
        regime="trend",
        candles=c,
        indices=idx,
        symbols=s,
        net_returns=nval,
        gross_returns=g,
        trap_indices=indices,
        trap_symbols=syms,
        trap_fwd_returns=fwd,
        samples_for_walkforward=samples,
        pvalue=0.001,
        fdr_batch_pvalues=[0.001, 0.2, 0.4],
        fee_rt=fee,
        panel_columns=panel,
    )
    assert v.accepted
    assert st.mean(g) >= 2 * fee  # sanity: the economic bar is really cleared


def test_no_panel_is_not_silently_passed():
    fee = ag.DEFAULT_FEE_RT
    c, indices, syms, fwd = _build()
    feat = fv.MomentumFeature(k=3)
    g, nval, s, idx = _select(feat, c, indices, syms, fwd, fee)
    samples = [
        wfv.Sample("SYN", i, feat.compute(c, i), fv.forward_return(c, i, 1), "trend")
        for i in indices
    ]
    v = ag.evaluate_feature(
        feature=feat,
        regime="trend",
        candles=c,
        indices=idx,
        symbols=s,
        net_returns=nval,
        gross_returns=g,
        trap_indices=indices,
        trap_symbols=syms,
        trap_fwd_returns=fwd,
        samples_for_walkforward=samples,
        pvalue=0.001,
        fdr_batch_pvalues=[0.001, 0.2, 0.4],
        fee_rt=fee,
        panel_columns=None,
    )
    assert not v.accepted, "NOT_APPLICABLE incrementality must not auto-accept"
    assert "incremental_vif" in v.not_applicable_gates
    incr = next(gt for gt in v.gates if gt.name == "incremental_vif")
    assert incr.result == ag.GateResult.NOT_APPLICABLE
    # every other gate is an explicit PASS
    assert all(gt.result == ag.GateResult.PASS for gt in v.gates if gt.name != "incremental_vif")


def test_noise_feature_rejected():
    fee = ag.DEFAULT_FEE_RT
    c, indices, syms, fwd = _build()

    class Noise:
        name = "noise"

        def __init__(self):
            self.rng = random.Random(7)
            self.cache: dict[int, float] = {}

        def compute(self, candles, i):
            return self.cache.setdefault(i, self.rng.gauss(0, 1))

    nf = Noise()
    g, nval, s, idx = _select(nf, c, indices, syms, fwd, fee)
    samples = [
        wfv.Sample("SYN", i, nf.compute(c, i), fv.forward_return(c, i, 1), "trend") for i in indices
    ]
    rng = random.Random(2)
    panel = [[rng.gauss(0, 1) for _ in idx] for _ in range(2)]
    v = ag.evaluate_feature(
        feature=nf,
        regime="trend",
        candles=c,
        indices=idx,
        symbols=s,
        net_returns=nval,
        gross_returns=g,
        trap_indices=indices,
        trap_symbols=syms,
        trap_fwd_returns=fwd,
        samples_for_walkforward=samples,
        pvalue=0.4,
        fdr_batch_pvalues=[0.001, 0.2, 0.4],
        fee_rt=fee,
        panel_columns=panel,
    )
    assert not v.accepted


def test_leaked_feature_rejected():
    fee = ag.DEFAULT_FEE_RT
    c, indices, syms, fwd = _build()
    feat = fv.MomentumFeature(k=3)
    g, nval, s, idx = _select(feat, c, indices, syms, fwd, fee)
    leaked = fv.LeakedFeature()
    samples = [
        wfv.Sample("SYN", i, leaked.compute(c, i), fv.forward_return(c, i, 1), "trend")
        for i in indices[:-1]
    ]
    rng = random.Random(3)
    panel = [[rng.gauss(0, 1) for _ in idx] for _ in range(2)]
    v = ag.evaluate_feature(
        feature=leaked,
        regime="trend",
        candles=c,
        indices=idx,
        symbols=s,
        net_returns=nval,
        gross_returns=g,
        trap_indices=indices[:-1],
        trap_symbols=syms[:-1],
        trap_fwd_returns=fwd[:-1],
        samples_for_walkforward=samples,
        pvalue=0.001,
        fdr_batch_pvalues=[0.001, 0.2, 0.4],
        fee_rt=fee,
        panel_columns=panel,
    )
    leak_gate = next(gt for gt in v.gates if gt.name == "leakage_clean")
    assert leak_gate.result == ag.GateResult.FAIL
    assert not v.accepted


def test_default_reject_all_gates_required():
    # a verdict with any non-PASS gate must have accepted=False
    gates = [ag.Gate("g1", ag.GateResult.PASS, ""), ag.Gate("g2", ag.GateResult.FAIL, "")]
    v = ag.AcceptanceVerdict(feature="x", regime="trend", gates=gates, fee_rt=0.5)
    # constructed directly defaults to accepted=False
    assert v.accepted is False


def test_preregistration_ledger_append_only(tmp_path):
    path = str(tmp_path / "ledger.jsonl")
    led = ag.PreRegistrationLedger(path=path)
    led.register("f1", "trend", "h1")
    led.register("f2", "chop", "h2")
    assert led.batch_size() == 2
    with open(path) as f:
        lines = f.read().strip().splitlines()
    assert len(lines) == 2


def test_vif_detects_collinear_feature():
    # a target that is a linear combo of the panel has high VIF (not incremental)
    rng = random.Random(4)
    a = [rng.gauss(0, 1) for _ in range(100)]
    b = [rng.gauss(0, 1) for _ in range(100)]
    target = [2 * a[i] + 0.5 * b[i] + rng.gauss(0, 0.01) for i in range(100)]
    vif = ag.vif_against_panel(target, [a, b])
    assert vif is not None and vif > 5.0


def test_vif_none_without_panel():
    assert ag.vif_against_panel([1.0, 2.0, 3.0], []) is None
