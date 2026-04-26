"""Phase-by-phase smoke tests mapped to the implementation plan.

Each class corresponds to a phase. Each test maps to a smoke test from the plan.
Tests are skipped until their phase is implemented — remove the skip marker as you go.

Run with:
    uv run pytest tests/smoke/test_phases.py -v
    uv run pytest tests/smoke/test_phases.py::TestPhase2Ingestion -v
"""

from __future__ import annotations

import asyncio
import time
from uuid import UUID

import pytest


# ---------------------------------------------------------------------------
# Phase 1 — Schema + sessions
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="implement after phase 1")
class TestPhase1Sessions:
    """Schema applied, SessionStore CRUD works, persistence across restarts."""

    def test_migrations_apply_clean(self) -> None:
        """Migrations run on a blank Supabase project without errors."""
        # supabase migration up && supabase db diff --schema public
        # assert no drift
        ...

    @pytest.mark.asyncio
    async def test_session_create_returns_uuid(self, demo_idea: str) -> None:
        """SessionStore.create() returns a valid UUID and persists the row."""
        from gecko_core.sessions.store import SessionStore

        store = SessionStore()
        sid = await store.create(idea=demo_idea, tier="basic")
        assert UUID(sid)  # parses

    @pytest.mark.asyncio
    async def test_session_persists_across_processes(self, demo_idea: str) -> None:
        """A session created in one connection is retrievable from another."""
        from gecko_core.sessions.store import SessionStore

        sid = await SessionStore().create(idea=demo_idea, tier="basic")
        # simulate process restart — fresh client
        retrieved = await SessionStore().get(sid)
        assert retrieved is not None
        assert retrieved.idea == demo_idea


# ---------------------------------------------------------------------------
# Phase 2 — Ingestion adapters + pipeline
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="implement after phase 2")
class TestPhase2Ingestion:
    """End-to-end source → chunks → embeddings → Supabase."""

    @pytest.mark.asyncio
    async def test_youtube_with_captions_produces_chunks(
        self, session_id: str, sample_youtube_with_captions: str
    ) -> None:
        """A YouTube URL with captions ingests and produces > 0 chunks."""
        from gecko_core.ingestion.pipeline import ingest

        result = await ingest(session_id=session_id, urls=[sample_youtube_with_captions])
        assert result.sources[0].chunk_count > 0
        assert result.sources[0].type == "youtube"

    @pytest.mark.asyncio
    async def test_youtube_without_captions_skips_gracefully(
        self, session_id: str, sample_youtube_without_captions: str
    ) -> None:
        """No captions → source skipped, no exception, other sources still process."""
        from gecko_core.ingestion.pipeline import ingest

        result = await ingest(
            session_id=session_id, urls=[sample_youtube_without_captions]
        )
        # source not in result.sources, but tracked in result.skipped
        assert len(result.skipped) == 1
        assert "captions" in result.skipped[0].reason.lower()

    @pytest.mark.asyncio
    async def test_web_article_produces_chunks(
        self, session_id: str, sample_web_article: str
    ) -> None:
        """A standard blog post extracts and chunks."""
        from gecko_core.ingestion.pipeline import ingest

        result = await ingest(session_id=session_id, urls=[sample_web_article])
        assert result.sources[0].chunk_count > 0
        assert result.sources[0].type == "web"

    @pytest.mark.asyncio
    async def test_chunk_size_respected(self, session_id: str, sample_web_article: str) -> None:
        """Every chunk is <= 512 tokens (PRD acceptance criterion)."""
        from gecko_core.ingestion.pipeline import ingest
        from gecko_core.sessions.store import SessionStore

        await ingest(session_id=session_id, urls=[sample_web_article])
        chunks = await SessionStore().list_chunks(session_id)
        for c in chunks:
            assert c.token_count <= 512

    @pytest.mark.asyncio
    async def test_idempotent_reingest(self, session_id: str, sample_web_article: str) -> None:
        """Same URL ingested twice → no duplicate chunks."""
        from gecko_core.ingestion.pipeline import ingest
        from gecko_core.sessions.store import SessionStore

        await ingest(session_id=session_id, urls=[sample_web_article])
        await ingest(session_id=session_id, urls=[sample_web_article])
        chunks = await SessionStore().list_chunks(session_id)
        # count should match a single ingestion, not double
        assert len({c.id for c in chunks}) == len(chunks)

    @pytest.mark.asyncio
    async def test_five_sources_under_three_minutes(
        self, session_id: str, sample_web_article: str
    ) -> None:
        """PRD: full ingestion of 5 sources < 3 minutes."""
        from gecko_core.ingestion.pipeline import ingest

        urls = [sample_web_article] * 5  # use 5 distinct URLs in real test
        start = time.monotonic()
        await ingest(session_id=session_id, urls=urls)
        elapsed = time.monotonic() - start
        assert elapsed < 180

    @pytest.mark.asyncio
    async def test_tavily_discovery_returns_relevant_urls(self, demo_idea: str) -> None:
        """Tavily for the demo idea returns 5–10 URLs."""
        from gecko_core.ingestion.discovery import discover

        urls = await discover(demo_idea)
        assert 5 <= len(urls) <= 10


