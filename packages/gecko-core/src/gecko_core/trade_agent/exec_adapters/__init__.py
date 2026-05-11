"""Execution rails — wallet/facilitator-neutral.

Three adapters today: OKX, SendAI, Backpack. The runtime dispatches by
name; nobody imports a specific module. Each adapter has a stub mode
(safe default; logs the intended call) and a live mode (executes).

Per Pattern C: live mode for a new adapter is gated on a recorded-fixture
contract test against the real facilitator. SendAI + Backpack ship as
stub-only until their contract tests land.

The stub/live mode toggle is env-driven per adapter
(``OKX_EXEC_MODE`` / ``SENDAI_EXEC_MODE`` / ``BACKPACK_EXEC_MODE``) so
operators can flip rails independently — mirrors the ``X402_MODE`` shape
in :mod:`gecko_core.payments.modes`.
"""

from __future__ import annotations

import logging
import os
from typing import Literal, Protocol

from gecko_core.trade_agent.exec_adapters.backpack import BackpackExecAdapter
from gecko_core.trade_agent.exec_adapters.okx import OKXExecAdapter
from gecko_core.trade_agent.exec_adapters.sendai import SendAIExecAdapter

logger = logging.getLogger(__name__)

ExecRail = Literal["okx", "okx-agentic-wallet", "sendai", "backpack", "spec-only"]
ExecMode = Literal["stub", "live"]


class ExecAdapterError(Exception):
    """Raised on a non-recoverable execution failure."""


class ExecAdapter(Protocol):
    """Wallet-neutral execution protocol — the runtime never imports a
    specific adapter module."""

    name: str
    mode: ExecMode

    async def submit(self, *, mint: str, side: str, size_usd: float) -> dict: ...


_ADAPTER_REGISTRY: dict[str, type] = {
    "okx": OKXExecAdapter,
    "okx-agentic-wallet": OKXExecAdapter,
    "sendai": SendAIExecAdapter,
    "backpack": BackpackExecAdapter,
}


def get_adapter(rail: str, *, mode: ExecMode | None = None) -> ExecAdapter:
    """Factory — return an adapter instance for ``rail``.

    Mode resolution order: explicit kwarg → per-rail env var → "stub".
    """
    rail_key = rail.lower()
    if rail_key not in _ADAPTER_REGISTRY:
        raise ExecAdapterError(
            f"unknown execution rail: {rail!r}. known: {sorted(_ADAPTER_REGISTRY)}"
        )

    if mode is None:
        env_var = {
            "okx": "OKX_EXEC_MODE",
            "okx-agentic-wallet": "OKX_EXEC_MODE",
            "sendai": "SENDAI_EXEC_MODE",
            "backpack": "BACKPACK_EXEC_MODE",
        }.get(rail_key, "EXEC_MODE")
        resolved = os.environ.get(env_var, "stub").lower()
        if resolved not in ("stub", "live"):
            raise ExecAdapterError(f"invalid {env_var}={resolved!r}; must be 'stub' or 'live'")
        mode = resolved  # type: ignore[assignment]

    cls = _ADAPTER_REGISTRY[rail_key]
    return cls(mode=mode)  # type: ignore[return-value]


__all__ = [
    "BackpackExecAdapter",
    "ExecAdapter",
    "ExecAdapterError",
    "ExecMode",
    "ExecRail",
    "OKXExecAdapter",
    "SendAIExecAdapter",
    "get_adapter",
]
