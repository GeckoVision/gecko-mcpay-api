"""S26-VERDICT-FIDELITY-01 — PIVOT must win over low-grounding REFINE floor.

derive_verdict() previously checked is_low_grounding → REFINE before
checking gap in ('Full','False') → PIVOT.  A session with a Full/False gap
and fewer-than-threshold citations returned REFINE (softened verdict).
"""

from gecko_core.models import Citation, Verdict, derive_verdict, is_low_grounding


def _thin_citations(n: int = 1) -> list[Citation]:
    """Build n citations all with low similarity so is_low_grounding() is True."""
    return [
        Citation(source_url=f"https://example.com/{i}", chunk_index=i, similarity=0.1)
        for i in range(n)
    ]


def test_full_gap_returns_pivot_even_with_low_grounding() -> None:
    citations = _thin_citations(1)
    assert is_low_grounding(citations), "precondition: citations must be low-grounding"
    verdict = derive_verdict("Full", citations=citations)
    assert verdict == Verdict.PIVOT, "Full gap + low_grounding must return PIVOT, not REFINE"


def test_false_gap_returns_pivot_even_with_low_grounding() -> None:
    citations = _thin_citations(1)
    assert is_low_grounding(citations)
    verdict = derive_verdict("False", citations=citations)
    assert verdict == Verdict.PIVOT


def test_partial_gap_still_gets_low_grounding_floor() -> None:
    citations = _thin_citations(1)
    verdict = derive_verdict("Partial:segment", citations=citations)
    assert verdict == Verdict.REFINE, "Partial gap + low_grounding must still floor to REFINE"


def test_full_gap_no_citations_returns_pivot() -> None:
    verdict = derive_verdict("Full", citations=None)
    assert verdict == Verdict.PIVOT


def test_kill_overrides_pivot() -> None:
    """KILL always wins — incoherence overrides gap classification."""
    verdict = derive_verdict("Full", citations=None, incoherence_flag_count=2)
    assert verdict == Verdict.KILL
