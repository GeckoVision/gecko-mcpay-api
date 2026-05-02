"""S18-REACH-CI-01 — wedge reachability gate.

Encodes the ``feedback_wedge_reachability_check`` lesson: every "we shipped X"
claim demands an end-to-end reachability audit. This test fails fast in CI
when the wedge wiring breaks — i.e. when a stub research run produces ZERO
non-web ``provider_kind`` chunks OR ZERO non-https citation URIs.

The test is deliberately *positive* (assert wedge is reachable) and the
failure message points operators at the most likely break:

- Provider dispatcher silently skipping bazaar/arxiv/twitsh
- Ingest pipeline dropping non-web chunks before they hit the chunks table
- Synthetic URI scheme regression (e.g. arxiv emitting an empty URL)

Why this duplicates ``test_dispatch_wires_to_chunks.py`` partially: that file
proves the dispatcher wires *the call* into the ingest function. This file
proves the *full claim* — non-web chunks AND non-https citations — which is
what the wedge sentence in PRD/skill.md/splash actually promises. A
single-line break in either layer would pass the dispatch test and fail this
one. That's the design.
"""

from __future__ import annotations

import importlib
from typing import Any
from uuid import UUID, uuid4

import pytest
from gecko_core.sources import SourceResult


class _FakeStore:
    async def add_cost(self, session_id: UUID, kind: str, amount_usd: float) -> None:
        return None


