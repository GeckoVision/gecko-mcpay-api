"""Gecko core SDK — Builder Bootstrap Platform business logic.

Public API:
    research(idea: str, *, tier: Tier = "basic", urls: list[str] | None = None) -> ResearchResult
    ask(session_id: str, question: str) -> AskResult
    sources(session_id: str) -> list[SourceInfo]

Everything else is internal — CLI, MCP, and API call only these three functions.
"""

from gecko_core.models import (
    AskResult,
    ResearchResult,
    SourceInfo,
    Tier,
)
from gecko_core.workflows import ask, list_sources, research, sources

__all__ = [
    "AskResult",
    "ResearchResult",
    "SourceInfo",
    "Tier",
    "ask",
    "list_sources",
    "research",
    "sources",
]
