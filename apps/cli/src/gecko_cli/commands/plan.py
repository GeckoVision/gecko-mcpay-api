"""`gecko plan` — run the full 5-voice Advisor Panel over a session."""

from __future__ import annotations

import asyncio
from uuid import UUID

import click
from rich.console import Console
from rich.table import Table

console = Console()


@click.command("plan")
@click.argument("session_id")
@click.option(
    "--tier-preset",
    "tier_preset",
    type=click.Choice(("quality", "balanced", "budget", "free")),
    default="balanced",
    show_default=True,
)
def plan_cmd(session_id: str, tier_preset: str) -> None:
    """Run the 5-voice panel (CEO / CTO / BM / PM / SM) for SESSION_ID."""
    from gecko_core.orchestration.advisor import (
        AdvisorSessionNotFoundError,
        generate_panel,
    )
    from gecko_core.routing.catalog import Tier

    try:
        sid = UUID(session_id)
    except ValueError as exc:
        raise click.BadParameter(f"session_id is not a valid UUID: {exc}") from exc

    try:
        tier = Tier(tier_preset)
    except ValueError as exc:
        raise click.BadParameter(f"unknown tier_preset: {exc}") from exc

    try:
        panel = asyncio.run(generate_panel(sid, tier_preset=tier))
    except AdvisorSessionNotFoundError as exc:
        console.print(f"[red]Not found:[/red] {exc}")
        raise SystemExit(1) from exc

    table = Table(title=f"Advisor Panel — session {panel.session_id}")
    table.add_column("Voice")
    table.add_column("Model")
    table.add_column("Closing line")
    for v in panel.voices:
        table.add_row(v.role.value, v.model_used, v.closing_line)
    console.print(table)
    console.print(f"[dim]total advisor cost: ${panel.total_cost_usd:.4f}[/dim]")
