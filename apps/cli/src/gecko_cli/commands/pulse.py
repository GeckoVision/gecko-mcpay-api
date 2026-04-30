"""`gecko pulse` — re-run the advisor panel and surface deltas."""

from __future__ import annotations

import asyncio
from uuid import UUID

import click
from rich.console import Console
from rich.table import Table

console = Console()


@click.command("pulse")
@click.argument("session_id")
@click.option(
    "--tier-preset",
    "tier_preset",
    type=click.Choice(("quality", "balanced", "budget", "free")),
    default="balanced",
    show_default=True,
)
def pulse_cmd(session_id: str, tier_preset: str) -> None:
    """Re-run the panel for SESSION_ID and report what changed.

    Until migration 018_pulse_runs.sql ships, no prior pulse is on file
    and every run reports ``no prior pulse`` for each voice.
    """
    from gecko_core.orchestration.advisor import (
        AdvisorSessionNotFoundError,
        run_pulse,
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
        result = asyncio.run(
            run_pulse(sid, previous_panel=None, tier_preset=tier)
        )
    except AdvisorSessionNotFoundError as exc:
        console.print(f"[red]Not found:[/red] {exc}")
        raise SystemExit(1) from exc

    table = Table(title=f"Pulse — session {result.panel.session_id}")
    table.add_column("Voice")
    table.add_column("Changed?")
    table.add_column("Now")
    table.add_column("Was")
    for d in result.deltas:
        table.add_row(
            d.role.value,
            "yes" if d.changed else "no",
            d.current_closing_line,
            d.previous_closing_line or "—",
        )
    console.print(table)
    console.print(
        f"[dim]total cost: ${result.panel.total_cost_usd:.4f}[/dim]"
    )
