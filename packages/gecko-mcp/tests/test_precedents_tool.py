"""Tests for the `gecko_precedents` MCP tool (S2X-12)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from gecko_mcp import server as server_module
from gecko_mcp.server import call_tool, list_tools


def test_precedents_tool_listed() -> None:
    import asyncio

    tools = asyncio.run(list_tools())
    by_name = {t.name: t for t in tools}
    assert "gecko_precedents" in by_name
    schema = by_name["gecko_precedents"].inputSchema
    assert schema["required"] == ["idea"]
    assert "top_k" in schema["properties"]


async def test_gecko_precedents_returns_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    canned = [
        {
            "id": "11111111-1111-1111-1111-111111111111",
            "idea_summary": "a generic SaaS ledger",
            "verdict": "kill",
            "key_comparables": ["QuickBooks", "Xero"],
            "similarity": 0.92,
        }
    ]

    seen: dict[str, Any] = {}

    async def _fake(*, idea: str, top_k: int) -> list[dict[str, Any]]:
        seen["idea"] = idea
        seen["top_k"] = top_k
        return canned

    monkeypatch.setattr(server_module, "_run_precedents", _fake)

    out = await call_tool("gecko_precedents", {"idea": "a SaaS ledger for SMBs", "top_k": 3})
    assert len(out) == 1
    payload = json.loads(out[0].text)
    assert payload == canned
    assert seen == {"idea": "a SaaS ledger for SMBs", "top_k": 3}


async def test_gecko_precedents_default_top_k(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    async def _fake(*, idea: str, top_k: int) -> list[dict[str, Any]]:
        seen["top_k"] = top_k
        return []

    monkeypatch.setattr(server_module, "_run_precedents", _fake)
    await call_tool("gecko_precedents", {"idea": "x"})
    assert seen["top_k"] == 5


async def test_gecko_available_sources_returns_catalog() -> None:
    out = await call_tool("gecko_available_sources", {})
    payload = json.loads(out[0].text)
    assert isinstance(payload, list)
    names = {entry["name"] for entry in payload}
    # Every entry from the spec must be present.
    assert {"hn", "reddit", "twit_sh", "gecko_precedent", "tavily", "colosseum"} <= names
    # Every entry must carry the four catalog fields.
    for entry in payload:
        assert set(entry.keys()) == {"name", "description", "gating", "cost_per_call"}
