"""Tests for the `gecko_classify` MCP tool (S2X-12).

Strategy: monkeypatch `_run_classify` (the thin internal entry point) with
a coroutine that returns a canned classification. The MCP wrapper is a
JSON-serialization layer; the classifier itself is covered in
`packages/gecko-core/tests/test_classifier_accuracy.py`.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from gecko_mcp import server as server_module
from gecko_mcp.server import call_tool, list_tools


def test_classify_tool_listed() -> None:
    # `list_tools` is async; awaited via a fresh event loop in the harness.
    import asyncio

    tools = asyncio.run(list_tools())
    by_name = {t.name for t in tools}
    assert "gecko_classify" in by_name


async def test_gecko_classify_returns_categories_and_scores(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canned = {
        "categories": ["crypto", "defi"],
        "scores": {
            "crypto": 0.71,
            "defi": 0.68,
            "devtools": 0.31,
            "saas": 0.22,
            "regulated": 0.11,
            "hackathon-team": 0.05,
        },
    }

    async def _fake(*, idea: str) -> dict[str, Any]:
        assert idea == "an AMM for SPL tokens"
        return canned

    monkeypatch.setattr(server_module, "_run_classify", _fake)

    out = await call_tool("gecko_classify", {"idea": "an AMM for SPL tokens"})
    assert len(out) == 1
    payload = json.loads(out[0].text)
    assert payload == canned
    assert set(payload.keys()) == {"categories", "scores"}
    assert payload["categories"] == ["crypto", "defi"]
    assert isinstance(payload["scores"], dict)
    assert all(isinstance(v, float) for v in payload["scores"].values())
