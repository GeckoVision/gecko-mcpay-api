"""Tests for the source catalog registry (`available_sources`)."""

from __future__ import annotations

from gecko_core.sources import (
    SourceCatalogEntry,
    available_sources,
    register_source,
)


def test_available_sources_includes_v1_entries() -> None:
    entries = available_sources()
    names = {e.name for e in entries}
    # V1 + flywheel sources mandated by S2X-12.
    assert {"hn", "reddit", "twit_sh", "gecko_precedent", "tavily", "colosseum"} <= names


def test_available_sources_entries_are_well_formed() -> None:
    for entry in available_sources():
        assert isinstance(entry, SourceCatalogEntry)
        assert entry.name
        assert entry.description
        assert entry.gating
        assert entry.cost_per_call


def test_register_source_is_idempotent_on_name() -> None:
    register_source(
        SourceCatalogEntry(
            name="__test_dup__",
            description="first",
            gating="Always",
            cost_per_call="Free",
        )
    )
    register_source(
        SourceCatalogEntry(
            name="__test_dup__",
            description="second",
            gating="Always",
            cost_per_call="Free",
        )
    )
    matches = [e for e in available_sources() if e.name == "__test_dup__"]
    assert len(matches) == 1
    assert matches[0].description == "second"


def test_available_sources_returns_a_copy() -> None:
    entries = available_sources()
    entries.clear()
    # The canonical list must be unaffected.
    assert available_sources()
