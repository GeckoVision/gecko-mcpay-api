"""SSE endpoint tests for /research/pro/{session_id}/events.

Covers:
  - 401 on missing / malformed / expired token
  - successful event stream from a seeded fake `pro_events` table
  - stream closes when an event with type='final' is observed
  - 202 from POST /research/pro carries events_url + events_token
"""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient


def _purge_gecko_api_modules() -> None:
    for mod in [m for m in sys.modules if m.startswith("gecko_api")]:
        sys.modules.pop(mod, None)


def _seeded_events(session_id: UUID) -> list[Any]:
    """Build five ProEventRow-shaped objects: 2 turns + 1 final."""
    from datetime import UTC, datetime

    from gecko_core.sessions.store import ProEventRow

    now = datetime.now(UTC)
    return [
        ProEventRow(
            id=1,
            session_id=session_id,
            seq=1,
            event_type="turn_start",
            agent="analyst",
            content="",
            tokens_in=0,
            tokens_out=0,
            ts=time.time(),
            created_at=now,
        ),
        ProEventRow(
            id=2,
            session_id=session_id,
            seq=2,
            event_type="turn_end",
            agent="analyst",
            content="TAM looks plausible.",
            tokens_in=10,
            tokens_out=20,
            ts=time.time(),
            created_at=now,
        ),
        ProEventRow(
            id=3,
            session_id=session_id,
            seq=3,
            event_type="final",
            agent=None,
            content="done",
            tokens_in=0,
            tokens_out=0,
            ts=time.time(),
            created_at=now,
        ),
    ]


@pytest.fixture
def client_and_store() -> Iterator[tuple[TestClient, AsyncMock, str]]:
    os.environ["X402_MODE"] = "stub"
    os.environ["GECKO_WALLET_ADDRESS"] = "STUB_TEST_WALLET"
    os.environ["EVENTS_SECRET"] = "test-secret-fixed-for-fixture"
    _purge_gecko_api_modules()

    from gecko_api.main import app

    fake_store = AsyncMock()
    fake_store.create = AsyncMock(side_effect=lambda *a, **kw: uuid4())
    fake_store.set_tx_signature = AsyncMock(return_value=None)
    fake_store.set_price = AsyncMock(return_value=None)
    fake_store.set_session_project = AsyncMock(return_value=None)
    fake_store.set_result = AsyncMock(return_value=None)
    fake_store.set_error = AsyncMock(return_value=None)
    fake_store.update_status = AsyncMock(return_value=None)
    fake_store.tail_pro_events = AsyncMock(return_value=[])

    with (
        patch("gecko_api.main.SessionStore.from_env", return_value=fake_store),
        patch("gecko_api.main._run_pro_background", new=AsyncMock(return_value=None)),
        TestClient(app) as c,
    ):
        yield c, fake_store, "test-secret-fixed-for-fixture"


def _post_pro_paid(client: TestClient) -> dict[str, Any]:
    """POST /research/pro through the stub-mode payment flow; return 202 body."""
    import base64
    import json

    r0 = client.post("/research/pro", json={"idea": "a hotel guide for Brazil", "tier": "pro"})
    assert r0.status_code == 402
    decoded = json.loads(base64.b64decode(r0.headers["payment-required"]).decode("utf-8"))
    accepts_entry = decoded["accepts"][0]
    payment_header = base64.b64encode(
        json.dumps(
            {
                "x402Version": 2,
                "payload": {"signature": "stub-sig", "transaction": "stub-tx"},
                "accepted": accepts_entry,
            }
        ).encode("utf-8")
    ).decode("utf-8")
    r = client.post(
        "/research/pro",
        json={"idea": "a hotel guide for Brazil", "tier": "pro"},
        headers={"PAYMENT-SIGNATURE": payment_header},
    )
    assert r.status_code == 202, r.text
    return r.json()


