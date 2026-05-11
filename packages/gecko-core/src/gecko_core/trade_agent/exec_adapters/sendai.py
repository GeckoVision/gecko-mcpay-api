"""SendAI execution adapter — stub-only in v0.1.

Live mode raises :class:`NotImplementedError`. Per Pattern C, we ship
live wiring only after a recorded-fixture contract test against the
real SendAI facilitator endpoint. Today: no fixture, no live.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Literal

logger = logging.getLogger(__name__)


@dataclass
class SendAIExecAdapter:
    name: str = "sendai"
    mode: Literal["stub", "live"] = "stub"

    async def submit(self, *, mint: str, side: str, size_usd: float) -> dict[str, Any]:
        intent = {
            "rail": "sendai",
            "mint": mint,
            "side": side,
            "size_usd": size_usd,
        }
        if self.mode == "stub":
            logger.info(
                "exec.stub rail=sendai mint=%s side=%s size_usd=%s",
                mint,
                side,
                size_usd,
            )
            return {"mode": "stub", "ok": True, "intent": intent}

        raise NotImplementedError(
            "SendAI live exec is not wired yet — needs a recorded-fixture "
            "contract test against the SendAI facilitator before flipping. "
            "Set SENDAI_EXEC_MODE=stub to use safely."
        )


__all__ = ["SendAIExecAdapter"]
