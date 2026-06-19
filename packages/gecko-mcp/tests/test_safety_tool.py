"""Tests for the `gecko_safety` MCP tool.

Light fakes only — never hits the API. The tool is a thin forward to the free
`POST /safety` endpoint, so dispatch is verified by stubbing the module-level
client's `safety` method. Mirrors `test_trade_research_tool.py`.
"""

from __future__ import annotations

import json
from typing import Any

from gecko_mcp import server as server_module
from gecko_mcp.server import call_tool, list_tools


def test_safety_tool_listed() -> None:
    import asyncio

    tools = asyncio.run(list_tools())
    by_name = {t.name: t for t in tools}
    assert "gecko_safety" in by_name

    tool = by_name["gecko_safety"]
    schema = tool.inputSchema
    # The single structural axis: the SPL mint to check.
    assert schema["required"] == ["mint"]
    assert schema["properties"]["mint"]["type"] == "string"

    # Description must signal the sub-second pre-trade gate + the gate values.
    desc = tool.description or ""
    assert "safety" in desc.lower()
    assert "gate" in desc.lower()


async def test_gecko_safety_returns_gate_and_block(monkeypatch: Any) -> None:
    """Tool returns the /safety response: gate + SafetyBlock fields."""
    canned: dict[str, Any] = {
        "gate": "caution",
        "checked": True,
        "honeypot": False,
        "rug_flags": ["high_holder_concentration"],
        "information_mev": {"label": "elevated", "score": 0.42},
    }

    seen: dict[str, Any] = {}

    class _FakeClient:
        async def safety(self, mint: str) -> dict[str, Any]:
            seen["mint"] = mint
            return canned

    monkeypatch.setattr(server_module, "_get_client", lambda: _FakeClient())

    out = await call_tool(
        "gecko_safety",
        {"mint": "So11111111111111111111111111111111111111112"},
    )
    assert len(out) == 1
    payload = json.loads(out[0].text)
    assert payload == canned
    assert payload["gate"] in {"block", "caution", "ok", "unknown"}
    # mint is forwarded unchanged to the client.
    assert seen == {"mint": "So11111111111111111111111111111111111111112"}
