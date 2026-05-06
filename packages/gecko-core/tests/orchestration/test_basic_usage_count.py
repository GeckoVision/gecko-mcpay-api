"""S20-A6 — basic-tier wiring: synth completion fires bump_usage_counts.

Asserts that ``basic.generate``:
  (a) schedules ``bump_usage_counts`` (via ``asyncio.create_task``) with the
      result's ``cited_doc_ids`` when the LLM produced citations, and
  (b) does NOT call ``bump_usage_counts`` when ``cited_doc_ids`` is empty
      (no wasted Mongo trip).

We monkeypatch ``bump_usage_counts`` to an ``AsyncMock`` so we can assert
call args without reaching Mongo. The fire-and-forget task is drained via
``asyncio.gather`` over pending tasks before assertion to avoid races.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest


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
            SourceInfo(
                url=u,
                type="web",
                chunk_count=1,
                indexed_at=datetime.now(UTC),
            )
            for u in urls
        ]

    async def list_sources(self, _session_id: Any) -> list[Any]:
        return self._sources

    async def add_cost(self, *_a: Any, **_k: Any) -> None:
        return None


def _llm_payload(citations: list[dict[str, Any]]) -> str:
    return json.dumps(
        {
            "business_plan": {
                "problem": "p",
                "icp": "i",
                "solution": "s",
                "market": "m",
                "business_model": "bm",
                "channels": "c",
                "risks": [],
                "citations": [
                    {
                        "source_url": "https://example.com/a",
                        "chunk_index": 0,
                        "similarity": 0.85,
                    }
                ],
            },
            "validation_report": {
                "market_size_signal": "x",
                "competitor_analysis": "x",
                "demand_evidence": "x",
                "risk_flags": [],
                "citations": [
                    {
                        "source_url": "https://example.com/a",
                        "chunk_index": 0,
                        "similarity": 0.85,
                    }
                ],
                "gap_classification": "Partial:UX",
                "gap_summary": "competitor X covers fraud but not replay debugging",
                "gap_explanation": ("The UX is the gap [1]. Ship the replay-from-error path."),
            },
            "prd": {
                "v1_scope": ["x"],
                "v2_scope": ["x"],
                "v3_scope": ["x"],
                "acceptance_criteria": ["x"],
                "non_functional": ["x"],
                "success_metrics": ["x"],
                "citations": [
                    {
                        "source_url": "https://example.com/a",
                        "chunk_index": 0,
                        "similarity": 0.85,
                    }
                ],
            },
            "citations": citations,
        }
    )


async def _drain_pending(seen_before: set[asyncio.Task[Any]]) -> None:
    """Wait for tasks created during the call (the fire-and-forget bump)."""
    pending = [t for t in asyncio.all_tasks() if t not in seen_before and not t.done()]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


async def test_generate_fires_bump_when_citations_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gecko_core.orchestration import basic as basic_mod

    chunks = [_mk_chunk(0, "chunk-AAA")]

    async def _fake_rag_query(*_a: object, **_kw: object) -> list[Any]:
        return chunks

    async def _fake_call_llm(**_kw: Any) -> tuple[str, float]:
        payload = _llm_payload(
            [
                {
                    "idx": 1,
                    "doc_id": "chunk-AAA",
                    "url": "https://example.com/a",
                    "span": "passage",
                }
            ]
        )
        return payload, 0.0001

    bump_mock = AsyncMock(return_value=1)
    monkeypatch.setattr(basic_mod, "rag_query", _fake_rag_query)
    monkeypatch.setattr(basic_mod, "_call_llm", _fake_call_llm)
    # Patch the symbol where _dispatch_usage_count_bump imports it from.
    monkeypatch.setattr(
        "gecko_core.db.mongo_chunks.bump_usage_counts",
        bump_mock,
    )

    store = _FakeStore(["https://example.com/a"])

    seen_before = set(asyncio.all_tasks())
    result = await basic_mod.generate(
        session_id=uuid4(),
        idea="test idea",
        store=store,  # type: ignore[arg-type]
        openai_client=AsyncMock(),
    )
    await _drain_pending(seen_before)

    assert result.cited_doc_ids == ["chunk-AAA"]
    bump_mock.assert_awaited_once_with(["chunk-AAA"])


async def test_generate_skips_bump_when_no_citations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gecko_core.orchestration import basic as basic_mod

    chunks = [_mk_chunk(0, "chunk-AAA")]

    async def _fake_rag_query(*_a: object, **_kw: object) -> list[Any]:
        return chunks

    async def _fake_call_llm(**_kw: Any) -> tuple[str, float]:
        # Empty top-level citations list — model didn't cite any chunk_id.
        return _llm_payload([]), 0.0001

    bump_mock = AsyncMock(return_value=0)
    monkeypatch.setattr(basic_mod, "rag_query", _fake_rag_query)
    monkeypatch.setattr(basic_mod, "_call_llm", _fake_call_llm)
    monkeypatch.setattr(
        "gecko_core.db.mongo_chunks.bump_usage_counts",
        bump_mock,
    )

    store = _FakeStore(["https://example.com/a"])

    seen_before = set(asyncio.all_tasks())
    result = await basic_mod.generate(
        session_id=uuid4(),
        idea="test idea",
        store=store,  # type: ignore[arg-type]
        openai_client=AsyncMock(),
    )
    await _drain_pending(seen_before)

    assert result.cited_doc_ids == []
    bump_mock.assert_not_called()
