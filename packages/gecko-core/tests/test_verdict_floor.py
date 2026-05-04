"""S17-VERDICT-01 / S26-VERDICT-FIDELITY-01 — evidence-strength floor on derive_verdict.

S17: grounding floor prevents thin evidence from producing inflated verdicts.
S26: PIVOT (Full/False gap) must NOT be softened to REFINE by the floor —
     if the problem doesn't exist, that signal is authoritative regardless of
     evidence volume. The floor only applies to ambiguous partial-gap verdicts.
"""

from __future__ import annotations

from gecko_core.models import (
    SIGNAL_STRENGTH_MIN_CITATIONS,
    SIGNAL_STRENGTH_MIN_SIMILARITY,
    Citation,
    Verdict,
    derive_verdict,
    is_low_grounding,
)


def _cite(sim: float, idx: int = 0) -> Citation:
    return Citation(
        source_url="https://example.com/x",
        chunk_index=idx,
        similarity=sim,
    )


# ---------------------------------------------------------------------------
# is_low_grounding
# ---------------------------------------------------------------------------


def test_is_low_grounding_true_when_no_citations() -> None:
    assert is_low_grounding(None) is True
    assert is_low_grounding([]) is True


def test_is_low_grounding_true_when_below_min_citations() -> None:
    # 2 citations < SIGNAL_STRENGTH_MIN_CITATIONS (3); even with high sim
    # the floor still fires on count alone.
    citations = [_cite(0.9, 0), _cite(0.9, 1)]
    assert len(citations) < SIGNAL_STRENGTH_MIN_CITATIONS
    assert is_low_grounding(citations) is True


def test_is_low_grounding_true_when_max_sim_below_threshold() -> None:
    # Plenty of citations but every one is below the similarity floor.
    citations = [_cite(0.27, i) for i in range(5)]
    assert max(c.similarity for c in citations) < SIGNAL_STRENGTH_MIN_SIMILARITY
    assert is_low_grounding(citations) is True


def test_is_low_grounding_false_when_thresholds_met() -> None:
    citations = [_cite(0.41, 0), _cite(0.30, 1), _cite(0.25, 2)]
    assert is_low_grounding(citations) is False


# ---------------------------------------------------------------------------
# derive_verdict — floor wins over gap mapping
# ---------------------------------------------------------------------------


def test_verdict_pivot_survives_weak_grounding() -> None:
    """S26-VERDICT-FIDELITY-01: PIVOT must survive low_grounding.

    Full/False gap means the problem doesn't exist — that signal is
    authoritative even when evidence is thin. Flooring to REFINE would
    tell a founder to "refine" when they should "pivot", which is harmful.
    The low_grounding flag is still set on the result for the renderer.
    """
    weak = [_cite(0.27)]
    assert is_low_grounding(weak), "precondition: weak citations are low-grounding"
    # Full gap + thin evidence → PIVOT (S26 fix)
    assert derive_verdict("Full", citations=weak) is Verdict.PIVOT
    assert derive_verdict("False", citations=weak) is Verdict.PIVOT
    # Partial gap + thin evidence → REFINE (floor still applies)
    assert derive_verdict("Partial:segment", citations=weak) is Verdict.REFINE


def test_verdict_floor_overrides_go_promotion() -> None:
    """Even a Partial:pricing + strong consensus floors to REFINE when
    grounding is thin. The advisor panel cannot ship over weak evidence."""
    weak = [_cite(0.27), _cite(0.20)]
    # Without the floor, Partial:pricing + 1.0 consensus → GO.
    assert derive_verdict("Partial:pricing", advisor_consensus=1.0) is Verdict.GO
    # With the floor, → REFINE.
    assert (
        derive_verdict(
            "Partial:pricing",
            advisor_consensus=1.0,
            citations=weak,
        )
        is Verdict.REFINE
    )


def test_verdict_strong_grounding_keeps_normal_mapping() -> None:
    """Floor must NOT misfire on healthy citation sets."""
    strong = [_cite(0.62, 0), _cite(0.55, 1), _cite(0.48, 2)]
    assert is_low_grounding(strong) is False
    assert derive_verdict("Full", citations=strong) is Verdict.PIVOT
    assert (
        derive_verdict(
            "Partial:pricing",
            advisor_consensus=1.0,
            citations=strong,
        )
        is Verdict.GO
    )
    assert derive_verdict("Partial:UX", citations=strong) is Verdict.REFINE


def test_verdict_legacy_callers_without_citations_unchanged() -> None:
    """Pre-S17 callers that pass no citations argument keep the old
    behavior — the floor is opt-in, not a silent regression."""
    # Full → PIVOT (legacy KILL semantic).
    assert derive_verdict("Full") is Verdict.PIVOT
    assert derive_verdict("False") is Verdict.PIVOT
    # Partial:UX → REFINE (irrespective of consensus).
    assert derive_verdict("Partial:UX") is Verdict.REFINE
    assert derive_verdict("Partial:UX", advisor_consensus=1.0) is Verdict.REFINE
    # Partial:pricing + strong consensus → GO.
    assert derive_verdict("Partial:pricing", advisor_consensus=0.9) is Verdict.GO
    # Partial:pricing without consensus → REFINE (lean conservative).
    assert derive_verdict("Partial:pricing") is Verdict.REFINE
