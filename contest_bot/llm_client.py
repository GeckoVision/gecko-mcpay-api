"""Synchronous OpenRouter chat client for the local-lab voice layer.

The contest bot's main loop is sync (see ``gecko_wrap.GeckoGate`` —
same shape, ``httpx.Client`` injected lazily). This client mirrors that
choice so voices can be invoked from a sync context without crossing
the sync/async boundary inside the bot.

Wire flow per :meth:`chat`:

  1. POST ``https://openrouter.ai/api/v1/chat/completions`` with the
     standard OpenAI-shaped chat payload (``model``, ``messages``,
     optional ``response_format`` + ``temperature``).
  2. Required headers:
       * ``Authorization: Bearer ${OPENROUTER_API_KEY}`` — fail loudly
         if unset (CLAUDE.md "no secrets in code" / fail-fast posture).
       * ``HTTP-Referer: https://geckovision.tech`` — OpenRouter
         attribution.
       * ``X-Title: Gecko-Lab`` — request label in the OpenRouter
         dashboard.
  3. On 429 / 5xx, retry once after a 2s backoff (capped). On any
     other 4xx, raise immediately — no point retrying a 401/403/422.
  4. Parse ``choices[0].message.content`` and ``usage.cost`` for the
     :class:`LLMResponse` envelope.

The client never falls back to a default provider key — if the env
var is missing it raises ``OpenRouterConfigError`` at the call site
so the voice layer (which is the only caller) surfaces the misconfig
loudly instead of silently returning empty opinions.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_REFERER = "https://geckovision.tech"
OPENROUTER_TITLE = "Gecko-Lab"

DEFAULT_TIMEOUT_S = 45.0
DEFAULT_RETRY_BACKOFF_S = 2.0


class OpenRouterError(Exception):
    """Base for OpenRouter client errors."""


class OpenRouterConfigError(OpenRouterError):
    """Raised when required env (OPENROUTER_API_KEY) is unset."""


class OpenRouterCallError(OpenRouterError):
    """Raised on transport failure or unexpected non-2xx after retry."""


class LLMResponse(BaseModel):
    """Parsed result of one OpenRouter chat call.

    ``raw`` carries the full upstream JSON body so voices that want
    additional fields (logprobs, native_finish_reason, etc.) can read
    them without re-shaping the client.
    """

    model_config = ConfigDict(extra="allow")

    content: str
    model_used: str
    cost_usd: float
    prompt_tokens: int
    completion_tokens: int
    elapsed_ms: int
    raw: dict[str, Any] = Field(default_factory=dict)


class OpenRouterClient:
    """Thin synchronous OpenRouter chat wrapper.

    One instance per agent / voice-runner. ``http_client`` may be
    injected (for tests using ``httpx.MockTransport``). Otherwise the
    client lazy-inits its own ``httpx.Client`` on first call and is
    closed via :meth:`aclose`.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        retry_backoff_s: float = DEFAULT_RETRY_BACKOFF_S,
        http_client: httpx.Client | None = None,
    ) -> None:
        # Capture the env-set key once at construction; if the caller
        # passes ``api_key`` explicitly that wins. Either way we fail
        # loudly if both are absent — the voice layer treats the
        # OpenRouter call as load-bearing, so silent fallback would
        # produce empty opinions that look like real abstentions.
        env_key = os.environ.get("OPENROUTER_API_KEY")
        resolved = api_key or env_key
        if not resolved:
            raise OpenRouterConfigError(
                "OPENROUTER_API_KEY is not set. Export it before invoking "
                "the local lab voices (see docs/strategy/2026-05-20-local-panel-voices-spec.md)."
            )
        self._api_key = resolved
        self._timeout_s = timeout_s
        self._retry_backoff_s = retry_backoff_s
        self._http_client = http_client
        self._owns_client = http_client is None

    def _client(self) -> httpx.Client:
        if self._http_client is None:
            self._http_client = httpx.Client(timeout=self._timeout_s)
        return self._http_client

    def aclose(self) -> None:
        """Close the underlying httpx client when this client owns it.

        Named ``aclose`` to mirror the convention used in
        ``gecko_core.trade_agent.oracle_client.GeckoOracleClient`` —
        even though this client is synchronous, the lifecycle hook
        keeps the API consistent across the project.
        """
        if self._owns_client and self._http_client is not None:
            self._http_client.close()
            self._http_client = None

    def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        response_format: dict[str, Any] | None = None,
        temperature: float = 0.0,
    ) -> LLMResponse:
        """Run one chat completion. Raises on unrecoverable failure."""
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if response_format is not None:
            body["response_format"] = response_format
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": OPENROUTER_REFERER,
            "X-Title": OPENROUTER_TITLE,
        }

        client = self._client()
        started = time.monotonic()
        response = self._post_with_retry(client, body, headers)
        elapsed_ms = int((time.monotonic() - started) * 1000)

        try:
            parsed = response.json()
        except (ValueError, TypeError) as exc:
            raise OpenRouterCallError(
                f"OpenRouter response was not valid JSON: {response.text[:200]!r}"
            ) from exc
        if not isinstance(parsed, dict):
            raise OpenRouterCallError(
                f"OpenRouter response was not a JSON object: {type(parsed).__name__}"
            )

        return _build_llm_response(parsed, fallback_model=model, elapsed_ms=elapsed_ms)

    def _post_with_retry(
        self,
        client: httpx.Client,
        body: dict[str, Any],
        headers: dict[str, str],
    ) -> httpx.Response:
        """One retry on 429 / 5xx; no retry on other 4xx."""
        attempts = 0
        while True:
            attempts += 1
            try:
                response = client.post(OPENROUTER_URL, json=body, headers=headers)
            except httpx.HTTPError as exc:
                if attempts == 1:
                    logger.warning(
                        "openrouter: transport error on attempt %d (%s); retrying after %.1fs",
                        attempts,
                        exc,
                        self._retry_backoff_s,
                    )
                    time.sleep(self._retry_backoff_s)
                    continue
                raise OpenRouterCallError(
                    f"transport error after {attempts} attempts: {type(exc).__name__}: {exc}"
                ) from exc

            if response.status_code == 200:
                return response

            retryable = response.status_code == 429 or 500 <= response.status_code < 600
            if retryable and attempts == 1:
                logger.warning(
                    "openrouter: %d on attempt %d; retrying after %.1fs",
                    response.status_code,
                    attempts,
                    self._retry_backoff_s,
                )
                time.sleep(self._retry_backoff_s)
                continue

            raise OpenRouterCallError(
                f"OpenRouter returned {response.status_code}: {response.text[:200]!r}"
            )


