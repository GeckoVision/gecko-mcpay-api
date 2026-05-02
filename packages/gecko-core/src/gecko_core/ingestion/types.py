"""Ingestion-internal result types.

`SourceCandidate` lives in `gecko_core.models` (crosses every boundary).
`IngestionResult` and `SourceOutcome` are exposed because the workflow + CLI
need them to render summaries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field


# S17-WEDGE-WIRE-02 — Tiny structural shape that each provider's
# ``embed_adapter.to_chunks(...)`` returns. Keeps the per-provider
# rendering logic isolated in the provider package while letting the
# shared ``ingest_provider_chunks`` pipeline consume a uniform record.
#
# Note: ``provider_kind`` is intentionally NOT a field here — it is
# applied by ``ingest_provider_chunks`` at the call boundary, not by
# the adapter. See ``docs/strategy/2026-05-02-wedge-wire-path-b-design.md``
# §2.1 for the rationale (no shared switch-statement adapter).
@dataclass(frozen=True)
class ProviderChunk:
    """One embeddable unit produced by a provider's embed adapter.

    Attributes:
        resource_id:  Stable identifier for the upstream resource the
            chunk belongs to (Bazaar service slug, arxiv id, session id
            for twit.sh, ...). Used to group chunks under the same
            synthetic ``sources`` row.
        chunk_index: Order within ``resource_id``. Persisted to
            ``chunks.chunk_index`` for idempotency.
        text:        The text that will be embedded + retrieved. Must
            be non-empty after strip; empties are filtered out before
            the embedder is called.
        metadata:    Free-form dict carried alongside the chunk. The
            ingest path does not persist this today (no ``metadata``
            column on ``chunks``) — kept for future structured-citation
            work and for unit tests that want to assert provenance.
    """

    resource_id: str
    chunk_index: int
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


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
    # S12-PROVIDER-01 — populated when a SourceProvider's fetch() times
    # out, raises, or reports unhealthy. Empty by default. The S13+
    # critic agent in `orchestration/pro.py` reads this to surface gaps
    # in-debate ("we couldn't verify FlightAware reliability because the
    # provider was unreachable; treat the verdict as conditional"),
    # turning the failure mode into a visible feature.
    degraded_sources: list[str] = Field(default_factory=list)
