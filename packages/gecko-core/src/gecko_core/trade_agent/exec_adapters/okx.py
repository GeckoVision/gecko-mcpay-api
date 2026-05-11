"""OKX execution adapter — shells ``onchainos dex-swap``.

v0.1 wraps the OKX onchainos CLI. Stub mode logs the intended invocation
without spawning; live mode shells out and parses stdout. Both modes
write an audit-log entry via the runtime journal (caller responsibility).

The shell-out shape mirrors the ``okx-dex-swap`` peer skill: the live
binary returns a JSON receipt on stdout when it succeeds.

Pattern B avoidance: live mode is not stubbed in code — it really runs
the binary — but the contract test (SE-4 ticket follow-up) replays a
recorded fixture against a fake ``onchainos`` shim so we don't burn real
gas in CI.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from dataclasses import dataclass
from typing import Any, Literal

logger = logging.getLogger(__name__)


@dataclass
class OKXExecAdapter:
    """Shell-based OKX adapter."""

    name: str = "okx"
    mode: Literal["stub", "live"] = "stub"
    binary: str = "onchainos"
    timeout_s: float = 30.0

    async def submit(self, *, mint: str, side: str, size_usd: float) -> dict[str, Any]:
        """Submit a swap. Returns the parsed receipt dict.

        Stub mode returns a synthetic receipt with ``mode='stub'`` and
        does NOT spawn the binary. Live mode requires the binary on
        PATH; raises :class:`FileNotFoundError` if missing.
        """
        intent = {
            "rail": "okx",
            "mint": mint,
            "side": side,
            "size_usd": size_usd,
        }

        if self.mode == "stub":
            logger.info("exec.stub rail=okx mint=%s side=%s size_usd=%s", mint, side, size_usd)
            return {"mode": "stub", "ok": True, "intent": intent}

        # live
        if shutil.which(self.binary) is None:
            raise FileNotFoundError(f"OKX exec live mode needs '{self.binary}' on PATH")

        cmd = [
            self.binary,
            "dex-swap",
            "--mint",
            mint,
            "--side",
            side,
            "--size-usd",
            str(size_usd),
            "--json",
        ]
        logger.info("exec.live rail=okx cmd=%s", " ".join(cmd))
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self.timeout_s)
        except TimeoutError:
            proc.kill()
            raise

        if proc.returncode != 0:
            raise RuntimeError(
                f"onchainos dex-swap failed rc={proc.returncode} "
                f"stderr={stderr.decode(errors='replace')[:500]}"
            )

        try:
            receipt = json.loads(stdout.decode())
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"onchainos dex-swap returned non-JSON: {stdout[:200]!r}") from exc

        receipt.setdefault("mode", "live")
        receipt.setdefault("intent", intent)
        return receipt


__all__ = ["OKXExecAdapter"]
