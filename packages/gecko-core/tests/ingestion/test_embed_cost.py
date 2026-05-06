"""S20-RAG-04 — embed-cost rate-table assertions.

Locks the published Voyage list prices into a unit test so a typo in
`_EMBED_RATES_USD_PER_1M` (or an accidental drop of `voyage-3` while
swapping defaults to `voyage-context-3`) is caught at PR time, not when
the economics ledger silently zeroes a session out.
"""

from __future__ import annotations

from gecko_core.ingestion.embedder import (
    _EMBED_RATES_USD_PER_1M,
    estimate_embed_cost_usd,
)


def test_voyage_context_3_present_and_priced() -> None:
    assert "voyage-context-3" in _EMBED_RATES_USD_PER_1M
    assert _EMBED_RATES_USD_PER_1M["voyage-context-3"] == 0.06


def test_voyage_3_legacy_still_priced() -> None:
    # voyage-3 must remain pricable so legacy chunks ingested under it
    # still attribute cost correctly. S20-RAG-04 is a default swap, not
    # a removal.
    assert "voyage-3" in _EMBED_RATES_USD_PER_1M
    assert _EMBED_RATES_USD_PER_1M["voyage-3"] == 0.06


def test_estimate_embed_cost_voyage_context_3_one_million_tokens() -> None:
    assert estimate_embed_cost_usd("voyage-context-3", 1_000_000) == 0.06


def test_estimate_embed_cost_unknown_model_returns_zero() -> None:
    assert estimate_embed_cost_usd("not-a-real-model", 1_000_000) == 0.0
