"""`bb earnings` — surface publish.new artifact sales for the user's wallet.

Sprint 14 S14-PUB-02. Reads `GET /api/artifact?wallet=<addr>` from
publish.new (no auth needed for read) and renders a Rich table summarizing
each artifact's slug, title, price, transaction count, and gross volume in
USD.

The publish.new read API is unauthenticated — anyone can query the per-
artifact ledger for a given wallet. We deliberately do NOT cross-check
against an internal `publish_artifacts` table in V1 because the canonical
ledger lives on publish.new (and on-chain). The CLI is a transport.

Stub-mode behavior: when ``X402_MODE=stub`` and the user has not pointed
``PUBLISH_NEW_BASE_URL`` at a real endpoint, we still attempt the GET so
the founder sees a clean "no artifacts yet" empty-state. We never invent
fake sales rows in stub mode — the empty state is the correct surface.
"""

from __future__ import annotations

import asyncio
import os
from decimal import Decimal
from typing import Any

import click
import httpx
from gecko_core.payments.publish_new import (
    DEFAULT_PUBLISH_NEW_BASE_URL,
)
from rich.console import Console
from rich.table import Table

console = Console()


def _resolve_wallet(override: str | None) -> str:
    """Resolve the wallet to query.

    Order: explicit ``--wallet`` flag, then ``GECKO_WALLET_ADDRESS_BASE``.
    No silent fallback — empty / missing → the caller surfaces a clear
    pointer to ``bb wallet add publish-new``.
    """
    candidate = (override or os.environ.get("GECKO_WALLET_ADDRESS_BASE", "")).strip()
    return candidate


def _resolve_base_url() -> str:
    return os.environ.get("PUBLISH_NEW_BASE_URL") or DEFAULT_PUBLISH_NEW_BASE_URL


async def _fetch_artifacts(wallet: str, base_url: str) -> list[dict[str, Any]]:
    """GET /api/artifact?wallet=<addr> from publish.new.

    Returns the raw list-of-dicts payload. Failures (network, 4xx/5xx,
    non-JSON) raise — the caller renders a clear error and exits non-zero.
    """
    async with httpx.AsyncClient(
        base_url=base_url,
        timeout=10.0,
        headers={
            "Accept": "application/json",
            "User-Agent": "gecko-cli/0.1 (+https://geckovision.tech)",
        },
    ) as client:
        resp = await client.get("/api/artifact", params={"wallet": wallet})
    if resp.status_code >= 400:
        raise RuntimeError(f"publish.new returned HTTP {resp.status_code}: {resp.text[:200]}")
    try:
        body = resp.json()
    except ValueError as exc:
        raise RuntimeError(f"publish.new returned non-JSON: {exc}") from exc

    # Accept a few common envelope shapes — the read API isn't strictly
    # specced and we don't want to brittle-couple to one.
    if isinstance(body, list):
        return [item for item in body if isinstance(item, dict)]
    if isinstance(body, dict):
        for key in ("artifacts", "results", "items", "data"):
            value = body.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _rows_from_artifacts(artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize the upstream rows into a stable shape for rendering.

    Tolerates camelCase / snake_case variation; missing fields render as
    "—" / 0 / 0.00. Computes the gross volume locally so a future schema
    drift on the wire doesn't silently break the totals row.
    """
    rows: list[dict[str, Any]] = []
    for raw in artifacts:
        slug = str(raw.get("slug") or raw.get("artifact_slug") or "—")
        title = str(raw.get("title") or "—")
        try:
            price = Decimal(str(raw.get("price_usd") or raw.get("price") or "0"))
        except Exception:
            price = Decimal("0")
        tx_count = int(raw.get("transaction_count") or raw.get("tx_count") or raw.get("sales") or 0)
        # Prefer the upstream-supplied gross when present (in case there
        # are pricing changes mid-window); fall back to price * tx_count.
        gross_raw = raw.get("gross_volume_usd") or raw.get("volume_usd")
        if gross_raw is not None:
            try:
                gross = Decimal(str(gross_raw))
            except Exception:
                gross = price * Decimal(tx_count)
        else:
            gross = price * Decimal(tx_count)
        rows.append(
            {
                "slug": slug,
                "title": title,
                "price": price,
                "tx_count": tx_count,
                "gross": gross,
            }
        )
    return rows


def _render_table(wallet: str, rows: list[dict[str, Any]]) -> Table:
    table = Table(
        title=f"publish.new earnings — {wallet}",
        title_justify="left",
        show_lines=False,
    )
    table.add_column("slug", style="bold")
    table.add_column("title", overflow="fold")
    table.add_column("price", justify="right")
    table.add_column("tx", justify="right")
    table.add_column("gross", justify="right")

    if not rows:
        table.add_row("—", "no artifacts yet", "—", "0", "$0.00")
        return table

    total_tx = 0
    total_gross = Decimal("0")
    for row in rows:
        table.add_row(
            row["slug"],
            row["title"],
            f"${row['price']:.2f}",
            str(row["tx_count"]),
            f"${row['gross']:.2f}",
        )
        total_tx += int(row["tx_count"])
        total_gross += row["gross"]

    table.add_section()
    table.add_row(
        "[bold]TOTAL[/bold]",
        "",
        "",
        f"[bold]{total_tx}[/bold]",
        f"[bold]${total_gross:.2f}[/bold]",
    )
    return table


@click.command("earnings")
@click.option(
    "--wallet",
    "wallet",
    default=None,
    help=("Base 0x wallet address to query. Defaults to GECKO_WALLET_ADDRESS_BASE."),
)
def earnings_cmd(wallet: str | None) -> None:
    """Show publish.new artifact sales for a wallet (S14-PUB-02)."""
    resolved = _resolve_wallet(wallet)
    if not resolved:
        console.print(
            "[red]bb earnings:[/red] no wallet configured. Run "
            "`bb wallet add publish-new` or pass `--wallet 0x...`."
        )
        return

    base = _resolve_base_url()

    try:
        artifacts = asyncio.run(_fetch_artifacts(resolved, base))
    except (httpx.HTTPError, RuntimeError) as exc:
        console.print(f"[red]bb earnings:[/red] {exc}")
        return

    rows = _rows_from_artifacts(artifacts)
    table = _render_table(resolved, rows)
    console.print(table)
    if not rows:
        console.print(
            '[dim]No artifacts yet. Run `bb research --idea "..." --publish` '
            "to mint your first one.[/dim]"
        )
