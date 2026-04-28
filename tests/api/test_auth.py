"""Tests for the frames.ag bearer-token verification dependency.

Strategy: respx mocks the frames.ag /balances round-trip. We assert the
HTTP-level contract (401/503/200) and the cache behaviour.
"""

from __future__ import annotations

import pytest
import respx
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from gecko_api.auth import (
    FRAMES_BASE_URL,
    _reset_cache_for_tests,
    verify_frames_token,
)
from httpx import Response


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    _reset_cache_for_tests()


def _make_app() -> FastAPI:
    app = FastAPI()

    @app.get("/whoami")
    async def whoami(username: str = Depends(verify_frames_token)) -> dict[str, str]:
        return {"username": username}

    return app


def test_missing_authorization_header_returns_401() -> None:
    client = TestClient(_make_app())
    r = client.get("/whoami", headers={"X-Frames-Username": "alice"})
    assert r.status_code == 401


def test_missing_username_header_returns_401() -> None:
    client = TestClient(_make_app())
    r = client.get("/whoami", headers={"Authorization": "Bearer mf_token"})
    assert r.status_code == 401


def test_malformed_authorization_returns_401() -> None:
    client = TestClient(_make_app())
    r = client.get(
        "/whoami",
        headers={"Authorization": "Token mf_xxx", "X-Frames-Username": "alice"},
    )
    assert r.status_code == 401


@respx.mock
def test_valid_token_passes_and_caches() -> None:
    route = respx.get(f"{FRAMES_BASE_URL}/wallets/alice/balances").mock(
        return_value=Response(200, json={"balances": []})
    )
    client = TestClient(_make_app())
    r = client.get(
        "/whoami",
        headers={"Authorization": "Bearer mf_good", "X-Frames-Username": "alice"},
    )
    assert r.status_code == 200
    assert r.json() == {"username": "alice"}
    assert route.call_count == 1

    # Second call hits the cache — no second frames.ag round-trip.
    r2 = client.get(
        "/whoami",
        headers={"Authorization": "Bearer mf_good", "X-Frames-Username": "alice"},
    )
    assert r2.status_code == 200
    assert route.call_count == 1


@respx.mock
def test_frames_401_propagates_as_401() -> None:
    respx.get(f"{FRAMES_BASE_URL}/wallets/alice/balances").mock(
        return_value=Response(401, json={"detail": "bad token"})
    )
    client = TestClient(_make_app())
    r = client.get(
        "/whoami",
        headers={"Authorization": "Bearer mf_bad", "X-Frames-Username": "alice"},
    )
    assert r.status_code == 401


@respx.mock
def test_frames_5xx_returns_503_and_does_not_cache() -> None:
    route = respx.get(f"{FRAMES_BASE_URL}/wallets/alice/balances").mock(
        return_value=Response(503, text="upstream down")
    )
    client = TestClient(_make_app())
    r = client.get(
        "/whoami",
        headers={"Authorization": "Bearer mf_x", "X-Frames-Username": "alice"},
    )
    assert r.status_code == 503

    # Cache miss should re-attempt — no poison-cache on 5xx.
    r2 = client.get(
        "/whoami",
        headers={"Authorization": "Bearer mf_x", "X-Frames-Username": "alice"},
    )
    assert r2.status_code == 503
    assert route.call_count == 2


@respx.mock
def test_cached_username_mismatch_returns_401() -> None:
    """If the same token is presented with a different X-Frames-Username
    after caching, refuse — the binding is fixed at first verification."""
    respx.get(f"{FRAMES_BASE_URL}/wallets/alice/balances").mock(
        return_value=Response(200, json={"balances": []})
    )
    client = TestClient(_make_app())
    r1 = client.get(
        "/whoami",
        headers={"Authorization": "Bearer mf_t", "X-Frames-Username": "alice"},
    )
    assert r1.status_code == 200

    r2 = client.get(
        "/whoami",
        headers={"Authorization": "Bearer mf_t", "X-Frames-Username": "bob"},
    )
    assert r2.status_code == 401
