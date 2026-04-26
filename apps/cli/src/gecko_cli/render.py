"""Terminal rendering for CLI output. Owned by the product-designer agent.

Rules (from .claude/agents/product-designer.md):
- Hierarchy via Rich box drawing, not emoji
- Color is meaning: green=success, yellow=warn, red=fail, dim=metadata
- Three documents render as Panels separated by Rules
- Citations are a numbered list at the end of each panel
"""

from __future__ import annotations

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table

from gecko_core.models import AskResult, Citation, ResearchResult, SourceInfo


def render_research_result(console: Console, result: ResearchResult) -> None:
    console.print(Rule(f"Session {result.session_id} · tier={result.tier}"))

    console.print(Panel(
        Markdown(_business_plan_md(result.business_plan)),
        title="Business Plan",
        border_style="cyan",
    ))

    console.print(Panel(
        Markdown(_validation_md(result.validation_report)),
        title="Validation Report",
        border_style="cyan",
    ))

    console.print(Panel(
        Markdown(_prd_md(result.prd)),
        title="PRD",
        border_style="cyan",
    ))

    console.print(Rule(f"Indexed {len(result.sources)} sources"))


def render_ask_result(console: Console, result: AskResult) -> None:
    console.print(Panel(Markdown(result.answer), title="Answer", border_style="cyan"))
    if result.citations:
        console.print(_citations_block(result.citations))


def render_sources_table(console: Console, sources: list[SourceInfo]) -> None:
    table = Table(title=f"Indexed sources ({len(sources)})")
    table.add_column("URL", overflow="fold")
    table.add_column("Type")
    table.add_column("Chunks", justify="right")
    table.add_column("Indexed at", style="dim")
    for s in sources:
        table.add_row(
            str(s.url), s.type, str(s.chunk_count), s.indexed_at.isoformat(timespec="seconds")
        )
    console.print(table)


def _business_plan_md(bp) -> str:
    return (
        f"**Problem.** {bp.problem}\n\n"
        f"**ICP.** {bp.icp}\n\n"
        f"**Solution.** {bp.solution}\n\n"
        f"**Market.** {bp.market}\n\n"
        f"**Business model.** {bp.business_model}\n\n"
        f"**Channels.** {bp.channels}\n\n"
        f"**Key risks.**\n" + "\n".join(f"- {r}" for r in bp.risks)
        + _citations_md(bp.citations)
    )


def _validation_md(v) -> str:
    return (
        f"**Market size signal.** {v.market_size_signal}\n\n"
        f"**Competitor analysis.** {v.competitor_analysis}\n\n"
        f"**Demand evidence.** {v.demand_evidence}\n\n"
        f"**Risk flags.**\n" + "\n".join(f"- {r}" for r in v.risk_flags)
        + _citations_md(v.citations)
    )


def _prd_md(p) -> str:
    return (
        "**V1 scope.**\n" + "\n".join(f"- {x}" for x in p.v1_scope) + "\n\n"
        "**V2 scope.**\n" + "\n".join(f"- {x}" for x in p.v2_scope) + "\n\n"
        "**V3 scope.**\n" + "\n".join(f"- {x}" for x in p.v3_scope) + "\n\n"
        "**Acceptance criteria.**\n" + "\n".join(f"- {x}" for x in p.acceptance_criteria) + "\n\n"
        "**Non-functional.**\n" + "\n".join(f"- {x}" for x in p.non_functional) + "\n\n"
        "**Success metrics.**\n" + "\n".join(f"- {x}" for x in p.success_metrics)
        + _citations_md(p.citations)
    )


def _citations_md(cs: list[Citation]) -> str:
    if not cs:
        return ""
    lines = ["", "---", "**Sources.**"]
    for i, c in enumerate(cs, 1):
        lines.append(f"{i}. {c.source_url}")
    return "\n".join(lines)


def _citations_block(cs: list[Citation]) -> Panel:
    body = "\n".join(f"{i}. {c.source_url}" for i, c in enumerate(cs, 1))
    return Panel(body, title="Sources", border_style="dim")
