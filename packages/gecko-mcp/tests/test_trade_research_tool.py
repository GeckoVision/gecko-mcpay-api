"""Tests for the `gecko_trade_research` MCP tool (Phase 8b).

Light fakes only — never fires AG2 or hits the API. The tool dispatch is
verified by monkeypatching the module-level `_run_trade_research` helper,
matching the pattern used in `test_precedents_tool.py`.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from gecko_mcp import server as server_module
from gecko_mcp.server import call_tool, list_tools


def test_trade_research_tool_listed() -> None:
    import asyncio

    tools = asyncio.run(list_tools())
    by_name = {t.name: t for t in tools}
    assert "gecko_trade_research" in by_name

    tool = by_name["gecko_trade_research"]
    schema = tool.inputSchema
    # Required fields = the two structural axes the panel reads.
    assert sorted(schema["required"]) == ["idea", "protocol"]
    # vertical / tier ship with sensible defaults so single-shot callers
    # don't have to know the corpus shape.
    assert schema["properties"]["vertical"]["default"] == "dex"
    assert schema["properties"]["tier"]["default"] == "basic"

    # Description must clearly distinguish from gecko_research so a Claude
    # Code skill author picks the right tool.
    desc = tool.description or ""
    assert "trade" in desc.lower()
    assert "gecko_research" in desc  # explicit cross-reference


async def test_gecko_trade_research_returns_verdict_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tool returns a verdict dict with the canonical shape (act|pass|defer)."""
    canned: dict[str, Any] = {
        "verdict": "act",
        "confidence": 0.7,
        "key_drivers": ["technical alignment", "fundamental TVL growth"],
        "dissent_count": 1,
        "blocker_questions": ["Does Pyth uptime hold through CPI?"],
        "turns": [{"agent": "technical_analyst", "content": "...", "parsed_verdict": None}],
    }

    seen: dict[str, Any] = {}

    async def _fake(*, idea: str, protocol: str, vertical: str, tier: str) -> dict[str, Any]:
        seen.update({"idea": idea, "protocol": protocol, "vertical": vertical, "tier": tier})
        return canned

    monkeypatch.setattr(server_module, "_run_trade_research", _fake)

    out = await call_tool(
        "gecko_trade_research",
        {"idea": "Should I open a JTO long?", "protocol": "jito"},
    )
    assert len(out) == 1
    payload = json.loads(out[0].text)
    assert payload == canned
    assert payload["verdict"] in {"act", "pass", "defer"}
    # Defaults are forwarded into the helper.
    assert seen == {
        "idea": "Should I open a JTO long?",
        "protocol": "jito",
        "vertical": "dex",
        "tier": "basic",
    }


async def test_gecko_trade_research_forwards_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Caller-supplied vertical/tier reach the helper unchanged."""
    seen: dict[str, Any] = {}

    async def _fake(*, idea: str, protocol: str, vertical: str, tier: str) -> dict[str, Any]:
        seen.update({"vertical": vertical, "tier": tier})
        return {
            "verdict": "defer",
            "confidence": 0.4,
            "key_drivers": [],
            "dissent_count": 0,
            "blocker_questions": [],
            "turns": [],
        }

    monkeypatch.setattr(server_module, "_run_trade_research", _fake)

    await call_tool(
        "gecko_trade_research",
        {
            "idea": "x",
            "protocol": "Kamino",
            "vertical": "dex",
            "tier": "pro",
        },
    )
    assert seen == {"vertical": "dex", "tier": "pro"}


async def test_gecko_trade_research_rejects_bad_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """tier outside basic|pro raises before the helper runs."""
    called = False

    async def _fake(**_kwargs: Any) -> dict[str, Any]:
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(server_module, "_run_trade_research", _fake)

    with pytest.raises(ValueError, match="tier"):
        await call_tool(
            "gecko_trade_research",
            {"idea": "x", "protocol": "drift", "tier": "ultra"},
        )
    assert called is False
