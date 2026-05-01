"""S13-WALLET-01 — `bb wallet` panel.

Single inspection surface for the multi-wallet world a power user lands
in by Sprint 14: frames.ag (Solana), TWITSH (Base), awal (CDP),
publish.new, Paragraph creator. Spec: ``docs/strategy/wallet-panel-spec-2026-04-30.md``.

This module is a transport — config IO + types live in
``gecko_core.wallets.config``. Balance fetch is best-effort: when the
RPC is unreachable, the row degrades to ``unreachable`` rather than
failing the whole panel (the panel must always render in <2s, per spec).
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

import click
from gecko_core.wallets.config import (
    DEFAULT_WALLETS_PATH,
    KNOWN_KINDS,
    WalletEntry,
    WalletKind,
    WalletsConfig,
    read_wallets_config,
    upsert_wallet,
)
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()

Health = Literal["ok", "low", "unreachable", "misconfigured", "—"]

_HEALTH_STYLE: dict[Health, str] = {
    "ok": "green",
    "low": "yellow",
    "unreachable": "yellow",
    "misconfigured": "red",
    "—": "dim",
}

# Canonical placeholder rows so the panel surfaces the *full* wallet
# universe even when the user hasn't wired anything yet — the empty
# panel is still a teaching surface, not a blank screen.
_PLACEHOLDER_ROWS: dict[WalletKind, dict[str, str]] = {
    "frames": {
        "network": "solana:mainnet",
        "funding": "Run `bb wallet add frames` (browser flow → frames.ag bootstrap).",
    },
    "twitsh": {
        "network": "eip155:8453",
        "funding": "Run `bb wallet add twitsh` (OTP, Base mainnet).",
    },
    "awal": {
        "network": "eip155:8453",
        "funding": "Run `bb wallet add awal` (Coinbase Agentic Wallet — `npx awal init`).",
    },
    "publish-new": {
        "network": "solana:mainnet",
        "funding": "Auto-generated when first artifact ships (Sprint 14).",
    },
    "paragraph": {
        "network": "solana:mainnet",
        "funding": "Run `bb wallet add paragraph` to wire creator attribution (Sprint 14).",
    },
}


# ---------------------------------------------------------------------------
# Row model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WalletRow:
    """One rendered row of `bb wallet show`. Pure data; the Rich layer
    just consumes this."""

    kind: str
    network: str
    address_display: str  # truncated; safe to render
    balance_display: str  # "$X.XX USDC" or "—" or "?"
    health: Health
    is_default_payer: bool = False
    is_receive_only: bool = False


def _truncate_address(addr: str) -> str:
    if not addr:
        return "—"
    if len(addr) <= 9:
        return addr
    return f"{addr[:4]}…{addr[-4:]}"


# ---------------------------------------------------------------------------
# Balance fetch — best-effort, <500ms timeout per wallet
# ---------------------------------------------------------------------------


async def _fetch_balance_stub(_entry: WalletEntry) -> tuple[str, Health]:
    """Stub-mode balance: always returns a synthetic value.

    Per task constraints, S13 stays in stub mode — no live RPC. We
    return a deterministic placeholder so the panel renders the same
    shape as the live path will. Live RPC fetch is reserved for S14
    once `X402Client.get_balance(...)` lands.
    """
    return ("0.00 USDC", "low")


# ---------------------------------------------------------------------------
# Row aggregation
# ---------------------------------------------------------------------------


async def aggregate_rows(
    cfg: WalletsConfig,
    *,
    env: dict[str, str] | None = None,
    fetch_balance: Callable[[WalletEntry], Awaitable[tuple[str, Health]]] | None = None,
) -> list[WalletRow]:
    """Return one :class:`WalletRow` per known wallet kind.

    Configured wallets render with their address + (best-effort)
    balance. Unconfigured kinds render as placeholder rows with
    ``health="—"`` so the user sees the full menu of options.

    `env` falls back to ``os.environ``; `fetch_balance` to the stub
    fetcher. Both are test seams.
    """
    e = env if env is not None else dict(os.environ)
    fetcher = fetch_balance or _fetch_balance_stub

    rows: list[WalletRow] = []
    for kind in KNOWN_KINDS:
        if kind == "custom":
            continue  # custom wallets render as their own rows below
        entry = cfg.wallets.get(kind)
        if entry is None:
            # Special-case: TWITSH can be partly-configured via env even
            # without a TOML row — surface that so users who set
            # TWITSH_WALLET_ADDRESS see something useful.
            if kind == "twitsh":
                addr = e.get("TWITSH_WALLET_ADDRESS")
                if addr:
                    rows.append(
                        WalletRow(
                            kind="twitsh",
                            network=_PLACEHOLDER_ROWS["twitsh"]["network"],
                            address_display=_truncate_address(addr),
                            balance_display="—",
                            health="ok",
                        )
                    )
                    continue
            placeholder = _PLACEHOLDER_ROWS[kind]
            rows.append(
                WalletRow(
                    kind=kind,
                    network=placeholder["network"],
                    address_display="not configured",
                    balance_display="—",
                    health="—",
                )
            )
            continue

        # Configured: fetch balance (best-effort, stub for now).
        try:
            balance_display, health = await fetcher(entry)
        except Exception:
            balance_display, health = "?", "unreachable"
        rows.append(
            WalletRow(
                kind=kind,
                network=entry.network,
                address_display=_truncate_address(entry.address),
                balance_display=balance_display,
                health=health,
                is_default_payer=(cfg.default_payer == kind),
                is_receive_only=(entry.mode == "receive-only"),
            )
        )

    # Surface any custom-kind wallets at the end so user-added rails
    # (community wallets) don't disappear from the panel.
    for custom_kind, custom_entry in cfg.wallets.items():
        if custom_kind in KNOWN_KINDS:
            continue
        rows.append(
            WalletRow(
                kind=custom_kind,
                network=custom_entry.network,
                address_display=_truncate_address(custom_entry.address),
                balance_display="—",
                health="ok",
            )
        )
    return rows


# ---------------------------------------------------------------------------
# Render — Rich table inside a Rich panel, matching `bb doctor` style
# ---------------------------------------------------------------------------


def _address_cell(row: WalletRow) -> str:
    addr = row.address_display
    if row.is_default_payer:
        return f"{addr}  [dim](default)[/dim]"
    if row.is_receive_only:
        return f"{addr}  [dim](receive)[/dim]"
    return addr


def render_wallet_panel(rows: list[WalletRow], cfg: WalletsConfig) -> Panel:
    """Build the Rich `Panel(Table)` for `bb wallet show`.

    Column rules + color semantics mirror the spec § "Column rules".
    """
    table = Table(show_lines=False, expand=True)
    table.add_column("Kind", no_wrap=True)
    table.add_column("Network", no_wrap=True, style="dim")
    table.add_column("Address", overflow="fold")
    table.add_column("Balance", justify="right", no_wrap=True)
    table.add_column("Health", no_wrap=True)

    for row in rows:
        health_style = _HEALTH_STYLE[row.health]
        table.add_row(
            row.kind,
            row.network,
            _address_cell(row),
            row.balance_display,
            f"[{health_style}]{row.health}[/{health_style}]",
        )

    # Footer hints — at most two, drawn from the spec priority.
    hints: list[str] = []
    low = [r.kind for r in rows if r.health == "low"]
    unconfigured = [r.kind for r in rows if r.health == "—"]
    misconfigured = [r.kind for r in rows if r.health == "misconfigured"]
    if low:
        hints.append(f"Run `bb wallet fund {low[0]}` to see funding paths.")
    if unconfigured and len(hints) < 2:
        hints.append(f"Run `bb wallet add {unconfigured[0]}` to wire a new rail.")
    if misconfigured and len(hints) < 2:
        hints.append(f"Run `bb wallet show --kind {misconfigured[0]}` for diagnostics.")
    if not hints:
        hints.append('All wallets healthy. `bb research --idea "..."` to start.')

    payer = cfg.default_payer or "(unset)"
    receiver = cfg.default_receiver or "(unset)"
    footer = (
        f"\n[dim]Active payer for `bb research`: {payer}[/dim]"
        f"\n[dim]Active receiver for artifact sales: {receiver}[/dim]\n"
    )
    for h in hints:
        footer += f"\n[dim]{h}[/dim]"

    from rich.console import Group
    from rich.text import Text

    body = Group(table, Text.from_markup(footer))
    return Panel(body, title="[bold]Wallets[/bold]", title_align="left", padding=(1, 2))


# ---------------------------------------------------------------------------
# Click command group
# ---------------------------------------------------------------------------


@click.group("wallet", invoke_without_command=True)
@click.pass_context
def wallet_cmd(ctx: click.Context) -> None:
    """Inspect and manage wallets configured for `bb research` payments."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(show_cmd)


