"""Smoke tests for the CLI renderer (Phase 7)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from gecko_cli.render import (
    WorkflowProgress,
    progress_context,
    render_ask_result,
    render_research_result,
    render_source_candidates,
    render_sources_table,
)
from gecko_core.models import (
    PRD,
    AskResult,
    BusinessPlan,
    Citation,
    ResearchResult,
    SourceCandidate,
    SourceInfo,
    ValidationReport,
)
from rich.console import Console

# --- Fixtures --------------------------------------------------------------


def _cite(url: str, idx: int = 0, sim: float = 0.83) -> Citation:
    return Citation(source_url=url, chunk_index=idx, similarity=sim)  # type: ignore[arg-type]


def _make_result(idea: str = "AI-native CRM") -> ResearchResult:
    bp_cites = [
        _cite("https://example.com/a", 1),
        _cite("https://example.com/b", 4),
    ]
    val_cites = [
        _cite("https://example.com/c", 2),
        _cite("https://example.com/d", 7),
    ]
    prd_cites = [
        _cite("https://example.com/e", 0),
        _cite("https://example.com/f", 3),
    ]
    return ResearchResult(
        session_id="sess_abc123",
        tier="basic",
        business_plan=BusinessPlan(
            problem=f"Idea: {idea}. Sales reps drown in tooling.",
            icp="Series A SaaS revops leaders.",
            solution="Single agentic CRM that drafts, sends, and learns.",
            market="$45B CRM TAM, growing 12% YoY.",
            business_model="Per-seat SaaS, $99/seat/mo.",
            channels="Founder-led sales, design partner program.",
            risks=["Incumbent lock-in", "Trust in AI-written outreach"],
            citations=bp_cites,
        ),
        validation_report=ValidationReport(
            market_size_signal="3 funded competitors raised >$10M in 2025.",
            competitor_analysis="Salesforce, HubSpot dominate; Attio is closest.",
            demand_evidence="42 design-partner sign-ups in 2 weeks.",
            risk_flags=["Regulated industries lag", "Data residency"],
            citations=val_cites,
        ),
        prd=PRD(
            v1_scope=["Inbox triage", "Draft suggestions"],
            v2_scope=["Pipeline analytics", "Auto-followups"],
            v3_scope=["Voice agent"],
            acceptance_criteria=["Draft latency < 2s", "99.5% uptime"],
            non_functional=["SOC2 Type II", "EU data residency option"],
            success_metrics=["DAU/MAU > 0.4", "30-day retention > 60%"],
            citations=prd_cites,
        ),
        sources=[
            SourceInfo(
                url="https://example.com/a",  # type: ignore[arg-type]
                type="web",
                chunk_count=12,
                indexed_at=datetime.now(UTC) - timedelta(minutes=2),
            ),
            SourceInfo(
                url="https://example.com/b",  # type: ignore[arg-type]
                type="youtube",
                chunk_count=34,
                indexed_at=datetime.now(UTC) - timedelta(hours=1),
            ),
        ],
    )


# --- Width handling --------------------------------------------------------


@pytest.mark.parametrize("width", [80, 120, 200])
def test_render_research_result_at_widths(width: int) -> None:
    console = Console(record=True, width=width, color_system=None)
    render_research_result(_make_result(), console=console)
    out = console.export_text()
    # Body content survives at every width.
    assert "Business Plan" in out
    assert "Validation Report" in out
    assert "PRD" in out
    # No mid-word ellipsis clipping in body content (Rich uses U+2026).
    # We accept ellipsis only inside Progress; this output has none.
    assert "…" not in out


def test_render_research_result_long_idea_header_does_not_error() -> None:
    long_idea = "x" * 500
    result = _make_result(idea=long_idea)
    console = Console(record=True, width=80, color_system=None)
    render_research_result(result, console=console)
    out = console.export_text()
    assert "Business Plan" in out


# --- Citations -------------------------------------------------------------


def test_three_panels_each_have_two_numbered_citations() -> None:
    console = Console(record=True, width=120, color_system=None)
    render_research_result(_make_result(), console=console)
    out = console.export_text()
    # 6 total citations (2 per panel), numbered [1] and [2] within each panel.
    assert out.count("[1] ") == 3
    assert out.count("[2] ") == 3
    # Sanity: the URLs render.
    for letter in ["a", "b", "c", "d", "e", "f"]:
        assert f"https://example.com/{letter}" in out


# --- Sources table ---------------------------------------------------------


def test_render_sources_table_empty_does_not_crash() -> None:
    console = Console(record=True, width=100, color_system=None)
    render_sources_table([], console=console)
    out = console.export_text()
    assert "Indexed sources (0)" in out
    assert "no sources indexed yet" in out


def test_render_sources_table_sorted_desc() -> None:
    now = datetime.now(UTC)
    sources = [
        SourceInfo(
            url="https://old.example.com",  # type: ignore[arg-type]
            type="web",
            chunk_count=1,
            indexed_at=now - timedelta(days=2),
        ),
        SourceInfo(
            url="https://new.example.com",  # type: ignore[arg-type]
            type="web",
            chunk_count=2,
            indexed_at=now - timedelta(minutes=1),
        ),
    ]
    console = Console(record=True, width=120, color_system=None)
    render_sources_table(sources, console=console)
    out = console.export_text()
    assert out.find("new.example.com") < out.find("old.example.com")


# --- Ask -------------------------------------------------------------------


def test_render_ask_result() -> None:
    res = AskResult(
        session_id="sess_x",
        answer="Because the market is growing.",
        citations=[_cite("https://example.com/a", 1)],
    )
    console = Console(record=True, width=100, color_system=None)
    render_ask_result(res, console=console)
    out = console.export_text()
    assert "Because the market is growing." in out
    assert "[1] " in out


# --- Source candidates -----------------------------------------------------


def test_render_source_candidates_empty() -> None:
    console = Console(record=True, width=100, color_system=None)
    render_source_candidates([], console=console)
    out = console.export_text()
    assert "Discovered sources (0)" in out


def test_render_source_candidates_rows() -> None:
    cands = [
        SourceCandidate(
            url="https://example.com/x",  # type: ignore[arg-type]
            title="Great Read",
            type="web",
            score=0.9,
        ),
        SourceCandidate(
            url="https://youtu.be/abc",  # type: ignore[arg-type]
            title="",
            type="youtube",
            score=0.7,
        ),
    ]
    console = Console(record=True, width=120, color_system=None)
    render_source_candidates(cands, console=console)
    out = console.export_text()
    assert "Great Read" in out
    assert "youtu.be/abc" in out


# --- Progress --------------------------------------------------------------


def test_progress_context_yields_progress() -> None:
    console = Console(record=True, width=120, color_system=None)
    with progress_context(console=console) as p:
        task = p.add_task("Working", total=1, phase="x")
        p.advance(task, 1)


def test_workflow_progress_phases() -> None:
    console = Console(record=True, width=120, color_system=None)
    with WorkflowProgress(console=console) as wp:
        wp.start_discovery()
        wp.start_indexing(3)
        wp.advance_indexing(1)
        wp.advance_indexing(2)
        wp.start_generating()
        wp.complete()
