"""Backpack execution adapter — stub-only in v0.1.

Mirrors :mod:`.sendai` exactly. Live mode raises until we ship a
contract test against the Backpack facilitator.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Literal

logger = logging.getLogger(__name__)


@dataclass
class BackpackExecAdapter:
    name: str = "backpack"
    mode: Literal["stub", "live"] = "stub"

    async def submit(self, *, mint: str, side: str, size_usd: float) -> dict[str, Any]:
        intent = {
            "rail": "backpack",
            "mint": mint,
            "side": side,
            "size_usd": size_usd,
        }
        if self.mode == "stub":
            logger.info(
                "exec.stub rail=backpack mint=%s side=%s size_usd=%s",
                mint,
                side,
                size_usd,
            )
            return {"mode": "stub", "ok": True, "intent": intent}

        raise NotImplementedError(
            "Backpack live exec is not wired yet — needs a recorded-fixture "
            "contract test against the Backpack facilitator before flipping. "
            "Set BACKPACK_EXEC_MODE=stub to use safely."
        )


__all__ = ["BackpackExecAdapter"]
