"""`gecko scaffold` — emit a 3-file project starter bundle for a Pro session.

Demo wow-moment: after a Pro debate verdict, run this and the user gets
PRD.md, business-plan.md, BUILDING.md ready to paste into Claude Code.
Free — the user already paid for the debate that produced the transcript.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import UUID

import click
from rich.console import Console
from rich.table import Table

console = Console()


def _human_size(num_bytes: int) -> str:
    """Render a byte count as a short human string (KB granularity is fine here)."""
    if num_bytes < 1024:
        return f"{num_bytes} B"
    return f"{num_bytes / 1024:.1f} KB"


@click.command("scaffold")
@click.argument("session_id")
@click.option(
    "--output-dir",
    "output_dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path.cwd,
    show_default="current directory",
    help="Workspace root. Files land under <output_dir>/.gecko/scaffolds/<session_id>/.",
)
def scaffold_cmd(session_id: str, output_dir: Path) -> None:
    """Generate PRD.md / business-plan.md / BUILDING.md for SESSION_ID."""
    # Lazy imports — keeps the CLI startup path fast for unrelated commands.
    from gecko_core.orchestration.scaffold import (
        KillVerdictError,
        ScaffoldError,
        SessionNotFoundError,
        SessionNotReadyError,
        generate_scaffold,
    )

    try:
        sid = UUID(session_id)
    except ValueError as exc:
        raise click.BadParameter(f"session_id is not a valid UUID: {exc}") from exc

    try:
        result = asyncio.run(generate_scaffold(sid, output_dir))
    except KillVerdictError as exc:
        console.print(f"[red]Refused:[/red] {exc}")
        console.print(
            "[dim]Scaffolding is only available for SHIP / PIVOT verdicts.[/dim]"
        )
        raise SystemExit(2) from exc
    except SessionNotFoundError as exc:
        console.print(f"[red]Not found:[/red] {exc}")
        raise SystemExit(1) from exc
    except SessionNotReadyError as exc:
        console.print(f"[yellow]Not ready:[/yellow] {exc}")
        raise SystemExit(1) from exc
    except ScaffoldError as exc:
        console.print(f"[red]Scaffold failed:[/red] {exc}")
        raise SystemExit(1) from exc

    table = Table(title=f"Scaffold ready (session {result.session_id})")
    table.add_column("File")
    table.add_column("Size", justify="right")
    for path in result.paths:
        size = path.stat().st_size if path.exists() else 0
        table.add_row(str(path), _human_size(size))
    console.print(table)
    console.print(f"[dim]synthesizer tokens: {result.tokens_used}[/dim]")
    if result.summary:
        console.print(f"[dim]{result.summary[:160]}[/dim]")
