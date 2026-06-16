"""Phase 2.1 — news reaches the panel slate (Pattern E reachability).

The WHOLE POINT: prove that when a news provider is injected into the
PRODUCTION verdict path (`run_trade_panel_with_retrieval`), a contemporary
news chunk lands on the slate the `sentiment_analyst` voice reads — so it
stops defaulting to a constant `neutral` for lack of narrative.

Per Pattern E ("'wired' != 'reaches the model'"), per-layer adapter unit
tests are necessary but NOT sufficient — this test calls the actual prod
wrapper and asserts the news chunk is in the `retrieved_chunks` handed to
`run_trade_panel`. It also asserts the flag-OFF default makes NO news call,
and that a provider error fails-OPEN (panel still runs).

No LLM, no Mongo, no network: retrieval is monkeypatched empty, the panel
is monkeypatched to a chunk-capturing stub, and a fake/stub provider is
injected. The factory is exercised separately in gecko-core unit tests.
"""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar

import pytest
from gecko_core.orchestration.trade_panel import run_trade_panel_with_retrieval
from gecko_core.orchestration.trade_panel.news_provider import build_news_chunk


@pytest.fixture(autouse=True)
def _no_retrieval(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip Mongo — corpus retrieval is orthogonal to the news claim."""

    async def _empty(*_a: Any, **_k: Any) -> list[dict[str, Any]]:
        return []

    monkeypatch.setattr(
        "gecko_core.orchestration.trade_panel.retrieve_trade_corpus_chunks",
        _empty,
    )


@pytest.fixture()
def _capture_panel(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Replace run_trade_panel with a stub that records the chunk slate."""
    captured: dict[str, Any] = {}

    class _Verdict:
        turns: ClassVar[list[Any]] = []
        confidence = 0.5
        safety = None

        def model_copy(self, *, update: dict[str, Any]) -> _Verdict:
            return self

    async def _stub(*_a: Any, retrieved_chunks: list[dict[str, Any]], **_k: Any) -> Any:
        captured["chunks"] = retrieved_chunks
        return _Verdict()

    monkeypatch.setattr("gecko_core.orchestration.trade_panel.run_trade_panel", _stub)
    # The post-panel citation / grounding / safety attach steps iterate verdict
    # internals — neutralize them so this test stays scoped to the news-merge
    # claim (their own reachability is covered by their own tests).
    monkeypatch.setattr(
        "gecko_core.orchestration.trade_panel.partition_emitted_citations",
        lambda *_a, **_k: ([], []),
    )
    monkeypatch.setattr(
        "gecko_core.orchestration.trade_panel.apply_grounding_gate",
        lambda v, *_a, **_k: (v, None),
    )
    monkeypatch.setattr(
        "gecko_core.orchestration.trade_panel._attach_safety",
        lambda v, *_a, **_k: v,
    )
    return captured


class _FakeNewsProvider:
    """Light fake — returns one panel-shaped news chunk."""

    def __init__(self) -> None:
        self.calls = 0

    async def fetch_news_chunks(
        self, protocol: str, *, max_results: int = 5, as_of: Any = None
    ) -> list[dict[str, Any]]:
        self.calls += 1
        return [
            build_news_chunk(
                headline="Kamino governance proposal passes",
                body="The DAO approved a fee switch this morning.",
                url="https://news.example/kamino-1",
                protocol=protocol,
            )
        ]


class _BrokenNewsProvider:
    async def fetch_news_chunks(self, *_a: Any, **_k: Any) -> list[dict[str, Any]]:
        raise RuntimeError("news upstream is down")


def test_injected_news_chunk_reaches_panel_slate(_capture_panel: dict[str, Any]) -> None:
    """With a provider injected, a news chunk MUST be on the panel slate."""
    provider = _FakeNewsProvider()

    asyncio.run(
        run_trade_panel_with_retrieval(
            idea="should I buy kamino right now?",
            protocol="kamino",
            agent_factory=lambda _c: {},
            news_provider=provider,
        )
    )

    assert provider.calls == 1, "provider was not invoked"
    slate = _capture_panel["chunks"]
    news_chunks = [c for c in slate if c.get("provider_kind") == "okx_news_live"]
    assert news_chunks, "no news chunk reached the panel slate"
    assert "Kamino governance proposal" in news_chunks[0]["text"]


def test_no_provider_makes_no_news_call(_capture_panel: dict[str, Any]) -> None:
    """Flag-off default (news_provider=None) → no news, no behavior delta."""
    asyncio.run(
        run_trade_panel_with_retrieval(
            idea="should I buy kamino right now?",
            protocol="kamino",
            agent_factory=lambda _c: {},
            news_provider=None,
        )
    )
    slate = _capture_panel["chunks"]
    assert [c for c in slate if c.get("provider_kind") == "okx_news_live"] == []


def test_provider_error_fails_open(_capture_panel: dict[str, Any]) -> None:
    """A news-provider error MUST NOT break the panel (fail-OPEN)."""
    # Should not raise; the panel still runs with no news chunk.
    asyncio.run(
        run_trade_panel_with_retrieval(
            idea="should I buy kamino right now?",
            protocol="kamino",
            agent_factory=lambda _c: {},
            news_provider=_BrokenNewsProvider(),
        )
    )
    slate = _capture_panel["chunks"]
    assert [c for c in slate if c.get("provider_kind") == "okx_news_live"] == []
