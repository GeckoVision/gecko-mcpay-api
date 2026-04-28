"""Demo agent — calls gecko-api, handles x402, signs payment, retries.

This is the canonical shape any third-party agent (Cursor, LangGraph, MCPay
competitor) can copy. It talks ONLY to the API over HTTP — never imports
gecko_core. That's the whole point of the v2 architecture.

On stage:

    gecko-demo-agent research "a hotel guide for Brazil"

Stub mode (fallback if devnet flakes):

    X402_MODE=stub gecko-demo-agent research "..." --api-url http://localhost:8000
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any

import click
import httpx
from gecko_mcp.wallet import get_keypair_for_signing
from x402 import x402Client
from x402.http.x402_http_client import x402HTTPClient
from x402.mechanisms.svm.exact import ExactSvmClientScheme
from x402.mechanisms.svm.signers import KeypairSigner

DEFAULT_API_URL = "http://localhost:8000"
EXPLORER_TX_URL = "https://explorer.solana.com/tx/{sig}?cluster={cluster}"


def _build_x402_client() -> x402HTTPClient:
    """Wire a keypair signer into the canonical x402 HTTP client.

    Same code path runs in stub and live mode — the stub facilitator on the
    server side accepts any well-formed signed payload, so we don't branch.
    """
    keypair = get_keypair_for_signing()
    signer = KeypairSigner(keypair)
    client = x402Client()
    scheme = ExactSvmClientScheme(signer=signer)
    # Register every network identifier the API might advertise. The API uses
    # `solana-devnet` / `solana-mainnet`; the `solana:*` wildcard covers any
    # CAIP-2 form a future facilitator might return.
    client.register("solana-devnet", scheme)
    client.register("solana-mainnet", scheme)
    client.register("solana:*", scheme)
    return x402HTTPClient(client)


def _explorer_url(tx_signature: str, network: str) -> str:
    cluster = "devnet" if "devnet" in network else "mainnet-beta"
    return EXPLORER_TX_URL.format(sig=tx_signature, cluster=cluster)


def _extract_tx_signature(response: httpx.Response) -> str | None:
    """The facilitator settle response is base64-JSON in `X-PAYMENT-RESPONSE`."""
    header = response.headers.get("X-PAYMENT-RESPONSE") or response.headers.get(
        "x-payment-response"
    )
    if not header:
        return None
    try:
        import base64

        decoded = json.loads(base64.b64decode(header).decode())
        sig = decoded.get("transaction") or decoded.get("tx_signature")
        return str(sig) if sig else None
    except Exception:
        return None


async def _research(idea: str, tier: str, api_url: str) -> int:
    route = "/research" if tier == "basic" else "/research/pro"
    body: dict[str, Any] = {"idea": idea, "tier": tier, "auto_approve": True}

    click.echo(f'Asking gecko-api: "{idea}"')

    async with httpx.AsyncClient(timeout=300.0) as http:
        first = await http.post(f"{api_url}{route}", json=body)

        if first.status_code == 402:
            # Decode the PAYMENT-REQUIRED header so we can show the operator
            # what we're about to spend before we sign anything.
            x402_http = _build_x402_client()
            try:
                requirements = x402_http.get_payment_required_response(
                    first.headers.get, first.content or None
                )
                opt = requirements.accepts[0]
                # `amount` is V2-only; V1's PaymentRequirementsV1 uses `max_amount_required`.
                amount_str = (
                    getattr(opt, "amount", None) or getattr(opt, "max_amount_required", None) or "0"
                )
                price_display = f"{int(amount_str) / 1_000_000:.2f} USDC"
                click.echo(f"402 received. Paying {price_display} on Solana ({opt.network})...")
            except Exception as exc:
                click.echo(f"could not decode payment requirements: {exc}", err=True)
                return 1

            payment_headers, _ = await x402_http.handle_402_response(
                dict(first.headers), first.content or None
            )
            second = await http.post(f"{api_url}{route}", json=body, headers=payment_headers)
        else:
            second = first

        if second.status_code >= 300:
            click.echo(
                f"request failed: HTTP {second.status_code} {second.text[:200]}",
                err=True,
            )
            return 1

        click.echo("Documents received.")
        click.echo(json.dumps(second.json(), indent=2))

        tx_sig = _extract_tx_signature(second)
        if tx_sig:
            network = os.environ.get("X402_NETWORK", "solana-devnet")
            # Stub-mode signatures are clearly marked (`stub-...`); skip the
            # explorer link in that case — it would 404 on stage.
            if not tx_sig.startswith("stub-"):
                click.echo(f"Tx: {_explorer_url(tx_sig, network)}")
            else:
                click.echo(f"Tx: {tx_sig} (stub)")
    return 0


async def _ask(session_id: str, question: str, api_url: str) -> int:
    async with httpx.AsyncClient(timeout=120.0) as http:
        r = await http.post(f"{api_url}/sessions/{session_id}/ask", json={"question": question})
        if r.status_code >= 300:
            click.echo(f"ask failed: HTTP {r.status_code} {r.text[:200]}", err=True)
            return 1
        click.echo(json.dumps(r.json(), indent=2))
    return 0


@click.group()
def cli() -> None:
    """Gecko demo agent — x402 reference client."""


@cli.command()
@click.argument("idea")
@click.option("--tier", type=click.Choice(["basic", "pro"]), default="basic")
@click.option("--api-url", default=DEFAULT_API_URL, show_default=True)
def research(idea: str, tier: str, api_url: str) -> None:
    """Run a Builder Bootstrap research session (handles x402 payment)."""
    code = asyncio.run(_research(idea=idea, tier=tier, api_url=api_url))
    sys.exit(code)


@cli.command()
@click.argument("session_id")
@click.argument("question")
@click.option("--api-url", default=DEFAULT_API_URL, show_default=True)
def ask(session_id: str, question: str, api_url: str) -> None:
    """Ask a follow-up question against an existing paid session (free)."""
    code = asyncio.run(_ask(session_id=session_id, question=question, api_url=api_url))
    sys.exit(code)


if __name__ == "__main__":
    cli()