def test_research_pro_202_carries_events_url_and_token(
    client_and_store: tuple[TestClient, AsyncMock, str],
) -> None:
    client, _, _ = client_and_store
    body = _post_pro_paid(client)
    assert body["status"] == "processing"
    assert body["events_url"].startswith("/research/pro/")
    assert body["events_url"].endswith("/events")
    assert isinstance(body["events_token"], str) and len(body["events_token"]) > 20


def test_sse_rejects_missing_token(
    client_and_store: tuple[TestClient, AsyncMock, str],
) -> None:
    client, _, _ = client_and_store
    sid = uuid4()
    r = client.get(f"/research/pro/{sid}/events")
    assert r.status_code == 401


def test_sse_rejects_malformed_token(
    client_and_store: tuple[TestClient, AsyncMock, str],
) -> None:
    client, _, _ = client_and_store
    sid = uuid4()
    r = client.get(f"/research/pro/{sid}/events?token=not-a-valid-token")
    assert r.status_code == 401


def test_sse_rejects_expired_token(
    client_and_store: tuple[TestClient, AsyncMock, str],
) -> None:
    client, _, secret = client_and_store
    from gecko_api.events_token import issue_token

    sid = uuid4()
    # Issue with negative TTL → already expired.
    expired = issue_token(sid, secret, ttl_seconds=-10)
    r = client.get(f"/research/pro/{sid}/events?token={expired}")
    assert r.status_code == 401


def test_sse_rejects_token_for_different_session(
    client_and_store: tuple[TestClient, AsyncMock, str],
) -> None:
    client, _, secret = client_and_store
    from gecko_api.events_token import issue_token

    sid = uuid4()
    other = uuid4()
    token = issue_token(other, secret)
    r = client.get(f"/research/pro/{sid}/events?token={token}")
    assert r.status_code == 401


def test_sse_streams_until_final(
    client_and_store: tuple[TestClient, AsyncMock, str],
) -> None:
    client, store, secret = client_and_store
    from gecko_api.events_token import issue_token

    sid = uuid4()
    seeded = _seeded_events(sid)

    # tail_pro_events: drain all rows on first call, empty on subsequent.
    calls = {"n": 0}

    async def _tail(_sid: UUID, after_id: int = 0, limit: int = 50) -> list[Any]:
        calls["n"] += 1
        if calls["n"] == 1:
            return [r for r in seeded if r.id > after_id]
        return []

    store.tail_pro_events = AsyncMock(side_effect=_tail)

    token = issue_token(sid, secret)
    with client.stream("GET", f"/research/pro/{sid}/events?token={token}") as response:
        assert response.status_code == 200
        body = b""
        for chunk in response.iter_bytes():
            body += chunk
            if b'"type":"final"' in body or b'"type": "final"' in body:
                break

    text = body.decode("utf-8")
    # All three events delivered, final terminates the stream.
    assert "turn_start" in text
    assert "turn_end" in text
    assert "final" in text
    # Heartbeats are comments — not asserted here; the loop exits on final.


def test_sse_accepts_bearer_header(
    client_and_store: tuple[TestClient, AsyncMock, str],
) -> None:
    """Authorization: Bearer <token> works as an alternative to ?token=."""
    client, store, secret = client_and_store
    from gecko_api.events_token import issue_token

    sid = uuid4()
    seeded = _seeded_events(sid)

    async def _tail(_sid: UUID, after_id: int = 0, limit: int = 50) -> list[Any]:
        return [r for r in seeded if r.id > after_id]

    store.tail_pro_events = AsyncMock(side_effect=_tail)

    token = issue_token(sid, secret)
    with client.stream(
        "GET",
        f"/research/pro/{sid}/events",
        headers={"Authorization": f"Bearer {token}"},
    ) as response:
        assert response.status_code == 200
        # Read enough to confirm the stream is alive.
        first = next(response.iter_bytes())
        assert first  # bytes received
