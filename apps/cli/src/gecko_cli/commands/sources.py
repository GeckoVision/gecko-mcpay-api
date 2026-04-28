"""`bb sources` — list indexed sources for a session."""

from __future__ import annotations

import asyncio

import click
import gecko_core
from rich.console import Console

from gecko_cli._render_compat import render_sources_table

console = Console()


@click.command("sources")
@click.argument("session_id")
def sources_cmd(session_id: str) -> None:
    """List indexed sources for a session."""
    rows = asyncio.run(gecko_core.list_sources(session_id=session_id))
    render_sources_table(console, rows)
