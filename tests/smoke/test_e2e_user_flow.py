"""End-to-end smoke test: walks the entire 7-step user flow.

This is the test that must pass on the demo machine before Monday.

Run with:
    uv run pytest tests/smoke/test_e2e_user_flow.py -v -s

The -s flag is recommended so you see real-time progress (rich output, agent chat).
"""

from __future__ import annotations

import os
import time
from uuid import UUID

import pytest


@pytest.mark.skip(reason="enable after phases 1-7 are implemented")
class TestEndToEndUserFlow:
    """The 7-step flow from the implementation plan, executed in order.

    Each test depends on the previous one — they're sequenced via class-scoped state.
    """

    session_id: str = ""

    @pytest.mark.asyncio
    async def test_step_1_through_6_basic_tier(self, demo_idea: str) -> None:
        """Steps 1-6: describe → discover → approve → pay → ingest → generate (basic)."""
        import gecko_core

        # X402_MODE must be stub for this test
        assert os.environ.get("X402_MODE", "stub") == "stub"

        start = time.monotonic()
        result = await gecko_core.research(idea=demo_idea, tier="basic")
        elapsed = time.monotonic() - start

        # session_id is a valid UUID
        assert UUID(result.session_id)
        TestEndToEndUserFlow.session_id = result.session_id

        # all three documents are present and non-empty
        assert result.business_plan.problem
        assert result.business_plan.solution
        assert result.validation_report.market_size_signal
        assert result.prd.v1_scope

        # citations are real
        all_source_urls = {str(s.url) for s in result.sources}
        for doc in (result.business_plan, result.validation_report, result.prd):
            assert len(doc.citations) >= 1
            for c in doc.citations:
                assert str(c.source_url) in all_source_urls

        # PRD: basic completes in < 60s for generation, < 3 min total including ingestion
        assert elapsed < 240, f"end-to-end took {elapsed:.1f}s, target < 240s"

    @pytest.mark.asyncio
    async def test_step_7_follow_up_question(self) -> None:
        """Step 7: KB stays alive — ask a follow-up, get a grounded answer."""
        import gecko_core

        assert TestEndToEndUserFlow.session_id, "previous step must have run"

        result = await gecko_core.ask(
            session_id=TestEndToEndUserFlow.session_id,
            question="what's the strongest validation signal for this idea?",
        )

        assert result.answer
        assert len(result.citations) >= 1, "answer must be grounded — no empty citations"

    @pytest.mark.asyncio
    async def test_step_7_sources_visible(self) -> None:
        """Step 7: bb sources lists what was indexed."""
        import gecko_core

        sources = await gecko_core.sources(session_id=TestEndToEndUserFlow.session_id)
        assert 5 <= len(sources) <= 10
        for s in sources:
            assert s.chunk_count > 0
            assert s.type in ("youtube", "web")

    @pytest.mark.asyncio
    async def test_re_ask_uses_persisted_kb(self) -> None:
        """A second ask() call uses the same KB without re-ingesting."""
        import gecko_core

        start = time.monotonic()
        result = await gecko_core.ask(
            session_id=TestEndToEndUserFlow.session_id,
            question="what are the biggest risk flags?",
        )
        elapsed = time.monotonic() - start

        assert result.answer
        # ask() should be fast — no ingestion, just RAG + LLM
        assert elapsed < 15, f"ask() took {elapsed:.1f}s, target < 15s"


@pytest.mark.skip(reason="enable after phase 6 is implemented; expensive — runs Pro tier")
class TestEndToEndProTier:
    """Pro tier end-to-end. Costs real money in live mode; safe in stub."""

    @pytest.mark.asyncio
    async def test_pro_tier_full_flow(self, demo_idea: str) -> None:
        """Pro tier completes in < 5 minutes and produces grounded documents."""
        import gecko_core

        start = time.monotonic()
        result = await gecko_core.research(idea=demo_idea, tier="pro")
        elapsed = time.monotonic() - start

        assert UUID(result.session_id)
        assert elapsed < 300, f"pro tier took {elapsed:.1f}s, target < 300s"

        # Pro should produce richer documents — assert minimum content depth
        assert len(result.business_plan.risks) >= 3
        assert len(result.validation_report.risk_flags) >= 2
        assert len(result.prd.v1_scope) >= 5
