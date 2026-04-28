"""`gecko-mcp quickstart` — first-run bootstrap.

Walks a brand-new user from "I just installed gecko-mcp" to "I can run my
first research session" in one interactive command. Each step is idempotent:
re-running quickstart on a working install just confirms each piece is up.

Steps (in order):
    1. Wallet     — verify ~/.agentwallet/config.json (frames.ag) is connected
    2. LLM        — verify ClawRouter is reachable on localhost:8402, install
                    if missing, start if not running
    3. MCP        — register `gecko` with Claude Code (`claude mcp add ...`)
    4. Doctor     — run the full doctor check
    5. First run  — print the exact command to invoke from Claude Code

Each step prints a clear ✅/❌ and a one-liner remediation. We never log
secrets — apiTokens are read once, used in memory, never echoed.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time

import click
import httpx

from gecko_mcp.wallet import CONFIG_PATH

CLAWROUTER_URL = "http://localhost:8402/v1"
CLAWROUTER_BIN = "@blockrun/clawrouter"


def _ok(msg: str) -> None:
    click.secho(f"  ✅ {msg}", fg="green")


def _warn(msg: str) -> None:
    click.secho(f"  ⚠️  {msg}", fg="yellow")


def _fail(msg: str) -> None:
    click.secho(f"  ❌ {msg}", fg="red")


def _hdr(n: int, total: int, title: str) -> None:
    click.echo()
    click.secho(f"[{n}/{total}] {title}", bold=True)


def _check_wallet() -> bool:
    """Return True if frames.ag credentials are present and parseable."""
    if not CONFIG_PATH.exists():
        _fail(f"no frames.ag credentials at {CONFIG_PATH}")
        click.echo()
        click.echo("    To connect, paste this into Claude Code:")
        click.secho(
            "      Read https://frames.ag/skill.md and follow the instructions "
            "to join AgentWallet.",
            bold=True,
        )
        click.echo()
        click.echo("    Then re-run `gecko-mcp quickstart`.")
        return False
    try:
        cfg = json.loads(CONFIG_PATH.read_text())
    except Exception as exc:
        _fail(f"could not parse {CONFIG_PATH}: {exc}")
        return False
    username = cfg.get("username") or "<missing>"
    sol = cfg.get("solanaAddress") or "<missing>"
    _ok(f"connected as @{username}")
    click.echo(f"     solana: {sol}")
    click.echo(f"     fund:   https://frames.ag/u/{username}")
    return True


def _clawrouter_reachable() -> bool:
    try:
        r = httpx.get(f"{CLAWROUTER_URL}/models", timeout=2.0)
        r.raise_for_status()
    except Exception:
        return False
    return True


def _check_llm(*, auto_install: bool) -> bool:
    """Verify ClawRouter is reachable; offer to install/start if not."""
    if _clawrouter_reachable():
        _ok(f"ClawRouter reachable on {CLAWROUTER_URL}")
        return True

    if not shutil.which("npx"):
        _fail("ClawRouter not reachable AND `npx` is missing")
        click.echo("    Install Node.js (>=18) first: https://nodejs.org")
        return False

    _warn(f"ClawRouter not reachable on {CLAWROUTER_URL}")
    if auto_install:
        proceed = True
    else:
        proceed = click.confirm(
            f"    Run `npx -y {CLAWROUTER_BIN}` to install + start it now?",
            default=True,
        )
    if not proceed:
        click.echo("    Skipped — start it later with `gecko-mcp llm start`.")
        return False

    click.echo("    Starting ClawRouter (this may take ~30s on first run)...")
    proc = subprocess.Popen(
        ["npx", "-y", CLAWROUTER_BIN],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    # Poll for readiness — npx download + boot takes 10-60s on first run.
    for _ in range(60):
        time.sleep(1)
        if _clawrouter_reachable():
            _ok(f"ClawRouter reachable on {CLAWROUTER_URL} (pid {proc.pid})")
            click.echo("     (running in background; stop with `kill <pid>` if needed)")
            return True
    _fail("ClawRouter did not become reachable within 60s")
    click.echo("    Try `gecko-mcp llm start` in a separate terminal and re-run quickstart.")
    return False


def _check_mcp_registration() -> bool:
    """Best-effort check that `gecko` is registered with Claude Code."""
    if not shutil.which("claude"):
        _warn("`claude` CLI not found — skipping MCP registration check")
        click.echo("    Install Claude Code: https://docs.anthropic.com/claude/claude-code")
        return False
    try:
        out = subprocess.run(
            ["claude", "mcp", "list"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception as exc:
        _warn(f"could not query Claude Code MCP list: {exc}")
        return False

    if "gecko" in out.stdout:
        _ok("gecko MCP server registered with Claude Code")
        return True

    _warn("gecko MCP server not registered yet")
    click.echo("    Run:")
    click.secho("      claude mcp add gecko -- gecko-mcp serve", bold=True)
    click.echo("    Then re-run `gecko-mcp quickstart` to verify.")
    return False


def _check_gecko_api() -> bool:
    url = os.environ.get("GECKO_API_URL", "https://api.geckovision.tech").rstrip("/")
    try:
        r = httpx.get(f"{url}/healthz", timeout=3.0)
        r.raise_for_status()
    except Exception as exc:
        _warn(f"gecko-api not reachable at {url} ({exc.__class__.__name__})")
        click.echo(f"    Set GECKO_API_URL or start the API. Defaulted to {url}.")
        return False
    _ok(f"gecko-api reachable at {url}")
    return True


@click.command()
@click.option(
    "--auto-install",
    is_flag=True,
    default=False,
    help="Install/start ClawRouter without prompting (for scripted setups).",
)
def quickstart(auto_install: bool) -> None:
    """First-run bootstrap. Walks you from install to first research call."""
    click.secho("Gecko quickstart", bold=True)
    click.echo("Verifying each piece of the stack is ready.")
    click.echo()

    total = 4
    ok_count = 0

    _hdr(1, total, "Wallet (frames.ag AgentWallet)")
    if _check_wallet():
        ok_count += 1

    _hdr(2, total, "LLM router (ClawRouter)")
    if _check_llm(auto_install=auto_install):
        ok_count += 1

    _hdr(3, total, "Claude Code MCP registration")
    if _check_mcp_registration():
        ok_count += 1

    _hdr(4, total, "gecko-api connectivity")
    if _check_gecko_api():
        ok_count += 1

    click.echo()
    if ok_count == total:
        click.secho("🎉  All checks passed. You're ready to run your first session.", fg="green")
        click.echo()
        click.echo("In Claude Code, ask:")
        click.secho("  Use gecko_research to validate: a hotel guide for Brazil", bold=True)
        click.echo()
        click.echo("Then inspect economics:")
        click.secho("  gecko-mcp economics <session_id>", bold=True)
        sys.exit(0)

    click.secho(
        f"  {ok_count}/{total} checks passed. Address the failures above and re-run.",
        fg="yellow",
    )
    sys.exit(1)


__all__ = ["quickstart"]
