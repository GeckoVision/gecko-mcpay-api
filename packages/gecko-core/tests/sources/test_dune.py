"""DuneClient tests — light fakes via httpx.MockTransport (Phase 3.4).

Never fires a real Dune request. The execute -> status-poll -> results flow is
simulated with a routed MockTransport; the happy path returns rows, the error
path fails-OPEN to None, and a disabled/sentinel key short-circuits with zero
HTTP calls.
"""

from __future__ import annotations

import httpx
import pytest
from gecko_core.sources.dune import (
    DUNE_API_KEY_ENV,
    DuneClient,
    DuneResult,
)

_QUERY_ID = 4242
_EXECUTION_ID = "01HX-exec-abc"


def _route(
    handlers: dict[str, object], *, record: list[httpx.Request] | None = None
) -> httpx.MockTransport:
    """Build a MockTransport that dispatches on (method, path)."""

    def handler(request: httpx.Request) -> httpx.Response:
        if record is not None:
            record.append(request)
        key = f"{request.method} {request.url.path}"
        resp = handlers.get(key)
        if resp is None:
            raise AssertionError(f"unexpected request: {key}")
        return resp  # type: ignore[return-value]

    return httpx.MockTransport(handler)


def _happy_handlers() -> dict[str, object]:
    return {
        f"POST /api/v1/query/{_QUERY_ID}/execute": httpx.Response(
            200, json={"execution_id": _EXECUTION_ID, "state": "QUERY_STATE_PENDING"}
        ),
        f"GET /api/v1/execution/{_EXECUTION_ID}/status": httpx.Response(
            200, json={"state": "QUERY_STATE_COMPLETED"}
        ),
        f"GET /api/v1/execution/{_EXECUTION_ID}/results": httpx.Response(
            200,
            json={
                "result": {
                    "rows": [
                        {"holder_bucket": "0-1%", "wallets": 1200},
                        {"holder_bucket": "1-5%", "wallets": 40},
                    ],
                    "metadata": {"column_names": ["holder_bucket", "wallets"], "row_count": 2},
                }
            },
        ),
    }


@pytest.mark.asyncio
async def test_run_query_happy_path_returns_rows() -> None:
    """execute -> COMPLETED -> results maps cleanly into a DuneResult."""
    transport = _route(_happy_handlers())
    async with httpx.AsyncClient(transport=transport) as http:
        client = DuneClient(api_key="real-key", client=http, poll_interval=0.0)
        result = await client.run_query(_QUERY_ID)

    assert isinstance(result, DuneResult)
    assert result.query_id == _QUERY_ID
    assert result.execution_id == _EXECUTION_ID
    assert result.row_count == 2
    assert result.rows[0]["holder_bucket"] == "0-1%"
    assert result.metadata["row_count"] == 2
    # One execute = one credit charged; status/results polls are not counted.
    assert client.executions_used == 1


