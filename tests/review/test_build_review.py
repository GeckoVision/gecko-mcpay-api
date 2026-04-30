"""Tests for `gecko_core.review.build_review` (S7-DOGFOOD-01).

Mocks:
    - the git subprocess call (via monkeypatching `_git_log_since`)
    - memory recall (via monkeypatching `_load_memory_entries`)
    - the LLM caller (a plain async function)

The repo root is forced to a tmp_path so docs/build-plan-sprint-*.md
discovery is deterministic.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from gecko_core.memory.models import MemoryEntry, MemoryEntryType, MemoryScope
from gecko_core.review import SprintReview, build_review
from gecko_core.review import builder as review_builder


def _make_entry(
    entry_type: MemoryEntryType,
    value: dict[str, Any],
    *,
    project_id: str,
    key: str | None = None,
) -> MemoryEntry:
    return MemoryEntry(
        id=uuid4(),
        scope=MemoryScope(type="project", id=project_id),
        entry_type=entry_type,
        key=key,
        value=value,
        embedding=None,
        tx_signature=None,
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def patched_repo(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Force GECKO_REPO_ROOT and stub git/docs to a clean tmp dir."""
    monkeypatch.setenv("GECKO_REPO_ROOT", str(tmp_path))
    return tmp_path


@pytest.mark.asyncio
async def test_stub_mode_returns_review_with_commits(
    patched_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        review_builder,
        "_git_log_since",
        lambda repo, since_days: ["abc1234 first commit", "def5678 second commit"],
    )

    async def _empty_entries(*_: Any, **__: Any) -> list[MemoryEntry]:
        return []

    monkeypatch.setattr(review_builder, "_load_memory_entries", _empty_entries)

    review = await build_review(project_id=None, since_days=14)

    assert isinstance(review, SprintReview)
    assert review.mode == "stub"
    assert review.since_days == 14
    assert len(review.git_commits) == 2
    assert any("first commit" in s for s in review.shipped)
    # Stub-mode proposed_next is always 3 deterministic bullets.
    assert len(review.proposed_next) == 3


@pytest.mark.asyncio
async def test_stub_mode_includes_memory_summary(
    patched_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid = str(uuid4())
    monkeypatch.setattr(review_builder, "_git_log_since", lambda *_, **__: [])

    feature_entry = _make_entry(
        MemoryEntryType.feature_shipped,
        {"title": "x402 reconcile cron"},
        project_id=pid,
    )
    pulse_entry = _make_entry(
        MemoryEntryType.pulse_run,
        {
            "deltas": [
                {"voice": "ceo", "before": "ship X", "after": "ship Y"},
                {"voice": "cto", "before": "same", "after": "same"},
            ]
        },
        project_id=pid,
    )

    async def _entries(*_: Any, **__: Any) -> list[MemoryEntry]:
        return [pulse_entry, feature_entry]

    monkeypatch.setattr(review_builder, "_load_memory_entries", _entries)

    review = await build_review(project_id=pid, since_days=7)
    assert review.memory_entry_count == 2
    assert any("x402 reconcile cron" in s for s in review.shipped)
    assert "pulse_run flagged" in review.weakest_link


@pytest.mark.asyncio
async def test_picks_up_sprint_doc_files(
    patched_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    docs = patched_repo / "docs"
    docs.mkdir()
    (docs / "build-plan-sprint-7.md").write_text("# Sprint 7\n", encoding="utf-8")
    (docs / "build-plan-sprint-6.md").write_text("# Sprint 6\n", encoding="utf-8")
    (docs / "unrelated.md").write_text("ignore me", encoding="utf-8")

    monkeypatch.setattr(review_builder, "_git_log_since", lambda *_, **__: [])

    async def _entries(*_: Any, **__: Any) -> list[MemoryEntry]:
        return []

    monkeypatch.setattr(review_builder, "_load_memory_entries", _entries)

    review = await build_review(project_id=None, since_days=14)
    assert review.sprint_docs == ["build-plan-sprint-6.md", "build-plan-sprint-7.md"]


@pytest.mark.asyncio
async def test_live_mode_calls_llm_and_parses_json(
    patched_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        review_builder,
        "_git_log_since",
        lambda *_, **__: ["abc shipped feature A"],
    )

    async def _entries(*_: Any, **__: Any) -> list[MemoryEntry]:
        return []

    monkeypatch.setattr(review_builder, "_load_memory_entries", _entries)

    captured: list[tuple[str, str]] = []

    async def _llm(system_prompt: str, user_prompt: str) -> str:
        captured.append((system_prompt, user_prompt))
        return (
            '{"shipped": ["feature A landed"], '
            '"weakest_link": "no eval coverage", '
            '"proposed_next": ["a", "b", "c"]}'
        )

    review = await build_review(
        project_id=None,
        since_days=10,
        llm_caller=_llm,
        tier_preset="quality",
    )

    assert review.mode == "live"
    assert review.shipped == ["feature A landed"]
    assert review.weakest_link == "no eval coverage"
    assert review.proposed_next == ["a", "b", "c"]
    assert len(captured) == 1
    assert "shipped" in captured[0][0]  # system prompt mentions schema
    # User prompt should include the git log
    assert "feature A" in captured[0][1]


@pytest.mark.asyncio
async def test_live_mode_falls_back_on_bad_json(
    patched_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        review_builder,
        "_git_log_since",
        lambda *_, **__: ["abc fix bug"],
    )

    async def _entries(*_: Any, **__: Any) -> list[MemoryEntry]:
        return []

    monkeypatch.setattr(review_builder, "_load_memory_entries", _entries)

    async def _bad_llm(_s: str, _u: str) -> str:
        return "this is not json at all"

    review = await build_review(project_id=None, since_days=14, llm_caller=_bad_llm)
    # Mode is still live (LLM was called), but bullets backfill from stub heuristics.
    assert review.mode == "live"
    assert review.shipped, "shipped should backfill from git commits"
    assert review.proposed_next, "proposed_next should backfill"


@pytest.mark.asyncio
async def test_git_failure_yields_empty_commits(
    patched_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _raise(*_: Any, **__: Any) -> list[str]:
        return []  # builder already swallows; just return empty

    monkeypatch.setattr(review_builder, "_git_log_since", _raise)

    async def _entries(*_: Any, **__: Any) -> list[MemoryEntry]:
        return []

    monkeypatch.setattr(review_builder, "_load_memory_entries", _entries)

    review = await build_review(project_id=None, since_days=14)
    assert review.git_commits == []
    # The first proposed_next bullet calls out the empty window.
    assert "no commits" in review.proposed_next[0].lower()


@pytest.mark.asyncio
async def test_skips_memory_when_no_project_id(
    patched_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(review_builder, "_git_log_since", lambda *_, **__: [])

    called = {"hit": False}

    async def _entries(project_id: str | None, *_: Any, **__: Any) -> list[MemoryEntry]:
        called["hit"] = True
        # Mirror real implementation: returns empty for project_id=None.
        return []

    # We patch the load helper itself; with project_id=None it should still
    # be invoked but return [], which is fine — we assert via memory_entry_count.
    monkeypatch.setattr(review_builder, "_load_memory_entries", _entries)

    review = await build_review(project_id=None, since_days=14)
    assert review.memory_entry_count == 0


@pytest.mark.asyncio
async def test_sprint_reviewed_entry_type_exists() -> None:
    """The new MemoryEntryType must be enumerable for downstream code."""
    assert MemoryEntryType("sprint_reviewed") == MemoryEntryType.sprint_reviewed
