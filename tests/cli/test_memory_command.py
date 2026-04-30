"""Tests for `gecko memory` CLI commands (S5-MEM-03)."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from click.testing import CliRunner
from gecko_cli.commands import memory as memory_module
from gecko_cli.main import cli


def test_memory_save_command(monkeypatch: pytest.MonkeyPatch) -> None:
    new_id = str(uuid4())

    async def _fake(**kwargs: Any) -> str:
        assert kwargs["scope_type"] == "project"
        assert kwargs["scope_id"] == "p-1"
        assert kwargs["entry_type"] == "user_note"
        assert kwargs["value"] == {"text": "hi"}
        return new_id

    monkeypatch.setattr(memory_module, "_do_save", _fake)
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "memory",
            "save",
            "--scope",
            "project:p-1",
            "--type",
            "user_note",
            "--value",
            '{"text": "hi"}',
        ],
    )
    assert result.exit_code == 0, result.output
    assert new_id in result.output


def test_memory_recall_command(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake(**kwargs: Any) -> list[dict[str, Any]]:
        assert kwargs["scope_type"] == "project"
        assert kwargs["scope_id"] == "p-1"
        return [
            {
                "id": "abc",
                "entry_type": "verdict_received",
                "key": None,
                "value": {"verdict": "ship"},
                "tx_signature": None,
                "created_at": "2026-04-29T00:00:00+00:00",
            }
        ]

    monkeypatch.setattr(memory_module, "_do_recall", _fake)
    runner = CliRunner()
    result = runner.invoke(cli, ["memory", "recall", "--scope", "project:p-1"])
    assert result.exit_code == 0, result.output
    assert "verdict_received" in result.output


def test_memory_search_command(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake(**kwargs: Any) -> list[dict[str, Any]]:
        assert kwargs["query"] == "did we decide"
        return [
            {
                "id": "x",
                "entry_type": "plan_advised",
                "key": None,
                "value": {"voices": []},
                "similarity": 0.812,
                "created_at": "2026-04-29T00:00:00+00:00",
            }
        ]

    monkeypatch.setattr(memory_module, "_do_search", _fake)
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["memory", "search", "--scope", "session:s-1", "did we decide"],
    )
    assert result.exit_code == 0, result.output
    assert "0.812" in result.output


def test_memory_save_rejects_bad_scope() -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "memory",
            "save",
            "--scope",
            "no-colon-here",
            "--type",
            "user_note",
            "--value",
            "{}",
        ],
    )
    assert result.exit_code != 0
    assert "scope" in result.output.lower()
