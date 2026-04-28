"""Ingestion-side settings.

Kept separate from `SupabaseSettings` because OpenAI + Tavily are external
service credentials with different rotation/scoping concerns from the DB.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class IngestionSettings(BaseSettings):
    openai_api_key: SecretStr = Field(..., alias="OPENAI_API_KEY")
    tavily_api_key: SecretStr = Field(..., alias="TAVILY_API_KEY")
    embed_model: str = Field("text-embedding-3-small", alias="EMBED_MODEL")
    deepgram_api_key: SecretStr | None = Field(default=None, alias="DEEPGRAM_API_KEY")
    deepgram_max_audio_minutes: int = Field(default=30, alias="DEEPGRAM_MAX_AUDIO_MIN")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )


@lru_cache(maxsize=1)
def get_ingestion_settings() -> IngestionSettings:
    return IngestionSettings()
