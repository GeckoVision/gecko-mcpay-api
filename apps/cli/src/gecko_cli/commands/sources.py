"""`gecko sources` — list indexed sources for a session, or the source catalog.

Two modes:

* `gecko sources <session_id>` — sources indexed into a specific session's
  knowledge base (the original behaviour).
* `gecko sources --catalog` — the static catalog of every source Gecko
  *can* query (Tavily, HN, Reddit, twit.sh, Colosseum, gecko_precedent…),
  with description, gating, and per-call cost. No session needed.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict

import click
import gecko_core
from rich.console import Console
from rich.table import Table

from gecko_cli._render_compat import render_sources_table

console = Console()


def _render_catalog() -> None:
    from gecko_core.sources import available_sources

    entries = available_sources()
    table = Table(title=f"Gecko source catalog ({len(entries)})")
    table.add_column("Name")
    table.add_column("Description", overflow="fold")
    table.add_column("Gating")
    table.add_column("Cost / call")
    for entry in entries:
        row = asdict(entry)
        table.add_row(row["name"], row["description"], row["gating"], row["cost_per_call"])
    console.print(table)


@click.command("sources")
@click.argument("session_id", required=False)
@click.option(
    "--catalog",
    is_flag=True,
    default=False,
    help="List the static source catalog instead of session-indexed sources.",
)
def sources_cmd(session_id: str | None, catalog: bool) -> None:
    """List indexed sources for SESSION_ID, or the static catalog with --catalog."""
    if catalog:
        if session_id is not None:
            raise click.UsageError("Pass either SESSION_ID or --catalog, not both.")
        _render_catalog()
        return
    if session_id is None:
        raise click.UsageError("SESSION_ID is required (or pass --catalog).")
    rows = asyncio.run(gecko_core.list_sources(session_id=session_id))
    render_sources_table(console, rows)
