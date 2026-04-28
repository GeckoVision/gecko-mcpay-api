"""Ingestion-internal result types.

`SourceCandidate` lives in `gecko_core.models` (crosses every boundary).
`IngestionResult` and `SourceOutcome` are exposed because the workflow + CLI
need them to render summaries.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class SourceOutcome(BaseModel):
    """Per-source result of an ingestion run."""

    url: str
    type: str
    status: str  # "indexed" | "skipped" | "failed"
    chunk_count: int = 0
    reason: str | None = None


class IngestionResult(BaseModel):
    """Aggregate result of `pipeline.ingest()`."""

    session_id: str
    indexed: int = 0
    skipped: int = 0
    failed: int = 0
    total_chunks: int = 0
    outcomes: list[SourceOutcome] = Field(default_factory=list)
