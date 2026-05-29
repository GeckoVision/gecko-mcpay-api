"""Execution adapters — venue-agnostic swap surface.

Sprint 21 Phase B (2026-05-28). Today the bot's swap path is hardwired
to :class:`OnchainOS` (OKX onchainOS CLI). This package isolates a
:class:`ExecutionAdapter` Protocol so the bot can plug in alternative
execution venues — SendAI Solana Agent Kit, Backpack, direct Jupiter,
custom — without changing the bot's decision loop.

USAGE (v0.3, not yet wired)::

    from executors import build_executor
    executor = build_executor()  # reads EXECUTION_ADAPTER env var
    result = executor.swap(from_token="USDC...", to_token="JTO...",
                           readable_amount="45", wallet=WALLET_ADDRESS)

Current bot.py STILL imports OnchainOS directly per Sprint 21 Phase B
scope discipline: ship the abstraction surface + OKX wrapper + SendAI
stub, defer the bot.py cutover to v0.3 once a real SendAI integration
is built. The abstraction is the contract; the migration path is the
follow-up.
"""

from __future__ import annotations

from executors.base import ExecutionAdapter, SwapAttempt, SwapOutcome
from executors.okx_adapter import OKXExecutor
from executors.sendai_adapter import SendAIExecutor, SendAINotConfiguredError

__all__ = [
    "ExecutionAdapter",
    "OKXExecutor",
    "SendAIExecutor",
    "SendAINotConfiguredError",
    "SwapAttempt",
    "SwapOutcome",
]
