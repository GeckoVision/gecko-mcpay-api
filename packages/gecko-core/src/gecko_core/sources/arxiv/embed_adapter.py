"""Arxiv -> ProviderChunk adapter.

S17-WEDGE-WIRE-02 — Renders Arxiv abstract entries (the dict shape
emitted by ``ArxivSource._entry_to_chunk``) into :class:`ProviderChunk`
records so they can be embedded + indexed alongside Tavily web chunks.

Each Arxiv entry is already a single self-contained chunk (title +
abstract); we don't sub-chunk further. ``resource_id`` is the arxiv id
(e.g. ``2401.12345``) which lets every entry land as its own
``sources`` row keyed by the real arxiv abstract URL.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from gecko_core.ingestion.types import ProviderChunk

# Cap mirrors the bazaar adapter — comfortably under text-embedding-3-small's
# 8k-token limit. Arxiv abstracts are typically 1-3 KB so this is a guard
# rather than a routine truncation.
_MAX_TEXT_CHARS = 6000


def _render_text(entry: dict[str, Any]) -> str:
    """Render an Arxiv entry as embedding-friendly text.

    The title leads (strongest retrieval signal), then authors +
    publication date as a compact attribution line, then the abstract.
    Empty title or abstract degrades gracefully — both rarely missing
    from the real feed but the parser tolerates it, so we do too.
    """
    raw_md = entry.get("metadata")
    md: dict[str, Any] = raw_md if isinstance(raw_md, dict) else entry
    title = str(md.get("title") or "").strip()
    summary = str(md.get("abstract") or md.get("summary") or entry.get("text") or "").strip()
    if summary and title and summary.startswith(title):
        # ``ArxivSource._entry_to_chunk`` packs ``"{title}\n\n{abstract}"``
        # into ``text``; strip the duplicated title so the rendered output
        # doesn't carry it twice when callers pass the raw chunk dict.
        summary = summary[len(title) :].lstrip("\n").strip()

    raw_authors = md.get("authors") or []
    authors: list[str] = []
    if isinstance(raw_authors, Sequence) and not isinstance(raw_authors, (str, bytes)):
        authors = [str(a).strip() for a in raw_authors if str(a).strip()]
    elif isinstance(raw_authors, str) and raw_authors.strip():
        authors = [raw_authors.strip()]

    published = str(md.get("published_date") or md.get("published") or "").strip()

    parts: list[str] = []
    if title:
        parts.append(title)
    attribution_bits: list[str] = []
    if authors:
        attribution_bits.append("Authors: " + ", ".join(authors[:8]))
    if published:
        attribution_bits.append(f"Published: {published}")
    if attribution_bits:
        parts.append("\n".join(attribution_bits))
    if summary:
        parts.append("Abstract:\n" + summary)

    text = "\n\n".join(parts).strip()
    if not text:
        text = (entry.get("text") or "").strip()
    if len(text) > _MAX_TEXT_CHARS:
        text = text[:_MAX_TEXT_CHARS]
    return text


def _resource_id_for(entry: dict[str, Any]) -> str:
    raw_md = entry.get("metadata")
    md: dict[str, Any] = raw_md if isinstance(raw_md, dict) else entry
    arxiv_id = str(md.get("arxiv_id") or "").strip()
    if arxiv_id:
        return arxiv_id
    abs_url = str(md.get("abs_url") or "").strip()
    if abs_url:
        # Trailing path segment of the abs URL is the arxiv id.
        return abs_url.rsplit("/", 1)[-1] or abs_url
    return "arxiv-unknown"


def _abs_url_for(entry: dict[str, Any]) -> str:
    """The synthetic_uri for the source row — Arxiv has a real URL.

    Falls back to constructing the standard ``https://arxiv.org/abs/<id>``
    form when only the id is present.
    """
    raw_md = entry.get("metadata")
    md: dict[str, Any] = raw_md if isinstance(raw_md, dict) else entry
    abs_url = str(md.get("abs_url") or "").strip()
    if abs_url:
        return abs_url
    arxiv_id = str(md.get("arxiv_id") or "").strip()
    if arxiv_id:
        return f"https://arxiv.org/abs/{arxiv_id}"
    return "https://arxiv.org/abs/unknown"


def to_chunks(payload: Sequence[dict[str, Any]]) -> list[ProviderChunk]:
    """Convert ArxivSource chunk dicts into ProviderChunk records.

    One Arxiv entry == one ProviderChunk (no sub-chunking). The dispatcher
    is responsible for one source row per entry (Arxiv has real URLs);
    ``ingest_provider_chunks`` honors that by grouping on
    ``(synthetic_uri, resource_id)``.
    """
    out: list[ProviderChunk] = []
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        text = _render_text(entry)
        if not text:
            continue
        resource_id = _resource_id_for(entry)
        out.append(
            ProviderChunk(
                resource_id=resource_id,
                chunk_index=0,
                text=text,
                metadata={
                    "abs_url": _abs_url_for(entry),
                    **(entry.get("metadata") or {}),
                },
            )
        )
    return out


__all__ = ["_abs_url_for", "to_chunks"]
