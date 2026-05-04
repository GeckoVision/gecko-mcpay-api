"""Fixture tests for the 2026-05-03 ``gap_explanation`` field.

The dogfood feedback was that ``gap_classification: "Partial:UX"`` shipped
with no narrative — a viewer can't tell whether the wedge category is weak
or the presentation is shallow. The fix is a 2-3 sentence ``gap_explanation``
that grounds the label in chunks via inline ``[n]`` markers and names the
shipping consequence.

These tests exercise the model boundary (mock at the AsyncOpenAI seam, no
live LLM call) so the eval harness owns live verification separately. We
cover:

  * happy path — explanation populates from a fixture LLM response and
    survives validation through the strict-mode wire (Commit D) and the
    json_object fallback path.
  * inline-`[n]` filter — out-of-range refs are stripped, in-range refs
    survive, prose stays readable.
  * backwards compat — a fixture LLM response that omits the field
    (legacy cassette shape) round-trips with ``gap_explanation is None``.
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
    """Mirrors the helper in test_basic.py — mocks the with_raw_response.create
    surface so the cost-header path is exercised but no network call fires."""
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
async def test_gap_explanation_populates_with_inline_citations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fixture explanation containing valid `[1]` markers survives end-to-end.

    Asserts the schema accepts the field, the inline-ref filter doesn't
    strip in-range markers, and the explanation is non-empty + cited.
    """
    sid: UUID = uuid4()
    url = "https://example.com/a"

    async def _fake_rag(*a: Any, **kw: Any) -> list[RagChunk]:
        return [_make_chunk(url)]

    monkeypatch.setattr(basic_mod, "rag_query", _fake_rag)

    explanation = (
        "The UX is the gap, not the category — competitor X covers fraud "
        "detection but its replay-debug flow assumes you know which webhook "
        "fired [1]. Ship the replay-from-error path before competing on the "
        "dashboard."
    )
    store = _store_with_sources([url])
    client = _mk_openai_client([json.dumps(_payload(url, gap_explanation=explanation))])

    result = await basic_mod.generate(sid, "an idea", store, openai_client=client)

    assert result.validation_report.gap_classification == "Partial:UX"
    got = result.validation_report.gap_explanation
    assert got is not None and got.strip(), "gap_explanation must be non-empty"
    # In-range citation survived the inline-ref filter.
    assert "[1]" in got
    # Sentence-count is bounded — terminal-screen-friendly.
    assert got.count(". ") <= 3, f"explanation longer than 3 sentences: {got!r}"


@pytest.mark.asyncio
async def test_gap_explanation_strips_dangling_inline_refs(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """`[n]` markers outside the chunk range are stripped; in-range survive."""
    import logging

    sid: UUID = uuid4()
    url = "https://example.com/a"

    async def _fake_rag(*a: Any, **kw: Any) -> list[RagChunk]:
        # Two chunks indexed → valid range is [1] and [2]; [9] is dangling.
        return [_make_chunk(url, idx=0), _make_chunk(url, idx=1, sim=0.85)]

    monkeypatch.setattr(basic_mod, "rag_query", _fake_rag)

    bad_explanation = (
        "Pricing is the gap [1], not the category. Competitor X charges "
        "$X/mo [9] which is wrong for indie devs [2]."
    )
    store = _store_with_sources([url])
    client = _mk_openai_client([json.dumps(_payload(url, gap_explanation=bad_explanation))])

    caplog.set_level(logging.WARNING, logger="gecko_core.orchestration.basic")
    result = await basic_mod.generate(sid, "idea", store, openai_client=client)

    got = result.validation_report.gap_explanation
    assert got is not None
    # In-range refs preserved.
    assert "[1]" in got
    assert "[2]" in got
    # Dangling [9] stripped.
    assert "[9]" not in got
    # The drop was logged.
    assert any("gap_explanation.inline_ref.dropped" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_gap_explanation_optional_for_legacy_payloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Legacy LLM responses (and existing cassettes) that omit gap_explanation
    must still round-trip through Pydantic validation (the field is
    ``str | None``). Note: as of v0.1.10 the basic-tier synthesizer
    actively re-prompts when the field is missing; this test covers the
    *Pydantic* compatibility surface, so we feed enough mock responses
    to exhaust the bounded retry loop and assert ``low_explanation`` is
    True at the end. The retry-and-flag wiring itself is exercised in
    ``test_basic_strict_gap_explanation.py`` and
    ``test_basic_low_explanation_flag.py``.
    """
    sid: UUID = uuid4()
    url = "https://example.com/a"

    async def _fake_rag(*a: Any, **kw: Any) -> list[RagChunk]:
        return [_make_chunk(url)]

    monkeypatch.setattr(basic_mod, "rag_query", _fake_rag)

    store = _store_with_sources([url])
    # initial + 2 retries = 3 mock responses, all omitting the field.
    payload_no_exp = json.dumps(_payload(url, gap_explanation=None))
    client = _mk_openai_client([payload_no_exp, payload_no_exp, payload_no_exp])

    result = await basic_mod.generate(sid, "idea", store, openai_client=client)

    # Pydantic accepted the missing field on every pass — backwards-compat
    # with pre-2026-05-03 cassettes. The model surface stays valid.
    assert result.validation_report.gap_explanation is None
    # The structural verdict surface is unchanged for legacy payloads.
    assert result.validation_report.gap_classification == "Partial:UX"
    # v0.1.10 — the synthesizer surfaces the missing field via the flag
    # rather than synthesising a fallback narrative.
    assert result.low_explanation is True
