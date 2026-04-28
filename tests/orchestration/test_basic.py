"""Unit tests for orchestration.basic.

Mocks: the OpenAI client, the RAG query layer, and the SessionStore. We
exercise the happy path, the validation-retry path, and the
citation-mismatch failure path.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from gecko_core.models import SourceInfo
from gecko_core.orchestration import basic as basic_mod
from gecko_core.rag.query import RagChunk


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


def _valid_payload(url: str) -> dict[str, Any]:
    cit = [{"source_url": url, "chunk_index": 0, "similarity": 0.9}]
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
        "validation_report": {
            "market_size_signal": "m",
            "competitor_analysis": "c",
            "demand_evidence": "d",
            "risk_flags": ["rf"],
            "citations": cit,
        },
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
    """Build an AsyncOpenAI-shaped mock for the v3 raw-response surface.

    Orchestration uses `client.chat.completions.with_raw_response.create()` so it
    can read the `x-clawrouter-cost-usd` header. Each call returns a raw object
    whose `.parse()` yields the typical chat-completion shape and whose
    `.headers.get(...)` returns None (no cost header → token-based fallback).
    """
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


@pytest.mark.asyncio
async def test_generate_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    sid: UUID = uuid4()
    url = "https://example.com/a"
    chunks = [_make_chunk(url)]

    async def _fake_rag(*a: Any, **kw: Any) -> list[RagChunk]:
        return chunks

    monkeypatch.setattr(basic_mod, "rag_query", _fake_rag)

    store = _store_with_sources([url])
    client = _mk_openai_client([json.dumps(_valid_payload(url))])

    result = await basic_mod.generate(sid, "an idea", store, openai_client=client)

    assert result.session_id == str(sid)
    assert result.tier == "basic"
    assert result.business_plan.problem == "p"
    assert len(result.sources) == 1


@pytest.mark.asyncio
async def test_generate_retries_on_validation_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sid: UUID = uuid4()
    url = "https://example.com/a"

    async def _fake_rag(*a: Any, **kw: Any) -> list[RagChunk]:
        return [_make_chunk(url)]

    monkeypatch.setattr(basic_mod, "rag_query", _fake_rag)

    store = _store_with_sources([url])

    # First response: missing `prd` → validation fails. Second: valid.
    bad = json.dumps({"business_plan": {}, "validation_report": {}})
    good = json.dumps(_valid_payload(url))
    client = _mk_openai_client([bad, good])

    result = await basic_mod.generate(sid, "idea", store, openai_client=client)
    assert result.session_id == str(sid)
    # Both calls happened.
    assert client.chat.completions.with_raw_response.create.await_count == 2


@pytest.mark.asyncio
async def test_generate_rejects_unknown_citation_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sid: UUID = uuid4()
    indexed_url = "https://example.com/a"
    bogus_url = "https://hallucinated.example.com/x"

    async def _fake_rag(*a: Any, **kw: Any) -> list[RagChunk]:
        return [_make_chunk(indexed_url)]

    monkeypatch.setattr(basic_mod, "rag_query", _fake_rag)

    store = _store_with_sources([indexed_url])
    client = _mk_openai_client([json.dumps(_valid_payload(bogus_url))])

    with pytest.raises(basic_mod.OrchestrationError, match="unknown URL"):
        await basic_mod.generate(sid, "idea", store, openai_client=client)


def test_ensure_tier_rejects_pro() -> None:
    with pytest.raises(NotImplementedError, match="Phase 6"):
        basic_mod._ensure_tier("pro")
