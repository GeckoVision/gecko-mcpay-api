"""S17-WEDGE-WIRE-02 — Arxiv embed adapter unit test."""

from __future__ import annotations

from gecko_core.sources.arxiv.embed_adapter import _abs_url_for, to_chunks


def _entry(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "text": "Verifiable Compute Markets\n\nWe propose a protocol...",
        "provider_kind": "free:arxiv",
        "metadata": {
            "title": "Verifiable Compute Markets",
            "abstract": "We propose a protocol for verifiable compute markets...",
            "authors": ["Jane Doe", "Aaron Buchwald"],
            "arxiv_id": "2401.12345",
            "abs_url": "https://arxiv.org/abs/2401.12345",
            "pdf_url": "https://arxiv.org/pdf/2401.12345",
            "published_date": "2026-04-30T00:00:00Z",
            "primary_category": "cs.CR",
        },
    }
    base.update(overrides)
    return base


def test_to_chunks_renders_title_authors_published_abstract() -> None:
    out = to_chunks([_entry()])

    assert len(out) == 1
    pc = out[0]
    assert pc.resource_id == "2401.12345"
    assert pc.chunk_index == 0
    assert "Verifiable Compute Markets" in pc.text
    assert "Authors: Jane Doe, Aaron Buchwald" in pc.text
    assert "Published: 2026-04-30T00:00:00Z" in pc.text
    assert "Abstract:" in pc.text
    assert "We propose a protocol for verifiable compute markets" in pc.text
    assert pc.metadata["abs_url"] == "https://arxiv.org/abs/2401.12345"


def test_to_chunks_drops_entries_without_text() -> None:
    out = to_chunks(
        [
            {"text": "", "metadata": {"title": "", "abstract": ""}},
            {},
        ]
    )
    assert out == []


def test_abs_url_for_falls_back_to_constructed_url() -> None:
    url = _abs_url_for({"metadata": {"arxiv_id": "2402.99999"}})
    assert url == "https://arxiv.org/abs/2402.99999"
