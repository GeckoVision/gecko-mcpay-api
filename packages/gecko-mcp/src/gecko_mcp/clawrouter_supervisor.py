"""ClawRouter supervisor — auto-start the proxy under `gecko-mcp serve`.

Claude Code launches `gecko-mcp serve` whenever the user invokes a Gecko tool.
We use that lifecycle to also bring up ClawRouter (`localhost:8402`) on
demand: if the proxy is already reachable we leave it alone; otherwise we
spawn `npx @blockrun/clawrouter` as a child process and wait for it to
become ready before returning control.

Design choices:
- Best-effort. If ClawRouter can't start (no Node, no network, npm install
  fails), we yield without it. The orchestrator falls through to the
  ``GECKO_LLM_ENDPOINT`` env override (e.g. OpenAI direct).
- Subprocess inherits stdio so logs flow to the MCP server's stderr —
  useful for debugging, never logs secrets (ClawRouter doesn't print any).
- Tear-down on exit. The MCP server's ``serve()`` exits when Claude Code
  closes the stdio pipe; we cancel the child to avoid orphaned proxies.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import shutil
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx

logger = logging.getLogger(__name__)

CLAWROUTER_DEFAULT_URL = "http://localhost:8402/v1"
CLAWROUTER_PACKAGE = "@blockrun/clawrouter"
READINESS_TIMEOUT_S = 60
READINESS_POLL_INTERVAL_S = 1.0


def _endpoint() -> str:
    return os.environ.get("GECKO_LLM_ENDPOINT", CLAWROUTER_DEFAULT_URL)


async def _is_reachable(url: str, *, timeout: float = 2.0) -> bool:
    try:
        async with httpx.AsyncClient(timeout=timeout) as http:
            r = await http.get(f"{url}/models")
            return r.status_code == 200
    except Exception:
        return False


async def _wait_for_ready(url: str, *, deadline_s: int) -> bool:
    """Poll until the proxy answers /models or the deadline elapses."""
    for _ in range(deadline_s):
        if await _is_reachable(url):
            return True
        await asyncio.sleep(READINESS_POLL_INTERVAL_S)
    return False


@asynccontextmanager
async def warm_clawrouter() -> AsyncIterator[asyncio.subprocess.Process | None]:
    """Async context manager: ensure ClawRouter is up; tear down on exit.

    Yields the child Process when we spawned one (so the caller could log
    its pid), or None when the proxy was already reachable / couldn't be
    started. Either way, the body of the `async with` runs.
    """
    url = _endpoint()

    # 1. Already running? Use it as-is.
    if await _is_reachable(url):
        logger.info("clawrouter already reachable at %s — not starting", url)
        yield None
        return

    # 2. User overrode the endpoint? They want a different LLM provider —
    # don't try to start ClawRouter on top of that.
    if url != CLAWROUTER_DEFAULT_URL:
        logger.info(
            "GECKO_LLM_ENDPOINT=%s does not point at local ClawRouter; skipping warmup",
            url,
        )
        yield None
        return

    # 3. No Node available? Skip (orchestrator will surface the error per-call).
    if shutil.which("npx") is None:
        logger.warning(
            "npx not found — cannot start ClawRouter. Install Node 18+ or set "
            "GECKO_LLM_ENDPOINT to a working OpenAI-compatible endpoint."
        )
        yield None
        return

    # 4. Spawn it.
    logger.info("starting ClawRouter via `npx -y %s`", CLAWROUTER_PACKAGE)
    try:
        proc = await asyncio.create_subprocess_exec(
            "npx",
            "-y",
            CLAWROUTER_PACKAGE,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
    except Exception as exc:
        logger.warning("ClawRouter spawn failed: %s", exc)
        yield None
        return

    ready = await _wait_for_ready(url, deadline_s=READINESS_TIMEOUT_S)
    if not ready:
        logger.warning(
            "ClawRouter did not become reachable within %ds; the orchestrator "
            "will surface connection errors per request",
            READINESS_TIMEOUT_S,
        )
    else:
        logger.info("ClawRouter ready at %s (pid %s)", url, proc.pid)

    try:
        yield proc
    finally:
        if proc.returncode is None:
            logger.info("stopping ClawRouter (pid %s)", proc.pid)
            try:
                proc.terminate()
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except (TimeoutError, ProcessLookupError):
                with contextlib.suppress(ProcessLookupError):
                    proc.kill()


__all__ = ["warm_clawrouter"]
