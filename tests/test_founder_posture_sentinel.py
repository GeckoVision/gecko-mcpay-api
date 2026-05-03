"""S21-CALIBRATION-FOUNDER-POSTURE-01 — structural eval for the
``founder_posture`` sentinel extractor.

Pure-Python unit test. No model calls. Sister to
``tests/test_idea_classification_sentinel.py``: validates that

1. The regex extractor in ``gecko_core.orchestration.pro.coherence``
   pulls the label from a judge transcript when the sentinel is
   present, lowercases it, and returns ``None`` cleanly when absent.
2. ``ResearchResult.founder_posture`` is excluded from the
   ``verdict_hash`` payload — calibration tilt must not flap the
   digest under stable retrieval.

The structural-vs-LLM-graded distinction matters: this regex is the
contract surface for the v5.5.2 founder-lens upgrade. If the judge
prompt drifts and stops emitting the sentinel, the post-processor
batch fills it in via a JSON-shaped fallback (covered by the
``run_post_processors`` integration test). This unit test guards the
regex layer only.
"""

from __future__ import annotations

from datetime import UTC, datetime

from gecko_core.models import (
    PRD,
    BusinessPlan,
    ResearchResult,
    SourceInfo,
    ValidationReport,
    Verdict,
)
from gecko_core.orchestration.pro.coherence import extract_founder_posture
from gecko_core.orchestration.pro.transcript import AgentTurn
from gecko_core.verdict_hash import verdict_hash


def _turn(agent: str, content: str, seq: int = 0) -> AgentTurn:
    return AgentTurn(
        seq=seq,
        agent=agent,  # type: ignore[arg-type]
        content=content,
        ts=0.0,
        tokens_in=0,
        tokens_out=0,
    )


def _judge_turn(content: str) -> AgentTurn:
    return _turn("judge", content)


def test_extract_founder_posture_high() -> None:
    turns = [
        _judge_turn(
            "idea_classification: iterative\nfounder_posture: high\nTAM: 7\nWEDGE: 8\n"
            "V1_FEASIBILITY: 7\nVerdict: SHIP V1 to ...\n"
            "gap_classification: Partial:segment\nFinal verdict: GO"
        )
    ]
    assert extract_founder_posture(turns) == "high"


def test_extract_founder_posture_moderate_case_insensitive() -> None:
    turns = [_judge_turn("Founder_Posture: MODERATE\nrest of prose")]
    assert extract_founder_posture(turns) == "moderate"


def test_extract_founder_posture_unclear() -> None:
    turns = [_judge_turn("founder_posture: unclear\nrest")]
    assert extract_founder_posture(turns) == "unclear"


def test_extract_founder_posture_missing_returns_none() -> None:
    turns = [_judge_turn("TAM: 6\nWEDGE: 5\nVerdict: SHIP V1.\nFinal verdict: REFINE")]
    assert extract_founder_posture(turns) is None


def test_extract_founder_posture_invalid_label_returns_none() -> None:
    # Adjacent words must not match — only the closed enum.
    turns = [_judge_turn("founder_posture: strong\nrest")]
    assert extract_founder_posture(turns) is None


def test_extract_founder_posture_first_match_wins() -> None:
    # Judge emits the sentinel; later voices may quote the judge.
    turns = [
        _judge_turn("founder_posture: high\nrest"),
        _turn("critic", "the judge said founder_posture: unclear", seq=1),
    ]
    assert extract_founder_posture(turns) == "high"


def test_extract_founder_posture_dict_replay_shape() -> None:
    turns = [{"agent": "judge", "content": "founder_posture: moderate\n"}]
    assert extract_founder_posture(turns) == "moderate"


# ---------------------------------------------------------------------------
# Hash exclusion: founder_posture must NOT change verdict_hash.
# ---------------------------------------------------------------------------


def _base_result() -> ResearchResult:
    return ResearchResult(
        session_id="00000000-0000-0000-0000-000000000000",
        tier="pro",
        business_plan=BusinessPlan(
            problem="p",
            icp="i",
            solution="s",
            market="m",
            business_model="b",
            channels="c",
            risks=["r"],
            citations=[],
        ),
        validation_report=ValidationReport(
            market_size_signal="x",
            competitor_analysis="x",
            demand_evidence="x",
            risk_flags=["x"],
            citations=[],
            gap_classification="Partial:UX",
        ),
        prd=PRD(
            v1_scope=["v1"],
            v2_scope=["v2"],
            v3_scope=["v3"],
            acceptance_criteria=["ac"],
            non_functional=["nf"],
            success_metrics=["sm"],
            citations=[],
        ),
        sources=[
            SourceInfo(
                url="https://example.com/a",
                type="web",
                chunk_count=2,
                indexed_at=datetime(2026, 5, 2, tzinfo=UTC),
            )
        ],
        verdict=Verdict.REFINE,
    )


def test_founder_posture_does_not_affect_verdict_hash() -> None:
    idea = "Stablecoin payouts API for LATAM gig platforms."
    bare = _base_result()
    h_bare = verdict_hash(idea, bare)
    for label in ("high", "moderate", "unclear"):
        mutated = bare.model_copy(update={"founder_posture": label})
        assert h_bare == verdict_hash(idea, mutated), (
            f"founder_posture={label!r} flipped the verdict_hash; "
            f"calibration tilt must not perturb the digest"
        )


def test_founder_posture_combined_with_idea_classification_excluded() -> None:
    # Combined exclusion guard — both fields off the hash payload at once.
    idea = "Same idea."
    bare = _base_result()
    fully = bare.model_copy(update={"idea_classification": "iterative", "founder_posture": "high"})
    assert verdict_hash(idea, bare) == verdict_hash(idea, fully)
