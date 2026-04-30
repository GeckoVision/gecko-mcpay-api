"""`bb sprint-review` — synthesize a SprintReview for the current repo (S7-DOGFOOD-03).

Wraps ``gecko_core.review.build_review`` and renders a Rich panel. The
``--write-doc`` flag archives the rendered review to
``docs/sprint-reviews/YYYY-MM-DD.md`` so the build-plan trail keeps growing
sprint over sprint.
"""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel

console = Console()

# Accept "14d", "7d", "30d", or a bare integer (interpreted as days).
_SINCE_PATTERN = re.compile(r"^\s*(\d+)\s*d?\s*$", re.IGNORECASE)


def _parse_since(value: str) -> int:
    """Parse ``--since`` into an integer day count.

    Accepts "14d" / "14" / "7d". Anything else raises ``click.BadParameter``.
    """
    match = _SINCE_PATTERN.match(value)
    if not match:
        raise click.BadParameter(f"--since must look like '14d' or a bare integer; got {value!r}")
    days = int(match.group(1))
    if days <= 0 or days > 365:
        raise click.BadParameter(f"--since must be between 1 and 365 days; got {days}")
    return days


def _render_review_markdown(review_dict: dict[str, object]) -> str:
    """Render the SprintReview dict as a markdown doc for --write-doc."""
    lines: list[str] = []
    lines.append(f"# Sprint review — {datetime.now(tz=UTC).date().isoformat()}")
    lines.append("")
    lines.append(f"- **project_id**: `{review_dict.get('project_id') or '—'}`")
    lines.append(f"- **since_days**: {review_dict.get('since_days')}")
    lines.append(f"- **mode**: {review_dict.get('mode')}")
    lines.append(f"- **memory_entry_count**: {review_dict.get('memory_entry_count')}")
    lines.append("")
    lines.append("## Shipped")
    shipped = review_dict.get("shipped") or []
    if isinstance(shipped, list) and shipped:
        for item in shipped:
            lines.append(f"- {item}")
    else:
        lines.append("- (nothing shipped in window)")
    lines.append("")
    lines.append("## Weakest link")
    lines.append(str(review_dict.get("weakest_link") or "—"))
    lines.append("")
    lines.append("## Proposed next")
    proposed = review_dict.get("proposed_next") or []
    if isinstance(proposed, list) and proposed:
        for item in proposed:
            lines.append(f"- {item}")
    else:
        lines.append("- (no proposals)")
    lines.append("")
    return "\n".join(lines)


@click.command("sprint-review")
@click.option("--since", "since", default="14d", show_default=True)
@click.option("--project-id", "project_id", default=None)
@click.option(
    "--tier-preset",
    "tier_preset",
    type=click.Choice(("quality", "balanced", "budget", "free")),
    default="balanced",
    show_default=True,
)
@click.option(
    "--write-doc",
    "write_doc",
    is_flag=True,
    default=False,
    help="Persist the rendered review to docs/sprint-reviews/YYYY-MM-DD.md.",
)
def sprint_review_cmd(
    since: str,
    project_id: str | None,
    tier_preset: str,
    write_doc: bool,
) -> None:
    """Synthesize a sprint review for the current repo.

    FREE in stub mode (no LLM call). In live mode the API surface charges
    $0.10 — this CLI calls gecko_core directly and bypasses x402 entirely
    so it stays a developer ergonomics tool.
    """
    from gecko_core.review import build_review

    days = _parse_since(since)

    review = asyncio.run(
        build_review(
            project_id=project_id,
            since_days=days,
            tier_preset=tier_preset,
        )
    )

    body_lines: list[str] = []
    body_lines.append(f"[bold]project_id[/bold]: {review.project_id or '—'}")
    body_lines.append(f"[bold]since_days[/bold]: {review.since_days}")
    body_lines.append(f"[bold]mode[/bold]: {review.mode}")
    body_lines.append(f"[bold]memory_entry_count[/bold]: {review.memory_entry_count}")
    body_lines.append("")
    body_lines.append("[bold cyan]Shipped[/bold cyan]")
    if review.shipped:
        for item in review.shipped:
            body_lines.append(f"  • {item}")
    else:
        body_lines.append("  (nothing shipped in window)")
    body_lines.append("")
    body_lines.append("[bold yellow]Weakest link[/bold yellow]")
    body_lines.append(f"  {review.weakest_link or '—'}")
    body_lines.append("")
    body_lines.append("[bold green]Proposed next[/bold green]")
    if review.proposed_next:
        for item in review.proposed_next:
            body_lines.append(f"  • {item}")
    else:
        body_lines.append("  (no proposals)")

    panel = Panel(
        "\n".join(body_lines),
        title="Sprint Review",
        border_style="cyan",
    )
    console.print(panel)

    if write_doc:
        doc_dir = Path.cwd() / "docs" / "sprint-reviews"
        doc_dir.mkdir(parents=True, exist_ok=True)
        today = datetime.now(tz=UTC).date().isoformat()
        doc_path = doc_dir / f"{today}.md"
        doc_path.write_text(
            _render_review_markdown(review.model_dump(mode="json")),
            encoding="utf-8",
        )
        console.print(f"[dim]wrote {doc_path}[/dim]")
