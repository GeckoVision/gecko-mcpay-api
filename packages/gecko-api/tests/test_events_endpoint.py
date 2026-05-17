"""S33-#73 — tests for POST /events (top-of-funnel telemetry).

Asserts:
    1. POST /events with a valid body returns 202 + minimal {"ok": true}.
    2. The gecko-core record_event helper is called with the parsed args.
    3. Unknown event_type is accepted (free-text column, no Literal gate).
    4. Oversized fields are rejected at the wire boundary (422).
    5. The route is unauthenticated — no 402, no payment header needed.
    6. Rate limiting is wired (decorator present + limit enforced).

Light fakes — `gecko_core.telemetry.record_event` is patched so this never
touches Supabase.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

# Force stub mode BEFORE importing the app — settings freeze at import time.
os.environ.setdefault("X402_MODE", "stub")
os.environ.setdefault("GECKO_WALLET_ADDRESS", "STUB_WALLET_ADDRESS_NOT_FOR_LIVE")


@pytest.fixture
def recorded() -> Iterator[list[dict]]:
    """Patch gecko_core.telemetry.record_event; yield the captured calls."""
    calls: list[dict] = []

    async def _fake_record(event_type: str, **kwargs: object) -> None:
        calls.append({"event_type": event_type, **kwargs})

    for mod in [m for m in sys.modules if m.startswith("gecko_api")]:
        sys.modules.pop(mod, None)

    with patch(
        "gecko_core.telemetry.record_event",
        new=AsyncMock(side_effect=_fake_record),
    ):
        yield calls


@pytest.fixture
def client(recorded: list[dict]) -> Iterator[TestClient]:
    from gecko_api.main import app

    with TestClient(app) as c:
        yield c


def test_post_events_returns_202(client: TestClient, recorded: list[dict]) -> None:
    r = client.post(
        "/events",
        json={
            "event_type": "install_started",
            "installer_tag": "v1.0.0",
            "metadata": {"os": "linux"},
        },
    )
    assert r.status_code == 202, r.text
    assert r.json() == {"ok": True}
    # Helper called with the parsed args.
    assert len(recorded) == 1
    assert recorded[0]["event_type"] == "install_started"
    assert recorded[0]["installer_tag"] == "v1.0.0"
    assert recorded[0]["metadata"] == {"os": "linux"}


def test_post_events_minimal_body(client: TestClient, recorded: list[dict]) -> None:
    r = client.post("/events", json={"event_type": "register", "wallet_address": "w1"})
    assert r.status_code == 202
    assert recorded[0]["wallet_address"] == "w1"
    assert recorded[0]["email"] is None


def test_post_events_unknown_event_type_accepted(client: TestClient, recorded: list[dict]) -> None:
    # event_type is free-text — the endpoint must not reject novel types.
    r = client.post("/events", json={"event_type": "skill_opened"})
    assert r.status_code == 202
    assert recorded[0]["event_type"] == "skill_opened"


def test_post_events_is_unauthenticated(client: TestClient) -> None:
    # No payment header, no auth — must NOT 402/401/403.
    r = client.post("/events", json={"event_type": "install_ok"})
    assert r.status_code == 202


def test_post_events_rejects_oversized_event_type(client: TestClient) -> None:
    r = client.post("/events", json={"event_type": "x" * 200})
    assert r.status_code == 422


def test_post_events_rejects_oversized_metadata(client: TestClient) -> None:
    big = {f"k{i}": "v" for i in range(100)}
    r = client.post("/events", json={"event_type": "install_ok", "metadata": big})
    assert r.status_code == 422


def test_post_events_requires_event_type(client: TestClient) -> None:
    r = client.post("/events", json={"installer_tag": "v1"})
    assert r.status_code == 422


def test_post_events_rate_limited(client: TestClient, recorded: list[dict]) -> None:
    # Limit is 30/minute. Fire past it from one bucket; expect a 429.
    statuses = [
        client.post("/events", json={"event_type": "install_started"}).status_code
        for _ in range(35)
    ]
    assert 202 in statuses
    assert 429 in statuses, f"rate limit never tripped: {statuses}"
