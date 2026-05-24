"""Smoke test for the Phase V CLI on the cached windows.

Confirms the full V.1/V.2 pipeline runs end-to-end on real cached candles and
returns a structured AcceptanceVerdict. Skips if the cached windows are absent
(they live in /tmp and are not committed).

Run: uv run pytest scripts/calibration/test_phase_v_cli.py -q
"""

from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import acceptance_gate as ag
import phase_v_cli as cli

W1 = "/tmp/cal_candles_d1.json"


@pytest.mark.skipif(not os.path.exists(W1), reason="cached window not present")
def test_cli_runs_end_to_end_on_cached_window():
    with open(W1) as f:
        raw = json.load(f)
    ledger = ag.PreRegistrationLedger()
    verdict = cli.run_window("W1", raw, "trend", ledger)
    # structural assertions — the pipeline produced a full structured verdict
    assert isinstance(verdict, ag.AcceptanceVerdict)
    gate_names = {g.name for g in verdict.gates}
    assert gate_names == {
        "leakage_clean",
        "net_ev_excl_zero",
        "survives_fdr",
        "n_eff_ge_30",
        "oos_same_sign",
        "incremental_vif",
        "economically_meaningful",
    }
    # default REJECT honesty: with no panel, incrementality is NOT_APPLICABLE and
    # the verdict is not accepted
    assert "incremental_vif" in verdict.not_applicable_gates
    assert verdict.accepted is False
    # the momentum demo on this chop tape must NOT clear the economic bar
    econ = next(g for g in verdict.gates if g.name == "economically_meaningful")
    assert econ.result == ag.GateResult.FAIL
    assert ledger.batch_size() == 1


@pytest.mark.skipif(not os.path.exists(W1), reason="cached window not present")
def test_cli_build_samples_are_causal_scored():
    with open(W1) as f:
        raw = json.load(f)
    built = cli.build_samples(raw, cli.fv.MomentumFeature(k=3))
    assert built["all_samples"], "should produce samples from the cached tape"
    # every sample's regime is one of the known labels
    assert all(s.regime in ("trend", "transitional", "chop") for s in built["all_samples"])
    # the demo feature is leakage-clean across all symbols
    assert cli.leakage_clean_all_symbols(cli.fv.MomentumFeature(k=3), built["per_symbol"])
