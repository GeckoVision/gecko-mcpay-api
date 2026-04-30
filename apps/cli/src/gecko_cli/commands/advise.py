"""`gecko advise` — invoke a single advisor voice over a session.

Cheap path (1 LLM call). Use `gecko plan` for the full 5-voice panel.
"""

from __future__ import annotations

import asyncio
from uuid import UUID

import click
from rich.console import Console

console = Console()

_VOICE_CHOICES = (
    "ceo",
    "cto",
    "business_manager",
    "product_manager",
    "staff_manager",
    "bm",
    "pm",
    "sm",
)


@click.command("advise")
@click.argument("session_id")
@click.option(
    "--voice",
    "voice",
    type=click.Choice(_VOICE_CHOICES, case_sensitive=False),
    required=True,
    help="Which advisor voice to invoke (aliases: bm, pm, sm).",
)
@click.option(
    "--tier-preset",
    "tier_preset",
    type=click.Choice(("quality", "balanced", "budget", "free")),
    default="balanced",
    show_default=True,
)
def advise_cmd(session_id: str, voice: str, tier_preset: str) -> None:
    """Run one advisor voice (CEO / CTO / BM / PM / SM) for SESSION_ID."""
    from gecko_core.orchestration.advisor import (
        AdvisorSessionNotFoundError,
        generate_voice,
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
        result = asyncio.run(generate_voice(sid, voice, tier_preset=tier))
    except AdvisorSessionNotFoundError as exc:
        console.print(f"[red]Not found:[/red] {exc}")
        raise SystemExit(1) from exc
    except ValueError as exc:
        console.print(f"[red]Bad voice:[/red] {exc}")
        raise SystemExit(2) from exc

    console.rule(f"[bold]{result.role.value.upper()}[/bold]  ({result.model_used})")
    console.print(result.output_md)
    console.rule()
    console.print(f"[bold]{result.closing_line}[/bold]")
    console.print(
        f"[dim]tokens in/out: {result.tokens_in}/{result.tokens_out}"
        + (f"  cost: ${result.cost_usd:.4f}" if result.cost_usd is not None else "")
        + "[/dim]"
    )
