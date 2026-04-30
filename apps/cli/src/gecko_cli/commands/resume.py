"""`gecko resume <project_id>` — recap a project's recent loop activity."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

import click
from rich.console import Console

console = Console()


async def _fetch(project_id: str, days: int) -> dict[str, Any]:
    from gecko_core.memory.resume import build_resume

    resume = await build_resume(project_id, days=days)
    return resume.model_dump(mode="json")


def _humanize_age(ts: str | None) -> str:
    if not ts:
        return "never"
    try:
        when = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return ts
    now = datetime.now(when.tzinfo) if when.tzinfo else datetime.now()
    delta = now - when
    days = delta.days
    if days <= 0:
        hours = max(int(delta.total_seconds() // 3600), 0)
        return f"{hours} hours ago" if hours else "moments ago"
    return f"{days} days ago"


@click.command("resume")
@click.argument("project_id")
@click.option("--days", default=30, show_default=True)
def resume_cmd(project_id: str, days: int) -> None:
    """Render a structured summary of PROJECT_ID's recent loop activity."""
    payload = asyncio.run(_fetch(project_id, days))
    console.print(f"[bold]Project:[/bold] {payload['project_id']}")
    console.print(f"Last activity: {_humanize_age(payload.get('last_activity_at'))}\n")

    by_type = payload.get("by_type", {})
    verdicts = by_type.get("verdict_received") or []
    if verdicts:
        console.print("[bold]Recent decisions:[/bold]")
        for v in verdicts[:5]:
            value = v.get("value") or {}
            verdict = str(value.get("verdict") or "").upper()
            idea = str(value.get("idea") or "")[:80]
            ts = v.get("created_at", "")[:10]
            console.print(f"  {ts}  {verdict:6s} — {idea!r}")
        console.print()

    voices = payload.get("last_panel_voices") or []
    if voices:
        console.print("[bold]Last advisor panel:[/bold]")
        for voice in voices:
            role = str(voice.get("role") or "?")
            line = str(voice.get("closing_line") or "")
            console.print(f"  {role}: {line}")
        console.print()

    deltas = payload.get("last_pulse_deltas") or []
    if deltas:
        console.print("[bold]Pulse delta vs prior:[/bold]")
        for d in deltas:
            voice = str(d.get("voice") or "?")
            before = str(d.get("before") or "(none)")
            after = str(d.get("after") or "(none)")
            if before != after:
                console.print(f"  {voice}: {before!r} -> {after!r}")
        console.print()

    if not (verdicts or voices or deltas):
        console.print("[dim]No memory entries in window. Try --days 90.[/dim]")
