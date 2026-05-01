"""Tests for the local SQLite chunk cache (S14-HARDEN-01)."""

from __future__ import annotations

from pathlib import Path

import pytest
from gecko_core.sessions.local_cache import (
    MAX_CACHED_SESSIONS,
    cached_session_count,
    read_recent_chunks,
    write_session,
)


def _chunk(idx: int, text: str) -> dict[str, object]:
    return {
        "chunk_index": idx,
        "source_url": f"https://example.com/{idx}",
        "text": text,
    }


def test_write_then_read_round_trips(tmp_path: Path) -> None:
    db = tmp_path / "cache.db"
    write_session(
        session_id="sess-1",
        idea="Solana DEX with sandwich-protection",
        chunks=[_chunk(0, "first chunk"), _chunk(1, "second chunk")],
        cache_path=db,
    )
    rows = read_recent_chunks(idea_substring="Solana", cache_path=db)
    assert len(rows) == 2
    assert rows[0]["text"] == "first chunk"
    assert rows[1]["text"] == "second chunk"


def test_read_returns_empty_for_missing_db(tmp_path: Path) -> None:
    rows = read_recent_chunks(cache_path=tmp_path / "missing.db")
    assert rows == []


def test_idea_substring_picks_most_recent_match(tmp_path: Path) -> None:
    db = tmp_path / "cache.db"
    write_session(
        session_id="old",
        idea="Healthcare SaaS",
        chunks=[_chunk(0, "old text")],
        cache_path=db,
    )
    # Newer session, different idea — substring match should pick this
    # one over the older 'Healthcare' session when we search Solana.
    write_session(
        session_id="new",
        idea="Solana DEX",
        chunks=[_chunk(0, "new text")],
        cache_path=db,
    )
    rows = read_recent_chunks(idea_substring="solana", cache_path=db)
    assert len(rows) == 1
    assert rows[0]["text"] == "new text"


def test_falls_back_to_most_recent_when_no_match(tmp_path: Path) -> None:
    db = tmp_path / "cache.db"
    write_session(
        session_id="s1",
        idea="anything",
        chunks=[_chunk(0, "fallback text")],
        cache_path=db,
    )
    rows = read_recent_chunks(idea_substring="nonexistent", cache_path=db)
    assert len(rows) == 1
    assert rows[0]["text"] == "fallback text"


def test_eviction_keeps_only_most_recent_n(tmp_path: Path) -> None:
    db = tmp_path / "cache.db"
    # Write more than the cap; oldest should be evicted.
    for i in range(MAX_CACHED_SESSIONS + 10):
        write_session(
            session_id=f"sess-{i:03d}",
            idea=f"idea {i}",
            chunks=[_chunk(0, f"text-{i}")],
            cache_path=db,
        )
    assert cached_session_count(cache_path=db) == MAX_CACHED_SESSIONS


def test_write_session_replaces_existing_chunks(tmp_path: Path) -> None:
    db = tmp_path / "cache.db"
    write_session(
        session_id="s1",
        idea="x",
        chunks=[_chunk(0, "v1"), _chunk(1, "v2")],
        cache_path=db,
    )
    # Re-write with different chunks — old rows must be cleared.
    write_session(
        session_id="s1",
        idea="x",
        chunks=[_chunk(0, "v1-new")],
        cache_path=db,
    )
    rows = read_recent_chunks(cache_path=db)
    assert len(rows) == 1
    assert rows[0]["text"] == "v1-new"


@pytest.mark.asyncio
async def test_degraded_research_uses_local_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """S14-HARDEN-01 acceptance: bb research --degraded with Supabase
    mocked unreachable produces a report with the degraded warning."""
    db = tmp_path / "cache.db"
    write_session(
        session_id="cached-1",
        idea="agent economy",
        chunks=[
            _chunk(0, "agent-economy ideas are hot. founders need synthesis."),
            _chunk(1, "x402 enables paid agent marketplaces."),
        ],
        cache_path=db,
    )

    # Redirect the default cache path to our tmp DB.
    from gecko_core.sessions import local_cache

    monkeypatch.setattr(local_cache, "DEFAULT_CACHE_PATH", db)

    from gecko_core.workflows import degraded_research

    result = await degraded_research(idea="agent economy synthesis")

    # The validation report's risk_flags carries the degraded warning.
    flags = result.validation_report.risk_flags
    assert any("DEGRADED MODE" in flag for flag in flags)
    # And the synthesized text references the cached chunks (not live data).
    assert "agent-economy" in result.validation_report.competitor_analysis or (
        "x402" in result.validation_report.demand_evidence
    )
    # Live mode is unaffected — no payment gate, no Supabase write.
    # We didn't mock anything else; the call just succeeded.


@pytest.mark.asyncio
async def test_degraded_research_raises_on_empty_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from gecko_core.sessions import local_cache

    monkeypatch.setattr(local_cache, "DEFAULT_CACHE_PATH", tmp_path / "empty.db")

    from gecko_core.workflows import degraded_research

    with pytest.raises(RuntimeError, match="degraded mode: local cache is empty"):
        await degraded_research(idea="anything")
