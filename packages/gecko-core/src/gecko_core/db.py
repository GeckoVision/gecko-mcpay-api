"""Shared Supabase client factory + settings.

Lives at gecko_core.db (not under sessions/) because ingestion and rag will
also need a service-role client. Service-role key is server-side only — never
exposed to gecko-mcpay-app, which uses the anon key + RLS via gecko-api.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from supabase import Client, create_client


class SupabaseSettings(BaseSettings):
    """Server-side Supabase config. Service-role key is a SecretStr so it
    never lands in logs or repr output."""

    url: str = Field(..., alias="SUPABASE_URL")
    service_role_key: SecretStr = Field(..., alias="SUPABASE_SERVICE_ROLE_KEY")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )


@lru_cache(maxsize=1)
def _settings() -> SupabaseSettings:
    return SupabaseSettings()  # type: ignore[call-arg]


def create_supabase_client(
    url: str | None = None,
    service_role_key: SecretStr | str | None = None,
) -> Client:
    """Build a Supabase client with the service-role key.

    Args fall back to env-loaded settings. Never accept the anon key here —
    this factory is for trusted server-side code only.
    """
    if url is None or service_role_key is None:
        s = _settings()
        url = url or s.url
        service_role_key = service_role_key or s.service_role_key

    key = (
        service_role_key.get_secret_value()
        if isinstance(service_role_key, SecretStr)
        else service_role_key
    )
    return create_client(url, key)