@pytest.mark.asyncio
async def test_run_query_polls_through_pending_state() -> None:
    """A PENDING status is polled again until COMPLETED."""
    calls = {"status": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST" and path.endswith("/execute"):
            return httpx.Response(200, json={"execution_id": _EXECUTION_ID})
        if path.endswith("/status"):
            calls["status"] += 1
            state = "QUERY_STATE_COMPLETED" if calls["status"] >= 2 else "QUERY_STATE_EXECUTING"
            return httpx.Response(200, json={"state": state})
        if path.endswith("/results"):
            return httpx.Response(200, json={"result": {"rows": [{"x": 1}], "metadata": {}}})
        raise AssertionError(path)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = DuneClient(api_key="real-key", client=http, poll_interval=0.0)
        result = await client.run_query(_QUERY_ID)

    assert result is not None
    assert result.row_count == 1
    assert calls["status"] == 2


@pytest.mark.asyncio
async def test_run_query_fails_open_on_http_error() -> None:
    """A 500 on execute fails-OPEN to None (never raises)."""
    transport = _route(
        {f"POST /api/v1/query/{_QUERY_ID}/execute": httpx.Response(500, json={"error": "boom"})}
    )
    async with httpx.AsyncClient(transport=transport) as http:
        client = DuneClient(api_key="real-key", client=http, poll_interval=0.0)
        result = await client.run_query(_QUERY_ID)

    assert result is None
    # Execute was attempted (credit was committed) before the 500.
    assert client.executions_used == 1


@pytest.mark.asyncio
async def test_run_query_fails_open_on_terminal_failure_state() -> None:
    """A QUERY_STATE_FAILED status terminates the poll and returns None."""
    transport = _route(
        {
            f"POST /api/v1/query/{_QUERY_ID}/execute": httpx.Response(
                200, json={"execution_id": _EXECUTION_ID}
            ),
            f"GET /api/v1/execution/{_EXECUTION_ID}/status": httpx.Response(
                200, json={"state": "QUERY_STATE_FAILED"}
            ),
        }
    )
    async with httpx.AsyncClient(transport=transport) as http:
        client = DuneClient(api_key="real-key", client=http, poll_interval=0.0)
        result = await client.run_query(_QUERY_ID)

    assert result is None


@pytest.mark.asyncio
async def test_run_query_fails_open_on_poll_timeout() -> None:
    """A perpetually-pending execution times out and returns None."""
    transport = _route(
        {
            f"POST /api/v1/query/{_QUERY_ID}/execute": httpx.Response(
                200, json={"execution_id": _EXECUTION_ID}
            ),
            f"GET /api/v1/execution/{_EXECUTION_ID}/status": httpx.Response(
                200, json={"state": "QUERY_STATE_EXECUTING"}
            ),
        }
    )
    async with httpx.AsyncClient(transport=transport) as http:
        # poll_timeout=0 => deadline already passed after the first status read.
        client = DuneClient(api_key="real-key", client=http, poll_interval=0.0, poll_timeout=0.0)
        result = await client.run_query(_QUERY_ID)

    assert result is None


@pytest.mark.asyncio
async def test_disabled_when_no_key_makes_no_call() -> None:
    """No key => disabled => returns None with ZERO HTTP requests."""
    seen: list[httpx.Request] = []
    transport = _route({}, record=seen)
    async with httpx.AsyncClient(transport=transport) as http:
        client = DuneClient(api_key=None, client=http)
        assert client.enabled is False
        result = await client.run_query(_QUERY_ID)

    assert result is None
    assert seen == []
    assert client.executions_used == 0


@pytest.mark.asyncio
async def test_sentinel_key_from_env_is_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """The SSM `__unset__` sentinel is treated as unset by from_env."""
    monkeypatch.setenv(DUNE_API_KEY_ENV, "__unset__")
    seen: list[httpx.Request] = []
    transport = _route({}, record=seen)
    async with httpx.AsyncClient(transport=transport) as http:
        client = DuneClient.from_env(client=http)
        assert client.enabled is False
        result = await client.run_query(_QUERY_ID)

    assert result is None
    assert seen == []


@pytest.mark.asyncio
async def test_from_env_enabled_with_real_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """A real env key enables the client and the header is sent (not logged)."""
    monkeypatch.setenv(DUNE_API_KEY_ENV, "real-env-key")
    seen: list[httpx.Request] = []
    transport = _route(_happy_handlers(), record=seen)
    async with httpx.AsyncClient(transport=transport) as http:
        client = DuneClient.from_env(client=http, poll_interval=0.0)
        assert client.enabled is True
        result = await client.run_query(_QUERY_ID)

    assert result is not None
    assert result.row_count == 2
    assert seen[0].headers["X-Dune-Api-Key"] == "real-env-key"


@pytest.mark.asyncio
async def test_credit_ceiling_fails_closed() -> None:
    """At the max-executions ceiling, run_query refuses to spend another credit."""
    transport = _route(_happy_handlers())
    async with httpx.AsyncClient(transport=transport) as http:
        client = DuneClient(api_key="real-key", client=http, poll_interval=0.0, max_executions=1)
        first = await client.run_query(_QUERY_ID)
        assert first is not None
        assert client.executions_used == 1

        # Second call is over the ceiling: returns None, no new execute.
        second = await client.run_query(_QUERY_ID)
        assert second is None
        assert client.executions_used == 1


@pytest.mark.asyncio
async def test_params_are_sent_as_query_parameters() -> None:
    """params dict is forwarded under Dune's `query_parameters` body key."""
    seen: list[httpx.Request] = []
    transport = _route(_happy_handlers(), record=seen)
    async with httpx.AsyncClient(transport=transport) as http:
        client = DuneClient(api_key="real-key", client=http, poll_interval=0.0)
        await client.run_query(_QUERY_ID, params={"token_mint": "So111..."})

    execute_req = seen[0]
    assert execute_req.method == "POST"
    body = execute_req.read().decode()
    assert "query_parameters" in body
    assert "token_mint" in body
