"""`gecko precedents` — look up similar prior Gecko verdicts (the flywheel)."""

from __future__ import annotations

import asyncio
from typing import Any

import click
from rich.console import Console
from rich.table import Table

console = Console()


async def _fetch(idea: str, top_k: int) -> list[dict[str, Any]]:
    # Lazy imports keep the unrelated CLI commands fast — these pull in
    # the supabase client + numpy.
    from gecko_core.ingestion.embedder import embed
    from gecko_core.sessions.store import SessionStore

    vecs, _tokens = await embed([idea])
    if not vecs:
        return []
    store = SessionStore.from_env()
    rows = await store.retrieve_gecko_precedent(embedding=vecs[0], limit=top_k)
    return [r.model_dump(mode="json") for r in rows]


@click.command("precedents")
@click.argument("idea")
@click.option(
    "--top-k",
    "top_k",
    type=int,
    default=5,
    show_default=True,
    help="Max number of precedent rows to return.",
)
def precedents_cmd(idea: str, top_k: int) -> None:
    """List the top-K Gecko flywheel precedents for IDEA."""
    rows = asyncio.run(_fetch(idea, top_k))
    if not rows:
        console.print("[dim]No prior precedents found.[/dim]")
        return

    table = Table(title=f"Gecko precedents (top {len(rows)})")
    table.add_column("Verdict")
    table.add_column("Similarity", justify="right")
    table.add_column("Idea summary", overflow="fold")
    table.add_column("Comparables", overflow="fold")
    for r in rows:
        sim_val = r.get("similarity")
        sim_text = f"{float(sim_val):.3f}" if sim_val is not None else "-"
        comparables = r.get("key_comparables") or []
        comparables_text = ", ".join(str(c) for c in comparables)
        table.add_row(
            str(r.get("verdict", "")),
            sim_text,
            str(r.get("idea_summary", "")),
            comparables_text,
        )
    console.print(table)
