"""SSE consumer for Pro-tier `/research/pro/{session_id}/events`.

The Pro tier's wow moment is watching the 5 agents argue. Frames.ag's
`/x402/fetch` is request/response — it can't stream. So once the parent
`/research/pro` POST settles, we drop frames and subscribe to SSE directly
from `gecko-mcp` against `api.geckovision.tech`.

Auth: session-scoped HMAC token issued by the API alongside the 202 ACK.
This endpoint is read-after-payment — no x402 gating, no frames roundtrip.

Reconnect policy: one transparent reconnect on transient drop. On a second
drop, callers fall back to polling `/sessions/{id}/result`.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)


@dataclass
class SseEvent:
    """One server-sent event after parsing.

    `event` is the SSE event-name (default 'message' if unset). `data` is the
    decoded JSON payload (dict) or the raw string when not JSON-parseable.
    """

    event: str
    data: Any
    raw: str


class SseError(RuntimeError):
    """Raised when SSE setup fails irrecoverably (4xx, malformed token, etc)."""


async def _iter_events(
    response: httpx.Response,
) -> AsyncIterator[SseEvent]:
    """Parse SSE from an httpx streaming response.

    Tolerates heartbeats (`: ping`), multi-line `data:` blocks, and unknown
    fields. Yields one SseEvent per blank-line-delimited block.
    """
    event_name = "message"
    data_lines: list[str] = []
    async for raw_line in response.aiter_lines():
        line = raw_line.rstrip("\r")
        if line == "":
            if data_lines:
                joined = "\n".join(data_lines)
                try:
                    parsed: Any = json.loads(joined)
                except json.JSONDecodeError:
                    parsed = joined
                yield SseEvent(event=event_name, data=parsed, raw=joined)
            event_name = "message"
            data_lines = []
            continue
        if line.startswith(":"):  # heartbeat / comment
            continue
        if line.startswith("event:"):
            event_name = line[len("event:") :].strip()
            continue
        if line.startswith("data:"):
            data_lines.append(line[len("data:") :].lstrip())
            continue
        # ignore unknown fields (id:, retry:, etc — not used here)


async def stream_pro_events(
    events_url: str,
    events_token: str,
    *,
    on_event: Callable[[SseEvent], Awaitable[None]] | None = None,
    progress: Callable[[str], Awaitable[None]] | None = None,
    http_client: httpx.AsyncClient | None = None,
    timeout_s: float = 300.0,
    reconnect_once: bool = True,
) -> dict[str, Any] | None:
    """Stream events until a `final` event arrives. Returns the final payload.

    Args:
        events_url: Absolute URL like https://api.geckovision.tech/research/pro/{sid}/events
        events_token: The HMAC token issued by the 202 ACK.
        on_event: Optional async callback fired for every event (incl. heartbeats? no — heartbeats are filtered upstream).
        progress: Optional async callback for human-readable progress strings.
            Fired on each `turn_end` event with `[<agent>] <first 200 chars>...`.
        http_client: Inject for tests; otherwise we build one with `?token=` in URL.
        timeout_s: Hard deadline. Mirrors the server's 300s cap.
        reconnect_once: If True, transparently retry one time on transient drop.

    Returns:
        The dict payload of the `final` event (when type='final'), or None if
        the stream closed without a final (caller falls back to /result poll).
    """
    drops_remaining = 1 if reconnect_once else 0

    while True:
        try:
            return await _stream_once(
                events_url, events_token, on_event, progress, http_client, timeout_s
            )
        except (httpx.HTTPError, httpx.StreamError) as exc:
            if drops_remaining <= 0:
                logger.warning("SSE final drop after reconnect: %s", exc)
                raise SseError(f"SSE drop: {exc}") from exc
            drops_remaining -= 1
            logger.info("SSE transient drop — reconnecting once: %s", exc)
            continue


async def _stream_once(
    events_url: str,
    events_token: str,
    on_event: Callable[[SseEvent], Awaitable[None]] | None,
    progress: Callable[[str], Awaitable[None]] | None,
    http_client: httpx.AsyncClient | None,
    timeout_s: float,
) -> dict[str, Any] | None:
    """One SSE attempt — exits on `final`, error event, or timeout."""
    sep = "&" if "?" in events_url else "?"
    url = f"{events_url}{sep}token={events_token}"
    headers = {"Accept": "text/event-stream"}

    owned_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=httpx.Timeout(timeout_s, connect=10.0))
    try:
        async with client.stream("GET", url, headers=headers) as response:
            if response.status_code >= 400:
                # Read body before raising for a useful error message.
                body = await response.aread()
                raise SseError(
                    f"SSE setup failed [{response.status_code}]: {body.decode('utf-8', errors='replace')[:200]}"
                )

            deadline = asyncio.get_event_loop().time() + timeout_s
            async for event in _iter_events(response):
                if asyncio.get_event_loop().time() >= deadline:
                    return None
                if on_event is not None:
                    await on_event(event)

                payload = event.data if isinstance(event.data, dict) else {}
                ev_type = payload.get("type")
                if ev_type == "turn_end" and progress is not None:
                    agent = payload.get("agent") or "?"
                    content = str(payload.get("content") or "")
                    snippet = content[:200] + ("..." if len(content) > 200 else "")
                    await progress(f"[{agent}] {snippet}")
                if ev_type == "final":
                    return payload
                if ev_type == "error":
                    # Surface as None — caller polls /result for the persisted error.
                    return None
            return None
    finally:
        if owned_client:
            await client.aclose()


__all__ = ["SseError", "SseEvent", "stream_pro_events"]
