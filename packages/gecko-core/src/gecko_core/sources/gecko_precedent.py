"""Gecko Flywheel as a `Source` (S2X-06).

The flywheel is the only "source" populated from internal state rather than
a third-party API. We wrap retrieval as a `Source` so it flows through the
same dispatcher pipeline as Colosseum / HN / twit.sh — uniform error-
handling, uniform cost ledger (always 0 — internal Postgres call), uniform
introspection on whether a source fired.

Unlike external sources, `applies_to` always returns True: precedent
retrieval is category-agnostic; the cosine threshold inside
`retrieve_gecko_precedent` does the gating. If the corpus is empty the
source still fires (with an empty payload) so the renderer can produce the
"No prior precedents found." line — that absence is itself signal.
"""

from __future__ import annotations

from gecko_core.sessions.store import GeckoPrecedent, SessionStore
from gecko_core.sources import SourceResult


class GeckoPrecedentSource:
    """`Source`-conforming wrapper around `SessionStore.retrieve_gecko_precedent`.

    The constructor takes the embedding (already computed by the caller —
    we don't re-embed inside the source so the caller keeps cost
    attribution centralized) and the store handle.
    """

    name = "gecko_precedent"

    def __init__(
        self,
        *,
        embedding: list[float],
        store: SessionStore,
        similarity_threshold: float = 0.78,
        limit: int = 5,
    ) -> None:
        self._embedding = embedding
        self._store = store
        self._similarity_threshold = similarity_threshold
        self._limit = limit

    async def applies_to(self, *, categories: set[str]) -> bool:
        # Precedent retrieval is category-agnostic; cosine threshold gates
        # relevance, not categories. The `categories` arg is part of the
        # protocol so we accept it but ignore it.
        del categories
        return True

    async def fetch(self, *, idea: str, categories: set[str]) -> SourceResult:
        del idea, categories  # retrieval is driven by the embedding only
        precedents: list[GeckoPrecedent] = await self._store.retrieve_gecko_precedent(
            embedding=self._embedding,
            similarity_threshold=self._similarity_threshold,
            limit=self._limit,
        )
        # Serialize as JSON-safe dicts so the payload round-trips through
        # the result store without Pydantic-on-the-other-side coupling.
        payload_rows = [p.model_dump(mode="json") for p in precedents]
        return SourceResult(
            source_name=self.name,
            payload={"precedents": payload_rows, "count": len(payload_rows)},
            cost_usd=0.0,
            fired=True,
        )


__all__ = ["GeckoPrecedentSource"]
