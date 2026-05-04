"""v0.1.10 — ``ResearchResult.low_explanation`` honest-surfacing flag.

Sibling concept to ``low_grounding``: when the basic-tier synthesizer
exhausts its retry budget for ``gap_explanation`` (the 2-3 sentence
narrative grounding the gap_classification label), we DO NOT synthesise
text from gap_summary or gap_classification. The field stays None /
empty and ``low_explanation`` is True so consumers (CLI renderer, HTML
report, API JSON) can surface "the model did not produce an explanation;
treat the verdict letter alone".

This file pins the flag's wiring end-to-end: the basic-tier path sets it,
the ResearchResult model accepts it, the verdict-hash payload doesn't
include it (so reruns reproduce the digest regardless of explanation
flap).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from gecko_core.models import ResearchResult, SourceInfo
from gecko_core.orchestration import basic as basic_mod
from gecko_core.rag.query import RagChunk
from gecko_core.verdict_hash import verdict_hash


def _make_chunk(url: str, idx: int = 0, sim: float = 0.9) -> RagChunk:
    return RagChunk(
        source_id=uuid4(),
        source_url=url,
        chunk_index=idx,
        text=f"content for {url} chunk {idx}",
        similarity=sim,
    )


def _make_source(url: str) -> SourceInfo:
    return SourceInfo(url=url, type="web", chunk_count=3, indexed_at=datetime.now(UTC))


def _payload(url: str, *, gap_explanation: str | None) -> dict[str, Any]:
    cit = [{"source_url": url, "chunk_index": 0, "similarity": 0.9}]
    vr: dict[str, Any] = {
        "market_size_signal": "m",
        "competitor_analysis": "c",
        "demand_evidence": "d",
        "risk_flags": ["rf"],
        "citations": cit,
        "gap_classification": "Partial:UX",
        "gap_summary": "Stripe Radar covers fraud but not webhook replay debugging.",
    }
    if gap_explanation is not None:
        vr["gap_explanation"] = gap_explanation
    return {
        "business_plan": {
            "problem": "p",
            "icp": "i",
            "solution": "s",
            "market": "m",
            "business_model": "bm",
            "channels": "c",
            "risks": ["r1"],
            "citations": cit,
        },
        "validation_report": vr,
        "prd": {
            "v1_scope": ["a"],
            "v2_scope": ["b"],
            "v3_scope": ["c"],
            "acceptance_criteria": ["ac"],
            "non_functional": ["nf"],
            "success_metrics": ["sm"],
            "citations": cit,
        },
    }


def _mk_openai_client(contents: list[str]) -> MagicMock:
    client = MagicMock()
    completions = MagicMock()

    def _raw(content: str) -> MagicMock:
        parsed = MagicMock(
            choices=[MagicMock(message=MagicMock(content=content))],
            usage=None,
            model="openai/gpt-4o",
        )
        raw = MagicMock()
        raw.parse = MagicMock(return_value=parsed)
        raw.headers = MagicMock()
        raw.headers.get = MagicMock(return_value=None)
        return raw

    raws = [_raw(c) for c in contents]
    with_raw = MagicMock()
    with_raw.create = AsyncMock(side_effect=raws)
    completions.with_raw_response = with_raw
    client.chat = MagicMock(completions=completions)
    return client


def _store_with_sources(urls: list[str]) -> MagicMock:
    store = MagicMock()
    store.list_sources = AsyncMock(return_value=[_make_source(u) for u in urls])
    store.add_cost = AsyncMock(return_value=None)
    return store


def test_research_result_low_explanation_default_false() -> None:
    """Backwards-compat default. Existing serialised ResearchResult rows /
    test fixtures that pre-date v0.1.10 round-trip with low_explanation=False
    rather than failing validation on a missing key.
    """
    # Build the minimal valid ResearchResult payload via model_construct
    # to dodge the heavy nested-fields requirement; the field default is
    # what's under test, not the rest of the shape.
    result = ResearchResult.model_construct(
        session_id="00000000-0000-0000-0000-000000000000",
        tier="basic",
    )
    assert result.low_explanation is False


@pytest.mark.asyncio
async def test_low_explanation_true_when_two_retries_both_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: 2 retries both return empty ``gap_explanation``. The
    final ResearchResult has ``low_explanation=True`` and
    ``validation_report.gap_explanation`` is None or empty (NOT a
    synthesized fallback).
    """
    sid: UUID = uuid4()
    url = "https://example.com/a"

    async def _fake_rag(*a: Any, **kw: Any) -> list[RagChunk]:
        return [_make_chunk(url)]

    monkeypatch.setattr(basic_mod, "rag_query", _fake_rag)

    p1 = _payload(url, gap_explanation=None)
    p2 = _payload(url, gap_explanation="")
    p3 = _payload(url, gap_explanation=None)

    store = _store_with_sources([url])
    client = _mk_openai_client([json.dumps(p1), json.dumps(p2), json.dumps(p3)])

    result = await basic_mod.generate(sid, "idea", store, openai_client=client)

    assert result.low_explanation is True
    # Honest surfacing — no fabricated narrative. The field is None or
    # empty; the renderer keys off `low_explanation` to display the
    # "model did not produce an explanation" affordance.
    val = result.validation_report.gap_explanation
    assert val is None or val == "" or not val.strip()
    # The structural verdict shape is unaffected by the missing prose.
    assert result.validation_report.gap_classification == "Partial:UX"


def test_verdict_hash_excludes_low_explanation() -> None:
    """``low_explanation`` is a prose-surface property, not a structural
    verdict signal. Two ResearchResults that differ ONLY in that flag
    must produce the same verdict_hash so reruns under the same
    retrieval reproduce the digest. Same posture as ``gap_explanation``
    itself, ``pro_session_summary``, post-processor readouts.
    """
    base = ResearchResult.model_construct(
        session_id="00000000-0000-0000-0000-000000000000",
        tier="basic",
        sources=[],
        low_explanation=False,
    )
    flipped = ResearchResult.model_construct(
        session_id="00000000-0000-0000-0000-000000000000",
        tier="basic",
        sources=[],
        low_explanation=True,
    )
    # Stub out the validation_report attr access path used by
    # _verdict_payload — we just need both calls to walk the same code.
    from types import SimpleNamespace

    vr_stub = SimpleNamespace(gap_classification="Partial:UX")
    base.validation_report = vr_stub  # type: ignore[assignment]
    flipped.validation_report = vr_stub  # type: ignore[assignment]
    # verdict default is REFINE on both.
    assert verdict_hash("idea", base) == verdict_hash("idea", flipped)
