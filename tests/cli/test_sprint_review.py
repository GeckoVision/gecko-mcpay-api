"""Tests for `bb sprint-review` (S7-DOGFOOD-03)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner
from gecko_cli.main import cli
from gecko_core.review.models import SprintReview


def _canned_review(*, mode: str = "stub") -> SprintReview:
    return SprintReview(
        project_id=None,
        since_days=14,
        shipped=["commit: ship feature X", "commit: fix bug Y"],
        weakest_link="no eval coverage on advisor panel",
        proposed_next=["lock release", "run pulse", "schedule review"],
        mode=mode,
        git_commits=["abc1234 ship feature X", "def5678 fix bug Y"],
        memory_entry_count=0,
        sprint_docs=["build-plan-sprint-7.md"],
        generated_at=datetime.now(tz=UTC),
    )


def test_sprint_review_renders_panel(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake(**_: Any) -> SprintReview:
        return _canned_review()

    import gecko_core.review as review_pkg

    monkeypatch.setattr(review_pkg, "build_review", _fake)
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["sprint-review", "--since", "14d"],
        env={"COLUMNS": "240"},
    )
    assert result.exit_code == 0, result.output
    assert "Sprint Review" in result.output
    assert "ship feature X" in result.output
    assert "Weakest link" in result.output
    assert "Proposed next" in result.output


def test_sprint_review_writes_doc(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    async def _fake(**_: Any) -> SprintReview:
        return _canned_review()

    import gecko_core.review as review_pkg

    monkeypatch.setattr(review_pkg, "build_review", _fake)
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["sprint-review", "--since", "7d", "--write-doc"],
        env={"COLUMNS": "240"},
    )
    assert result.exit_code == 0, result.output
    today = datetime.now(tz=UTC).date().isoformat()
    expected = tmp_path / "docs" / "sprint-reviews" / f"{today}.md"
    assert expected.exists(), f"missing {expected}"
    body = expected.read_text(encoding="utf-8")
    assert "Sprint review" in body
    assert "ship feature X" in body
    assert "Proposed next" in body


def test_sprint_review_rejects_bad_since() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["sprint-review", "--since", "garbage"])
    assert result.exit_code != 0
    assert "since" in result.output.lower() or "Invalid" in result.output


def test_sprint_review_accepts_bare_integer(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    async def _fake(**kwargs: Any) -> SprintReview:
        captured.update(kwargs)
        return _canned_review()

    import gecko_core.review as review_pkg

    monkeypatch.setattr(review_pkg, "build_review", _fake)
    runner = CliRunner()
    result = runner.invoke(cli, ["sprint-review", "--since", "30"])
    assert result.exit_code == 0, result.output
    assert captured["since_days"] == 30
