"""S17-WEDGE-WIRE-02 — dispatcher wires provider payloads into chunks.

Drives ``_dispatch_stub_integration_providers`` end-to-end with mocked
``dispatch_sources`` (so we don't need network or live providers) and
mocked ``ingest_provider_chunks`` (so we can assert call shape per
provider). Also pins the rollback hatch: with
``GECKO_WEDGE_WIRE_ENABLED=false``, the ingest hook is NOT called.
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


def _patched_workflows(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Reload workflows with the env flag set, then patch its collaborators.

    Reload is needed because ``_WEDGE_WIRE_ENABLED`` is read once at
    module import; flipping the env after import is silent otherwise.
    """
    import gecko_core.workflows as workflows

    importlib.reload(workflows)

    async def _fake_classify(_idea: str) -> set[str]:
        return {"crypto", "agentic-economy"}

    async def _fake_dispatch_sources(**_kwargs: Any) -> dict[str, SourceResult]:
        return {
            "bazaar": SourceResult(
                source_name="bazaar",
                payload={
                    "chunks": [
                        {
                            "text": "raw",
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
                            "text": "Title\n\nAbstract.",
                            "provider_kind": "free:arxiv",
                            "cost_usd": "0",
                            "metadata": {
                                "title": "Verifiable Compute Markets",
                                "abstract": "Abstract.",
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

    # ``dispatch_sources`` is imported *inside* the function — patch on
    # the source module so the local import resolves to our fake. Use
    # ``importlib.import_module`` rather than ``import gecko_core.sources``
    # because ``gecko_core/__init__.py`` rebinds the ``sources`` name to a
    # workflow function, shadowing the package on the parent attribute.
    sources_mod = importlib.import_module("gecko_core.sources")
    monkeypatch.setattr(sources_mod, "dispatch_sources", _fake_dispatch_sources)

    classify_mod = importlib.import_module("gecko_core.classify")
    monkeypatch.setattr(classify_mod, "classify_idea", _fake_classify)

    # Stub the provider factories so we don't reach for env / network.
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
async def test_dispatch_wires_each_provider_through_ingest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GECKO_WEDGE_WIRE_ENABLED", "true")
    workflows = _patched_workflows(monkeypatch)

    calls: list[dict[str, Any]] = []

    async def _fake_ingest(**kwargs: Any) -> int:
        calls.append(dict(kwargs))
        return len(kwargs["chunks"])

    import gecko_core.ingestion.pipeline as pipeline_mod

    monkeypatch.setattr(pipeline_mod, "ingest_provider_chunks", _fake_ingest)

    sid = uuid4()
    summary = await workflows._dispatch_stub_integration_providers(
        session_id=sid,
        idea="crypto agentic markets",
        store=_FakeStore(),  # type: ignore[arg-type]
        payment_mode="stub",
    )

    assert summary is not None
    kinds = sorted(c["provider_kind"] for c in calls)
    assert kinds == ["arxiv", "bazaar", "twitsh"]

    by_kind = {c["provider_kind"]: c for c in calls}
    assert by_kind["bazaar"]["synthetic_uri"].startswith("bazaar://")
    assert by_kind["arxiv"]["synthetic_uri"].startswith("https://arxiv.org/abs/")
    assert by_kind["twitsh"]["synthetic_uri"] == f"twitsh://session/{sid}"


@pytest.mark.asyncio
async def test_dispatch_skips_ingest_when_flag_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GECKO_WEDGE_WIRE_ENABLED", "false")
    workflows = _patched_workflows(monkeypatch)

    calls: list[dict[str, Any]] = []

    async def _fake_ingest(**kwargs: Any) -> int:
        calls.append(dict(kwargs))
        return 0

    import gecko_core.ingestion.pipeline as pipeline_mod

    monkeypatch.setattr(pipeline_mod, "ingest_provider_chunks", _fake_ingest)

    sid = uuid4()
    summary = await workflows._dispatch_stub_integration_providers(
        session_id=sid,
        idea="crypto agentic markets",
        store=_FakeStore(),  # type: ignore[arg-type]
        payment_mode="stub",
    )

    # Cost-ledger / log path still runs; chunk ingest does not.
    assert summary is not None
    assert calls == []
