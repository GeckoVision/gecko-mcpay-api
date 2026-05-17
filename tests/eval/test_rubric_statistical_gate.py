"""S34-WS1-A — unit tests for the rubric scorer's statistical pass-gate.

These cover the *pure* aggregation logic only — no LLM, no network, no
panel call. They assert the property the statistical review demanded:
a dimension passes only when the bootstrap 95% CI lower bound clears
its threshold, not merely when the point mean does.

Light-fakes per the over-mocking guidance: we hand the pure functions
plain float lists / synthetic rows; nothing is monkeypatched.
"""

from __future__ import annotations

from tests.eval.scripts.score_defi_trade_rubric import (
    PASS_THRESHOLDS,
    SHIP_GATE_N,
    _aggregate,
    _bootstrap_ci,
    _statistical_pass,
    evaluate_retrieval_pregate,
)


def _row(**scores: float) -> dict[str, object]:
    """Synthetic per-fixture row — only the keys _aggregate touches."""
    full = {d: scores.get(d, 1.0) for d in PASS_THRESHOLDS}
    passed = all(full[d] >= PASS_THRESHOLDS[d] for d in PASS_THRESHOLDS)
    return {"scores": full, "passed": passed}


def test_bootstrap_ci_is_deterministic() -> None:
    """Fixed seed → identical CI on repeat calls (reproducible gate)."""
    values = [0.5, 0.6, 0.4, 0.7, 0.5, 0.5, 0.6, 0.4, 0.5, 0.6]
    first = _bootstrap_ci(values)
    second = _bootstrap_ci(values)
    assert first == second


def test_bootstrap_ci_brackets_the_mean() -> None:
    values = [0.2, 0.4, 0.6, 0.8, 0.5, 0.5, 0.3, 0.7, 0.5, 0.5]
    mean, lo, hi = _bootstrap_ci(values)
    assert lo <= mean <= hi
    assert hi > lo  # non-degenerate with spread


def test_bootstrap_ci_degenerate_inputs() -> None:
    assert _bootstrap_ci([]) == (0.0, 0.0, 0.0)
    assert _bootstrap_ci([0.42]) == (0.42, 0.42, 0.42)
    # zero-variance input → CI collapses to the mean
    mean, lo, hi = _bootstrap_ci([0.6] * 10)
    assert mean == lo == hi == 0.6


def test_statistical_pass_rejects_a_borderline_point_pass() -> None:
    """The core S33 finding: citation_relevance mean 0.52 vs a 0.50 bar
    with a wide CI must NOT count as a statistical pass.

    Values chosen to mean ~0.52 with real spread — the exact shape the
    statistical review flagged as a 'coin-flip'.
    """
    values = [0.5, 0.5, 0.5, 0.5, 0.6, 0.6, 0.5, 0.4, 0.5, 0.6]
    result = _statistical_pass("citation_relevance", values)
    assert result["threshold"] == 0.50
    assert result["point_pass"] is True  # mean clears the bar
    assert result["ci_low"] < 0.50  # but the CI lower bound does not
    assert result["statistical_pass"] is False  # so the gate says NO


def test_statistical_pass_accepts_a_solidly_clear_dimension() -> None:
    """A dimension well above its bar with a tight CI passes."""
    values = [1.0] * 10  # provider_kind_coverage-style perfect run
    result = _statistical_pass("provider_kind_coverage", values)
    assert result["point_pass"] is True
    assert result["statistical_pass"] is True
    assert result["ci_low"] >= result["threshold"]


