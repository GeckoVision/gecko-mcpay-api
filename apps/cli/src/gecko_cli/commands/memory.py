"""`gecko memory` — save/recall/search the native decision-memory layer."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import click
from rich.console import Console
from rich.table import Table

console = Console()


def _parse_scope(raw: str) -> tuple[str, str]:
    """Parse `--scope project:<id>` / `session:<id>` / `user:<id>`."""
    if ":" not in raw:
        raise click.BadParameter("scope must be of the form '<type>:<id>' (e.g. project:abc-123)")
    type_, id_ = raw.split(":", 1)
    type_ = type_.strip().lower()
    id_ = id_.strip()
    if type_ not in ("project", "session", "user"):
        raise click.BadParameter(f"scope type must be project|session|user, got {type_!r}")
    if not id_:
        raise click.BadParameter("scope id must be non-empty")
    return type_, id_


async def _do_save(
    *,
    scope_type: str,
    scope_id: str,
    entry_type: str,
    value: dict[str, Any],
    key: str | None,
) -> str:
    from gecko_core.memory import (
        MemoryEntryType,
        MemoryScope,
        save,
    )

    new_id = await save(
        MemoryScope(type=scope_type, id=scope_id),  # type: ignore[arg-type]
        MemoryEntryType(entry_type),
        value,
        key=key,
    )
    return str(new_id)


async def _do_recall(
    *,
    scope_type: str,
    scope_id: str,
    entry_type: str | None,
    key: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    from gecko_core.memory import MemoryEntryType, MemoryScope, recall

    et = MemoryEntryType(entry_type) if entry_type else None
    rows = await recall(
        MemoryScope(type=scope_type, id=scope_id),  # type: ignore[arg-type]
        entry_type=et,
        key=key,
        limit=limit,
    )
    return [
        {
            "id": str(r.id),
            "entry_type": r.entry_type.value,
            "key": r.key,
            "value": r.value,
            "tx_signature": r.tx_signature,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


async def _do_search(
    *,
    scope_type: str,
    scope_id: str,
    query: str,
    top_k: int,
) -> list[dict[str, Any]]:
    from gecko_core.memory import MemoryScope, search

    matches = await search(
        MemoryScope(type=scope_type, id=scope_id),  # type: ignore[arg-type]
        query,
        top_k=top_k,
    )
    return [
        {
            "id": str(entry.id),
            "entry_type": entry.entry_type.value,
            "key": entry.key,
            "value": entry.value,
            "similarity": sim,
            "created_at": entry.created_at.isoformat(),
        }
        for entry, sim in matches
    ]


@click.group("memory")
def memory_cmd() -> None:
    """Native Gecko decision-memory layer (S5-MEM-03)."""


@memory_cmd.command("save")
@click.option("--scope", "scope_raw", required=True, help="<type>:<id>, e.g. project:abc-123")
@click.option(
    "--type",
    "entry_type",
    required=True,
    type=click.Choice(
        [
            "verdict_received",
            "scaffold_generated",
            "plan_advised",
            "advisor_voiced",
            "pulse_run",
            "feature_shipped",
            "user_note",
        ]
    ),
)
@click.option("--value", "value_raw", required=True, help="JSON-encoded payload")
@click.option("--key", "key", default=None)
def memory_save_cmd(scope_raw: str, entry_type: str, value_raw: str, key: str | None) -> None:
    """Save a memory entry."""
    scope_type, scope_id = _parse_scope(scope_raw)
    try:
        value = json.loads(value_raw)
    except json.JSONDecodeError as exc:
        raise click.BadParameter(f"--value must be valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise click.BadParameter("--value must decode to a JSON object")
    new_id = asyncio.run(
        _do_save(
            scope_type=scope_type,
            scope_id=scope_id,
            entry_type=entry_type,
            value=value,
            key=key,
        )
    )
    console.print(f"[green]saved[/green] {new_id}")


@memory_cmd.command("recall")
@click.option("--scope", "scope_raw", required=True)
@click.option("--type", "entry_type", default=None)
@click.option("--key", "key", default=None)
@click.option("--limit", default=20, show_default=True)
def memory_recall_cmd(scope_raw: str, entry_type: str | None, key: str | None, limit: int) -> None:
    """Recall recent memory entries for a scope."""
    scope_type, scope_id = _parse_scope(scope_raw)
    rows = asyncio.run(
        _do_recall(
            scope_type=scope_type,
            scope_id=scope_id,
            entry_type=entry_type,
            key=key,
            limit=limit,
        )
    )
    if not rows:
        console.print("[dim]No memory entries found.[/dim]")
        return
    table = Table(title=f"memory ({scope_type}:{scope_id})")
    table.add_column("Created", overflow="fold")
    table.add_column("Type")
    table.add_column("Key")
    table.add_column("Value", overflow="fold")
    for r in rows:
        table.add_row(
            r["created_at"],
            r["entry_type"],
            r["key"] or "-",
            json.dumps(r["value"], default=str)[:200],
        )
    console.print(table)


@memory_cmd.command("search")
@click.option("--scope", "scope_raw", required=True)
@click.option("--top-k", "top_k", default=5, show_default=True)
@click.argument("query")
def memory_search_cmd(scope_raw: str, top_k: int, query: str) -> None:
    """Cosine-similarity search within a scope."""
    scope_type, scope_id = _parse_scope(scope_raw)
    rows = asyncio.run(
        _do_search(
            scope_type=scope_type,
            scope_id=scope_id,
            query=query,
            top_k=top_k,
        )
    )
    if not rows:
        console.print("[dim]No matches.[/dim]")
        return
    table = Table(title=f"memory search ({scope_type}:{scope_id})")
    table.add_column("Sim", justify="right")
    table.add_column("Type")
    table.add_column("Created")
    table.add_column("Value", overflow="fold")
    for r in rows:
        table.add_row(
            f"{r['similarity']:.3f}",
            r["entry_type"],
            r["created_at"],
            json.dumps(r["value"], default=str)[:200],
        )
    console.print(table)
