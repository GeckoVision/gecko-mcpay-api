"""S17-WEDGE-WIRE-02 — Bazaar embed adapter unit test.

Pins the contract: ``to_chunks(list[BazaarChunk]) -> list[ProviderChunk]``
produces records with non-empty, human-readable text and stable
``resource_id`` derivation.
"""

from __future__ import annotations

from decimal import Decimal

from gecko_core.ingestion.types import ProviderChunk
from gecko_core.sources.bazaar.embed_adapter import to_chunks
from gecko_core.sources.bazaar.types import BazaarChunk


def test_to_chunks_renders_title_description_price_provider() -> None:
    chunk = BazaarChunk(
        text="raw fallback text",
        provider_kind="bazaar:json",
        cost_usd=Decimal("0.10"),
        metadata={
            "service_slug": "crypto-onramp",
            "title": "Coinbase Onramp",
            "description": "Buy crypto with a credit card.",
            "merchant": "Coinbase",
            "price_usd_cents": 250,
        },
    )

    out = to_chunks([chunk])

    assert len(out) == 1
    pc = out[0]
    assert isinstance(pc, ProviderChunk)
    assert pc.resource_id == "crypto-onramp"
    assert pc.chunk_index == 0
    assert "Coinbase Onramp" in pc.text
    assert "Buy crypto with a credit card." in pc.text
    assert "Price: 2.50 USD" in pc.text
    assert "Provider: Coinbase" in pc.text
    # Metadata is preserved for downstream citation rendering.
    assert pc.metadata["service_slug"] == "crypto-onramp"


def test_to_chunks_drops_empty_text() -> None:
    empty = BazaarChunk(text="", provider_kind="bazaar:json", metadata={})
    out = to_chunks([empty])
    assert out == []


def test_to_chunks_falls_back_to_text_when_metadata_sparse() -> None:
    chunk = BazaarChunk(
        text="API returns USDC quote in 200 ms.",
        provider_kind="bazaar:text",
        metadata={"resource_id": "quote-api"},
    )
    out = to_chunks([chunk])
    assert len(out) == 1
    assert "USDC quote" in out[0].text
    assert out[0].resource_id == "quote-api"


def test_to_chunks_assigns_per_resource_indices() -> None:
    a1 = BazaarChunk(text="t1", provider_kind="bazaar:json", metadata={"service_slug": "a"})
    a2 = BazaarChunk(text="t2", provider_kind="bazaar:json", metadata={"service_slug": "a"})
    b1 = BazaarChunk(text="t3", provider_kind="bazaar:json", metadata={"service_slug": "b"})

    out = to_chunks([a1, a2, b1])

    by_resource: dict[str, list[int]] = {}
    for pc in out:
        by_resource.setdefault(pc.resource_id, []).append(pc.chunk_index)
    assert sorted(by_resource["a"]) == [0, 1]
    assert by_resource["b"] == [0]
