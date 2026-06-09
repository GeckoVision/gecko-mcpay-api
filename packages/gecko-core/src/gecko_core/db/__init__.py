"""Database accessors for gecko-core.

Two stores live here:

- **Supabase (Postgres + pgvector)** — sessions, sources, payments, memory.
  Public surface: :class:`SupabaseSettings`, :func:`create_supabase_client`.
  Re-exported from this package so legacy imports
  ``from gecko_core.db import create_supabase_client`` keep working.

- **MongoDB Atlas** — chunks + chunk_embedding_cache + chunks_write_audit
  in the ``gecko_rag`` database (post S18 cutover). See
  :mod:`gecko_core.db.mongo`.

Chunk-store selection goes through :func:`get_chunk_store` — default
``supabase`` until S18-MONGO-CUTOVER-01 flips it to ``mongo``.
"""

from __future__ import annotations

import os
from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from supabase import Client, create_client

from gecko_core.db.chunk_store import ChunkStore, ChunkStoreSettings, get_chunk_store

# Sentinels treated as "not configured" (mirrors the .env.example placeholders +
# the is_privy_configured sentinel set). Cheap, network-free detection.
_SUPABASE_SENTINELS: frozenset[str] = frozenset(
    {"", "__unset__", "__dev_change_me__", "changeme", "your-supabase-url"}
)


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


def is_supabase_configured(
    url: str | None = None,
    service_role_key: str | None = None,
) -> bool:
    """Cheap, network-free check: are real (non-sentinel) Supabase creds present?

    Reads the process environment (``SUPABASE_URL`` / ``SUPABASE_SERVICE_ROLE_KEY``)
    when args are ``None``. Does NOT construct a client or touch the network — it
    only gates which ``GrantStore`` the wallet factory picks. Mirrors the
    ``is_privy_configured`` sentinel pattern.
    """
    raw_url = url if url is not None else os.environ.get("SUPABASE_URL", "")
    raw_key = (
        service_role_key
        if service_role_key is not None
        else os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    )
    clean_url = (raw_url or "").strip()
    clean_key = (raw_key or "").strip()
    if clean_url in _SUPABASE_SENTINELS or clean_key in _SUPABASE_SENTINELS:
        return False
    return bool(clean_url) and bool(clean_key)


__all__ = [
    "ChunkStore",
    "ChunkStoreSettings",
    "SupabaseSettings",
    "create_supabase_client",
    "get_chunk_store",
    "is_supabase_configured",
]