# ---------------------------------------------------------------------------
# Phase 3 — Approval flow
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="implement after phase 3")
class TestPhase3Approval:
    """User confirms source list before payment + ingestion."""

    def test_yes_flag_skips_prompt(self) -> None:
        """`bb research --yes` proceeds without prompting."""
        # use click.testing.CliRunner
        ...

    def test_no_yes_flag_shows_table_and_prompts(self) -> None:
        """`bb research` (no --yes) shows source table, blocks on stdin."""
        ...

    def test_rejection_aborts_session(self) -> None:
        """User says 'n' → session status = cancelled, no payment, no ingestion."""
        ...

    @pytest.mark.asyncio
    async def test_mcp_auto_approve_default_true(self, demo_idea: str) -> None:
        """gecko_research from MCP auto-approves by default for Claude Code flow."""
        ...


# ---------------------------------------------------------------------------
# Phase 4 — Payment gate
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="implement after phase 4")
class TestPhase4Payments:
    """x402 gate runs before indexing. Three modes: stub, live, frames."""

    @pytest.mark.asyncio
    async def test_stub_mode_passes_quickly(self, session_id: str) -> None:
        """Stub mode passes the gate in < 200ms."""
        from gecko_core.payments.x402_client import (
            PaymentIntent,
            get_client,
        )

        client = get_client("stub")
        intent = PaymentIntent(
            intent_id="test-1", session_id=session_id, tier="basic", amount_usd="15.00"
        )
        start = time.monotonic()
        result = await client.charge(intent)
        elapsed = time.monotonic() - start
        assert result.status == "success"
        assert elapsed < 0.2

    @pytest.mark.asyncio
    async def test_idempotent_intent_id(self, session_id: str) -> None:
        """Same intent_id charged twice → second is a no-op (no double-charge)."""
        from gecko_core.payments.x402_client import PaymentIntent, get_client

        client = get_client("stub")
        intent = PaymentIntent(
            intent_id="dup-1", session_id=session_id, tier="basic", amount_usd="15.00"
        )
        r1 = await client.charge(intent)
        r2 = await client.charge(intent)
        assert r1.status == r2.status == "success"
        # tx_signature should be identical or both None — no two distinct transactions

    @pytest.mark.asyncio
    async def test_failed_payment_blocks_indexing(self, demo_idea: str) -> None:
        """Forced failure: no chunks created, session status='failed'."""
        # monkeypatch StubX402Client to return failed
        # call workflows.research, expect PaymentRequiredError
        # assert no rows in chunks table for the session
        ...

    def test_unknown_mode_raises(self) -> None:
        """X402_MODE=garbage fails fast at startup."""
        from gecko_core.payments.x402_client import get_client

        with pytest.raises(ValueError, match="unknown X402_MODE"):
            get_client("garbage")


# ---------------------------------------------------------------------------
# Phase 5 — Basic orchestration
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="implement after phase 5")
class TestPhase5BasicOrchestration:
    """Single GPT-4o-mini call produces three documents with citations."""

    @pytest.mark.asyncio
    async def test_returns_valid_research_result(self, session_id: str, demo_idea: str) -> None:
        """basic.generate returns a ResearchResult that validates against the schema."""
        from gecko_core.orchestration.basic import generate

        # assume session already has indexed chunks (set up via fixture)
        result = await generate(session_id=session_id, idea=demo_idea)
        assert result.business_plan is not None
        assert result.validation_report is not None
        assert result.prd is not None

    @pytest.mark.asyncio
    async def test_every_claim_has_citation(self, session_id: str, demo_idea: str) -> None:
        """PRD: every section has at least one citation."""
        from gecko_core.orchestration.basic import generate

        result = await generate(session_id=session_id, idea=demo_idea)
        assert len(result.business_plan.citations) >= 1
        assert len(result.validation_report.citations) >= 1
        assert len(result.prd.citations) >= 1

    @pytest.mark.asyncio
    async def test_citations_point_to_indexed_sources(
        self, session_id: str, demo_idea: str
    ) -> None:
        """Every citation URL exists in the session's sources table — no hallucination."""
        from gecko_core.orchestration.basic import generate
        from gecko_core.sessions.store import SessionStore

        result = await generate(session_id=session_id, idea=demo_idea)
        source_urls = {str(s.url) for s in await SessionStore().list_sources(session_id)}
        for doc in (result.business_plan, result.validation_report, result.prd):
            for c in doc.citations:
                assert str(c.source_url) in source_urls, f"hallucinated URL: {c.source_url}"

    @pytest.mark.asyncio
    async def test_under_60_seconds(self, session_id: str, demo_idea: str) -> None:
        """PRD: basic generation < 60s."""
        from gecko_core.orchestration.basic import generate

        start = time.monotonic()
        await generate(session_id=session_id, idea=demo_idea)
        assert time.monotonic() - start < 60