def _build_llm_response(
    parsed: dict[str, Any], *, fallback_model: str, elapsed_ms: int
) -> LLMResponse:
    """Build :class:`LLMResponse` from the OpenRouter JSON body.

    Defensive coercion — OpenRouter occasionally omits ``usage.cost``
    on free-tier models. Missing numbers degrade to 0.0 / 0 instead of
    raising, since the voice layer treats cost as telemetry not a
    contract field.
    """
    choices = parsed.get("choices") or []
    content = ""
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        message = choices[0].get("message") or {}
        if isinstance(message, dict):
            raw_content = message.get("content")
            if isinstance(raw_content, str):
                content = raw_content

    usage = parsed.get("usage") or {}
    if not isinstance(usage, dict):
        usage = {}

    cost_usd = _coerce_float(usage.get("cost"))
    prompt_tokens = _coerce_int(usage.get("prompt_tokens"))
    completion_tokens = _coerce_int(usage.get("completion_tokens"))
    model_used = parsed.get("model")
    if not isinstance(model_used, str) or not model_used:
        model_used = fallback_model

    return LLMResponse(
        content=content,
        model_used=model_used,
        cost_usd=cost_usd,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        elapsed_ms=elapsed_ms,
        raw=parsed,
    )


def _coerce_float(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return 0.0
    return 0.0


def _coerce_int(value: Any) -> int:
    if isinstance(value, bool):
        # bool is a subclass of int; OpenRouter never returns bools
        # here, but guard anyway so a stray True doesn't become 1.
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


__all__ = [
    "DEFAULT_RETRY_BACKOFF_S",
    "DEFAULT_TIMEOUT_S",
    "OPENROUTER_REFERER",
    "OPENROUTER_TITLE",
    "OPENROUTER_URL",
    "LLMResponse",
    "OpenRouterCallError",
    "OpenRouterClient",
    "OpenRouterConfigError",
    "OpenRouterError",
]
