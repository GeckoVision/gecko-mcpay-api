"""v0.1.10 — strict-mode + retry path for the ``gap_explanation`` field.

The dogfood repro was: kimi-k2.6 via OpenRouter shipped a basic-tier
research result whose ``validation_report.gap_classification`` was
``Partial:UX`` but ``gap_explanation`` was missing. The fix is twofold:

1. **Strict mode** on the OpenAI plane — the schema produced by
   ``llm_helpers.pydantic_to_strict_schema`` lists every property in
   ``required``, including ``gap_explanation``. The model literally
   cannot decode a sequence that omits the field; if it has nothing to
   say, the schema permits ``null`` (the field is ``str | None``) but
   the field MUST be present on the wire.

2. **Retry path** for the OpenRouter / json_object plane (kimi etc.) —
   when ``_has_gap_explanation`` returns False after the first call, the
   synthesizer re-prompts with ``_GAP_EXPLANATION_RETRY_SUFFIX`` (model
   self-correction prompt). Capped at ``_GAP_EXPLANATION_MAX_RETRIES``;
   gated on cost so expensive providers don't 3x their spend.

These tests pin both behaviors at the model boundary. They mock at the
AsyncOpenAI seam so no live LLM call fires.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from gecko_core.llm_helpers import pydantic_to_strict_schema
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
    """Mocks the with_raw_response.create surface like the existing tests."""
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


# ---------------------------------------------------------------------------
# 1a — Strict schema verification
# ---------------------------------------------------------------------------


def test_strict_schema_lists_gap_explanation_as_required() -> None:
    """The strict-mode schema for ``_LLMOutput`` puts every ValidationReport
    property in ``required``, including ``gap_explanation``. Under
    OpenAI Structured Outputs strict mode this means the field MUST be
    present on the wire — the model can emit ``null`` (the field is
    ``str | None``) but it cannot omit the key.

    This is the schema-level guarantee that closes the v0.1.9 dogfood gap
    on the OpenAI plane. Without this assertion a future change to
    ``pydantic_to_strict_schema`` that silently drops Optional fields
    from ``required`` would silently regress the strict-mode contract.
    """
    schema = pydantic_to_strict_schema(basic_mod._LLMOutput)
    defs = schema.get("$defs", {})
    vr = defs.get("ValidationReport")
    assert vr is not None, "ValidationReport definition missing from strict schema"
    required = vr.get("required", [])
    assert "gap_explanation" in required, (
        f"strict-mode schema must list gap_explanation in required; got {required}"
    )
    # Also verify the property exists with a nullable type so emitting
    # `null` is decoder-valid (the model isn't forced to fabricate text).
    props = vr.get("properties", {})
    ge_prop = props.get("gap_explanation")
    assert ge_prop is not None, "gap_explanation property missing from properties"
    # Pydantic emits `anyOf: [{type: string}, {type: null}]` for `str | None`.
    any_of = ge_prop.get("anyOf")
    assert any_of is not None and any(p.get("type") == "null" for p in any_of), (
        "gap_explanation must allow null in the strict schema"
    )


# ---------------------------------------------------------------------------
# 1b — Retry path for the json_object plane (OpenRouter / kimi)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retry_fires_when_gap_explanation_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the first call returns no ``gap_explanation``, the synthesizer
    re-prompts with the self-correction suffix and uses the retry's
    response when it complies. The brief: cap at 2 retries; we assert the
    second call fires and the populated explanation lifts onto the result.
    """
    sid: UUID = uuid4()
    url = "https://example.com/a"

    async def _fake_rag(*a: Any, **kw: Any) -> list[RagChunk]:
        return [_make_chunk(url)]

    monkeypatch.setattr(basic_mod, "rag_query", _fake_rag)

    first_payload = _payload(url, gap_explanation=None)  # field absent
    fixed_explanation = (
        "The UX is the gap, not the category — Stripe Radar covers fraud "
        "detection but its replay-debug flow assumes you already know which "
        "webhook fired [1]. Ship the replay-from-error path before competing "
        "on the dashboard."
    )
    second_payload = _payload(url, gap_explanation=fixed_explanation)

    store = _store_with_sources([url])
    client = _mk_openai_client([json.dumps(first_payload), json.dumps(second_payload)])

    result = await basic_mod.generate(sid, "an idea", store, openai_client=client)

    # Retry fired: the create mock saw exactly 2 calls.
    assert client.chat.completions.with_raw_response.create.await_count == 2
    # The retry's explanation lifted onto the result.
    got = result.validation_report.gap_explanation
    assert got is not None and got.strip(), "retry should have populated gap_explanation"
    assert "[1]" in got
    # `low_explanation` flag is False once the retry succeeds.
    assert result.low_explanation is False


@pytest.mark.asyncio
async def test_retry_stops_after_two_attempts_and_sets_low_explanation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two retries both return empty/missing ``gap_explanation`` — the
    synthesizer accepts the missing field, sets ``low_explanation=True``,
    and leaves ``validation_report.gap_explanation`` as None. NO synthesis.

    Total calls = 3 (initial + 2 retries). No 3rd retry.
    """
    sid: UUID = uuid4()
    url = "https://example.com/a"

    async def _fake_rag(*a: Any, **kw: Any) -> list[RagChunk]:
        return [_make_chunk(url)]

    monkeypatch.setattr(basic_mod, "rag_query", _fake_rag)

    # All three responses miss gap_explanation. We use empty-string and
    # None and absent-key to cover the three observed shapes.
    p1 = _payload(url, gap_explanation=None)  # absent
    p2 = _payload(url, gap_explanation="")  # empty string
    p3 = _payload(url, gap_explanation="   ")  # whitespace-only

    store = _store_with_sources([url])
    client = _mk_openai_client([json.dumps(p1), json.dumps(p2), json.dumps(p3)])

    result = await basic_mod.generate(sid, "an idea", store, openai_client=client)

    # Bounded: at most initial + 2 retries = 3 LLM calls. Brief says cap
    # retries at 2 — the budget is respected.
    assert client.chat.completions.with_raw_response.create.await_count == 3
    # Honest surfacing — no synthesized fallback.
    assert result.validation_report.gap_explanation in (None, "", "   ")
    # Pydantic's None vs "" — we accept either; the operator-visible
    # signal is the flag, not the field shape.
    assert result.low_explanation is True
