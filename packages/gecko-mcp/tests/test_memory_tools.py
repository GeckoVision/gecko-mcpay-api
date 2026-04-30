"""Tests for memory MCP tools (S5-MEM-03)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from gecko_mcp import server as server_module
from gecko_mcp.server import call_tool, list_tools


async def test_memory_tools_listed() -> None:
    tools = await list_tools()
    by_name = {t.name: t for t in tools}
    for n in ("gecko_memory_save", "gecko_memory_recall", "gecko_memory_search"):
        assert n in by_name, f"missing tool {n}"


async def test_memory_save_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake(**kwargs: Any) -> dict[str, Any]:
        assert kwargs["scope_type"] == "project"
        assert kwargs["scope_id"] == "p-1"
        assert kwargs["entry_type"] == "user_note"
        assert kwargs["value"] == {"text": "hello"}
        return {"id": "abc"}

    monkeypatch.setattr(server_module, "_run_memory_save", _fake)
    out = await call_tool(
        "gecko_memory_save",
        {
            "scope_type": "project",
            "scope_id": "p-1",
            "entry_type": "user_note",
            "value": {"text": "hello"},
        },
    )
    payload = json.loads(out[0].text)
    assert payload == {"id": "abc"}


async def test_memory_save_bad_entry_type(monkeypatch: pytest.MonkeyPatch) -> None:
    # Real handler — exercise the validation path.
    out = await call_tool(
        "gecko_memory_save",
        {
            "scope_type": "project",
            "scope_id": "p",
            "entry_type": "not_a_real_type",
            "value": {},
        },
    )
    payload = json.loads(out[0].text)
    assert payload["error"] == "bad_entry_type"


async def test_memory_recall_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake(**kwargs: Any) -> list[dict[str, Any]]:
        assert kwargs["limit"] == 7
        return [{"id": "x", "entry_type": "user_note", "value": {}}]

    monkeypatch.setattr(server_module, "_run_memory_recall", _fake)
    out = await call_tool(
        "gecko_memory_recall",
        {"scope_type": "project", "scope_id": "p", "limit": 7},
    )
    payload = json.loads(out[0].text)
    assert isinstance(payload, list) and payload[0]["id"] == "x"


async def test_memory_recall_default_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    async def _fake(**kwargs: Any) -> list[dict[str, Any]]:
        seen.update(kwargs)
        return []

    monkeypatch.setattr(server_module, "_run_memory_recall", _fake)
    await call_tool("gecko_memory_recall", {"scope_type": "session", "scope_id": "s"})
    assert seen["limit"] == 20


async def test_memory_search_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake(**kwargs: Any) -> list[dict[str, Any]]:
        assert kwargs["query"] == "what did we decide"
        assert kwargs["top_k"] == 3
        return [{"id": "x", "similarity": 0.8, "value": {}, "entry_type": "user_note"}]

    monkeypatch.setattr(server_module, "_run_memory_search", _fake)
    out = await call_tool(
        "gecko_memory_search",
        {
            "scope_type": "project",
            "scope_id": "p",
            "query": "what did we decide",
            "top_k": 3,
        },
    )
    payload = json.loads(out[0].text)
    assert payload[0]["similarity"] == 0.8


async def test_resume_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake(**kwargs: Any) -> dict[str, Any]:
        assert kwargs == {"project_id": "proj-x", "days": 14}
        return {"project_id": "proj-x", "by_type": {}, "last_panel_voices": []}

    monkeypatch.setattr(server_module, "_run_resume", _fake)
    out = await call_tool(
        "gecko_resume",
        {"project_id": "proj-x", "days": 14},
    )
    payload = json.loads(out[0].text)
    assert payload["project_id"] == "proj-x"
