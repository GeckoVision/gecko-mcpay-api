"""S20-A1 — schema-drift guard for the categorized-knowledge taxonomy.

Mirrors ``tests/test_payment_mode_consistency.py``. Every value in
``CATEGORIES`` / ``VERTICALS`` / ``KNOWLEDGE_SOURCES`` must appear
literally in the source of ``taxonomy.py`` (catches accidental rename
or drift between the runtime tuple and the ``Literal`` definition).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import get_args

from gecko_core.knowledge.taxonomy import (
    CATEGORIES,
    KNOWLEDGE_SOURCES,
    VERTICALS,
    Category,
    KnowledgeSource,
    Vertical,
    default_chunk_metadata,
    is_valid_subcategory,
)

_TAXONOMY_PATH = (
    Path(__file__).resolve().parents[2] / "src" / "gecko_core" / "knowledge" / "taxonomy.py"
)


def test_canonical_categories_value() -> None:
    assert CATEGORIES == (
        "market_intelligence",
        "business_financial",
        "investment_signals",
        "product",
        "technical_engineering",
        "ai_ml",
        "design_ux",
    )
    assert len(CATEGORIES) == 7


def test_canonical_verticals_value() -> None:
    assert VERTICALS == (
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
    assert len(VERTICALS) == 11


def test_canonical_knowledge_sources_value() -> None:
    assert KNOWLEDGE_SOURCES == (
        "web",
        "tavily",
        "twit_sh",
        "bazaar",
        "pay_sh",
        "user_query",
        "enriched_output",
    )
    assert len(KNOWLEDGE_SOURCES) == 7


def test_literal_get_args_matches_runtime_tuples() -> None:
    """The Literal type alias and the runtime tuple cannot drift."""
    assert get_args(Category) == CATEGORIES
    assert get_args(Vertical) == VERTICALS
    assert get_args(KnowledgeSource) == KNOWLEDGE_SOURCES


def test_taxonomy_source_contains_every_value() -> None:
    """Schema-drift guard — every value appears literally in source.

    Mirrors the SQL-scan pattern in test_payment_mode_consistency.py:
    parse the file as text, assert each constant value is mentioned.
    Catches the case where someone edits CATEGORIES without updating
    the Literal[...] definition (or vice versa).
    """
    src = _TAXONOMY_PATH.read_text(encoding="utf-8")
    for value in (*CATEGORIES, *VERTICALS, *KNOWLEDGE_SOURCES):
        # Each value must appear quoted at least twice — once in the
        # Literal alias, once in the runtime tuple.
        quoted = f'"{value}"'
        assert src.count(quoted) >= 2, (
            f"value {value!r} missing or under-declared in taxonomy.py "
            f"(found {src.count(quoted)} occurrences, expected >= 2)"
        )


def test_is_valid_subcategory_canonical_example() -> None:
    """Per the brainstorm decision: regulated lives as a subcategory."""
    assert is_valid_subcategory("business_financial", "regulatory") is True


def test_is_valid_subcategory_rejects_unknown() -> None:
    assert is_valid_subcategory("business_financial", "bogus") is False


def test_default_chunk_metadata_shape() -> None:
    before = datetime.now(UTC)
    md = default_chunk_metadata()
    after = datetime.now(UTC)

    assert set(md.keys()) == {"confidence", "usage_count", "timestamp", "pioneer"}
    assert md["confidence"] == 0.0
    assert md["usage_count"] == 0
    assert md["pioneer"] is False
    assert isinstance(md["timestamp"], datetime)
    # Within the last second (allow a small fudge for slow CI).
    assert before - timedelta(seconds=1) <= md["timestamp"] <= after + timedelta(seconds=1)


def test_all_25_literal_values_via_constant_tuples() -> None:
    """7 Categories + 11 Verticals + 7 KnowledgeSources = 25 values
    must be reachable via the public constant tuples."""
    total = len(CATEGORIES) + len(VERTICALS) + len(KNOWLEDGE_SOURCES)
    assert total == 25
    # And each constant tuple has no duplicates.
    assert len(set(CATEGORIES)) == len(CATEGORIES)
    assert len(set(VERTICALS)) == len(VERTICALS)
    assert len(set(KNOWLEDGE_SOURCES)) == len(KNOWLEDGE_SOURCES)
