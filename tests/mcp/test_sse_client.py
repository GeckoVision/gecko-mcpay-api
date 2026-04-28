"""Unit tests for `gecko_mcp.sse_client.stream_pro_events`.

Strategy: build an `httpx.MockTransport` that returns a streaming response
by chunking SSE bytes. Verify that the parser yields events in order, fires
`progress` per turn_end, and reconnects exactly once on a transient drop.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from gecko_mcp.sse_client import SseError, stream_pro_events


def _sse_bytes(events: list[dict[str, Any]]) -> bytes:
    """Encode a list of payloads as SSE 'turn' events, ending with a final."""
    out: list[str] = []
    for ev in events:
        out.append(f"event: turn\ndata: {json.dumps(ev)}\n\n")
    return "".join(out).encode("utf-8")


def _make_transport(payload: bytes, status: int = 200) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=status, content=payload)

    return httpx.MockTransport(handler)


async def test_progress_fires_per_turn_end() -> None:
    payload = _sse_bytes(
        [
            {"type": "turn_start", "agent": "analyst", "content": "", "seq": 1},
            {
                "type": "turn_end",
                "agent": "analyst",
                "content": "TAM looks plausible.",
                "seq": 2,
            },
            {
                "type": "turn_end",
                "agent": "critic",
                "content": "Wedge is fuzzy.",
                "seq": 3,
            },
            {"type": "final", "agent": None, "content": "done", "seq": 4},
        ]
    )
    transport = _make_transport(payload)
    http = httpx.AsyncClient(transport=transport)

    progress_calls: list[str] = []

    async def _progress(line: str) -> None:
        progress_calls.append(line)

    final = await stream_pro_events(
        events_url="http://test/research/pro/abc/events",
        events_token="t",
        progress=_progress,
        http_client=http,
    )

    assert final is not None
    assert final["type"] == "final"
    assert len(progress_calls) == 2
    assert progress_calls[0].startswith("[analyst]")
    assert progress_calls[1].startswith("[critic]")

    await http.aclose()


async def test_tolerates_heartbeat_comments() -> None:
    payload = b": ping\n\n" + _sse_bytes(
        [
            {"type": "turn_end", "agent": "judge", "content": "ship.", "seq": 1},
            {"type": "final", "content": "done", "agent": None, "seq": 2},
        ]
    )
    transport = _make_transport(payload)
    http = httpx.AsyncClient(transport=transport)

    progress_calls: list[str] = []

    async def _progress(line: str) -> None:
        progress_calls.append(line)

    final = await stream_pro_events(
        events_url="http://test/x",
        events_token="t",
        progress=_progress,
        http_client=http,
    )
    assert final is not None
    assert final["type"] == "final"
    assert progress_calls == ["[judge] ship."]
    await http.aclose()


async def test_4xx_setup_failure_raises_sse_error() -> None:
    transport = _make_transport(b'{"detail":"unauthorized"}', status=401)
    http = httpx.AsyncClient(transport=transport)

    with pytest.raises(SseError, match="SSE setup failed"):
        await stream_pro_events(
            events_url="http://test/x",
            events_token="bad",
            http_client=http,
            reconnect_once=False,
        )
    await http.aclose()


async def test_reconnects_once_on_transient_drop(monkeypatch: pytest.MonkeyPatch) -> None:
    """First attempt raises a transport error; second yields a complete stream."""
    attempts = {"n": 0}
    final_payload = _sse_bytes(
        [
            {"type": "turn_end", "agent": "judge", "content": "ok", "seq": 1},
            {"type": "final", "content": "done", "agent": None, "seq": 2},
        ]
    )

    async def _stream_once(
        events_url: str,
        events_token: str,
        on_event: Any,
        progress: Any,
        http_client: Any,
        timeout_s: float,
    ) -> dict[str, Any] | None:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise httpx.RemoteProtocolError("transient drop")
        # Second attempt: pretend success.
        return {"type": "final", "content": "done"}

    from gecko_mcp import sse_client

    monkeypatch.setattr(sse_client, "_stream_once", _stream_once)

    final = await stream_pro_events(
        events_url="http://test/x",
        events_token="t",
        reconnect_once=True,
    )
    assert attempts["n"] == 2
    assert final is not None and final["type"] == "final"
    _ = final_payload  # silence


async def test_second_drop_raises_sse_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two drops in a row → SseError so caller can fall back to /result poll."""
    attempts = {"n": 0}

    async def _stream_once(*_a: Any, **_kw: Any) -> dict[str, Any] | None:
        attempts["n"] += 1
        raise httpx.RemoteProtocolError("drop")

    from gecko_mcp import sse_client

    monkeypatch.setattr(sse_client, "_stream_once", _stream_once)

    with pytest.raises(SseError):
        await stream_pro_events(
            events_url="http://test/x",
            events_token="t",
            reconnect_once=True,
        )
    assert attempts["n"] == 2
