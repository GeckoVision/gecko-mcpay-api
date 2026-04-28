"""LLM provider facade for gecko-mcp — ClawRouter (v3).

ClawRouter is BlockRunAI's local OpenAI-compatible smart router. It runs as
a daemon on `localhost:8402` and pays per-call via x402 USDC. We don't host
it; we shell out to it.

Install path for non-OpenClaw agents (Claude Code, Cursor, VS Code, etc.):
    npx @blockrun/clawrouter

The OpenClaw curl|bash form is intentionally NOT used here.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

import click
import httpx

CLAWROUTER_DEFAULT_URL = "http://localhost:8402/v1"
CLAWROUTER_DEFAULT_MODEL = "blockrun/auto"
CLAWROUTER_INSTALL_CMD = ["npx", "-y", "@blockrun/clawrouter"]


def _endpoint() -> str:
    return os.environ.get("GECKO_LLM_ENDPOINT", CLAWROUTER_DEFAULT_URL)


def _has_npx() -> bool:
    return shutil.which("npx") is not None


@click.group()
def llm() -> None:
    """Manage the LLM router (ClawRouter) that backs gecko_research."""


@llm.command()
def install() -> None:
    """Install ClawRouter via npx (Claude Code path).

    Runs `npx -y @blockrun/clawrouter` interactively. The first invocation
    downloads + sets up the proxy and a local BIP-39 keypair; subsequent
    calls (`llm start`) start the proxy.
    """
    if not _has_npx():
        click.secho(
            "❌ npx not found. Install Node.js (>=18) first: https://nodejs.org",
            fg="red",
            err=True,
        )
        sys.exit(1)
    click.echo("Installing ClawRouter via npx...")
    click.echo(f"  $ {' '.join(CLAWROUTER_INSTALL_CMD)}")
    try:
        subprocess.run(CLAWROUTER_INSTALL_CMD, check=True)
    except subprocess.CalledProcessError as exc:
        click.secho(f"ClawRouter install failed (exit {exc.returncode})", fg="red", err=True)
        sys.exit(1)


@llm.command()
def start() -> None:
    """Start the ClawRouter proxy (foreground).

    For background/daemon mode, see ClawRouter's own slash commands once
    installed (`/start`, `/stop`).
    """
    if not _has_npx():
        click.secho("❌ npx not found. Run `gecko-mcp llm install` first.", fg="red", err=True)
        sys.exit(1)
    try:
        subprocess.run(CLAWROUTER_INSTALL_CMD, check=True)
    except subprocess.CalledProcessError as exc:
        sys.exit(exc.returncode)


@llm.command()
def status() -> None:
    """Show whether the local proxy is reachable and which models are available."""
    url = _endpoint()
    try:
        r = httpx.get(f"{url}/models", timeout=5.0)
        r.raise_for_status()
    except httpx.HTTPError as exc:
        click.secho(f"❌ ClawRouter not reachable at {url}: {exc}", fg="red", err=True)
        click.echo("   Run `gecko-mcp llm start` (or `gecko-mcp llm install` first).")
        sys.exit(1)

    body = r.json()
    models = body.get("data", [])
    click.secho(f"✅ proxy on {url} ({len(models)} models)", fg="green")
    default = os.environ.get("GECKO_DEFAULT_MODEL", CLAWROUTER_DEFAULT_MODEL)
    click.echo(f"   default model: {default}")


@llm.command()
@click.option(
    "--model", default=None, help="Override model (default: GECKO_DEFAULT_MODEL or blockrun/auto)"
)
def test(model: str | None) -> None:
    """Send a tiny prompt through ClawRouter and print which model handled it."""
    url = _endpoint()
    chosen = model or os.environ.get("GECKO_DEFAULT_MODEL", CLAWROUTER_DEFAULT_MODEL)
    payload = {
        "model": chosen,
        "messages": [{"role": "user", "content": "Reply with only the word: pong"}],
    }
    try:
        r = httpx.post(
            f"{url}/chat/completions",
            json=payload,
            headers={"Authorization": "Bearer x402"},
            timeout=60.0,
        )
        r.raise_for_status()
    except httpx.HTTPError as exc:
        click.secho(f"❌ test request failed: {exc}", fg="red", err=True)
        sys.exit(1)
    body = r.json()
    content = body.get("choices", [{}])[0].get("message", {}).get("content", "")
    routed_model = body.get("model", chosen)
    click.secho(f"✅ {routed_model}: {content.strip()}", fg="green")


@llm.command()
@click.option("--free-only", is_flag=True, default=False)
def models(free_only: bool) -> None:
    """List available models. Use --free-only to filter NVIDIA-hosted free tier."""
    url = _endpoint()
    try:
        r = httpx.get(f"{url}/models", timeout=10.0)
        r.raise_for_status()
    except httpx.HTTPError as exc:
        click.secho(f"❌ ClawRouter not reachable at {url}: {exc}", fg="red", err=True)
        sys.exit(1)
    data = r.json().get("data", [])
    for m in data:
        mid = m.get("id", "?")
        if free_only and not mid.startswith("nvidia/"):
            continue
        click.echo(mid)


@llm.command(name="doctor")
def llm_doctor() -> None:
    """Verify the proxy is up and a free model can complete a request."""
    url = _endpoint()
    try:
        r = httpx.get(f"{url}/models", timeout=5.0)
        r.raise_for_status()
    except httpx.HTTPError as exc:
        click.secho(f"❌ proxy not reachable at {url}: {exc}", fg="red", err=True)
        sys.exit(1)
    click.secho(f"✅ proxy on {url}", fg="green")

    free_model = os.environ.get("GECKO_FREE_MODEL", "nvidia/gpt-oss-120b")
    try:
        r = httpx.post(
            f"{url}/chat/completions",
            json={
                "model": free_model,
                "messages": [{"role": "user", "content": "say hi"}],
            },
            headers={"Authorization": "Bearer x402"},
            timeout=60.0,
        )
        r.raise_for_status()
    except httpx.HTTPError as exc:
        click.secho(f"⚠️  free model `{free_model}` failed: {exc}", fg="yellow", err=True)
        sys.exit(1)
    click.secho(f"✅ free model `{free_model}` works", fg="green")
    body = json.dumps(r.json(), indent=2)[:200]
    click.echo(f"   sample: {body}...")