def test_statistical_pass_marks_a_solid_red() -> None:
    """hallucination at 0.10 vs a 0.30 bar — solidly failing both gates."""
    values = [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    result = _statistical_pass("hallucination_score", values)
    assert result["point_pass"] is False
    assert result["statistical_pass"] is False


def test_aggregate_ship_gate_requires_all_dims_statistically_green() -> None:
    """A run where every dim point-passes but one is a coin-flip must
    NOT report ship_gate_pass=True.
    """
    # citation_relevance ~0.52 mean with real per-fixture spread — the
    # S33 'coin-flip' shape: point-passes a 0.50 bar, CI straddles it.
    cit_rel = [0.3, 0.4, 0.5, 0.5, 0.5, 0.5, 0.6, 0.6, 0.7, 0.6]
    rows = [
        _row(
            verdict_accuracy=1.0,
            citation_relevance=cit_rel[i],
            provider_kind_coverage=1.0,
            hallucination_score=1.0,
            dissent_grounding=0.8,
            confidence_calibration=0.8,
        )
        for i in range(10)
    ]
    agg = _aggregate(rows)
    sg = agg["statistical_gate"]
    # citation_relevance hovers at the bar → not statistically green.
    assert "citation_relevance" not in sg["dims_statistically_green"]
    assert sg["ship_gate_pass"] is False
    # but it DOES point-pass — proving the gate closes a real gap.
    assert "citation_relevance" in sg["dims_point_green"]


def test_aggregate_ship_gate_eligibility_tracks_n() -> None:
    small = _aggregate([_row() for _ in range(10)])
    assert small["n_policy"]["ship_gate_eligible"] is False
    big = _aggregate([_row() for _ in range(SHIP_GATE_N)])
    assert big["n_policy"]["ship_gate_eligible"] is True


def test_aggregate_all_perfect_run_passes_ship_gate() -> None:
    """A run that is genuinely green on every dim with zero variance
    should clear the statistical gate (sanity: the gate is not a
    permanent red)."""
    rows = [_row() for _ in range(SHIP_GATE_N)]  # all dims = 1.0
    agg = _aggregate(rows)
    sg = agg["statistical_gate"]
    assert sg["n_statistically_green"] == sg["n_dims"]
    assert sg["ship_gate_pass"] is True
    assert agg["n_policy"]["ship_gate_eligible"] is True


def test_aggregate_empty_rows() -> None:
    assert _aggregate([]) == {"n": 0}


# --- S34-WS1-C — retrieval pre-gate decision logic ----------------------


def _retrieval_agg(canon_pass: bool, pkcov_pass: bool) -> dict[str, object]:
    """Synthetic retrieval-eval aggregate — only the keys the pre-gate reads."""
    return {
        "n": 10,
        "gate": {
            "canon_floor_pass": canon_pass,
            "pk_coverage_pass": pkcov_pass,
        },
    }


def test_pregate_passes_when_retrieval_healthy() -> None:
    """Both retrieval bars green → rubric run proceeds."""
    decision = evaluate_retrieval_pregate(_retrieval_agg(True, True))
    assert decision["pass"] is True
    assert decision["failed_dims"] == []


def test_pregate_aborts_on_canon_floor_failure() -> None:
    """The S33 fix→blind-rubric loop: canon never reached the panel.
    The pre-gate must abort before any LLM spend.
    """
    decision = evaluate_retrieval_pregate(_retrieval_agg(False, True))
    assert decision["pass"] is False
    assert "canon_floor" in decision["failed_dims"]
    assert "RETRIEVAL PRE-GATE FAILED" in decision["message"]


def test_pregate_aborts_on_pk_coverage_failure() -> None:
    decision = evaluate_retrieval_pregate(_retrieval_agg(True, False))
    assert decision["pass"] is False
    assert "provider_kind_coverage" in decision["failed_dims"]


def test_pregate_aborts_on_both_failing() -> None:
    decision = evaluate_retrieval_pregate(_retrieval_agg(False, False))
    assert decision["pass"] is False
    assert set(decision["failed_dims"]) == {"canon_floor", "provider_kind_coverage"}


def test_pregate_aborts_on_malformed_aggregate() -> None:
    """A retrieval aggregate with no gate block (e.g. n=0 scored) must
    abort, not silently pass — fail closed."""
    decision = evaluate_retrieval_pregate({"n": 0})
    assert decision["pass"] is False


def test_pregate_accepts_real_s33_retrieval_artifact() -> None:
    """End-to-end-ish: the actual post-S33 retrieval run on disk shows
    healthy retrieval, so the pre-gate would PASS it. Guards against the
    pre-gate spuriously blocking a good run."""
    import json
    from pathlib import Path

    artifact = Path(__file__).parent / "live_runs" / "2026-05-16-s33-retrieval-eval-run-10.json"
    if not artifact.exists():  # pragma: no cover - artifact may be pruned
        return
    agg = json.loads(artifact.read_text())["aggregate"]
    decision = evaluate_retrieval_pregate(agg)
    assert decision["pass"] is True
