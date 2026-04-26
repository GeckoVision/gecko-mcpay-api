"""Entry point for `gecko-mcp` command.

Subcommands:
    gecko-mcp serve [--env-file PATH]    — start MCP server over stdio
    gecko-mcp doctor                      — verify env vars + connectivity
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import click
from dotenv import load_dotenv

from gecko_mcp.server import serve

REQUIRED_ENV = [
    "OPENAI_API_KEY",
    "SUPABASE_URL",
    "SUPABASE_SERVICE_ROLE_KEY",
    "TAVILY_API_KEY",
]


@click.group()
def main() -> None:
    """Gecko MCP server."""


@main.command()
@click.option(
    "--env-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to .env file. Defaults to ~/.gecko/.env if present.",
)
def serve_cmd(env_file: Path | None) -> None:  # noqa: D401
    """Start the MCP server over stdio."""
    _load_env(env_file)
    asyncio.run(serve())


main.add_command(serve_cmd, name="serve")


@main.command()
def doctor() -> None:
    """Verify env vars and connectivity. Exit non-zero on any failure."""
    _load_env(None)

    failures: list[str] = []

    for var in REQUIRED_ENV:
        if not os.environ.get(var):
            failures.append(f"missing env var: {var}")

    mode = os.environ.get("X402_MODE", "stub")
    if mode not in ("stub", "live", "frames"):
        failures.append(f"X402_MODE must be 'stub', 'live', or 'frames', got {mode!r}")
    if mode == "live" and not os.environ.get("X402_FACILITATOR_URL"):
        failures.append("X402_MODE=live requires X402_FACILITATOR_URL")
    if mode == "frames" and not os.environ.get("FRAMES_API_KEY"):
        failures.append("X402_MODE=frames requires FRAMES_API_KEY")

    # TODO: probe Supabase + OpenAI + Tavily reachability

    if failures:
        click.secho("doctor: FAIL", fg="red", err=True)
        for f in failures:
            click.echo(f"  - {f}", err=True)
        sys.exit(1)

    click.secho("doctor: OK", fg="green")
    click.echo(f"  payments: {mode}")


def _load_env(env_file: Path | None) -> None:
    if env_file is not None:
        load_dotenv(env_file)
        return
    default = Path.home() / ".gecko" / ".env"
    if default.exists():
        load_dotenv(default)


if __name__ == "__main__":
    main()
