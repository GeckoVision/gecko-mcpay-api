"""`gecko-mcp economics <session_id>` — print per-session unit economics.

Hits gecko-api's free `GET /sessions/{id}/economics` endpoint and renders the
breakdown: what we charged (`price_usd`) vs what we actually spent (LLM,
embeddings, Tavily, Deepgram), with `margin_usd` as the bottom line.

Useful on devnet where prices are symbolic but costs are real — the margin
column tells you whether mainnet pricing will hold up.
"""

from __future__ import annotations

import os
import sys

import click
import httpx

DEFAULT_API_URL = "https://api.geckovision.tech"


def _api_url() -> str:
    return os.environ.get("GECKO_API_URL", DEFAULT_API_URL).rstrip("/")


def _fmt_usd(v: float | None) -> str:
    if v is None:
        return "—"
    return f"${v:>10.6f}"


@click.command()
@click.argument("session_id")
def economics(session_id: str) -> None:
    """Print the economics row for SESSION_ID (price, costs, margin)."""
    url = f"{_api_url()}/sessions/{session_id}/economics"
    try:
        r = httpx.get(url, timeout=10.0)
        r.raise_for_status()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            click.secho(f"session {session_id} not found", fg="red", err=True)
            sys.exit(2)
        click.secho(f"gecko-api returned {exc.response.status_code}", fg="red", err=True)
        sys.exit(1)
    except httpx.HTTPError as exc:
        click.secho(f"gecko-api unreachable at {url}: {exc}", fg="red", err=True)
        sys.exit(1)

    body = r.json()
    price = body.get("price_usd")
    cost_total = body.get("cost_total_usd")
    margin = body.get("margin_usd")
    tx = body.get("x402_tx_signature") or "—"

    click.echo(f"session    {session_id}")
    click.echo(f"price      {_fmt_usd(price)}")
    click.echo("costs:")
    click.echo(f"  llm      {_fmt_usd(body.get('cost_llm_usd'))}")
    click.echo(f"  embed    {_fmt_usd(body.get('cost_embed_usd'))}")
    click.echo(f"  tavily   {_fmt_usd(body.get('cost_tavily_usd'))}")
    click.echo(f"  deepgram {_fmt_usd(body.get('cost_deepgram_usd'))}")
    click.echo("  ───────────────────")
    click.echo(f"  total    {_fmt_usd(cost_total)}")

    margin_color = "green" if (margin or 0) >= 0 else "red"
    click.secho(f"margin     {_fmt_usd(margin)}", fg=margin_color, bold=True)
    click.echo(f"x402 tx    {tx}")
