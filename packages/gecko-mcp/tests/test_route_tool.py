"""Tests for the `gecko_route` MCP tool (S3-05).

Strategy: monkeypatch `_run_route` so the MCP wrapper test stays a pure
JSON-serialization assertion. The route() machinery itself is covered in
`packages/gecko-core/tests/routing/test_route.py`.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from gecko_mcp import server as server_module
from gecko_mcp.server import call_tool, list_tools


def test_route_tool_listed() -> None:
    tools = asyncio.run(list_tools())
    by_name = {t.name for t in tools}
    assert "gecko_route" in by_name


def test_route_tool_input_schema_shape() -> None:
    tools = asyncio.run(list_tools())
    tool = next(t for t in tools if t.name == "gecko_route")
    schema = tool.inputSchema
    assert schema["required"] == ["prompt"]
    props = schema["properties"]
    assert set(props) == {"prompt", "task_hint", "max_cost_usd", "prefer_premium"}
    assert set(props["task_hint"]["enum"]) == {
        "reasoning",
        "code",
        "extraction",
        "summary",
        "default",
    }


async def test_gecko_route_returns_serialized_route_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canned = {
        "response": "answer",
        "model_used": "gpt-4o-mini",
        "cost_usd": 0.0009,
        "tokens_in": 100,
        "tokens_out": 200,
        "savings_vs_premium": 0.0042,
    }

    async def _fake(
        *,
        prompt: str,
        task_hint: str,
        max_cost_usd: float,
        prefer_premium: bool,
    ) -> dict[str, Any]:
        assert prompt == "summarize this"
        assert task_hint == "summary"
        assert max_cost_usd == 0.01
        assert prefer_premium is False
        return canned

    monkeypatch.setattr(server_module, "_run_route", _fake)

    out = await call_tool(
        "gecko_route",
        {
            "prompt": "summarize this",
            "task_hint": "summary",
            "max_cost_usd": 0.01,
        },
    )
    assert len(out) == 1
    payload = json.loads(out[0].text)
    assert payload == canned


async def test_gecko_route_rejects_unknown_task_hint() -> None:
    # We hit the real `_run_route` for this — bad task_hint should raise
    # before any model is selected or x402 charge is invoked.
    with pytest.raises(ValueError, match="task_hint must be one of"):
        await call_tool(
            "gecko_route",
            {"prompt": "x", "task_hint": "bogus"},
        )