# ---------------------------------------------------------------------------
# Phase 6 — Pro orchestration (AutoGen GroupChat)
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="implement after phase 6")
class TestPhase6ProOrchestration:
    """5-agent GroupChat (orchestrator + 4 specialists)."""

    @pytest.mark.asyncio
    async def test_completes_under_5_minutes(self, session_id: str, demo_idea: str) -> None:
        """PRD: pro generation < 5 minutes."""
        from gecko_core.orchestration.pro import generate

        start = time.monotonic()
        await generate(session_id=session_id, idea=demo_idea)
        assert time.monotonic() - start < 300

    @pytest.mark.asyncio
    async def test_each_specialist_contributes(self, session_id: str, demo_idea: str) -> None:
        """Every specialist (Research, Market, Technical, Validator) sends >= 1 message."""
        from gecko_core.orchestration.pro import generate

        result = await generate(session_id=session_id, idea=demo_idea, return_transcript=True)
        speakers = {msg.sender for msg in result.transcript}
        assert {"Research", "Market Analyst", "Technical Architect", "Validator"} <= speakers

    @pytest.mark.asyncio
    async def test_rag_tool_called_during_chat(self, session_id: str, demo_idea: str) -> None:
        """Specialists call rag_query at least once (grounding evidence)."""
        from gecko_core.orchestration.pro import generate

        result = await generate(session_id=session_id, idea=demo_idea, return_transcript=True)
        rag_calls = [m for m in result.transcript if m.tool_name == "rag_query"]
        assert len(rag_calls) >= 1

    @pytest.mark.asyncio
    async def test_agent_context_persists_72h(self, session_id: str) -> None:
        """Agent state is fetchable up to 72h post-session."""
        # depends on persistence layer; implement after pro orchestration lands
        ...


# ---------------------------------------------------------------------------
# Phase 7 — Output rendering
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="implement after phase 7")
class TestPhase7Rendering:
    """The reveal moment — three Panels, separated by Rules, citations at end."""

    def test_renders_at_80_columns(self) -> None:
        """No clipping, no broken tables at narrow terminal."""
        from io import StringIO

        from rich.console import Console

        from gecko_cli.render import render_research_result

        console = Console(width=80, file=StringIO())
        # render a fixture ResearchResult, assert no exception
        ...

    def test_renders_at_200_columns(self) -> None:
        """Wide terminal — content spreads but doesn't fragment."""
        ...

    def test_citations_are_real_urls(self) -> None:
        """Rendered citations are clickable https:// URLs (terminal-detected)."""
        ...


# ---------------------------------------------------------------------------
# Phase 8 — MCP wiring
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="implement after phase 8")
class TestPhase8MCP:
    """Doctor + tool discovery + tool calls all work."""

    def test_doctor_passes_with_full_env(self) -> None:
        """gecko-mcp doctor exits 0 when all required env vars are set."""
        import subprocess

        proc = subprocess.run(["gecko-mcp", "doctor"], capture_output=True, text=True)
        assert proc.returncode == 0

    def test_doctor_fails_with_missing_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Doctor exits non-zero and names the missing var."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        import subprocess

        proc = subprocess.run(["gecko-mcp", "doctor"], capture_output=True, text=True)
        assert proc.returncode != 0
        assert "OPENAI_API_KEY" in proc.stderr

    @pytest.mark.asyncio
    async def test_list_tools_returns_three(self) -> None:
        """gecko_research, gecko_ask, gecko_sources are exposed."""
        from gecko_mcp.server import list_tools

        tools = await list_tools()
        names = {t.name for t in tools}
        assert names == {"gecko_research", "gecko_ask", "gecko_sources"}
