"""S20-A6 — pro-tier wiring: ``_run_pro_debate`` fires bump_usage_counts.

The pro pipeline propagates ``cited_doc_ids`` from the basic-tier result
via ``model_copy``; the debate doesn't recompute them. So the bump fires
on the post-debate result with the same id list the basic tier validated.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest


@pytest.fixture
def stubbed_rag(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    async def _fake_rag_query(*_a: object, **_kw: object) -> list[Any]:
        return [
            SimpleNamespace(
                source_url="https://example.com/a",
                chunk_index=0,
                similarity=0.9,
                text="Hosts care about local recommendations.",
            )
        ]

    monkeypatch.setattr("gecko_core.workflows.rag_query", _fake_rag_query, raising=False)
    monkeypatch.setattr("gecko_core.rag.query.rag_query", _fake_rag_query, raising=False)


@pytest.fixture
def stubbed_groupchat(monkeypatch: pytest.MonkeyPatch) -> None:
    canned = {
        "analyst": "TAM is real.",
        "critic": "Wedge is fuzzy.",
        "architect": "Next.js + Supabase.",
        "scoper": "V1 in 4 days.",
        "judge": "7/10 — ship V1.",
    }

    class _FakeAgent:
        def __init__(self, name: str) -> None:
            self.name = name

        async def a_generate_reply(self, messages: object = None) -> str:
            return canned[self.name]

    class _FakeChat:
        def __init__(self) -> None:
            self.agents = [_FakeAgent(n) for n in canned]
            self.messages: list[dict[str, object]] = []

    class _FakeManager:
        def __init__(self) -> None:
            self.groupchat = _FakeChat()

    def _fake_build(_cfg: dict[str, object], **_kw: object) -> _FakeManager:
        return _FakeManager()

    from gecko_core.orchestration import pro as pro_mod

    monkeypatch.setattr(pro_mod, "build_groupchat", _fake_build)


def _make_fake_store() -> AsyncMock:
    store = AsyncMock()
    store.appended_events: list[dict[str, Any]] = []  # type: ignore[attr-defined]
    store.appended_costs: list[dict[str, Any]] = []  # type: ignore[attr-defined]

    async def _append_pro_event(**kw: Any) -> int:
        store.appended_events.append(kw)  # type: ignore[attr-defined]
        return len(store.appended_events)  # type: ignore[attr-defined]

    async def _append_session_cost(**kw: Any) -> int:
        store.appended_costs.append(kw)  # type: ignore[attr-defined]
        return len(store.appended_costs)  # type: ignore[attr-defined]

    store.append_pro_event = AsyncMock(side_effect=_append_pro_event)
    store.append_session_cost = AsyncMock(side_effect=_append_session_cost)
    return store


async def _drain_pending(seen_before: set[asyncio.Task[Any]]) -> None:
    pending = [t for t in asyncio.all_tasks() if t not in seen_before and not t.done()]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


async def test_pro_pipeline_fires_bump_with_cited_doc_ids(
    stubbed_rag: None,
    stubbed_groupchat: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gecko_core.models import ResearchResult, SourceInfo
    from gecko_core.workflows import _run_pro_debate

    bump_mock = AsyncMock(return_value=1)
    monkeypatch.setattr(
        "gecko_core.db.mongo_chunks.bump_usage_counts",
        bump_mock,
    )

    fake_store = _make_fake_store()
    sid = uuid4()

    base_result = ResearchResult(
        session_id=str(sid),
        tier="basic",
        business_plan={  # type: ignore[arg-type]
            "problem": "p",
            "icp": "i",
            "solution": "s",
            "market": "m",
            "business_model": "bm",
            "channels": "c",
            "risks": ["r"],
            "citations": [],
        },
        validation_report={  # type: ignore[arg-type]
            "market_size_signal": "x",
            "competitor_analysis": "y",
            "demand_evidence": "z",
            "risk_flags": [],
            "citations": [],
        },
        prd={  # type: ignore[arg-type]
            "v1_scope": ["a"],
            "v2_scope": [],
            "v3_scope": [],
            "acceptance_criteria": ["b"],
            "non_functional": [],
            "success_metrics": [],
            "citations": [],
        },
        sources=[
            SourceInfo(
                url="https://example.com/a",
                type="web",
                chunk_count=1,
                indexed_at=datetime.now(UTC),
            )
        ],
        cited_doc_ids=["chunk-AAA", "chunk-BBB"],
    )

    seen_before = set(asyncio.all_tasks())
    result = await _run_pro_debate(sid, "an idea worth validating", base_result, fake_store)
    await _drain_pending(seen_before)

    assert result.tier == "pro"
    assert result.cited_doc_ids == ["chunk-AAA", "chunk-BBB"]
    bump_mock.assert_awaited_once_with(["chunk-AAA", "chunk-BBB"])
