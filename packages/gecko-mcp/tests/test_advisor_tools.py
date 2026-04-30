"""Tests for the advisor MCP tools (`gecko_advise`, `gecko_plan`, `gecko_pulse`).

We monkeypatch the thin internal entry points (`_run_advise`, `_run_plan`,
`_run_pulse`) — core paths are covered by `test_advisor.py`.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from gecko_mcp import server as server_module
from gecko_mcp.server import call_tool, list_tools


def test_advisor_tools_listed() -> None:
    tools = asyncio.run(list_tools())
    by_name = {t.name for t in tools}
    assert {"gecko_advise", "gecko_plan", "gecko_pulse"}.issubset(by_name)


def test_advise_input_schema_requires_session_and_voice() -> None:
    tools = asyncio.run(list_tools())
    advise = next(t for t in tools if t.name == "gecko_advise")
    assert advise.inputSchema["required"] == ["session_id", "voice"]
    assert "voice" in advise.inputSchema["properties"]


def test_plan_input_schema_requires_session() -> None:
    tools = asyncio.run(list_tools())
    plan = next(t for t in tools if t.name == "gecko_plan")
    assert plan.inputSchema["required"] == ["session_id"]


async def test_gecko_advise_returns_voice_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    canned = {
        "role": "ceo",
        "model_used": "moonshotai/kimi-k2.6",
        "output_md": "...",
        "closing_line": "Strategic priority: lock the LOI.",
        "tokens_in": 100,
        "tokens_out": 200,
        "cost_usd": 0.0023,
    }

    async def _fake(*, session_id: str, voice: str, tier_preset: str) -> dict[str, Any]:
        assert voice == "ceo"
        assert tier_preset == "balanced"
        return canned

    monkeypatch.setattr(server_module, "_run_advise", _fake)
    out = await call_tool(
        "gecko_advise",
        {
            "session_id": "00000000-0000-0000-0000-000000000001",
            "voice": "ceo",
        },
    )
    payload = json.loads(out[0].text)
    assert payload == canned


async def test_gecko_advise_session_not_found_returns_error_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake(*, session_id: str, voice: str, tier_preset: str) -> dict[str, Any]:
        return {"error": "session_not_found", "message": "session X not found"}

    monkeypatch.setattr(server_module, "_run_advise", _fake)
    out = await call_tool(
        "gecko_advise",
        {
            "session_id": "00000000-0000-0000-0000-000000000002",
            "voice": "cto",
        },
    )
    payload = json.loads(out[0].text)
    assert payload["error"] == "session_not_found"


async def test_gecko_plan_returns_panel_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    canned = {
        "session_id": "00000000-0000-0000-0000-000000000003",
        "voices": [
            {
                "role": "ceo",
                "model_used": "moonshotai/kimi-k2.6",
                "output_md": "x",
                "closing_line": "Strategic priority: ...",
                "tokens_in": 1,
                "tokens_out": 1,
                "cost_usd": 0.0,
            }
            for _ in range(5)
        ],
        "total_cost_usd": 0.0,
        "generated_at": "2026-04-29T00:00:00+00:00",
    }

    async def _fake(*, session_id: str, tier_preset: str) -> dict[str, Any]:
        return canned

    monkeypatch.setattr(server_module, "_run_plan", _fake)
    out = await call_tool(
        "gecko_plan",
        {"session_id": "00000000-0000-0000-0000-000000000003"},
    )
    payload = json.loads(out[0].text)
    assert payload["session_id"] == canned["session_id"]
    assert len(payload["voices"]) == 5


async def test_gecko_plan_paid_path_marker(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sprint 4: panel is FREE in MCP. The pricing field tracking that the
    Sprint 5 paid path is not yet wired is captured by checking that
    `total_cost_usd` is the LLM cost, not an x402 charge."""

    async def _fake(*, session_id: str, tier_preset: str) -> dict[str, Any]:
        return {
            "session_id": session_id,
            "voices": [],
            "total_cost_usd": 0.0142,
            "generated_at": "2026-04-29T00:00:00+00:00",
        }

    monkeypatch.setattr(server_module, "_run_plan", _fake)
    out = await call_tool(
        "gecko_plan",
        {"session_id": "00000000-0000-0000-0000-000000000004"},
    )
    payload = json.loads(out[0].text)
    assert payload["total_cost_usd"] < 0.10  # well under the eventual $0.25 charge


async def test_gecko_pulse_surfaces_delta(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake(*, session_id: str, tier_preset: str) -> dict[str, Any]:
        return {
            "panel": {
                "session_id": session_id,
                "voices": [],
                "total_cost_usd": 0.0,
                "generated_at": "2026-04-29T00:00:00+00:00",
            },
            "deltas": [
                {
                    "role": "ceo",
                    "previous_closing_line": "Strategic priority: A.",
                    "current_closing_line": "Strategic priority: B.",
                    "changed": True,
                    "reason": "closing line shifted vs prior pulse",
                }
            ],
            "previous_panel_at": None,
        }

    monkeypatch.setattr(server_module, "_run_pulse", _fake)
    out = await call_tool(
        "gecko_pulse",
        {"session_id": "00000000-0000-0000-0000-000000000005"},
    )
    payload = json.loads(out[0].text)
    assert payload["deltas"][0]["changed"] is True


async def test_gecko_pulse_no_prior(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake(*, session_id: str, tier_preset: str) -> dict[str, Any]:
        return {
            "panel": {
                "session_id": session_id,
                "voices": [],
                "total_cost_usd": 0.0,
                "generated_at": "2026-04-29T00:00:00+00:00",
            },
            "deltas": [
                {
                    "role": "ceo",
                    "previous_closing_line": None,
                    "current_closing_line": "Strategic priority: A.",
                    "changed": False,
                    "reason": "no prior pulse on file",
                }
            ],
            "previous_panel_at": None,
        }

    monkeypatch.setattr(server_module, "_run_pulse", _fake)
    out = await call_tool(
        "gecko_pulse",
        {"session_id": "00000000-0000-0000-0000-000000000006"},
    )
    payload = json.loads(out[0].text)
    assert payload["deltas"][0]["reason"] == "no prior pulse on file"
