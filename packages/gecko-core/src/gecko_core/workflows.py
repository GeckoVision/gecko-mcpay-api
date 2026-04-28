"""High-level workflows. CLI, MCP, and API call exactly these three functions.

The 7-step user flow (see `docs/implementation-plan.md`):

  1. User describes idea
  2. discover() OR validate provided URLs
  3. surface candidate sources for approval
  4. (after approval) payment gate
  5. ingest sources → chunks + embeddings
  6. orchestrate (basic | pro) → 3 documents
  7. return ResearchResult; KB stays alive for follow-up `ask`

Persistence happens BEFORE expensive work — the session row is inserted up
front so a crash mid-pipeline doesn't lose state. The payment gate runs
BEFORE ingestion so a payment failure can't burn OpenAI/Tavily credits.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from uuid import UUID

from openai import AsyncOpenAI

from gecko_core.ingestion import discover, ingest
from gecko_core.ingestion.settings import get_ingestion_settings
from gecko_core.models import (
    AskResult,
    Citation,
    ResearchResult,
    SourceCandidate,
    SourceInfo,
    SourceType,
    Tier,
)
from gecko_core.orchestration.basic import _ensure_tier
from gecko_core.orchestration.basic import generate as basic_generate
from gecko_core.orchestration.settings import get_orchestration_settings
from gecko_core.payments import run_payment_gate
from gecko_core.payments.x402_client import _settings as _payment_settings
from gecko_core.rag.query import rag_query
from gecko_core.sessions.store import PaymentMode, SessionStore

logger = logging.getLogger(__name__)


ApprovalCallback = Callable[[list[SourceCandidate]], Awaitable[bool]]
ProgressCallback = Callable[[str], None]


def _classify(url: str) -> SourceType:
    return "youtube" if ("youtube.com" in url or "youtu.be" in url) else "web"


def _candidates_from_urls(urls: list[str]) -> list[SourceCandidate]:
    # Pydantic coerces str → HttpUrl at validation; mypy sees the field as
    # HttpUrl-strict, hence the cast.
    return [
        SourceCandidate.model_validate({"url": u, "title": "", "type": _classify(u), "score": 1.0})
        for u in urls
        if u
    ]


def _emit(progress: ProgressCallback | None, msg: str) -> None:
    if progress is not None:
        progress(msg)


async def research(
    idea: str,
    *,
    tier: Tier = "basic",
    urls: list[str] | None = None,
    auto_approve: bool = True,
    approval_callback: ApprovalCallback | None = None,
    store: SessionStore | None = None,
    progress_callback: ProgressCallback | None = None,
    skip_payment_gate: bool = False,
    session_id: UUID | None = None,
) -> ResearchResult:
    """Run the full discover → approve → pay → index → generate workflow.

    Args:
        idea: Plain-language startup idea.
        tier: "basic" (single LLM pass) or "pro" (Phase 6, NotImplemented).
        urls: Optional seed URLs. When omitted, sources auto-discovered via Tavily.
        auto_approve: When True, skip the approval prompt. The CLI's `--yes`
            flag wires through here. When False, `approval_callback` is invoked.
        approval_callback: Async callable that receives the candidate list and
            returns True to proceed. Required when `auto_approve` is False.
        store: Inject a SessionStore (for tests). Defaults to env-built.
        progress_callback: Optional sync callable for UI progress strings.

    Returns:
        ResearchResult with business_plan, validation_report, prd, and sources.

    Raises:
        PaymentRequiredError: x402 gate failed.
        NotImplementedError: tier == "pro".
        OrchestrationError: LLM output failed validation after retry.
        RuntimeError: user declined approval.
    """
    _ensure_tier(tier)

    store = store or SessionStore.from_env()
    payment_mode: PaymentMode = _payment_settings().mode

    # Step 1 — persist session row before any expensive work, OR reuse one
    # the API already created (async pattern: API returns 202 with session_id
    # immediately, then runs this workflow under that pre-existing row).
    if session_id is None:
        session_id = await store.create(idea=idea, tier=tier, payment_mode=payment_mode)
    _emit(progress_callback, f"Session {session_id} created")

    # Step 2 — discover or validate.
    if urls:
        candidates = _candidates_from_urls(urls)
        _emit(progress_callback, f"Validating {len(candidates)} provided URLs")
    else:
        _emit(progress_callback, "Discovering sources via Tavily")
        candidates = await discover(idea)
        # Single advanced-search call per discovery; charge it to the session.
        from gecko_core.ingestion.discovery import TAVILY_ADVANCED_SEARCH_USD

        await store.add_cost(session_id, "tavily", TAVILY_ADVANCED_SEARCH_USD)

    if not candidates:
        await store.update_status(session_id, "failed")
        raise RuntimeError("no candidate sources found")

    # Step 3 — approval.
    if not auto_approve:
        if approval_callback is None:
            raise ValueError("approval_callback required when auto_approve=False")
        approved = await approval_callback(candidates)
        if not approved:
            await store.update_status(session_id, "failed")
            raise RuntimeError("user declined source approval")

    # Step 4 — payment gate. BEFORE ingestion. Stub passes; live can fail.
    # In v3, gecko-api's x402 middleware handles payment before this runs,
    # so the API passes skip_payment_gate=True to avoid double-charging.
    if not skip_payment_gate:
        _emit(progress_callback, "Running payment gate")
        await run_payment_gate(session_id, tier, store)
    else:
        _emit(progress_callback, "Payment already verified by API middleware")

    # Step 5 — ingest.
    _emit(progress_callback, f"Indexing {len(candidates)} sources")
    ingestion_result = await ingest(session_id, candidates, store)
    logger.info(
        "ingestion done session_id=%s indexed=%d skipped=%d failed=%d",
        session_id,
        ingestion_result.indexed,
        ingestion_result.skipped,
        ingestion_result.failed,
    )

    if ingestion_result.indexed == 0:
        await store.update_status(session_id, "failed")
        raise RuntimeError("ingestion produced zero indexed sources")

    # Step 6 — orchestrate.
    await store.update_status(session_id, "generating")
    _emit(progress_callback, "Generating documents")
    result = await basic_generate(session_id, idea, store)

    # Step 7 — mark complete and return.
    await store.update_status(session_id, "complete")
    _emit(progress_callback, "Done")
    return result


async def ask(
    session_id: UUID | str,
    question: str,
    store: SessionStore | None = None,
) -> AskResult:
    """Answer a follow-up question grounded in a session's knowledge base."""
    sid = session_id if isinstance(session_id, UUID) else UUID(str(session_id))
    store = store or SessionStore.from_env()

    chunks = await rag_query(sid, question, top_k=8, store=store)
    if not chunks:
        return AskResult(
            session_id=str(sid),
            answer=(
                "No relevant context was found in this session's knowledge "
                "base. Try a different question or re-run research with more "
                "sources."
            ),
            citations=[],
        )

    orch = get_orchestration_settings()
    ingest_s = get_ingestion_settings()
    client = AsyncOpenAI(api_key=ingest_s.openai_api_key.get_secret_value())

    context = "\n\n".join(
        f"[{i}] (source: {c.source_url}) {c.text}" for i, c in enumerate(chunks, 1)
    )

    resp = await client.chat.completions.create(
        model=orch.chat_model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You answer questions strictly from the provided context. "
                    "Cite chunk numbers like [1], [2] inline. If the context "
                    "is insufficient, say so."
                ),
            },
            {
                "role": "user",
                "content": f"Context:\n{context}\n\nQuestion: {question}",
            },
        ],
        temperature=orch.temperature,
    )
    answer = resp.choices[0].message.content or ""

    citations = [
        Citation(
            source_url=c.source_url,
            chunk_index=c.chunk_index,
            similarity=c.similarity,
        )
        for c in chunks
    ]
    return AskResult(session_id=str(sid), answer=answer, citations=citations)


async def list_sources(
    session_id: UUID | str,
    store: SessionStore | None = None,
) -> list[SourceInfo]:
    """List all indexed sources for a session."""
    sid = session_id if isinstance(session_id, UUID) else UUID(str(session_id))
    store = store or SessionStore.from_env()
    return await store.list_sources(sid)


# Backward-compatible name used by `gecko_core.__init__` re-export.
sources = list_sources


__all__ = ["ask", "list_sources", "research", "sources"]
