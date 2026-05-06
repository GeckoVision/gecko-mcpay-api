"""S20-C-CONFIDENCE-PROMPT-01 — basic-tier confidence propagation end-to-end.

Mocks the LLM seam (``_call_llm``) plus ``rag_query`` and the session
store so we can assert that:

  (a) a model emitting a top-level ``confidence`` lands as
      ``ResearchResult.confidence`` (document-level aggregate is the min
      across section emits — basic tier has one section so it equals the
      single emitted confidence);
  (b) a model that does NOT emit ``confidence`` keeps the default 0.0
      and does not fail validation (back-compat path);
  (c) ``ResearchResult.confidence`` round-trips through pydantic
      serialization (catches accidental field exclusion).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from gecko_core.models import ResearchResult


def _mk_chunk(idx: int, chunk_id: str, url: str = "https://example.com/a") -> Any:
    from gecko_core.rag.query import RagChunk

    return RagChunk(
        source_id=uuid4(),
        source_url=url,
        chunk_index=idx,
        text=f"context blob {idx}",
        similarity=0.85,
        provider_kind="web",
        chunk_id=chunk_id,
    )


class _FakeStore:
    def __init__(self, urls: list[str]) -> None:
        from gecko_core.models import SourceInfo

        self._sources = [
            SourceInfo(url=u, type="web", chunk_count=1, indexed_at=datetime.now(UTC)) for u in urls
        ]

    async def list_sources(self, _session_id: Any) -> list[Any]:
        return self._sources

    async def add_cost(self, *_a: Any, **_k: Any) -> None:
        return None


def _llm_payload(*, confidence: float | None = None) -> str:
    payload: dict[str, Any] = {
        "business_plan": {
            "problem": "p",
            "icp": "i",
            "solution": "s",
            "market": "m",
            "business_model": "bm",
            "channels": "c",
            "risks": [],
            "citations": [
                {"source_url": "https://example.com/a", "chunk_index": 0, "similarity": 0.85}
            ],
        },
        "validation_report": {
            "market_size_signal": "x",
            "competitor_analysis": "x",
            "demand_evidence": "x",
            "risk_flags": [],
            "citations": [
                {"source_url": "https://example.com/a", "chunk_index": 0, "similarity": 0.85}
            ],
            "gap_classification": "Partial:UX",
            "gap_summary": "competitor X covers fraud but not replay debugging",
            "gap_explanation": (
                "The UX is the gap — chunk one [1] confirms the wedge. "
                "Ship the replay-from-error path before competing on dashboards."
            ),
        },
        "prd": {
            "v1_scope": ["x"],
            "v2_scope": ["x"],
            "v3_scope": ["x"],
            "acceptance_criteria": ["x"],
            "non_functional": ["x"],
            "success_metrics": ["x"],
            "citations": [
                {"source_url": "https://example.com/a", "chunk_index": 0, "similarity": 0.85}
            ],
        },
        "citations": [
            {
                "idx": 1,
                "doc_id": "chunk-AAA",
                "url": "https://example.com/a",
                "span": "the cited passage",
            }
        ],
    }
    if confidence is not None:
        payload["confidence"] = confidence
        payload["rationale"] = "dense base, multi-citation"
    return json.dumps(payload)


@pytest.mark.asyncio
async def test_basic_generate_propagates_confidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mocked LLM emits confidence=0.6 → ResearchResult.confidence == 0.6.

    Basic tier has one section, so the document-level aggregate (min of
    per-section confidences) equals the single emitted value.
    """
    from gecko_core.orchestration import basic as basic_mod

    chunks = [_mk_chunk(0, "chunk-AAA")]

    async def _fake_rag_query(*_a: object, **_kw: object) -> list[Any]:
        return chunks

    async def _fake_call_llm(**_kw: Any) -> tuple[str, float]:
        return _llm_payload(confidence=0.6), 0.0001

    monkeypatch.setattr(basic_mod, "rag_query", _fake_rag_query)
    monkeypatch.setattr(basic_mod, "_call_llm", _fake_call_llm)

    store = _FakeStore(["https://example.com/a"])
    result = await basic_mod.generate(
        session_id=uuid4(),
        idea="test idea",
        store=store,  # type: ignore[arg-type]
        openai_client=AsyncMock(),
    )

    assert result.confidence == 0.6


@pytest.mark.asyncio
async def test_basic_generate_default_confidence_when_omitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Legacy/back-compat: model omits confidence → field defaults to 0.0."""
    from gecko_core.orchestration import basic as basic_mod

    chunks = [_mk_chunk(0, "chunk-AAA")]

    async def _fake_rag_query(*_a: object, **_kw: object) -> list[Any]:
        return chunks

    async def _fake_call_llm(**_kw: Any) -> tuple[str, float]:
        return _llm_payload(confidence=None), 0.0001

    monkeypatch.setattr(basic_mod, "rag_query", _fake_rag_query)
    monkeypatch.setattr(basic_mod, "_call_llm", _fake_call_llm)

    store = _FakeStore(["https://example.com/a"])
    result = await basic_mod.generate(
        session_id=uuid4(),
        idea="test idea",
        store=store,  # type: ignore[arg-type]
        openai_client=AsyncMock(),
    )

    assert result.confidence == 0.0


def test_research_result_confidence_roundtrips() -> None:
    """Reachability sanity check: ResearchResult.confidence survives a
    pydantic dump/validate roundtrip. Catches accidental field exclusion
    in serializers (e.g. ``model_dump(exclude={...})`` without including
    confidence).
    """
    from gecko_core.models import PRD as PRDModel
    from gecko_core.models import BusinessPlan, Citation, Tier, ValidationReport

    cite = Citation(
        source_url="https://example.com/a",
        chunk_index=0,
        similarity=0.9,
    )
    business_plan = BusinessPlan(
        problem="p",
        icp="i",
        solution="s",
        market="m",
        business_model="bm",
        channels="c",
        risks=[],
        citations=[cite],
    )
    validation_report = ValidationReport(
        market_size_signal="x",
        competitor_analysis="x",
        demand_evidence="x",
        risk_flags=[],
        citations=[cite],
        gap_classification="Partial:UX",
        gap_summary="x",
        gap_explanation="x",
    )
    prd = PRDModel(
        v1_scope=["x"],
        v2_scope=["x"],
        v3_scope=["x"],
        acceptance_criteria=["x"],
        non_functional=["x"],
        success_metrics=["x"],
        citations=[cite],
    )

    tier: Tier = "basic"
    result = ResearchResult(
        session_id=str(uuid4()),
        tier=tier,
        business_plan=business_plan,
        validation_report=validation_report,
        prd=prd,
        sources=[],
        confidence=0.7,
    )

    dumped = result.model_dump(mode="json")
    assert dumped["confidence"] == 0.7
    revived = ResearchResult.model_validate(dumped)
    assert revived.confidence == 0.7