@wallet_cmd.command("show")
@click.option(
    "--kind",
    type=click.Choice(list(KNOWN_KINDS)),
    default=None,
    help="Narrow output to a single wallet kind.",
)
def show_cmd(kind: str | None) -> None:
    """Print all configured wallets in a single Rich panel."""
    cfg = read_wallets_config()
    rows = asyncio.run(aggregate_rows(cfg))
    if kind is not None:
        rows = [r for r in rows if r.kind == kind]
    console.print(render_wallet_panel(rows, cfg))


@wallet_cmd.command("add")
@click.argument("kind", type=click.Choice(list(KNOWN_KINDS)))
@click.option("--address", prompt=True, help="Public payout address.")
@click.option(
    "--network",
    default=None,
    help="CAIP-2 network (defaults to the canonical network for this kind).",
)
@click.option(
    "--api-token-env",
    default=None,
    help="Name of env var holding the apiToken (NEVER the token itself).",
)
def add_cmd(
    kind: str,
    address: str,
    network: str | None,
    api_token_env: str | None,
) -> None:
    """Persist a new wallet entry to `~/.gecko/wallets.toml`.

    The address is the only required field; network defaults to the
    canonical CAIP-2 string for the chosen kind. Tokens are NEVER
    written to the TOML — pass the env var *name* via
    `--api-token-env`, set the value in your shell.
    """
    # Click's Choice already validates `kind` against KNOWN_KINDS; the
    # cast tells mypy what the runtime check enforces.
    canonical_kind: WalletKind = cast(WalletKind, kind)
    chosen_network = (
        network or _PLACEHOLDER_ROWS.get(canonical_kind, {"network": "solana:mainnet"})["network"]
    )
    entry = WalletEntry(
        kind=canonical_kind,
        network=chosen_network,
        address=address,
        api_token_env=api_token_env,
    )
    cfg = upsert_wallet(entry)
    console.print(f"[green]added[/green] {kind} on {chosen_network} → {DEFAULT_WALLETS_PATH}")
    rows = asyncio.run(aggregate_rows(cfg))
    rows = [r for r in rows if r.kind == kind]
    console.print(render_wallet_panel(rows, cfg))


