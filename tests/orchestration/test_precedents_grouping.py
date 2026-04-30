"""S9-PRECEDENT-01 — outcome-grouped precedent rendering for the critic agent.

Asserts:
  - GeckoPrecedent default outcome is 'unknown' (backfill safety).
  - group_precedents_by_outcome buckets correctly and preserves intra-bucket
    order.
  - render_precedent_block emits the structured count line + per-outcome
    sections, and skips empty buckets after the count line.
  - Each precedent's similarity + verdict tag still surface (back-compat).
  - Empty corpus path is unchanged.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4


def _precedent(
    *,
    summary: str,
    verdict: str,
    outcome: str = "unknown",
    similarity: float | None = 0.84,
) -> Any:
    from gecko_core.sessions.store import GeckoPrecedent

    return GeckoPrecedent(
        id=uuid4(),
        session_id=uuid4(),
        user_id=None,
        idea_summary=summary,
        verdict=verdict,  # type: ignore[arg-type]
        outcome=outcome,  # type: ignore[arg-type]
        key_comparables=[],
        similarity=similarity,
    )


# --- Schema -----------------------------------------------------------------


def test_gecko_precedent_default_outcome_is_unknown() -> None:
    """Existing rows + test fixtures that don't pass `outcome` must land on
    'unknown' so the default backfill stays safe."""
    from gecko_core.sessions.store import GeckoPrecedent

    p = GeckoPrecedent(
        id=uuid4(),
        session_id=uuid4(),
        user_id=None,
        idea_summary="x",
        verdict="ship",
        key_comparables=[],
    )
    assert p.outcome == "unknown"


# --- Grouping ---------------------------------------------------------------


def test_group_precedents_by_outcome_buckets_correctly() -> None:
    from gecko_core.orchestration.pro.precedents import group_precedents_by_outcome

    rows = [
        _precedent(summary="a", verdict="ship", outcome="shipped", similarity=0.9),
        _precedent(summary="b", verdict="kill", outcome="killed", similarity=0.85),
        _precedent(summary="c", verdict="ship", outcome="unknown", similarity=0.80),
        _precedent(summary="d", verdict="ship", outcome="shipped", similarity=0.79),
    ]
    grouped = group_precedents_by_outcome(rows)
    assert [p.idea_summary for p in grouped["shipped"]] == ["a", "d"]
    assert [p.idea_summary for p in grouped["killed"]] == ["b"]
    assert [p.idea_summary for p in grouped["unknown"]] == ["c"]


def test_group_precedents_by_outcome_returns_all_keys_when_empty() -> None:
    from gecko_core.orchestration.pro.precedents import group_precedents_by_outcome

    grouped = group_precedents_by_outcome([])
    assert set(grouped.keys()) == {"shipped", "killed", "unknown"}
    assert all(grouped[k] == [] for k in grouped)


# --- Rendering --------------------------------------------------------------


def test_render_block_emits_structured_count_line() -> None:
    """The count line is the parse anchor for the critic + judge prompts."""
    from gecko_core.orchestration.pro.precedents import render_precedent_block

    rows = [
        _precedent(summary="cap-table-diff", verdict="ship", outcome="shipped", similarity=0.91),
        _precedent(summary="generic gpt", verdict="kill", outcome="killed", similarity=0.79),
        _precedent(summary="generic gpt 2", verdict="kill", outcome="killed", similarity=0.78),
        _precedent(summary="vet-tele-rx", verdict="ship", outcome="unknown", similarity=0.72),
    ]
    block = render_precedent_block(rows)
    assert "Prior similar ideas Gecko evaluated:" in block
    assert "Precedents: 1 SHIPPED, 2 KILLED, 1 UNKNOWN" in block
    # Per-outcome sections.
    assert "SHIPPED:" in block
    assert "KILLED:" in block
    assert "UNKNOWN:" in block
    # Verdict tag + similarity still surface inside the bullets.
    assert "[SHIP] cap-table-diff (sim=0.91)" in block
    assert "[KILL] generic gpt (sim=0.79)" in block


def test_render_block_skips_empty_outcome_sections() -> None:
    """When a bucket is empty, the count line declares it (`0 KILLED`) but
    we don't waste tokens on a `KILLED:\\n  - (none)` placeholder."""
    from gecko_core.orchestration.pro.precedents import render_precedent_block

    rows = [
        _precedent(summary="a", verdict="ship", outcome="shipped", similarity=0.9),
    ]
    block = render_precedent_block(rows)
    assert "Precedents: 1 SHIPPED, 0 KILLED, 0 UNKNOWN" in block
    assert "SHIPPED:" in block
    assert "KILLED:" not in block
    assert "UNKNOWN:" not in block


def test_render_block_empty_corpus_unchanged() -> None:
    """Back-compat: empty corpus still produces the legacy 'No prior precedents
    found.' line so the analyst's behavior on a fresh category is unchanged."""
    from gecko_core.orchestration.pro.precedents import render_precedent_block

    block = render_precedent_block([])
    assert "Prior similar ideas Gecko evaluated:" in block
    assert "No prior precedents found." in block
    # No structured count line on the empty path.
    assert "Precedents:" not in block


def test_render_block_unknown_outcome_falls_through() -> None:
    """A row whose outcome doesn't validate against the Literal would be
    impossible via Pydantic, but we defensively bucket unknown values into
    'unknown' so a future migration that adds a fourth label can't crash a
    stale agent build mid-debate."""
    from gecko_core.orchestration.pro.precedents import group_precedents_by_outcome
    from gecko_core.sessions.store import GeckoPrecedent

    p = GeckoPrecedent.model_construct(  # type: ignore[call-arg]
        id=uuid4(),
        session_id=uuid4(),
        user_id=None,
        idea_summary="future-label",
        verdict="ship",
        outcome="pivoted",  # not a current Literal value
        key_comparables=[],
        similarity=0.7,
    )
    grouped = group_precedents_by_outcome([p])
    assert grouped["unknown"] == [p]
    assert grouped["shipped"] == []


# --- Prompt rendering / opening prompt --------------------------------------


def test_opening_prompt_carries_grouped_block() -> None:
    """End-to-end: the opening prompt the analyst sees contains both the
    structured count line and the bucketed bullets."""
    from gecko_core.orchestration.pro import _opening_prompt

    rows = [
        _precedent(summary="cap-table-diff", verdict="ship", outcome="shipped", similarity=0.91),
        _precedent(summary="generic gpt", verdict="kill", outcome="killed", similarity=0.79),
    ]
    prompt = _opening_prompt("an idea", "rag chunk", rows)
    assert "Precedents: 1 SHIPPED, 1 KILLED, 0 UNKNOWN" in prompt
    assert "SHIPPED:" in prompt
    assert "KILLED:" in prompt
    assert "[SHIP] cap-table-diff (sim=0.91)" in prompt
    assert "[KILL] generic gpt (sim=0.79)" in prompt
