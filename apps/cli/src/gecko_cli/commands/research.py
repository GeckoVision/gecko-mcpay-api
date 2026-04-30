"""`bb research` — discover, approve, pay, index, generate."""

from __future__ import annotations

import asyncio

import click
import gecko_core
from gecko_core.models import SourceCandidate
from rich.console import Console
from rich.table import Table

from gecko_cli._prompt import assume_yes
from gecko_cli._prompt import confirm as prompt_confirm
from gecko_cli._render_compat import progress_context, render_research_result
from gecko_cli.commands.project import resolve_project_id

console = Console()


def _print_candidates(candidates: list[SourceCandidate]) -> None:
    table = Table(title=f"Proposed sources ({len(candidates)})")
    table.add_column("#", justify="right", style="dim")
    table.add_column("Score", justify="right")
    table.add_column("Type")
    table.add_column("URL", overflow="fold")
    for i, c in enumerate(candidates, 1):
        table.add_row(str(i), f"{c.score:.2f}", c.type, str(c.url))
    console.print(table)


async def _interactive_approval(candidates: list[SourceCandidate]) -> bool:
    _print_candidates(candidates)
    # `prompt_confirm` honors top-level --yes / --non-interactive flags.
    return prompt_confirm("Proceed with these sources?", default=True)


@click.command("research")
@click.option("--idea", required=True, help="Plain-language startup idea.")
@click.option("--tier", type=click.Choice(["basic", "pro"]), default="basic")
@click.option("--urls", multiple=True, help="Optional seed URLs (repeatable).")
@click.option("--yes", "-y", is_flag=True, help="Skip the approval prompt.")
@click.option(
    "--project",
    "project",
    default=None,
    help="Attach this run to a project (UUID or name; falls back to .gecko/project.json).",
)
@click.option(
    "--tier-preset",
    "tier_preset",
    type=click.Choice(["quality", "balanced", "budget", "free"]),
    default="balanced",
    help=(
        "User-facing cost/quality preset (S4-MATRIX-01). Drives per-agent "
        "model selection via the curated catalog."
    ),
)
def research_cmd(
    idea: str,
    tier: str,
    urls: tuple[str, ...],
    yes: bool,
    project: str | None,
    tier_preset: str,
) -> None:
    """Discover, index, generate. The main workflow."""
    seed = list(urls) if urls else None
    project_id = resolve_project_id(project)
    if project_id is not None:
        console.print(f"[dim]project: {project_id}[/dim]")

    # Top-level --yes / --non-interactive bubble through `assume_yes`; keep
    # the per-command --yes flag for back-compat.
    auto_approve = assume_yes(local=yes)

    with progress_context(console, "Researching") as progress:

        def _progress(msg: str) -> None:
            progress.update(msg)

        result = asyncio.run(
            gecko_core.research(
                idea=idea,
                tier=tier,  # type: ignore[arg-type]
                urls=seed,
                auto_approve=auto_approve,
                approval_callback=None if auto_approve else _interactive_approval,
                progress_callback=_progress,
                tier_preset=tier_preset,
            )
        )

    render_research_result(console, result)
    console.print(f"[dim]session_id: {result.session_id}[/dim]")
