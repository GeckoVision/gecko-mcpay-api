"""Single source of truth for the categorized-knowledge taxonomy (S20-A1).

The Mongo chunk store partitions on TWO orthogonal axes: a knowledge
``Category`` (7 dimensions) and an app ``Vertical`` (~11 seeded). Every
chunk written carries both, plus a ``KnowledgeSource`` indicating where
the raw text came from.

Per Pattern A in CLAUDE.md, every consumer imports from this module —
no string-typed verticals or categories anywhere downstream. The
schema-drift test in ``tests/knowledge/test_taxonomy_consistency.py``
mirrors ``tests/test_payment_mode_consistency.py`` and asserts the
constant tuples and Literal definitions cannot drift.

Subcategories are NOT a Literal — they are free-form strings validated
at write time against ``SUBCATEGORIES``. Per the brainstorm decision,
``regulated`` lives as ``business_financial.regulatory`` (subcategory),
not a top-level Category.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final, Literal, TypedDict

# ---------------------------------------------------------------------------
# Knowledge category — the 7-dimension partition.
# ---------------------------------------------------------------------------

Category = Literal[
    "market_intelligence",
    "business_financial",
    "investment_signals",
    "product",
    "technical_engineering",
    "ai_ml",
    "design_ux",
]
"""Static type alias. Keep in sync with CATEGORIES manually — the
schema-drift test verifies they match (typing.get_args(Category))."""

CATEGORIES: Final[tuple[Category, ...]] = (
    "market_intelligence",
    "business_financial",
    "investment_signals",
    "product",
    "technical_engineering",
    "ai_ml",
    "design_ux",
)
"""Runtime tuple — used by Mongo validators and runtime enum checks."""


# ---------------------------------------------------------------------------
# App vertical — the ~11-cell seed taxonomy.
# ---------------------------------------------------------------------------

Vertical = Literal[
    "neobank",
    "dex",
    "marketplace",
    "prediction_market",
    "indexer",
    "b2b_saas",
    "consumer_social",
    "ai_agent_platform",
    "gaming",
    "infra_devtool",
    "unknown",
]
"""Static type alias. Keep in sync with VERTICALS manually."""

VERTICALS: Final[tuple[Vertical, ...]] = (
    "neobank",
    "dex",
    "marketplace",
    "prediction_market",
    "indexer",
    "b2b_saas",
    "consumer_social",
    "ai_agent_platform",
    "gaming",
    "infra_devtool",
    "unknown",
)
"""Runtime tuple — ``unknown`` is the catch-all when classification fails."""


# ---------------------------------------------------------------------------
# Knowledge source — where the chunk's raw text originated.
# ---------------------------------------------------------------------------

KnowledgeSource = Literal[
    "web",
    "tavily",
    "twit_sh",
    "bazaar",
    "pay_sh",
    "user_query",
    "enriched_output",
]
"""Static type alias. Keep in sync with KNOWLEDGE_SOURCES manually."""

KNOWLEDGE_SOURCES: Final[tuple[KnowledgeSource, ...]] = (
    "web",
    "tavily",
    "twit_sh",
    "bazaar",
    "pay_sh",
    "user_query",
    "enriched_output",
)
"""Runtime tuple — used by Mongo validators."""


# ---------------------------------------------------------------------------
# Subcategory map — free-form strings, validated against this map at
# write time. Seed each Category with at least one canonical subcategory.
# ---------------------------------------------------------------------------

SUBCATEGORIES: Final[dict[Category, tuple[str, ...]]] = {
    "market_intelligence": ("competitor", "trend", "tam", "segment"),
    "business_financial": ("regulatory", "unit_economics", "pricing", "gtm"),
    "investment_signals": ("funding_round", "valuation", "investor_thesis", "exit"),
    "product": ("feature", "roadmap", "user_feedback", "positioning"),
    "technical_engineering": ("architecture", "infra", "performance", "security"),
    "ai_ml": ("model", "rag", "eval", "prompt"),
    "design_ux": ("flow", "component", "research", "accessibility"),
}
"""Canonical subcategory seeds per Category. Mongo writes validate
``subcategory`` against this map. Subcategories are open-set and grow
over time — adding one is a single-line edit here."""


# ---------------------------------------------------------------------------
# ChunkMetadata — per-chunk bookkeeping carried alongside the embedding.
# ---------------------------------------------------------------------------


class ChunkMetadata(TypedDict):
    """Per-chunk metadata stored in Mongo alongside text + embedding.

    ``pioneer`` is True when this chunk was the first to seed an empty
    ``(vertical, category)`` cell — see future ticket A7 for the
    instrumentation that flips it.
    """

    confidence: float
    usage_count: int
    timestamp: datetime
    pioneer: bool


def is_valid_subcategory(category: Category, subcategory: str) -> bool:
    """Return True iff ``subcategory`` is registered under ``category``.

    Used by the Mongo write path. Unknown categories return False rather
    than raising — callers should already have validated ``category``
    against ``CATEGORIES``.
    """
    allowed = SUBCATEGORIES.get(category)
    if allowed is None:
        return False
    return subcategory in allowed


def default_chunk_metadata() -> ChunkMetadata:
    """Return a fresh metadata dict for a brand-new chunk.

    ``timestamp`` is timezone-aware UTC. ``pioneer`` defaults False; the
    A7 instrumentation flips it after checking for an empty cell.
    """
    return ChunkMetadata(
        confidence=0.0,
        usage_count=0,
        timestamp=datetime.now(UTC),
        pioneer=False,
    )


__all__ = [
    "CATEGORIES",
    "KNOWLEDGE_SOURCES",
    "SUBCATEGORIES",
    "VERTICALS",
    "Category",
    "ChunkMetadata",
    "KnowledgeSource",
    "Vertical",
    "default_chunk_metadata",
    "is_valid_subcategory",
]
