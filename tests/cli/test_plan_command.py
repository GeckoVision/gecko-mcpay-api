"""Tests for `gecko plan` CLI command (S4-ADVISOR-03)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from click.testing import CliRunner
from gecko_cli.main import cli
from gecko_core.orchestration.advisor.models import (
    PANEL_VOICE_ORDER,
    AdvisorPanel,
    AdvisorVoice,
)


def _canned_panel(sid: UUID) -> AdvisorPanel:
    voices = [
        AdvisorVoice(
            role=role,
            model_used=f"stub/{role.value}",
            output_md=f"voice {role.value}",
            closing_line=f"{role.value} closing line.",
            tokens_in=10,
            tokens_out=20,
            cost_usd=0.001,
        )
        for role in PANEL_VOICE_ORDER
    ]
    return AdvisorPanel(
        session_id=str(sid),
        voices=voices,
        total_cost_usd=0.005,
        generated_at=datetime.now().astimezone(),
    )


def test_plan_renders_voice_table(monkeypatch: pytest.MonkeyPatch) -> None:
    sid = uuid4()

    async def _fake(session_id: UUID | str, **_: Any) -> AdvisorPanel:
        return _canned_panel(sid)

    import gecko_core.orchestration.advisor as advisor_core

    monkeypatch.setattr(advisor_core, "generate_panel", _fake)
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["plan", str(sid), "--tier-preset", "balanced"],
        env={"COLUMNS": "240"},
    )
    assert result.exit_code == 0, result.output
    assert "Advisor Panel" in result.output
    for role in PANEL_VOICE_ORDER:
        assert role.value in result.output


def test_plan_invalid_uuid() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["plan", "not-a-uuid"])
    assert result.exit_code != 0
    assert "not a valid UUID" in result.output or "Invalid" in result.output
