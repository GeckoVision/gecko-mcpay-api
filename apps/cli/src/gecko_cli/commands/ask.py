"""`bb ask` — grounded follow-up against a session's knowledge base."""

from __future__ import annotations

import asyncio

import click
import gecko_core
from rich.console import Console

from gecko_cli._render_compat import render_ask_result

console = Console()


@click.command("ask")
@click.argument("session_id")
@click.argument("question")
def ask_cmd(session_id: str, question: str) -> None:
    """Ask a follow-up grounded in the session's KB."""
    result = asyncio.run(gecko_core.ask(session_id=session_id, question=question))
    render_ask_result(console, result)
