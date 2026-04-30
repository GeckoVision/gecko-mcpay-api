"""`gecko pulse` — re-run the advisor panel and surface deltas."""

from __future__ import annotations

import asyncio
from uuid import UUID

import click
from rich.console import Console
from rich.table import Table

console = Console()


@click.command("pulse")
@click.argument("session_id", required=False)
@click.option(
    "--project-id",
    "project_id",
    default=None,
    help="Project UUID — walks pulse history across all of the project's sessions.",
)
@click.option(
    "--tier-preset",
    "tier_preset",
    type=click.Choice(("quality", "balanced", "budget", "free")),
    default="balanced",
    show_default=True,
)
def pulse_cmd(session_id: str | None, project_id: str | None, tier_preset: str) -> None:
    """Re-run the panel and report what changed.

    Pass either SESSION_ID or --project-id (S5-API-02). Project-id wins
    when both are given. With migration 019_pulse_runs.sql, the advisor
    walks pulse history and computes real deltas across runs.
    """
    from gecko_core.orchestration.advisor import (
        AdvisorSessionNotFoundError,
        run_pulse,
    )
    from gecko_core.routing.catalog import Tier

    if not session_id and not project_id:
        raise click.BadParameter("either SESSION_ID or --project-id is required")

    sid: UUID | None = None
    if session_id:
        try:
            sid = UUID(session_id)
        except ValueError as exc:
            raise click.BadParameter(f"session_id is not a valid UUID: {exc}") from exc

    pid: UUID | None = None
    if project_id:
        try:
            pid = UUID(project_id)
        except ValueError as exc:
            raise click.BadParameter(f"project-id is not a valid UUID: {exc}") from exc

    try:
        tier = Tier(tier_preset)
    except ValueError as exc:
        raise click.BadParameter(f"unknown tier_preset: {exc}") from exc

    try:
        result = asyncio.run(run_pulse(session_id=sid, project_id=pid, tier_preset=tier))
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
    console.print(f"[dim]total cost: ${result.panel.total_cost_usd:.4f}[/dim]")
