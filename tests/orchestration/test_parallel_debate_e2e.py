"""S12-LATENCY-01 — stub-mode e2e: pro tier verdict shape unchanged after parallelization.

We're not measuring latency here (the unit tests in `test_parallel_debate.py`
cover concurrency proofs with controlled delays). This test guards that the
end-to-end pro-tier workflow still produces a well-formed transcript +
session summary after the analyst/critic parallel refactor — i.e. the
verdict shape is unchanged.
"""

from __future__ import annotations

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
                text="Some context.",
            )
        ]

    monkeypatch.setattr("gecko_core.workflows.rag_query", _fake_rag_query, raising=False)
    monkeypatch.setattr("gecko_core.rag.query.rag_query", _fake_rag_query, raising=False)


@pytest.fixture
def stubbed_groupchat(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace AG2 with a 5-voice fake — analyst/critic deliberately complete out of order."""
    import asyncio

    canned = {
        "analyst": ("TAM is real.", 0.05),  # analyst slower
        "critic": ("Wedge is fuzzy.", 0.0),  # critic finishes first
        "architect": ("Next.js + Supabase.", 0.0),
        "scoper": ("V1 in 4 days.", 0.0),
        "judge": ("8/10 — ship V1.", 0.0),
    }

    class _FakeAgent:
        def __init__(self, name: str) -> None:
            self.name = name

        async def a_generate_reply(self, messages: object = None) -> str:
            text, delay = canned[self.name]
            if delay:
                await asyncio.sleep(delay)
            return text

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


async def test_pro_tier_verdict_shape_unchanged_under_parallel_dispatch(
    stubbed_rag: None,
    stubbed_groupchat: None,
) -> None:
    """Stub-mode pro tier still emits the expected ResearchResult shape.

    Specifically: tier flipped to 'pro', transcript has 5 turns in canonical
    order, session summary populated from the judge — same contract Sprint
    11 callers depend on, after the S12-LATENCY-01 refactor.
    """
    from gecko_core.models import ResearchResult, SourceInfo
    from gecko_core.workflows import _run_pro_debate

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
                url="https://example.com/a",  # type: ignore[arg-type]
                type="web",
                chunk_count=1,
                indexed_at=datetime.now(UTC),
            )
        ],
    )

    result = await _run_pro_debate(sid, "an idea worth validating", base_result, fake_store)

    # Same shape as pre-refactor.
    assert result.tier == "pro"
    assert result.transcript is not None
    assert len(result.transcript["turns"]) == 5
    # Canonical order preserved despite analyst being the slower of the parallel pair.
    assert [t["agent"] for t in result.transcript["turns"]] == [
        "analyst",
        "critic",
        "architect",
        "scoper",
        "judge",
    ]
    assert result.pro_session_summary == "8/10 — ship V1."

    # Event journal: 5 turn_start + 5 turn_end + 1 final.
    assert len(fake_store.appended_events) == 11  # type: ignore[attr-defined]
    seqs = [e["seq"] for e in fake_store.appended_events]  # type: ignore[attr-defined]
    assert seqs == sorted(seqs)
