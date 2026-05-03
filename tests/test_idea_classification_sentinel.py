"""S21-CALIBRATION-CLASSIFY-01 — structural eval for the
``idea_classification`` sentinel extractor.

Pure-Python unit test. No model calls. Validates that:

1. The regex extractor in ``gecko_core.orchestration.pro.coherence``
   pulls the label from a judge transcript when the sentinel is
   present, lowercases it, and returns ``None`` cleanly when absent.
2. ``ResearchResult.idea_classification`` is excluded from the
   ``verdict_hash`` payload — calibration tilt must not flap the
   digest under stable retrieval.

The structural-vs-LLM-graded distinction matters: this regex is the
contract surface for the v5.5.1 calibration upgrade. If the judge
prompt drifts and stops emitting the sentinel as the FIRST line, the
field silently returns ``None`` — which is the correct degrade. The
live eval gate that asserts the field is NON-None when
``--calibration colosseum`` is active lives in
``tests/eval/`` (wired by software-engineer alongside the calibration
flag plumbing).
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
from gecko_core.orchestration.pro.coherence import extract_idea_classification
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


def test_extract_idea_classification_greenfield() -> None:
    turns = [
        _judge_turn(
            "idea_classification: greenfield\nTAM: 7\nWEDGE: 8\nV1_FEASIBILITY: 7\n"
            "Verdict: SHIP V1 to ...\ngap_classification: Partial:segment\n"
            "Final verdict: GO"
        )
    ]
    assert extract_idea_classification(turns) == "greenfield"


def test_extract_idea_classification_iterative_case_insensitive() -> None:
    turns = [_judge_turn("Idea_Classification: ITERATIVE\nrest of prose")]
    assert extract_idea_classification(turns) == "iterative"


def test_extract_idea_classification_unclear() -> None:
    turns = [_judge_turn("idea_classification: unclear\nrest")]
    assert extract_idea_classification(turns) == "unclear"


def test_extract_idea_classification_missing_returns_none() -> None:
    turns = [_judge_turn("TAM: 6\nWEDGE: 5\nVerdict: SHIP V1.\nFinal verdict: REFINE")]
    assert extract_idea_classification(turns) is None


def test_extract_idea_classification_invalid_label_returns_none() -> None:
    # Adjacent words must not match — only the closed enum.
    turns = [_judge_turn("idea_classification: greenish\nrest")]
    assert extract_idea_classification(turns) is None


def test_extract_idea_classification_first_match_wins() -> None:
    # Judge emits the sentinel; later voices may quote the judge.
    turns = [
        _judge_turn("idea_classification: iterative\nrest"),
        _turn("critic", "the judge said idea_classification: greenfield", seq=1),
    ]
    assert extract_idea_classification(turns) == "iterative"


def test_extract_idea_classification_dict_replay_shape() -> None:
    # Eval harness replays transcripts as plain dicts — duck-type the
    # ``content`` key the same way ``count_no_surviving_dissent_flags``
    # does. Regression guard for the harness path.
    turns = [{"agent": "judge", "content": "idea_classification: greenfield\n"}]
    assert extract_idea_classification(turns) == "greenfield"


# ---------------------------------------------------------------------------
# Hash exclusion: idea_classification must NOT change verdict_hash.
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


def test_idea_classification_does_not_affect_verdict_hash() -> None:
    idea = "Stablecoin payouts API for LATAM gig platforms."
    bare = _base_result()
    classified_greenfield = bare.model_copy(update={"idea_classification": "greenfield"})
    classified_iterative = bare.model_copy(update={"idea_classification": "iterative"})
    classified_unclear = bare.model_copy(update={"idea_classification": "unclear"})
    h_bare = verdict_hash(idea, bare)
    assert h_bare == verdict_hash(idea, classified_greenfield)
    assert h_bare == verdict_hash(idea, classified_iterative)
    assert h_bare == verdict_hash(idea, classified_unclear)
