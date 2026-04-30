"""`gecko project` — per-project budget envelopes (Phase B5 v2).

A "project" is a named budget bucket. v2 architecture:

* All payments flow from the user's frames.ag main wallet.
* The CLI talks to ``gecko-api`` over HTTP using bearer auth from
  ``~/.agentwallet/config.json``. **No Supabase creds required on the
  client side** — that's the v2 fix relative to v1, where the CLI
  imported ``SessionStore`` directly.
* Project state lives both locally (``<cwd>/.gecko/project.json``) and
  server-side (``projects`` table). The local file is a convenience
  cache so the MCP tool / ``bb research`` can auto-attach a project_id.

v3 (post-Shipathon): replace the local ``wallet_address: null`` and the
``paid_from_wallet_address = "<u>:main"`` markers with real Privy-managed
wallets. The CLI surface is identical.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import click
from gecko_mcp.api_client import GeckoAPIClient, GeckoAPIError
from rich.console import Console
from rich.table import Table

console = Console()

LOCAL_CONFIG_DIRNAME = ".gecko"
LOCAL_CONFIG_FILENAME = "project.json"
AGENT_WALLET_CONFIG = Path.home() / ".agentwallet" / "config.json"


# ---------------------------------------------------------------------------
# Local project.json helpers
# ---------------------------------------------------------------------------


def _local_config_path(cwd: Path | None = None) -> Path:
    base = cwd or Path.cwd()
    return base / LOCAL_CONFIG_DIRNAME / LOCAL_CONFIG_FILENAME


def read_local_project(cwd: Path | None = None) -> dict[str, Any] | None:
    """Read `<cwd>/.gecko/project.json` if present, else None."""
    path = _local_config_path(cwd)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())  # type: ignore[no-any-return]
    except (OSError, json.JSONDecodeError):
        return None


def write_local_project(data: dict[str, Any], cwd: Path | None = None) -> Path:
    path = _local_config_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")
    return path


def read_frames_username() -> str:
    """Pull the frames.ag username from `~/.agentwallet/config.json`.

    Aborts the command with a friendly error if the user hasn't run the
    frames.ag connect flow yet — there is no project without a wallet.
    """
    if not AGENT_WALLET_CONFIG.exists():
        click.secho(
            f"No frames.ag credentials at {AGENT_WALLET_CONFIG}.\n"
            "Run `gecko-mcp wallet new` (delegates to frames.ag's skill) and try again.",
            fg="red",
            err=True,
        )
        sys.exit(1)
    try:
        cfg = json.loads(AGENT_WALLET_CONFIG.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        click.secho(f"Could not read {AGENT_WALLET_CONFIG}: {exc}", fg="red", err=True)
        sys.exit(1)
    username = cfg.get("username")
    if not isinstance(username, str) or not username:
        click.secho(
            f"{AGENT_WALLET_CONFIG} is missing a username — re-run frames.ag connect.",
            fg="red",
            err=True,
        )
        sys.exit(1)
    return username


def _client() -> GeckoAPIClient:
    """Construct an API client wired to the user's wallet config.

    Tests patch this seam to inject a mocked client. The real client
    reads bearer + username from ``~/.agentwallet/config.json`` lazily.
    """
    return GeckoAPIClient()


def _abort_no_wallet() -> None:
    click.secho(
        f"No frames.ag credentials at {AGENT_WALLET_CONFIG}.\n"
        "Run `gecko-mcp wallet new` (delegates to frames.ag's skill) and try again.",
        fg="red",
        err=True,
    )
    sys.exit(1)


def _run(coro: Any) -> Any:
    """asyncio.run wrapper that maps wallet-missing GeckoAPIError to a friendly exit."""
    try:
        return asyncio.run(coro)
    except GeckoAPIError as exc:
        msg = str(exc)
        if "no frames.ag credentials" in msg:
            _abort_no_wallet()
        click.secho(f"API error: {msg}", fg="red", err=True)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Click command group
# ---------------------------------------------------------------------------


@click.group("project")
def project_cmd() -> None:
    """Per-project budget envelopes (v2: HTTP-only, no Supabase on the client)."""


@project_cmd.command("init")
@click.argument("name")
@click.option("--budget", type=float, required=True, help="Project budget in USD.")
def project_init(name: str, budget: float) -> None:
    """Create a new project + write `<cwd>/.gecko/project.json`."""
    username = read_frames_username()

    async def _do() -> dict[str, Any]:
        async with _client() as api:
            return await api.create_project(name=name, budget_usd=budget)

    created = _run(_do())
    project_id = str(created.get("project_id") or created.get("id") or "")

    config = {
        "project_id": project_id,
        "name": name,
        "frames_username": username,
        "wallet_address": None,  # v1/v2: paid from main wallet
        "wallet_provider": "frames-policy",
        "budget_usd": budget,
        "created_at": datetime.now(tz=UTC).isoformat(),
    }
    path = write_local_project(config)

    console.print(f"[green]Created project[/green] [bold]{name}[/bold]")
    console.print(f"  id:      {project_id}")
    console.print(f"  budget:  ${budget:.2f}")
    console.print(f"  config:  {path}")
    console.print()
    console.print(
        f"[dim]v2: payments flow from your main frames.ag wallet — fund at "
        f"https://frames.ag/u/{username}[/dim]"
    )


@project_cmd.command("list")
def project_list() -> None:
    """List all projects for the current frames.ag user."""
    username = read_frames_username()

    async def _do() -> list[dict[str, Any]]:
        async with _client() as api:
            return await api.list_projects()

    items = _run(_do())

    table = Table(title=f"Projects (@{username})")
    table.add_column("Name", style="bold")
    table.add_column("Budget", justify="right")
    table.add_column("Spent", justify="right")
    table.add_column("Remaining", justify="right")
    table.add_column("Sessions", justify="right")

    if not items:
        console.print(
            "[dim]No projects yet. Create one with[/dim] "
            "[bold]gecko project init <name> --budget 5.00[/bold]"
        )
        return

    for it in items:
        budget_val = it.get("budget_usd")
        spent_val = float(it.get("total_spent_usd") or 0)
        budget = f"${float(budget_val):.2f}" if budget_val is not None else "-"
        spent = f"${spent_val:.4f}"
        if budget_val is None:
            remaining = "-"
        else:
            remaining_val = float(budget_val) - spent_val
            color = "red" if remaining_val < 0 else "green"
            remaining = f"[{color}]${remaining_val:.4f}[/{color}]"
        table.add_row(
            str(it.get("name", "")),
            budget,
            spent,
            remaining,
            str(it.get("sessions_count") or 0),
        )

    console.print(table)


@project_cmd.command("show")
@click.argument("name")
def project_show(name: str) -> None:
    """Show details for one project: id, budget, spent, last 5 sessions."""
    username = read_frames_username()

    async def _do() -> dict[str, Any]:
        async with _client() as api:
            return await api.get_project(name)

    try:
        record = _run(_do())
    except SystemExit:
        raise
    if record is None:
        click.secho(f"No project named {name!r} for @{username}.", fg="red", err=True)
        sys.exit(1)

    pid = record.get("project_id") or record.get("id") or ""
    console.print(f"[bold]{record.get('name', name)}[/bold]")
    console.print(f"  id:        {pid}")
    budget_val = record.get("budget_usd")
    if budget_val is not None:
        console.print(f"  budget:    ${float(budget_val):.2f}")
    else:
        console.print("  budget:    -")
    spent = float(record.get("total_spent_usd") or 0)
    console.print(f"  spent:     ${spent:.4f}")
    remaining = record.get("budget_remaining_usd")
    if remaining is not None:
        color = "red" if float(remaining) < 0 else "green"
        console.print(f"  remaining: [{color}]${float(remaining):.4f}[/{color}]")
    wallet = record.get("wallet_address")
    console.print(f"  wallet:    {wallet or '<main wallet (v2)>'}")

    sessions = record.get("sessions") or []
    if not sessions:
        console.print("[dim]No sessions yet.[/dim]")
        return

    table = Table(title="Recent sessions")
    table.add_column("Session ID", style="dim")
    table.add_column("Idea", overflow="fold")
    table.add_column("Status")
    table.add_column("Cost", justify="right")
    for s in sessions:
        table.add_row(
            str(s.get("id", ""))[:8],
            str(s.get("idea") or "")[:60],
            str(s.get("status") or ""),
            f"${float(s.get('cost_total_usd') or 0):.4f}",
        )
    console.print(table)


@project_cmd.command("delete")
@click.argument("name")
@click.option("--yes", is_flag=True, help="Skip confirmation prompt.")
def project_delete(name: str, yes: bool) -> None:
    """Soft-delete a project. Sessions remain but are detached from the project."""
    from gecko_cli._prompt import assume_yes

    username = read_frames_username()
    # Honor top-level --yes / --non-interactive in addition to the
    # subcommand-local --yes flag.
    if not assume_yes(local=yes):
        click.confirm(f"Delete project {name!r} for @{username}?", abort=True)

    async def _do() -> None:
        async with _client() as api:
            await api.delete_project(name)

    _run(_do())
    console.print(f"[green]Deleted[/green] [bold]{name}[/bold]")


# ---------------------------------------------------------------------------
# Helper used by `bb research --project` wiring
# ---------------------------------------------------------------------------


def resolve_project_id(explicit: str | None = None, cwd: Path | None = None) -> UUID | None:
    """Resolve which project_id to attach to an outgoing request.

    Priority:
        1. explicit --project flag (UUID or name matching local config)
        2. <cwd>/.gecko/project.json's project_id
    """
    if explicit:
        try:
            return UUID(explicit)
        except ValueError:
            local = read_local_project(cwd)
            if local and local.get("name") == explicit:
                pid = local.get("project_id")
                if isinstance(pid, str):
                    return UUID(pid)
            return None

    local = read_local_project(cwd)
    if not local:
        return None
    pid = local.get("project_id")
    if isinstance(pid, str):
        try:
            return UUID(pid)
        except ValueError:
            return None
    return None
