"""Bazaar -> ProviderChunk adapter.

S17-WEDGE-WIRE-02 — Renders a sequence of :class:`BazaarChunk` records
into the shared :class:`ProviderChunk` shape so they can flow through
``ingest_provider_chunks`` and end up as rows in the ``chunks`` table
(provider_kind='bazaar') alongside Tavily-web chunks.

Why a per-provider adapter (and not a generic switch):
    Bazaar payloads are JSON product/service descriptors with structured
    fields (title, description, price, merchant). The right embedding
    text isn't ``json.dumps(payload)`` — it's a human-readable rendering
    that puts the discriminating attributes up front. Arxiv abstracts
    and tweets need different renderings entirely; a shared ``adapter``
    would be a switch-statement masquerading as abstraction. See the
    design memo §2.1 for the call.
"""

from __future__ import annotations

import re
from typing import Any

from gecko_core.ingestion.types import ProviderChunk
from gecko_core.sources.bazaar.types import BazaarChunk

# Maximum text length we feed the embedder per chunk. text-embedding-3-small
# accepts 8192 tokens (~32 KB chars at typical English density); we cap well
# below that so a single pathological description can't blow up a batch.
_MAX_TEXT_CHARS = 6000


def _slugify(value: str) -> str:
    """Best-effort slug for a Bazaar service id when none is supplied."""
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", value or "").strip("-").lower()
    return cleaned or "unknown"


def _resource_id_for(chunk: BazaarChunk) -> str:
    """Derive a stable resource id for grouping chunks under one source row.

    Falls back through ``metadata.service_slug`` -> ``metadata.resource_id``
    -> ``metadata.url`` -> a slugified ``provider_kind`` so we never
    collapse two distinct services into one synthetic source row.
    """
    md = chunk.metadata or {}
    for key in ("service_slug", "resource_id", "service_id", "id", "url"):
        val = md.get(key)
        if isinstance(val, str) and val.strip():
            return _slugify(val)
    return _slugify(chunk.provider_kind or "bazaar")


def _render_text(chunk: BazaarChunk) -> str:
    """Render a BazaarChunk into embedding-friendly text.

    Layout puts title + description first (highest signal for retrieval),
    then a short price/merchant footer that reads naturally to the LLM
    when the chunk is later cited. Falls back to the raw chunk.text when
    metadata is sparse — empty results are filtered upstream.
    """
    md: dict[str, Any] = chunk.metadata or {}
    title = str(md.get("title") or md.get("name") or "").strip()
    description = str(md.get("description") or md.get("summary") or chunk.text or "").strip()
    merchant = str(md.get("merchant") or md.get("seller") or md.get("provider") or "").strip()

    price_str = ""
    price_cents = md.get("price_usd_cents")
    if isinstance(price_cents, (int, float)) and price_cents > 0:
        price_str = f"{float(price_cents) / 100:.2f} USD"
    else:
        price = md.get("price_usd") or md.get("price")
        if isinstance(price, (int, float)) and price > 0:
            price_str = f"{float(price):.2f} USD"
        elif isinstance(price, str) and price.strip():
            price_str = price.strip()

    parts: list[str] = []
    if title:
        parts.append(title)
    if description and description != title:
        parts.append(description)
    footer_bits: list[str] = []
    if price_str:
        footer_bits.append(f"Price: {price_str}")
    if merchant:
        footer_bits.append(f"Provider: {merchant}")
    if footer_bits:
        parts.append("\n".join(footer_bits))

    text = "\n\n".join(p for p in parts if p).strip()
    if not text:
        # Last-resort: chunk.text itself (already truncated by the
        # adapter that produced the BazaarChunk).
        text = (chunk.text or "").strip()
    if len(text) > _MAX_TEXT_CHARS:
        text = text[:_MAX_TEXT_CHARS]
    return text


def to_chunks(payload: list[BazaarChunk]) -> list[ProviderChunk]:
    """Convert a list of BazaarChunk into ProviderChunk records.

    Chunks with empty rendered text are dropped (matches the embedder's
    expectations and the existing ``_filter_embeddable`` semantics on
    the Tavily path). ``chunk_index`` is assigned per-resource so the
    ``(source_id, chunk_index)`` uniqueness on the ``chunks`` table holds
    when several services land under one synthetic source row.
    """
    out: list[ProviderChunk] = []
    per_resource_index: dict[str, int] = {}
    for chunk in payload:
        text = _render_text(chunk)
        if not text:
            continue
        resource_id = _resource_id_for(chunk)
        idx = per_resource_index.get(resource_id, 0)
        per_resource_index[resource_id] = idx + 1
        out.append(
            ProviderChunk(
                resource_id=resource_id,
                chunk_index=idx,
                text=text,
                metadata=dict(chunk.metadata or {}),
            )
        )
    return out


__all__ = ["to_chunks"]
