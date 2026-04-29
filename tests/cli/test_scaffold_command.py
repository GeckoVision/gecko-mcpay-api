"""Tests for `gecko scaffold` CLI command (S3-01)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from click.testing import CliRunner
from gecko_cli.commands import scaffold as scaffold_module
from gecko_cli.main import cli

from gecko_core.orchestration.scaffold import (
    KillVerdictError,
    SessionNotFoundError,
)
from gecko_core.orchestration.scaffold.models import ScaffoldResult


def test_scaffold_command_module_exposes_command() -> None:
    assert scaffold_module.scaffold_cmd.name == "scaffold"


def test_scaffold_command_renders_paths_table(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sid = uuid4()
    target = tmp_path / ".gecko" / "scaffolds" / str(sid)
    target.mkdir(parents=True, exist_ok=True)
    paths = [target / "PRD.md", target / "business-plan.md", target / "BUILDING.md"]
    for p in paths:
        p.write_text("placeholder content for size assertion", encoding="utf-8")

    canned = ScaffoldResult(
        paths=paths,
        session_id=sid,
        tokens_used=4321,
        cost_usd=0.012,
        summary="Verdict: SHIP V1 to founders evaluating SAFE term sheets at pre-seed.",
    )

    async def _fake(
        session_id: UUID | str,
        output_dir: Path | str,
        **_: Any,
    ) -> ScaffoldResult:
        assert UUID(str(session_id)) == sid
        return canned

    import gecko_core.orchestration.scaffold as scaffold_core

    monkeypatch.setattr(scaffold_core, "generate_scaffold", _fake)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["scaffold", str(sid), "--output-dir", str(tmp_path)],
    )
    assert result.exit_code == 0, result.output
    assert "Scaffold ready" in result.output
    assert "PRD.md" in result.output
    assert "business-plan.md" in result.output
    assert "BUILDING.md" in result.output
    assert "4321" in result.output


def test_scaffold_command_invalid_uuid_errors(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["scaffold", "not-a-uuid", "--output-dir", str(tmp_path)])
    assert result.exit_code != 0
    assert "not a valid UUID" in result.output or "Invalid" in result.output


def test_scaffold_command_kill_verdict_exits_2(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sid = uuid4()

    async def _fake(*_args: Any, **_kwargs: Any) -> ScaffoldResult:
        raise KillVerdictError(f"session {sid} verdict was KILL")

    import gecko_core.orchestration.scaffold as scaffold_core

    monkeypatch.setattr(scaffold_core, "generate_scaffold", _fake)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["scaffold", str(sid), "--output-dir", str(tmp_path)],
    )
    assert result.exit_code == 2
    assert "Refused" in result.output


def test_scaffold_command_session_not_found_exits_1(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sid = uuid4()

    async def _fake(*_args: Any, **_kwargs: Any) -> ScaffoldResult:
        raise SessionNotFoundError(f"session {sid} not found")

    import gecko_core.orchestration.scaffold as scaffold_core

    monkeypatch.setattr(scaffold_core, "generate_scaffold", _fake)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["scaffold", str(sid), "--output-dir", str(tmp_path)],
    )
    assert result.exit_code == 1
    assert "Not found" in result.output
