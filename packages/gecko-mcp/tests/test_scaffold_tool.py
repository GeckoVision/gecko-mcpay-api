"""Tests for the `gecko_scaffold` MCP tool (S3-01).

We monkeypatch `_run_scaffold` (the thin internal entry point) — the
core path is covered by `packages/gecko-core/tests/orchestration/test_scaffold.py`.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from gecko_mcp import server as server_module
from gecko_mcp.server import call_tool, list_tools


def test_scaffold_tool_listed() -> None:
    tools = asyncio.run(list_tools())
    by_name = {t.name for t in tools}
    assert "gecko_scaffold" in by_name


def test_scaffold_input_schema_requires_session_id() -> None:
    tools = asyncio.run(list_tools())
    scaffold = next(t for t in tools if t.name == "gecko_scaffold")
    assert scaffold.inputSchema["required"] == ["session_id"]
    props = scaffold.inputSchema["properties"]
    assert "session_id" in props
    assert "output_dir" in props


async def test_gecko_scaffold_returns_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    canned = {
        "session_id": "00000000-0000-0000-0000-000000000123",
        "paths": [
            "/tmp/.gecko/scaffolds/abc/PRD.md",
            "/tmp/.gecko/scaffolds/abc/business-plan.md",
            "/tmp/.gecko/scaffolds/abc/BUILDING.md",
        ],
        "tokens_used": 5000,
        "summary": "Verdict: SHIP V1 to founders evaluating SAFE term sheets at pre-seed.",
    }

    async def _fake(*, session_id: str, output_dir: str | None) -> dict[str, Any]:
        assert session_id == "00000000-0000-0000-0000-000000000123"
        assert output_dir == "/work"
        return canned

    monkeypatch.setattr(server_module, "_run_scaffold", _fake)

    out = await call_tool(
        "gecko_scaffold",
        {
            "session_id": "00000000-0000-0000-0000-000000000123",
            "output_dir": "/work",
        },
    )
    assert len(out) == 1
    payload = json.loads(out[0].text)
    assert payload == canned
    assert len(payload["paths"]) == 3


async def test_gecko_scaffold_kill_verdict_returns_error_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Kill verdict surfaces as a structured error payload, not an exception."""

    async def _fake(*, session_id: str, output_dir: str | None) -> dict[str, Any]:
        return {"error": "kill_verdict", "message": "verdict was KILL"}

    monkeypatch.setattr(server_module, "_run_scaffold", _fake)

    out = await call_tool(
        "gecko_scaffold",
        {"session_id": "00000000-0000-0000-0000-000000000456"},
    )
    payload = json.loads(out[0].text)
    assert payload["error"] == "kill_verdict"
