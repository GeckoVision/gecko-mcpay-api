"""Ingestion-layer exceptions.

Kept narrow on purpose: the pipeline already uses well-known stdlib /
third-party exception classes (openai.RateLimitError, RuntimeError, etc.)
and the audit classifier matches by name. The exceptions defined here
are the ones the *audit* needs to be able to classify deterministically
without inspecting message strings — a class-name match wins over a
substring match every time.

S16-INGEST-02 introduces `ChunkValidationError` so pre-flight validation
in `SessionStore.insert_chunks` can refuse a doomed insert before it
crosses the wire. The DB CHECK constraint added in the same sprint is
the belt-and-braces backstop.
"""

from __future__ import annotations


class ChunkValidationError(ValueError):
    """A chunk row failed pre-flight validation in `insert_chunks`.

    Two cases today:

    1. Empty / whitespace-only text. `_filter_embeddable` should already
       have dropped this in the pipeline; if it didn't, we raise here
       instead of letting Postgres reject the row mid-batch (which would
       roll back the whole transaction and surface as `unknown`).
    2. Embedding wrong dimensionality (FM-2). Catches a poisoned cache
       row that re-embed didn't fix — surfaces as `dim_mismatch` to the
       audit classifier.

    Inherits from `ValueError` because callers that already catch
    `ValueError` for input-shape problems should treat this the same way.
    """

    def __init__(self, message: str, *, kind: str) -> None:
        super().__init__(message)
        self.kind = kind
        """One of {'empty_text', 'dim_mismatch'} — used by callers that
        want to map the validation failure to an audit `error_kind`
        without re-parsing the message."""


__all__ = ["ChunkValidationError"]
