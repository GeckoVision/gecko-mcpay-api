"""v5.5 — verdict_hash MUST NOT depend on post-processor readouts.

The 5 new fields on ResearchResult (per_voice, transcript_summary,
market_landscape, surviving_dissent, next_steps_with_falsifiers) are
post-hoc readouts. Including them in the hash would make the digest flap
on prompt changes that don't change the verdict.
"""

from __future__ import annotations

from datetime import UTC, datetime

from gecko_core.models import (
    PRD,
    BusinessPlan,
    Competitor,
    Dissent,
    Falsifier,
    MarketLandscape,
    NextStep,
    NextStepsWithFalsifiers,
    PerVoiceReadout,
    ResearchResult,
    SourceInfo,
    SurvivingDissent,
    ValidationReport,
    Verdict,
    VoicePosition,
)
from gecko_core.verdict_hash import verdict_hash


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


def _populated_post_processors() -> dict[str, object]:
    per_voice = PerVoiceReadout(
        voices=[
            VoicePosition(
                name="analyst",
                position="x",
                tension="y",
                recommendation="z",
                status="engaged",
            ),
            VoicePosition(
                name="critic",
                position=None,
                tension=None,
                recommendation=None,
                status="silent",
            ),
            VoicePosition(
                name="architect",
                position="a",
                tension=None,
                recommendation="r",
                status="deferred",
            ),
            VoicePosition(
                name="scoper",
                position="s",
                tension="t",
                recommendation="r",
                status="engaged",
            ),
            VoicePosition(
                name="judge",
                position="ship",
                tension=None,
                recommendation="ship",
                status="engaged",
            ),
        ]
    )
    landscape = MarketLandscape(
        competitors=[
            Competitor(
                name="Acme",
                what_they_do="prose synthesis",
                why_we_are_not_them="verdict_shape",
            ),
            Competitor(name="Other", what_they_do="x", flag="cannot_articulate_difference"),
        ],
    )
    dissent = SurvivingDissent(
        dissent_status="surviving",
        dissents=[Dissent(voice="scoper", verbatim="quote", on_topic="V1 4-day box")],
        rationale="held to end",
    )
    next_steps = NextStepsWithFalsifiers(
        steps=[
            NextStep(
                action="Email 5 vet practices",
                surfaced_by_voice="analyst",
                falsifier=Falsifier(
                    what_would_disprove_this="Fewer than 3 of 5 respond",
                    by_when="2026-05-23",
                ),
            )
        ]
    )
    return {
        "per_voice": per_voice,
        "transcript_summary": "Four. Sentence. Recap. Here.",
        "market_landscape": landscape,
        "surviving_dissent": dissent,
        "next_steps_with_falsifiers": next_steps,
        # S21-CALIBRATION-FOUNDER-POSTURE-01 — both calibration labels
        # are post-processor readouts and must not perturb the digest.
        "idea_classification": "iterative",
        "founder_posture": "high",
    }


def test_post_processor_fields_do_not_affect_hash() -> None:
    idea = "Stablecoin payouts API for LATAM gig platforms."
    bare = _base_result()
    enriched = bare.model_copy(update=_populated_post_processors())
    assert verdict_hash(idea, bare) == verdict_hash(idea, enriched)


def test_changing_post_processor_fields_does_not_change_hash() -> None:
    idea = "Same idea."
    enriched = _base_result().model_copy(update=_populated_post_processors())
    h1 = verdict_hash(idea, enriched)
    mutated = enriched.model_copy(
        update={
            "transcript_summary": "Totally different prose recap.",
            "market_landscape": MarketLandscape(
                competitors=[
                    Competitor(name="X", what_they_do="y", why_we_are_not_them="settlement_layer")
                ]
            ),
        }
    )
    assert h1 == verdict_hash(idea, mutated)
