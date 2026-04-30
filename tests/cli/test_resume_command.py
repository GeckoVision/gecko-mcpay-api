"""Tests for `gecko resume <project_id>` CLI command (S5-MEM-05)."""

from __future__ import annotations

from typing import Any

import pytest
from click.testing import CliRunner
from gecko_cli.commands import resume as resume_module
from gecko_cli.main import cli


def test_resume_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake(project_id: str, days: int) -> dict[str, Any]:
        assert project_id == "proj-1"
        assert days == 30
        return {
            "project_id": "proj-1",
            "last_activity_at": "2026-04-26T12:00:00+00:00",
            "by_type": {
                "verdict_received": [
                    {
                        "id": "v1",
                        "key": None,
                        "value": {"verdict": "ship", "idea": "Carta-aware diff"},
                        "tx_signature": None,
                        "created_at": "2026-04-26T12:00:00+00:00",
                    }
                ],
            },
            "last_panel_voices": [
                {"role": "ceo", "closing_line": "lock the LOI"},
                {"role": "cto", "closing_line": "ship the parser"},
            ],
            "last_pulse_deltas": [],
        }

    monkeypatch.setattr(resume_module, "_fetch", _fake)
    runner = CliRunner()
    result = runner.invoke(cli, ["resume", "proj-1"])
    assert result.exit_code == 0, result.output
    assert "Project" in result.output
    assert "SHIP" in result.output
    assert "lock the LOI" in result.output


def test_resume_no_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake(project_id: str, days: int) -> dict[str, Any]:
        return {
            "project_id": project_id,
            "last_activity_at": None,
            "by_type": {},
            "last_panel_voices": [],
            "last_pulse_deltas": [],
        }

    monkeypatch.setattr(resume_module, "_fetch", _fake)
    runner = CliRunner()
    result = runner.invoke(cli, ["resume", "proj-empty"])
    assert result.exit_code == 0, result.output
    assert "No memory entries" in result.output


def test_resume_custom_days(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    async def _fake(project_id: str, days: int) -> dict[str, Any]:
        seen["days"] = days
        return {
            "project_id": project_id,
            "last_activity_at": None,
            "by_type": {},
            "last_panel_voices": [],
            "last_pulse_deltas": [],
        }

    monkeypatch.setattr(resume_module, "_fetch", _fake)
    runner = CliRunner()
    result = runner.invoke(cli, ["resume", "proj-x", "--days", "90"])
    assert result.exit_code == 0, result.output
    assert seen["days"] == 90
