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
    assert set(props) == {
        "prompt",
        "task_hint",
        "max_cost_usd",
        "prefer_premium",
        "tier_preset",
    }
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
        "model_requested": "gpt-4o-mini",
        "cost_usd": 0.0009,
        "usage_cost_usd": None,
        "upstream_cost_usd": None,
        "tokens_in": 100,
        "tokens_out": 200,
        "savings_vs_premium": 0.0042,
    }

    async def _fake(
        *,
        client: Any,
        prompt: str,
        task_hint: str,
        max_cost_usd: float,
        prefer_premium: bool,
        tier_preset: str = "balanced",
    ) -> dict[str, Any]:
        del client, tier_preset
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


async def test_gecko_route_rejects_unknown_task_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # We hit the real `_run_route` for this — bad task_hint should raise
    # before any model is selected, x402 charge is invoked, or HTTP forward
    # is attempted. Force the local-dev fallback path so we don't accidentally
    # construct an API client.
    monkeypatch.setenv("GECKO_API_URL", "http://localhost:8000")
    with pytest.raises(ValueError, match="task_hint must be one of"):
        await call_tool(
            "gecko_route",
            {"prompt": "x", "task_hint": "bogus"},
        )


# ---------------------------------------------------------------------------
# S4-ROUTE-02 — gecko_route forwards through gecko-api in production
# ---------------------------------------------------------------------------


async def test_gecko_route_forwards_to_api_when_url_remote(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production env (GECKO_API_URL=https://api...) MUST route via api_client."""
    monkeypatch.setenv("GECKO_API_URL", "https://api.geckovision.tech")

    canned: dict[str, Any] = {
        "response": "via api",
        "model_used": "gpt-4o-mini",
        "model_requested": "gpt-4o-mini",
        "cost_usd": 0.001,
        "usage_cost_usd": 0.0011,
        "upstream_cost_usd": None,
        "tokens_in": 100,
        "tokens_out": 100,
        "savings_vs_premium": 0.005,
    }

    seen: dict[str, Any] = {}

    class _FakeClient:
        async def route(
            self,
            prompt: str,
            *,
            task_hint: str,
            max_cost_usd: float,
            prefer_premium: bool,
            tier_preset: str,
        ) -> dict[str, Any]:
            seen["prompt"] = prompt
            seen["task_hint"] = task_hint
            seen["max_cost_usd"] = max_cost_usd
            seen["prefer_premium"] = prefer_premium
            seen["tier_preset"] = tier_preset
            return canned

    monkeypatch.setattr(server_module, "_get_client", lambda: _FakeClient())

    out = await call_tool(
        "gecko_route",
        {
            "prompt": "hello there",
            "task_hint": "default",
            "max_cost_usd": 0.05,
            "tier_preset": "balanced",
        },
    )
    assert len(out) == 1
    assert json.loads(out[0].text) == canned
    assert seen["prompt"] == "hello there"
    assert seen["task_hint"] == "default"
    assert seen["tier_preset"] == "balanced"


async def test_gecko_route_local_fallback_calls_core_directly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Localhost / unset GECKO_API_URL → bypass api_client + call core directly."""
    monkeypatch.setenv("GECKO_API_URL", "http://localhost:8000")

    captured: dict[str, Any] = {}

    async def _fake_core_route(
        prompt: str,
        task_hint: str = "default",
        max_cost_usd: float = 0.05,
        prefer_premium: bool = False,
    ) -> Any:
        captured["prompt"] = prompt
        captured["task_hint"] = task_hint

        class _FakeResult:
            def model_dump(self, mode: str = "python") -> dict[str, Any]:
                del mode
                return {"response": "local", "model_used": "gpt-4o-mini"}

        return _FakeResult()

    import gecko_core.routing as core_routing

    monkeypatch.setattr(core_routing, "route", _fake_core_route)

    # Replace _get_client with one that explodes if reached — proves the
    # localhost branch never touches the client path.
    class _ExplodingClient:
        async def route(self, *_a: Any, **_kw: Any) -> Any:
            raise AssertionError("local fallback must not call api_client.route")

    monkeypatch.setattr(server_module, "_get_client", lambda: _ExplodingClient())

    out = await call_tool(
        "gecko_route",
        {"prompt": "ping", "task_hint": "summary"},
    )
    payload = json.loads(out[0].text)
    assert payload["response"] == "local"
    assert captured["prompt"] == "ping"
    assert captured["task_hint"] == "summary"
