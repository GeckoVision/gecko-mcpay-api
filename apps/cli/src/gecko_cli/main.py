"""bb / gecko CLI — thin wrapper over gecko-core.

All business logic lives in `gecko_core`. This module:
  - parses CLI args
  - calls into gecko_core
  - renders results with rich
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import click
from dotenv import load_dotenv
from rich.console import Console

import gecko_core
from gecko_cli.render import render_ask_result, render_research_result, render_sources_table

console = Console()


@click.group()
@click.option(
    "--env-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to .env file. Defaults to ~/.gecko/.env if present.",
)
def main(env_file: Path | None) -> None:
    """Gecko — Builder Bootstrap Platform."""
    if env_file:
        load_dotenv(env_file)
    else:
        default = Path.home() / ".gecko" / ".env"
        if default.exists():
            load_dotenv(default)


@main.command()
@click.option("--idea", required=True, help="Plain-language startup idea.")
@click.option("--tier", type=click.Choice(["basic", "pro"]), default="basic")
@click.option("--urls", multiple=True, help="Optional seed URLs (repeatable).")
def research(idea: str, tier: str, urls: tuple[str, ...]) -> None:
    """Discover, index, generate. The main workflow."""
    result = asyncio.run(
        gecko_core.research(idea=idea, tier=tier, urls=list(urls) if urls else None)
    )
    render_research_result(console, result)


@main.command()
@click.argument("session_id")
@click.argument("question")
def ask(session_id: str, question: str) -> None:
    """Follow-up question against a session's knowledge base."""
    result = asyncio.run(gecko_core.ask(session_id=session_id, question=question))
    render_ask_result(console, result)


@main.command()
@click.argument("session_id")
def sources(session_id: str) -> None:
    """List indexed sources for a session."""
    result = asyncio.run(gecko_core.sources(session_id=session_id))
    render_sources_table(console, result)


if __name__ == "__main__":
    main()
