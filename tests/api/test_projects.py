"""Tests for the /projects HTTP endpoints.

We mock SessionStore.from_env (no Supabase) and respx-mock frames.ag for the
bearer auth dependency.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
import respx
from fastapi.testclient import TestClient
from httpx import Response

# Force stub mode + scrub env that would change the resource server config
os.environ.setdefault("X402_MODE", "stub")
os.environ.setdefault("GECKO_WALLET_ADDRESS", "STUB_TEST_WALLET")


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {
        "Authorization": "Bearer mf_alicekey",
        "X-Frames-Username": "alice",
    }


def _project_row(name: str = "demo", budget: float | None = 5.0) -> dict[str, object]:
    return {
        "id": str(uuid4()),
        "frames_username": "alice",
        "name": name,
        "budget_usd": budget,
        "wallet_address": None,
        "wallet_provider": "frames-policy",
        "created_at": datetime.now(tz=UTC).isoformat(),
        "deleted_at": None,
    }


@pytest.fixture
def client() -> Iterator[TestClient]:
    import sys

    os.environ.pop("RESEARCH_BASIC_PRICE", None)
    os.environ.pop("RESEARCH_PRO_PRICE", None)
    for mod in [m for m in sys.modules if m.startswith("gecko_api")]:
        sys.modules.pop(mod, None)

    from gecko_api.auth import _reset_cache_for_tests
    from gecko_api.main import app

    _reset_cache_for_tests()

    fake_store = AsyncMock()
    fake_store.create_project = AsyncMock(return_value=uuid4())
    fake_store.get_project = AsyncMock(return_value=None)
    fake_store.list_projects = AsyncMock(return_value=[])
    fake_store.delete_project = AsyncMock(return_value=True)
    fake_store.project_total_spent = AsyncMock(return_value=0.0)
    fake_store.project_budget_remaining = AsyncMock(return_value=None)
    fake_store.list_project_sessions = AsyncMock(return_value=[])
    fake_store._project_spend = AsyncMock(return_value=(0.0, 0))

    with (
        patch("gecko_api.main.SessionStore.from_env", return_value=fake_store),
        TestClient(app) as c,
    ):
        c.fake_store = fake_store  # type: ignore[attr-defined]
        yield c


def _mock_frames_ok() -> respx.Router:
    from gecko_api.auth import FRAMES_BASE_URL

    router = respx.mock(assert_all_called=False)
    router.get(f"{FRAMES_BASE_URL}/wallets/alice/balances").mock(
        return_value=Response(200, json={"balances": []})
    )
    return router


def test_create_project_requires_auth(client: TestClient) -> None:
    r = client.post("/projects", json={"name": "demo", "budget_usd": 5.0})
    assert r.status_code == 401


def test_create_project_success(client: TestClient, auth_headers: dict[str, str]) -> None:
    row = _project_row(name="demo", budget=5.0)
    fake = client.fake_store  # type: ignore[attr-defined]
    fake.get_project = AsyncMock(return_value=row)

    with _mock_frames_ok():
        r = client.post("/projects", json={"name": "demo", "budget_usd": 5.0}, headers=auth_headers)

    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "demo"
    assert body["budget_usd"] == 5.0
    fake.create_project.assert_awaited_once()
    kwargs = fake.create_project.await_args.kwargs
    assert kwargs["username"] == "alice"
    assert kwargs["name"] == "demo"


def test_list_projects(client: TestClient, auth_headers: dict[str, str]) -> None:
    rows = [_project_row(name="alpha"), _project_row(name="beta", budget=None)]
    fake = client.fake_store  # type: ignore[attr-defined]
    fake.list_projects = AsyncMock(return_value=rows)
    fake._project_spend = AsyncMock(return_value=(1.0, 2))

    with _mock_frames_ok():
        r = client.get("/projects", headers=auth_headers)

    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body) == 2
    assert {it["name"] for it in body} == {"alpha", "beta"}
    assert all("total_spent_usd" in it for it in body)
    fake.list_projects.assert_awaited_once_with(username="alice")


def test_get_project_404(client: TestClient, auth_headers: dict[str, str]) -> None:
    with _mock_frames_ok():
        r = client.get("/projects/nope", headers=auth_headers)
    assert r.status_code == 404


def test_get_project_returns_sessions(client: TestClient, auth_headers: dict[str, str]) -> None:
    row = _project_row(name="demo", budget=10.0)
    fake = client.fake_store  # type: ignore[attr-defined]
    fake.get_project = AsyncMock(return_value=row)
    fake.project_total_spent = AsyncMock(return_value=2.0)
    fake.project_budget_remaining = AsyncMock(return_value=8.0)
    fake.list_project_sessions = AsyncMock(
        return_value=[
            {
                "id": "abcd1234-0000-0000-0000-000000000000",
                "idea": "x",
                "status": "complete",
                "cost_total_usd": 1.0,
                "created_at": "2026-04-27T00:00:00Z",
            }
        ]
    )
    with _mock_frames_ok():
        r = client.get("/projects/demo", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "demo"
    assert body["total_spent_usd"] == 2.0
    assert body["budget_remaining_usd"] == 8.0
    assert len(body["sessions"]) == 1


def test_delete_project_success(client: TestClient, auth_headers: dict[str, str]) -> None:
    fake = client.fake_store  # type: ignore[attr-defined]
    fake.delete_project = AsyncMock(return_value=True)
    with _mock_frames_ok():
        r = client.delete("/projects/demo", headers=auth_headers)
    assert r.status_code == 204
    fake.delete_project.assert_awaited_once_with(username="alice", name="demo")


def test_delete_project_404(client: TestClient, auth_headers: dict[str, str]) -> None:
    fake = client.fake_store  # type: ignore[attr-defined]
    fake.delete_project = AsyncMock(return_value=False)
    with _mock_frames_ok():
        r = client.delete("/projects/nope", headers=auth_headers)
    assert r.status_code == 404
