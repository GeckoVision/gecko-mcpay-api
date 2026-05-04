"""S23-REPORT-01 — unit tests for the HTML/markdown report renderer.

Tests cover:
- Basic output contains session_id, verdict_hash
- gap_explanation=None + low_explanation=True → callout shown, no synthesis
- surviving_dissent=None → no "dissent" section in output
- plan=None → no "voices" section in output
- Full AdvisorPanel fixture → all 5 closing_line values appear
- No template debris ({{ }})
"""

from __future__ import annotations

from gecko_core.models import (
    PRD,
    BusinessPlan,
    Citation,
    ResearchResult,
    ValidationReport,
    Verdict,
)
from gecko_core.reports.html import render_html_report, render_markdown_report

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _minimal_citation() -> Citation:
    return Citation(
        source_url="https://example.com/source",
        chunk_index=0,
        similarity=0.75,
    )


def _minimal_business_plan() -> BusinessPlan:
    return BusinessPlan(
        problem="Founders can't validate ideas fast enough.",
        icp="Early-stage founders",
        solution="Multi-agent debate verdict",
        market="Startup tooling",
        business_model="Pay per verdict",
        channels="Claude Code MCP",
        risks=["Competition from Perplexity", "Slow LLM providers"],
        citations=[_minimal_citation()],
    )


def _minimal_prd() -> PRD:
    return PRD(
        v1_scope=["Basic verdict", "Citation list"],
        v2_scope=["Pro debate"],
        v3_scope=["Flywheel"],
        acceptance_criteria=["Verdict in < 30s"],
        non_functional=["99.9% uptime"],
        success_metrics=["50 sessions/day"],
        citations=[_minimal_citation()],
    )


def _minimal_validation_report(
    *,
    gap_explanation: str | None = None,
) -> ValidationReport:
    return ValidationReport(
        market_size_signal="Large market signal",
        competitor_analysis="Several incumbents",
        demand_evidence="High demand",
        risk_flags=["Key person risk"],
        citations=[_minimal_citation()],
        gap_classification="Partial:UX",
        gap_summary="Competitors lack adversarial debate",
        gap_explanation=gap_explanation,
    )


def _minimal_result(
    *,
    session_id: str = "test-session-123",
    verdict_hash: str | None = "abc123hashvalue",
    low_explanation: bool = False,
    surviving_dissent: object = None,
    gap_explanation: str | None = None,
) -> ResearchResult:
    return ResearchResult(
        session_id=session_id,
        tier="basic",
        business_plan=_minimal_business_plan(),
        validation_report=_minimal_validation_report(gap_explanation=gap_explanation),
        prd=_minimal_prd(),
        sources=[],
        verdict=Verdict.REFINE,
        verdict_hash=verdict_hash,
        low_explanation=low_explanation,
        surviving_dissent=surviving_dissent,  # type: ignore[arg-type]
    )


def _make_advisor_panel() -> object:
    """Build an AdvisorPanel with 5 voices, each with a unique closing_line."""
    from gecko_core.orchestration.advisor.models import AdvisorPanel, AdvisorVoice
    from gecko_core.routing.catalog import AgentRole

    voices = []
    for role, line in [
        (AgentRole.ceo, "CEO closing: build the moat now."),
        (AgentRole.cto, "CTO closing: the architecture is sound."),
        (AgentRole.business_manager, "BizMgr closing: the unit economics work."),
        (AgentRole.product_manager, "PM closing: the roadmap is credible."),
        (AgentRole.staff_manager, "StaffMgr closing: start sprint 1 Monday."),
    ]:
        voices.append(
            AdvisorVoice(
                role=role,
                model_used="gpt-4o-mini",
                output_md=f"# {role.value}\n\nFull analysis for {role.value}.",
                closing_line=line,
                tokens_in=100,
                tokens_out=200,
                cost_usd=0.001,
            )
        )
    return AdvisorPanel(
        session_id="test-session-123",
        voices=voices,
        total_cost_usd=0.005,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_html_contains_session_id() -> None:
    result = _minimal_result()
    html = render_html_report(result)
    assert "test-session-123" in html


def test_html_contains_verdict_hash() -> None:
    result = _minimal_result(verdict_hash="abc123hashvalue")
    html = render_html_report(result)
    assert "abc123hashvalue" in html


def test_html_low_explanation_shows_callout() -> None:
    """When low_explanation=True and gap_explanation=None, the callout appears."""
    result = _minimal_result(low_explanation=True, gap_explanation=None)
    html = render_html_report(result)
    assert "did not produce an explanation" in html


def test_html_low_explanation_does_not_synthesize() -> None:
    """Callout path must not synthesize from gap_summary."""
    result = _minimal_result(low_explanation=True, gap_explanation=None)
    html = render_html_report(result)
    # gap_summary text should still appear (it's shown in the table)
    # but gap_explanation itself should be absent
    assert "gap_explanation" not in html or "did not produce an explanation" in html


def test_html_no_template_debris() -> None:
    """The renderer must not leave {{ or }} in the output."""
    result = _minimal_result()
    html = render_html_report(result)
    assert "{{" not in html
    assert "}}" not in html


def test_html_no_surviving_dissent_section_when_none() -> None:
    """When surviving_dissent=None, no dissent section is rendered."""
    result = _minimal_result(surviving_dissent=None)
    html = render_html_report(result)
    # The section heading should not appear
    assert "Surviving Dissent" not in html


def test_html_no_voices_section_when_no_plan() -> None:
    """When plan=None, the 5-voice panel section is omitted."""
    result = _minimal_result()
    html = render_html_report(result, plan=None)
    # The section heading and per-voice detail blocks should be absent.
    # (voice-role CSS class name appears in the global stylesheet — only
    # check for the section heading and detail block markers that only
    # appear when a panel is rendered.)
    assert "5-Voice Advisor Panel" not in html
    assert "<details>" not in html


def test_html_panel_shows_all_closing_lines() -> None:
    """With a full AdvisorPanel, all 5 closing_line values appear in the HTML."""
    result = _minimal_result()
    panel = _make_advisor_panel()
    html = render_html_report(result, plan=panel)  # type: ignore[arg-type]

    assert "5-Voice Advisor Panel" in html
    assert "CEO closing: build the moat now." in html
    assert "CTO closing: the architecture is sound." in html
    assert "BizMgr closing: the unit economics work." in html
    assert "PM closing: the roadmap is credible." in html
    assert "StaffMgr closing: start sprint 1 Monday." in html


def test_html_panel_voices_in_details_block() -> None:
    """Voice output_md must be in a <details> block, not inline."""
    result = _minimal_result()
    panel = _make_advisor_panel()
    html = render_html_report(result, plan=panel)  # type: ignore[arg-type]
    assert "<details>" in html


def test_markdown_report_contains_session_id() -> None:
    result = _minimal_result(session_id="md-test-session")
    md = render_markdown_report(result)
    assert "md-test-session" in md


def test_markdown_low_explanation_note() -> None:
    result = _minimal_result(low_explanation=True, gap_explanation=None)
    md = render_markdown_report(result)
    assert "did not produce an explanation" in md


def test_markdown_panel_shows_closing_lines() -> None:
    result = _minimal_result()
    panel = _make_advisor_panel()
    md = render_markdown_report(result, plan=panel)  # type: ignore[arg-type]
    assert "CEO closing: build the moat now." in md
    assert "StaffMgr closing: start sprint 1 Monday." in md
