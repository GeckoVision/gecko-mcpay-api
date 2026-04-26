"""High-level workflows. CLI, MCP, and API call exactly these three functions.

Implementation is delegated to submodules:
    research → ingestion + payments + orchestration + sessions
    ask      → rag + sessions
    sources  → sessions

This file is the boundary. Don't add side effects here — orchestrate, don't compute.
"""

from __future__ import annotations

from gecko_core.models import AskResult, ResearchResult, SourceInfo, Tier


async def research(
    idea: str,
    *,
    tier: Tier = "basic",
    urls: list[str] | None = None,
) -> ResearchResult:
    """Run the full discover → index → pay → generate workflow.

    Args:
        idea: Plain-language startup idea.
        tier: "basic" (single LLM pass) or "pro" (AutoGen GroupChat).
        urls: Optional seed URLs. When omitted, sources auto-discovered via Tavily.

    Returns:
        ResearchResult containing business_plan, validation_report, prd, and sources.

    Raises:
        PaymentRequiredError: x402 gate failed (live mode only).
        IngestionError: source extraction failed.
        OrchestrationError: LLM generation failed validation.
    """
    raise NotImplementedError("port from existing bb research implementation")


async def ask(session_id: str, question: str) -> AskResult:
    """Answer a follow-up question grounded in a session's knowledge base."""
    raise NotImplementedError("port from existing bb ask implementation")


async def sources(session_id: str) -> list[SourceInfo]:
    """List all indexed sources for a session."""
    raise NotImplementedError("port from existing bb sources implementation")
