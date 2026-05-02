"""Canonical ``ProviderKind`` Literal — the single source of truth.

S17-WEDGE-DATA-01. Mirrors the SQL ``CHECK`` constraint on
``chunks.provider_kind`` and ``sources.provider_kind`` (migration
``20260502000000_provider_kind.sql``). Drift between this Literal and the
SQL CHECK is caught by ``tests/test_provider_kind_consistency.py`` —
exactly the Pattern A enforcement shape we use for ``PaymentMode``.

Why one Literal here instead of per-provider strings:

  Sprint 16 wired Bazaar / Arxiv / twit.sh dispatchers but their chunks
  never reached the LLM because the ``chunks`` table had no
  ``provider_kind`` column. Path B (S17-WEDGE-WIRE-01) makes the kind a
  first-class column. Per Pattern A, every consumer routes through this
  module — never re-declares.

Note on legacy provider-internal ``provider_kind`` strings:

  ``BazaarChunk.provider_kind`` (``"bazaar:<resource_type>"``) and
  ``arxiv.provider._entry_to_chunk``'s ``"free:arxiv"`` are a *different*
  concept — adapter-internal billing/source tags, not the chunks-table
  kind. Software-engineer's S17-WEDGE-WIRE-02 will translate those to
  the canonical ``ProviderKind`` in the per-provider ``embed_adapter.py``
  before calling ``insert_chunks``. Don't conflate the two; this module
  owns only the chunks-table column values.

Adding a new provider kind:

  1. Add the value to ``ProviderKind`` below.
  2. Ship a migration that extends both
     ``chunks_provider_kind_check`` and ``sources_provider_kind_check``.
  3. The drift test will fail loudly until both sides agree.
"""

from __future__ import annotations

from typing import Final, Literal, get_args

ProviderKind = Literal[
    "web",
    "youtube",
    "bazaar",
    "arxiv",
    "twitsh",
    "hn",
    "reddit",
    "gecko_precedent",
]
"""Static type alias for the ``chunks.provider_kind`` /
``sources.provider_kind`` column. Every consumer imports from here."""

PROVIDER_KINDS: Final[tuple[str, ...]] = get_args(ProviderKind)
"""Runtime tuple — used by env validation and schema-drift assertions."""

__all__ = ["PROVIDER_KINDS", "ProviderKind"]
