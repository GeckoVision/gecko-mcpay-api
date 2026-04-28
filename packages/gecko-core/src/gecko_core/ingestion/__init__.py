"""Ingestion: discovery → extraction → chunking → embedding → store.

Public surface kept small: `discover`, `ingest`, plus the result/candidate
types used by the approval flow and the workflow layer.
"""

from gecko_core.models import SourceCandidate

from .discovery import discover
from .pipeline import ingest, url_hash
from .types import IngestionResult, SourceOutcome

__all__ = [
    "IngestionResult",
    "SourceCandidate",
    "SourceOutcome",
    "discover",
    "ingest",
    "url_hash",
]
