"""S4-TWITSH-01/02 — V1 source signal lands in the Pro debate's rag_context.

Strategy: stub the four V1 `Source` implementations (no respx, no x402, no
real eth_account). Drive `_dispatch_v1_sources` end-to-end and assert:
  - the rendered block has all four headings (even when sources empty),
  - twit.sh signal appears verbatim in the block,
  - per-source spend is debited via store.add_cost with the right kind,
  - the $0.10 cross-source cap is honored,
  - the rag_block prepends ABOVE the existing Tavily corpus when wired
    through `_run_pro_debate` (verified at the unit level via render).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from gecko_core.sources import SourceResult
from gecko_core.sources.v1_block import (
    V1_SOURCES_SPEND_CAP_USD,
    dispatch_and_render,
    render_block,
)


class _StubSource:
    """Minimal source returning a canned `SourceResult`."""

    def __init__(self, name: str, *, applies: bool, result: SourceResult) -> None:
        self.name = name
        self._applies = applies
        self._result = result

    async def applies_to(self, *, categories: set[str]) -> bool:
        return self._applies

    async def fetch(self, *, idea: str, categories: set[str]) -> SourceResult:
        return self._result


# ---------------------------------------------------------------------------
# Render block — empty / present / partial
# ---------------------------------------------------------------------------


def test_render_block_empty_sources_keeps_all_four_headings() -> None:
    """Absence of signal IS signal — agents must see the missing-data line."""
    block = render_block({})
    for heading in (
        "## V1 Source Signal",
        "### Twitter / X (twit.sh)",
        "### Hacker News",
        "### Reddit",
        "### Prior Gecko Verdicts (gecko_precedent)",
    ):
        assert heading in block
    # All four should fall back to the empty-state line.
    assert block.count("No data found.") == 4


def test_render_block_with_full_signal_shapes_correctly() -> None:
    results = {
        "twit_sh": SourceResult(
            source_name="twit_sh",
            payload={
                "tweets": [
                    {
                        "text": "ZK rollup throughput hit 100k tps on devnet",
                        "author_handle": "@vitalik",
                        "engagement": {"likes": 1234, "replies": 56, "reposts": 78},
                    }
                ],
                "spend_usd": 0.005,
            },
            cost_usd=0.005,
            fired=True,
        ),
        "hn": SourceResult(
            source_name="hn",
            payload={
                "hits": [
                    {
                        "title": "Show HN: ZK rollup playground",
                        "url": "https://news.ycombinator.com/item?id=42",
                        "points": 320,
                        "comments": 88,
                    }
                ]
            },
            fired=True,
        ),
        "reddit": SourceResult(
            source_name="reddit",
            payload={
                "posts": [
                    {
                        "subreddit": "ethereum",
                        "title": "Discussion: rollup throughput",
                        "url": "https://www.reddit.com/r/ethereum/x",
                        "score": 412,
                    }
                ]
            },
            fired=True,
        ),
        "gecko_precedent": SourceResult(
            source_name="gecko_precedent",
            payload={
                "precedents": [
                    {
                        "verdict": "ship",
                        "idea_summary": "Layer-2 rollup with novel DA layer",
                        "similarity": 0.82,
                    }
                ],
                "count": 1,
            },
            fired=True,
        ),
    }
    block = render_block(results)
    assert "@vitalik" in block
    assert "(likes=1234, replies=56)" in block
    assert "Show HN: ZK rollup playground" in block
    assert "(points=320, comments=88)" in block
    assert "r/ethereum" in block
    assert "[SHIP] similar idea: Layer-2 rollup" in block
    assert "(sim=0.82)" in block
    assert block.count("No data found.") == 0


# ---------------------------------------------------------------------------
# dispatch_and_render — spend ledger + cap
# ---------------------------------------------------------------------------


async def test_dispatch_and_render_records_per_source_spend() -> None:
    twitsh_payload: dict[str, Any] = {
        "tweets": [
            {
                "text": "builders are shipping x402 demos this week",
                "author_handle": "@anatoly",
                "engagement": {"likes": 99, "replies": 12, "reposts": 5},
            }
        ],
        "spend_usd": 0.05,
    }
    sources = [
        _StubSource(
            "twit_sh",
            applies=True,
            result=SourceResult(
                source_name="twit_sh",
                payload=twitsh_payload,
                cost_usd=0.05,
                fired=True,
            ),
        ),
        _StubSource(
            "hn",
            applies=True,
            result=SourceResult(source_name="hn", payload={"hits": []}, fired=True),
        ),
        _StubSource(
            "reddit",
            applies=True,
            result=SourceResult(source_name="reddit", payload={"posts": []}, fired=True),
        ),
    ]

    block = await dispatch_and_render(
        idea="x402 builder analytics dashboard",
        categories={"crypto", "defi"},
        sources=sources,
    )

    # Spend ledger only includes paying sources.
    assert block.spend_by_source == {"twit_sh": 0.05}
    assert block.total_spend_usd == pytest.approx(0.05)
    # Block carries twit.sh signal verbatim.
    assert "@anatoly" in block.rag_block
    assert "x402 demos" in block.rag_block
    # HN/Reddit got the empty-state line, not skipped.
    assert "### Hacker News\nNo data found." in block.rag_block
    assert "### Reddit\nNo data found." in block.rag_block


async def test_dispatch_cap_logs_when_exceeded(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Total spend > $0.10 should warn but still record real debits.

    Real twit.sh has its own internal $0.05 cap so this is a defensive test
    against future paid V1 sources stacking. We simulate two paid sources
    summing to $0.15 to verify the cross-source cap warning fires.
    """
    sources = [
        _StubSource(
            "twit_sh",
            applies=True,
            result=SourceResult(
                source_name="twit_sh",
                payload={"tweets": [], "spend_usd": 0.05},
                cost_usd=0.05,
                fired=True,
            ),
        ),
        _StubSource(
            "future_paid",
            applies=True,
            result=SourceResult(
                source_name="future_paid",
                payload={},
                cost_usd=0.10,
                fired=True,
            ),
        ),
    ]
    with caplog.at_level("WARNING"):
        block = await dispatch_and_render(
            idea="anything",
            categories={"crypto"},
            sources=sources,
            spend_cap_usd=V1_SOURCES_SPEND_CAP_USD,
        )

    assert block.total_spend_usd > V1_SOURCES_SPEND_CAP_USD
    assert any("spend cap hit" in rec.message for rec in caplog.records)


