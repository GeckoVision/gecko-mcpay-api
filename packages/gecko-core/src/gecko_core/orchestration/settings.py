"""Orchestration settings.

Kept separate from `IngestionSettings` so generation knobs (model, prompt
caps) rotate independently from data-pipeline credentials.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class OrchestrationSettings(BaseSettings):
    """LLM-side knobs for the basic + (later) pro orchestration paths."""

    # ClawRouter is the v3 default. Pin a JSON-mode-safe model for orchestration
    # steps that depend on response_format=json_object — `blockrun/auto` may
    # route to a model that breaks JSON mode. Override per-deploy via env.
    chat_model: str = Field("openai/gpt-4o", alias="CHAT_MODEL")

    # OpenAI-compatible base_url. Default points at the local ClawRouter proxy
    # (`npx @blockrun/clawrouter`) on port 8402. Set to OpenAI's URL for the v2
    # fallback path, or to any OpenAI-compatible gateway.
    llm_endpoint: str = Field("http://localhost:8402/v1", alias="GECKO_LLM_ENDPOINT")

    # Auth header value sent to the LLM endpoint. ClawRouter accepts the literal
    # "x402" because payments are wallet-signed. For OpenAI fallback, set to
    # the real API key.
    llm_api_key: str = Field("x402", alias="GECKO_LLM_API_KEY")

    # Defensive cap on prompt input tokens. Truncation happens in
    # orchestration.basic before the OpenAI call. 60k leaves comfortable
    # headroom under the 128k context window for response + system prompt.
    max_input_tokens: int = Field(60_000, alias="ORCH_MAX_INPUT_TOKENS")

    # Sampling. Low for grounded, deterministic-ish output.
    temperature: float = Field(0.3, alias="ORCH_TEMPERATURE")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )


@lru_cache(maxsize=1)
def get_orchestration_settings() -> OrchestrationSettings:
    return OrchestrationSettings()  # type: ignore[call-arg]


__all__ = ["OrchestrationSettings", "get_orchestration_settings"]
