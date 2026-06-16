"""Dune Analytics aggregate-query client (Phase 3.4, context-engineering).

Wire reference: https://docs.dune.com/api-reference/overview/introduction
(Execute-Query API v1). Auth header: ``X-Dune-Api-Key: <DUNE_API_KEY>``.

WHY Dune for the safety / decision-integrity layer: GeckoTerminal gives a single
liquidity ratio. Dune gives the *distribution behind* that ratio — holder
histograms, LP-concentration, wash-trade proxies — the "Information-MEV
deepening" that turns one scalar into a structural read. The query SQL itself
lives in a saved Dune query (referenced by ``query_id``); this client is a
generic execute-then-poll runner and does NOT hardcode any SQL. Query IDs are
config so a caller can wire holder-distribution / wash-trade reads later.

Dune is **execute-then-poll**:
  1. ``POST  /query/{query_id}/execute``         -> ``{execution_id, state}``
  2. ``GET   /execution/{execution_id}/status``  -> poll until
     ``QUERY_STATE_COMPLETED`` (or a terminal failure/cancel state)
  3. ``GET   /execution/{execution_id}/results`` -> ``{result: {rows, metadata}}``

COST: Dune charges per query credit on execute. A naive wiring on a hot path
could silently burn the monthly allowance, so this client carries a per-process
call counter + a hard ``max_executions`` ceiling and a DEBUG cost log. The
ceiling fails CLOSED (returns ``None``, no further execute) — the *retrieval*
fails-OPEN, but credit spend never silently overruns.

FRESHNESS: Dune materializations are minutes-fresh (5-15 min). Callers should
cache results with a long TTL (``DUNE_DEFAULT_TTL_SECONDS`` below) — re-running
the same saved query inside the TTL window wastes a credit for identical data.

Structured market/chain-aggregate source — httpx + pydantic only; not a
RAG/corpus source. Fail-OPEN: any error/timeout/disabled-key returns ``None``;
errors are redacted to their exception *type* (never the key, never the body).
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

DUNE_BASE_URL = "https://api.dune.com/api/v1"

# Env var holding the Dune API key. SSM sentinel convention: `__unset__` (and
# the empty string) are treated as truly unset -> client disabled, no call.
DUNE_API_KEY_ENV = "DUNE_API_KEY"

# Dune materializations are minutes-fresh; a long TTL avoids re-spending a
# credit on identical data. Callers own the cache — this is the recommended
# default, not enforced here.
DUNE_DEFAULT_TTL_SECONDS = 900  # 15 minutes

# Default per-process execute ceiling. Conservative on purpose: a future hot
# wiring inheriting the default cannot silently burn the credit budget.
DUNE_DEFAULT_MAX_EXECUTIONS = 50

# Terminal Dune execution states (https://docs.dune.com/api-reference).
_STATE_COMPLETED = "QUERY_STATE_COMPLETED"
_STATE_FAILED = "QUERY_STATE_FAILED"
_STATE_CANCELLED = "QUERY_STATE_CANCELLED"
_STATE_EXPIRED = "QUERY_STATE_EXPIRED"
_TERMINAL_FAILURE_STATES = frozenset({_STATE_FAILED, _STATE_CANCELLED, _STATE_EXPIRED})


def _env_clean(name: str) -> str:
    """Env value, stripped, treating the SSM ``__unset__`` sentinel as empty.

    House convention (mirrors ``safety_check._env_clean`` /
    ``news_factory._env_clean``): infra pushes ``__unset__`` for
    not-yet-provisioned keys so ECS resolves ``secrets:`` at boot without error;
    runtime code treats both ``""`` and ``__unset__`` as truly unset.
    """
    value = os.environ.get(name, "").strip()
    return "" if value == "__unset__" else value


class DuneResult(BaseModel):
    """Typed result of a completed Dune query execution.

    ``rows`` is the raw row dicts straight from Dune (column shape depends on
    the saved query's SELECT — the client stays SQL-agnostic). ``metadata``
    carries Dune's column names + row count; ``execution_id`` is kept for
    provenance / debugging.
    """

    model_config = ConfigDict(extra="ignore")

    query_id: int
    execution_id: str | None = None
    rows: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def row_count(self) -> int:
        return len(self.rows)


class DuneClient:
    """Async execute-then-poll client for Dune Analytics saved queries.

    Disabled (every method returns ``None``, no network call) when the API key
    is unset / ``__unset__`` and none is injected. Construct via
    :meth:`from_env` for the production-shaped path.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = DUNE_BASE_URL,
        timeout: float = 15.0,
        poll_interval: float = 2.0,
        poll_timeout: float = 60.0,
        max_executions: int = DUNE_DEFAULT_MAX_EXECUTIONS,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = (api_key or "").strip() or None
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._poll_interval = max(poll_interval, 0.0)
        self._poll_timeout = poll_timeout
        self._max_executions = max_executions
        self._client = client
        # Per-process credit guard. Counts EXECUTE calls (the credit-charged
        # op), not status/result polls.
        self._executions = 0

    @classmethod
    def from_env(
        cls,
        *,
        client: httpx.AsyncClient | None = None,
        **kwargs: Any,
    ) -> DuneClient:
        """Build from ``DUNE_API_KEY`` (sentinel-safe). Returns a disabled
        client when the key is unset — callers still get a usable object whose
        methods fail-OPEN to ``None``."""
        return cls(api_key=_env_clean(DUNE_API_KEY_ENV) or None, client=client, **kwargs)

    @property
    def enabled(self) -> bool:
        """True only when a real (non-sentinel) key is present."""
        return self._api_key is not None

    @property
    def executions_used(self) -> int:
        """Credit-charged executes spent this process (for cost telemetry)."""
        return self._executions

    @property
    def _headers(self) -> dict[str, str]:
        # Key is only ever placed in a header dict, never logged.
        return {"X-Dune-Api-Key": self._api_key or ""}

    async def _request(self, method: str, path: str, *, json: Any | None = None) -> Any:
        url = f"{self._base_url}{path}"
        if self._client is not None:
            resp = await self._client.request(
                method, url, headers=self._headers, json=json, timeout=self._timeout
            )
        else:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.request(method, url, headers=self._headers, json=json)
        resp.raise_for_status()
        return resp.json()

    async def run_query(
        self,
        query_id: int,
        params: dict[str, Any] | None = None,
    ) -> DuneResult | None:
        """Execute a saved Dune query, poll to completion, return rows.

        Generic: ``query_id`` selects the saved query (config, not code) and
        ``params`` maps to Dune query parameters. Returns ``None`` (fail-OPEN)
        on a disabled key, the credit ceiling, any HTTP/parse error, a terminal
        Dune failure state, or a poll timeout. Never raises to the caller.
        """
        if not self.enabled:
            logger.debug("dune.disabled query_id=%s (no api key)", query_id)
            return None

        if self._executions >= self._max_executions:
            # Fail CLOSED on credit ceiling: do not spend another credit.
            logger.warning(
                "dune.credit_ceiling_reached query_id=%s used=%d max=%d — skipping execute",
                query_id,
                self._executions,
                self._max_executions,
            )
            return None

        try:
            execution_id = await self._execute(query_id, params)
            if execution_id is None:
                return None
            if not await self._poll_until_complete(execution_id):
                return None
            return await self._fetch_results(query_id, execution_id)
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            # Redact to exception TYPE only — never the body, never the key.
            logger.warning(
                "dune.run_query_failed query_id=%s error=%s", query_id, type(exc).__name__
            )
            return None

    async def _execute(self, query_id: int, params: dict[str, Any] | None) -> str | None:
        body: dict[str, Any] = {}
        if params:
            body["query_parameters"] = params
        self._executions += 1
        logger.debug(
            "dune.execute query_id=%s credit_spent used=%d/%d",
            query_id,
            self._executions,
            self._max_executions,
        )
        data = await self._request("POST", f"/query/{query_id}/execute", json=body)
        if not isinstance(data, dict):
            return None
        execution_id = data.get("execution_id")
        return str(execution_id) if execution_id else None

    async def _poll_until_complete(self, execution_id: str) -> bool:
        """Poll status until completed (True) or terminal failure/timeout (False).

        Status polls are NOT credit-charged, so they do not touch the counter.
        """
        deadline = time.monotonic() + self._poll_timeout
        while True:
            data = await self._request("GET", f"/execution/{execution_id}/status")
            state = data.get("state") if isinstance(data, dict) else None
            if state == _STATE_COMPLETED:
                return True
            if state in _TERMINAL_FAILURE_STATES:
                logger.warning(
                    "dune.execution_terminal_failure execution_id=%s state=%s",
                    execution_id,
                    state,
                )
                return False
            if time.monotonic() >= deadline:
                logger.warning(
                    "dune.poll_timeout execution_id=%s last_state=%s timeout=%.1fs",
                    execution_id,
                    state,
                    self._poll_timeout,
                )
                return False
            await asyncio.sleep(self._poll_interval)

    async def _fetch_results(self, query_id: int, execution_id: str) -> DuneResult | None:
        data = await self._request("GET", f"/execution/{execution_id}/results")
        if not isinstance(data, dict):
            return None
        result = data.get("result")
        if not isinstance(result, dict):
            return None
        rows = result.get("rows")
        metadata = result.get("metadata")
        return DuneResult(
            query_id=query_id,
            execution_id=execution_id,
            rows=list(rows) if isinstance(rows, list) else [],
            metadata=dict(metadata) if isinstance(metadata, dict) else {},
        )


__all__ = [
    "DUNE_API_KEY_ENV",
    "DUNE_BASE_URL",
    "DUNE_DEFAULT_MAX_EXECUTIONS",
    "DUNE_DEFAULT_TTL_SECONDS",
    "DuneClient",
    "DuneResult",
]
