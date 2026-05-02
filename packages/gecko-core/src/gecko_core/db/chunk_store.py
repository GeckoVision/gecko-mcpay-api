"""Chunk-store selector — feature flag for S18 cutover.

Single source of truth for ``GECKO_CHUNK_STORE``. Pattern A: every
consumer that needs to know "are we on Mongo yet?" imports from here.

Two values today:
- ``supabase`` (default until M5 cutover) — legacy Postgres + pgvector.
- ``mongo`` — MongoDB Atlas Vector Search in ``gecko_rag`` DB.

No ``dual`` mode — solo-user cutover, see
``project_mongo_cutover_no_backfill`` memory.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ChunkStore = Literal["supabase", "mongo"]
"""Static type alias for the chunk-store selector."""


class ChunkStoreSettings(BaseSettings):
    """Resolved chunk-store config. Reads ``GECKO_CHUNK_STORE`` from env."""

    kind: ChunkStore = Field("supabase", alias="GECKO_CHUNK_STORE")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )


@lru_cache(maxsize=1)
def get_chunk_store() -> ChunkStore:
    """Return the active chunk store. Cached for the process lifetime."""
    return ChunkStoreSettings().kind  # type: ignore[call-arg]


__all__ = ["ChunkStore", "ChunkStoreSettings", "get_chunk_store"]