def _stub_workflow_collaborators(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Reload workflows with the wedge-wire flag on, patch dispatchers."""
    monkeypatch.setenv("GECKO_WEDGE_WIRE_ENABLED", "true")
    import gecko_core.workflows as workflows

    importlib.reload(workflows)

    async def _classify(_idea: str) -> set[str]:
        return {"crypto", "agentic-economy"}

    async def _dispatch(**_kwargs: Any) -> dict[str, SourceResult]:
        return {
            "bazaar": SourceResult(
                source_name="bazaar",
                payload={
                    "chunks": [
                        {
                            "text": "Coinbase Onramp lets users buy crypto with a card.",
                            "provider_kind": "bazaar:json",
                            "cost_usd": "0.05",
                            "metadata": {
                                "service_slug": "crypto-onramp",
                                "title": "Coinbase Onramp",
                                "description": "Buy crypto with a card.",
                                "merchant": "Coinbase",
                                "price_usd_cents": 250,
                            },
                            "creator_handle": None,
                        }
                    ]
                },
                cost_usd=0.05,
                fired=True,
            ),
            "twit_sh": SourceResult(
                source_name="twit_sh",
                payload={
                    "tweets": [
                        {
                            "text": "agentic markets are eating search.",
                            "author_handle": "@aeyakovenko",
                            "url": "https://x.com/aeyakovenko/1",
                            "engagement": {"likes": 10, "replies": 1, "reposts": 2},
                            "created_at": "2026-04-29T00:00:00Z",
                        }
                    ],
                    "from_cache": False,
                    "spend_usd": 0.001,
                },
                cost_usd=0.001,
                fired=True,
            ),
            "arxiv": SourceResult(
                source_name="arxiv",
                payload={
                    "chunks": [
                        {
                            "text": "Verifiable Compute Markets — abstract.",
                            "provider_kind": "free:arxiv",
                            "cost_usd": "0",
                            "metadata": {
                                "title": "Verifiable Compute Markets",
                                "abstract": "Abstract body.",
                                "authors": ["A. Author"],
                                "arxiv_id": "2401.12345",
                                "abs_url": "https://arxiv.org/abs/2401.12345",
                                "pdf_url": "",
                                "published_date": "2026-04-30",
                                "primary_category": "cs.CR",
                            },
                        }
                    ],
                    "abstract_count": 1,
                },
                cost_usd=0.0,
                fired=True,
            ),
        }

    sources_mod = importlib.import_module("gecko_core.sources")
    classify_mod = importlib.import_module("gecko_core.classify")
    monkeypatch.setattr(sources_mod, "dispatch_sources", _dispatch)
    monkeypatch.setattr(classify_mod, "classify_idea", _classify)

    class _Dummy:
        name = "dummy"

        async def applies_to(self, **_k: Any) -> bool:
            return True

        async def fetch(self, **_k: Any) -> SourceResult:
            return SourceResult(source_name=self.name)

        async def aclose(self) -> None:
            return None

    arxiv_mod = importlib.import_module("gecko_core.sources.arxiv")
    bazaar_mod = importlib.import_module("gecko_core.sources.bazaar")
    twitsh_mod = importlib.import_module("gecko_core.sources.twit_sh")
    monkeypatch.setattr(bazaar_mod, "make_bazaar_provider", lambda **_k: _Dummy())
    monkeypatch.setattr(arxiv_mod, "make_arxiv_source", lambda **_k: _Dummy())
    monkeypatch.setattr(twitsh_mod, "TwitshSource", lambda **_k: _Dummy())

    return workflows


@pytest.mark.asyncio
async def test_reach_ci_non_web_chunks_and_non_https_citations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The CI-gating reach test.

    Asserts: a stub research dispatch produces (a) at least one chunk with
    a non-web ``provider_kind``, and (b) at least one citation URI that is
    NOT an https URL — concretely, a ``bazaar://`` or ``twitsh://`` synthetic
    URI from the WIRE-02 path.
    """
    workflows = _stub_workflow_collaborators(monkeypatch)

    captured_chunks: list[dict[str, Any]] = []

    async def _fake_ingest(**kwargs: Any) -> int:
        captured_chunks.append(dict(kwargs))
        return len(kwargs.get("chunks") or [])

    import gecko_core.ingestion.pipeline as pipeline_mod

    monkeypatch.setattr(pipeline_mod, "ingest_provider_chunks", _fake_ingest)

    sid = uuid4()
    summary = await workflows._dispatch_stub_integration_providers(
        session_id=sid,
        idea="agentic markets for verifiable compute",
        store=_FakeStore(),
        payment_mode="stub",
    )

    assert summary is not None, "REACH-CI: dispatcher returned None — wedge_wire flag may be off"
    assert captured_chunks, (
        "REACH-CI: ingest_provider_chunks was never called — wedge wire is "
        "broken at the dispatch → ingest seam"
    )

    # (a) Non-web provider_kind floor.
    non_web_kinds = sorted(
        {c["provider_kind"] for c in captured_chunks if c["provider_kind"] != "web"}
    )
    assert non_web_kinds, (
        "REACH-CI: zero non-web provider_kind chunks reached ingest — the "
        "wedge claim 'grounded, adversarial verdicts on pre-ideas' demands "
        "non-web evidence in the corpus. Likely break: a provider's "
        "embed_adapter regressed or wedge_wire flag is off."
    )
    assert len(non_web_kinds) >= 2, (
        f"REACH-CI: only {non_web_kinds} non-web kinds present; expected ≥2 "
        f"(bazaar, twitsh, arxiv). Did a provider silently fail dispatch?"
    )

    # (b) Non-https citation URI floor — the synthetic URI is what the
    # citation renderer surfaces. bazaar:// and twitsh:// must be present.
    synthetic_uris = [c.get("synthetic_uri", "") for c in captured_chunks]
    non_https = [u for u in synthetic_uris if u and not u.startswith("https://")]
    assert non_https, (
        "REACH-CI: every synthetic_uri starts with https:// — the wedge "
        "claim of provider-attributed citations is invisible in the demo. "
        "Check bazaar/twitsh embed_adapter URI generation."
    )


@pytest.mark.asyncio
async def test_reach_ci_fails_loudly_when_wedge_wire_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Negative case: with the flag off, the test guarantee must NOT hold.

    Encodes the rollback hatch — if anyone flips
    ``GECKO_WEDGE_WIRE_ENABLED=false`` the demo claim breaks. This test
    documents that the gate is a real toggle, not a no-op.
    """
    monkeypatch.setenv("GECKO_WEDGE_WIRE_ENABLED", "false")
    import gecko_core.workflows as workflows

    importlib.reload(workflows)

    captured_chunks: list[dict[str, Any]] = []

    async def _fake_ingest(**kwargs: Any) -> int:
        captured_chunks.append(dict(kwargs))
        return 0

    import gecko_core.ingestion.pipeline as pipeline_mod

    monkeypatch.setattr(pipeline_mod, "ingest_provider_chunks", _fake_ingest)

    # Stub the dispatchers so the rest of the workflow doesn't crash on
    # missing env vars.
    _stub_workflow_collaborators(monkeypatch)
    monkeypatch.setenv("GECKO_WEDGE_WIRE_ENABLED", "false")
    importlib.reload(workflows)
    monkeypatch.setattr(pipeline_mod, "ingest_provider_chunks", _fake_ingest)

    sid = uuid4()
    await workflows._dispatch_stub_integration_providers(
        session_id=sid,
        idea="any idea",
        store=_FakeStore(),  # type: ignore[arg-type]
        payment_mode="stub",
    )
    assert captured_chunks == [], (
        "REACH-CI: with wedge_wire off, ingest_provider_chunks should NOT "
        "be called — but it was. Flag is broken or callers bypass it."
    )
