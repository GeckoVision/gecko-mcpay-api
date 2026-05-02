"""S19-STUB-FIXTURES-01 — dogfood matrix for idea-aware stub fixtures.

Ratchets the demo-realism bar above the S18 reach-CI floor: every
research run now produces stub citations that reference the idea on
screen, not the canonical Lisbon hotel boilerplate.

For each of 5 dogfood ideas we drive both stubs (twit.sh tweet
synthesizer and Bazaar stub-discovery + generic stub adapter) and
assert the resulting chunks contain at least one keyword from the
idea string. The 5th idea is a deliberate stretch case with no
bucket-keyword hits — it must still produce a non-empty result via
the "generic" fallback bucket so the reach-CI floor stays intact.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest
from gecko_core.payments.bazaar_discovery import StubDiscoveryClient
from gecko_core.payments.x402_consumer import StubX402Consumer
from gecko_core.sources.bazaar.provider import BazaarSourceProvider
from gecko_core.sources.twit_sh import _stub_tweets

# Five dogfood ideas: crypto, SaaS, hospitality (the actual idea from
# the demo screenshots), generic productivity, and a stretch case
# with zero bucket-keyword hits.
_DOGFOOD: list[tuple[str, set[str], list[str]]] = [
    (
        "an x402 onramp for solana-native agentic payments",
        {"crypto"},
        ["x402", "solana", "onramp", "agentic", "payments"],
    ),
    (
        "saas onboarding analytics for B2B teams",
        {"saas"},
        ["saas", "onboarding", "analytics"],
    ),
    (
        "a new app for hotels - generate local guides",
        {"hospitality"},
        ["hotels", "local", "guides"],
    ),
    (
        "a daily focus tracker for knowledge workers",
        {"productivity"},
        ["focus", "knowledge", "tracker"],
    ),
    (
        # Stretch case: no keywords match any bucket. Must still
        # produce content via the "generic" fallback.
        "qzx blorp glorpotron",
        set(),
        [],
    ),
]


def _contains_any(text: str, keywords: list[str]) -> bool:
    """Case-insensitive substring match for any keyword."""
    if not keywords:
        return True
    lower = text.lower()
    return any(kw.lower() in lower for kw in keywords)


@pytest.mark.parametrize("idea,categories,expected_kws", _DOGFOOD)
def test_twitsh_stub_is_idea_aware(
    idea: str, categories: set[str], expected_kws: list[str]
) -> None:
    tweets = _stub_tweets(idea, categories)
    assert tweets, f"twit.sh stub returned empty for idea={idea!r}"
    blob = " ".join(t["text"] for t in tweets)
    if expected_kws:
        assert _contains_any(blob, expected_kws), (
            f"twit.sh stub for {idea!r} produced no keyword hit; "
            f"got tweets={[t['text'] for t in tweets]}"
        )
    # Live shape: each tweet still carries the canonical keys.
    for t in tweets:
        assert {"text", "author_handle", "url", "engagement", "created_at"} <= t.keys()


@pytest.mark.parametrize("idea,categories,expected_kws", _DOGFOOD)
def test_bazaar_stub_is_idea_aware(
    idea: str, categories: set[str], expected_kws: list[str]
) -> None:
    """Drive the BazaarSourceProvider against the stub discovery client.

    The provider runs end-to-end: stub discovery synthesizes
    idea-aware resources, GenericBazaarAdapter takes the stub-fetch
    path (because the consumer is StubX402Consumer and no httpx
    client is injected), and emits a chunk whose text references the
    synthesized metadata.
    """

    async def _run() -> list[dict[str, object]]:
        discovery = StubDiscoveryClient()
        consumer = StubX402Consumer()
        provider = BazaarSourceProvider(
            discovery_client=discovery,
            x402_consumer=consumer,
            session_cap_usd=Decimal("0.50"),
        )
        result = await provider.fetch(idea=idea, categories=categories)
        assert result.fired, f"bazaar provider not fired for idea={idea!r}: {result.error}"
        return list(result.payload.get("chunks") or [])

    chunks = asyncio.run(_run())
    assert chunks, f"bazaar stub returned no chunks for idea={idea!r}"
    blob = " ".join(str(c.get("text", "")) for c in chunks)
    for c in chunks:
        meta = c.get("metadata") or {}
        if isinstance(meta, dict):
            blob += " " + str(meta.get("resource_url", ""))
    if expected_kws:
        assert _contains_any(blob, expected_kws), (
            f"bazaar stub for {idea!r} produced no keyword hit; got chunks={chunks}"
        )
    # Each chunk must carry a non-empty provider_kind starting with "bazaar:".
    for c in chunks:
        pk = str(c.get("provider_kind") or "")
        assert pk.startswith("bazaar:"), f"unexpected provider_kind {pk!r}"


def test_stretch_case_falls_back_to_generic_bucket() -> None:
    """No-keyword-match path: still non-empty (generic bucket fires)."""
    idea, categories, _ = _DOGFOOD[-1]
    tweets = _stub_tweets(idea, categories)
    assert len(tweets) >= 1

    async def _bz() -> list[dict[str, object]]:
        discovery = StubDiscoveryClient()
        consumer = StubX402Consumer()
        provider = BazaarSourceProvider(
            discovery_client=discovery,
            x402_consumer=consumer,
        )
        result = await provider.fetch(idea=idea, categories=categories)
        return list(result.payload.get("chunks") or [])

    chunks = asyncio.run(_bz())
    assert chunks, "generic-bucket fallback produced no bazaar chunks"