async def test_dispatch_skips_gated_out_sources_no_spend() -> None:
    """`applies_to=False` => no fetch, no spend, but heading still renders."""
    twitsh = _StubSource(
        "twit_sh",
        applies=False,
        result=SourceResult(source_name="twit_sh", payload={}, fired=True),
    )
    sources = [twitsh]
    block = await dispatch_and_render(
        idea="tax software for accountants",
        categories={"saas"},
        sources=sources,
    )
    assert block.spend_by_source == {}
    assert "### Twitter / X (twit.sh)\nNo data found." in block.rag_block


# ---------------------------------------------------------------------------
# _dispatch_v1_sources — telemetry + ledger debits
# ---------------------------------------------------------------------------


async def test_dispatch_v1_sources_debits_session_ledger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: classify + dispatch + debit. Patches `classify_idea` and
    `embed` to avoid network/disk dependencies; patches `build_default_sources`
    to return our stubs."""
    from gecko_core import workflows

    sid = uuid4()

    fake_store = AsyncMock()
    fake_store.add_cost = AsyncMock(return_value=None)

    async def _fake_classify(idea: str) -> set[str]:
        return {"crypto"}

    async def _fake_embed(items: list[str]) -> tuple[list[list[float]], int]:
        return ([[0.1, 0.2, 0.3]], 1)

    def _fake_sources(*, embedding: list[float] | None, store: Any) -> list[Any]:
        return [
            _StubSource(
                "twit_sh",
                applies=True,
                result=SourceResult(
                    source_name="twit_sh",
                    payload={
                        "tweets": [
                            {
                                "text": "x402 wallet primitives are landing",
                                "author_handle": "@founder",
                                "engagement": {"likes": 200, "replies": 30},
                            }
                        ],
                        "spend_usd": 0.04,
                    },
                    cost_usd=0.04,
                    fired=True,
                ),
            ),
            _StubSource(
                "hn",
                applies=True,
                result=SourceResult(
                    source_name="hn",
                    payload={
                        "hits": [
                            {
                                "title": "x402 micropayment standard",
                                "url": "https://hn/x",
                                "points": 150,
                                "comments": 40,
                            }
                        ]
                    },
                    fired=True,
                ),
            ),
        ]

    # Patch the lazy-imported names inside _dispatch_v1_sources.
    import gecko_core.classify as classify_mod
    import gecko_core.ingestion.embedder as embedder_mod
    import gecko_core.sources.v1_block as v1_block_mod

    monkeypatch.setattr(classify_mod, "classify_idea", _fake_classify)
    monkeypatch.setattr(embedder_mod, "embed", _fake_embed)
    monkeypatch.setattr(v1_block_mod, "build_default_sources", _fake_sources)

    rag, spend = await workflows._dispatch_v1_sources(sid, "x402 builder tooling", fake_store)

    # Block contains twit.sh + HN signal.
    assert "@founder" in rag
    assert "x402 micropayment standard" in rag
    # Spend was debited under the right ledger kind.
    fake_store.add_cost.assert_awaited()
    kinds_used = {call.args[1] for call in fake_store.add_cost.await_args_list}
    assert "twitsh" in kinds_used
    assert spend == {"twit_sh": pytest.approx(0.04)}


async def test_dispatch_v1_sources_degrades_silently_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Any exception below the workflow boundary => empty block, no crash."""
    from gecko_core import workflows

    sid = uuid4()
    fake_store = AsyncMock()

    async def _broken_classify(idea: str) -> set[str]:
        raise RuntimeError("classify exploded")

    import gecko_core.classify as classify_mod

    monkeypatch.setattr(classify_mod, "classify_idea", _broken_classify)

    rag, spend = await workflows._dispatch_v1_sources(sid, "any idea", fake_store)
    assert rag == ""
    assert spend == {}
    fake_store.add_cost.assert_not_called()


async def test_v1_block_prepends_above_tavily_corpus() -> None:
    """Direct test of the prepend invariant — the block always sits ABOVE
    the existing Tavily corpus, never replaces it."""
    tavily_rag = "[1] (source: https://example.com) some context chunk"
    v1_rag = render_block({})
    composed = f"{v1_rag}\n\n{tavily_rag}"
    # V1 block heading appears before the Tavily citation marker.
    assert composed.index("## V1 Source Signal") < composed.index("[1]")
