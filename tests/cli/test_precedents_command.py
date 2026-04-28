"""Tests for `gecko precedents` CLI command."""

from __future__ import annotations

from typing import Any

import pytest
from click.testing import CliRunner
from gecko_cli.commands import precedents as precedents_module
from gecko_cli.main import cli


def test_precedents_command_renders_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake(idea: str, top_k: int) -> list[dict[str, Any]]:
        assert idea == "a defi yield aggregator"
        assert top_k == 3
        return [
            {
                "id": "11111111-1111-1111-1111-111111111111",
                "idea_summary": "a generic yield aggregator",
                "verdict": "kill",
                "key_comparables": ["Yearn", "Beefy"],
                "similarity": 0.91,
            },
            {
                "id": "22222222-2222-2222-2222-222222222222",
                "idea_summary": "RWA lending protocol",
                "verdict": "ship",
                "key_comparables": ["Maple"],
                "similarity": 0.79,
            },
        ]

    monkeypatch.setattr(precedents_module, "_fetch", _fake)

    runner = CliRunner()
    result = runner.invoke(cli, ["precedents", "a defi yield aggregator", "--top-k", "3"])
    assert result.exit_code == 0, result.output
    assert "Gecko precedents" in result.output
    assert "kill" in result.output
    assert "ship" in result.output
    assert "Yearn" in result.output
    assert "0.910" in result.output


def test_precedents_command_empty_message(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake(idea: str, top_k: int) -> list[dict[str, Any]]:
        return []

    monkeypatch.setattr(precedents_module, "_fetch", _fake)

    runner = CliRunner()
    result = runner.invoke(cli, ["precedents", "an obscure idea"])
    assert result.exit_code == 0, result.output
    assert "No prior precedents found." in result.output


def test_precedents_command_default_top_k(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    async def _fake(idea: str, top_k: int) -> list[dict[str, Any]]:
        seen["top_k"] = top_k
        return []

    monkeypatch.setattr(precedents_module, "_fetch", _fake)

    runner = CliRunner()
    result = runner.invoke(cli, ["precedents", "x"])
    assert result.exit_code == 0, result.output
    assert seen["top_k"] == 5