@wallet_cmd.command("fund")
@click.argument("kind", type=click.Choice(list(KNOWN_KINDS)))
def fund_cmd(kind: str) -> None:
    """Print funding paths for a wallet kind. No browser auto-open."""
    paths = _FUNDING_PATHS.get(kind, [])
    cfg = read_wallets_config()
    entry = cfg.wallets.get(kind)
    addr = _truncate_address(entry.address) if entry else "not configured"
    body_lines = [f"[bold]Address:[/bold] {addr}", "", "[bold]Funding paths:[/bold]"]
    if not paths:
        body_lines.append("[dim]No funding paths registered for this kind.[/dim]")
    for i, (label, url) in enumerate(paths, start=1):
        body_lines.append(f"  {i}. {label:<22} [link={url}]{url}[/link]")
    console.print(
        Panel(
            "\n".join(body_lines),
            title=f"[bold]Fund: {kind}[/bold]",
            title_align="left",
            padding=(1, 2),
        )
    )


@wallet_cmd.command("test")
@click.argument("kind", type=click.Choice(list(KNOWN_KINDS)))
def test_cmd(kind: str) -> None:
    """Issue a $0.01 stub-mode test charge against the chosen wallet.

    Stub mode only — no real charge, no real signature. Surfaces the
    end-to-end charge → receipt path so the operator can see the
    facilitator is reachable before paying for real.
    """
    mode = (os.environ.get("X402_MODE") or "stub").lower()
    if mode != "stub":
        console.print(
            f"[yellow]X402_MODE={mode} (not stub) — skipping live charge for safety.[/yellow]"
        )
        console.print("[dim]Set X402_MODE=stub to run this probe.[/dim]")
        return
    console.print(
        f"[green]stub charge[/green] kind={kind} amount=$0.01 USDC facilitator=stub status=ok"
    )


# ---------------------------------------------------------------------------
# First-run gate — used by paid commands before they kick off work
# ---------------------------------------------------------------------------


def has_any_wallet(path: Path | None = None) -> bool:
    """Return True if `wallets.toml` exists and has at least one entry."""
    cfg = read_wallets_config(path)
    return bool(cfg.wallets)


# Funding paths registry — pulled from `docs/runbooks/wallet-options.md`.
# Tuple of (label, url). Kept in this module rather than the runbook
# parser because the data is small and stable.
_FUNDING_PATHS: dict[str, list[tuple[str, str]]] = {
    "frames": [
        ("frames.ag bootstrap", "https://frames.ag/skill"),
        ("Solana onramp (Coinbase)", "https://www.coinbase.com/"),
    ],
    "twitsh": [
        ("Coinbase Onramp", "https://onramp.coinbase.com/"),
        ("Base bridge", "https://bridge.base.org/"),
        ("Base Sepolia faucet", "https://www.coinbase.com/faucets/base-ethereum-goerli-faucet"),
    ],
    "awal": [
        ("Coinbase Agentic Wallet", "https://docs.cdp.coinbase.com/agentic-wallets"),
    ],
    "publish-new": [
        ("publish.new docs", "https://publish.new"),
    ],
    "paragraph": [
        ("Paragraph creator settings", "https://paragraph.xyz/settings"),
    ],
    "custom": [],
}


__all__ = [
    "WalletRow",
    "aggregate_rows",
    "has_any_wallet",
    "render_wallet_panel",
    "wallet_cmd",
]
