"""SendAI Solana Agent Kit execution adapter (stub).

Sprint 21 Phase B (2026-05-28). The adapter surface is real; the actual
HTTP wire to SendAI is deferred to v0.3.

WHY A STUB INSTEAD OF A FULL IMPLEMENTATION

SendAI integration requires:
  - SendAI API key / RPC endpoint setup
  - Jupiter route discovery via the Agent Kit SDK
  - Solana wallet keypair management (different from OKX's TEE pattern)
  - End-to-end live test on Solana devnet/mainnet

That's a research-+-integration ticket, not a stub-in-an-afternoon. We
ship the adapter surface so:
  1. The bot's future migration to a venue-neutral executor is unblocked
     — the contract is fixed, only the implementation is missing.
  2. The skill manifest can honestly say "two venues supported" with
     SendAI marked as v0.3 in the roadmap.
  3. A user who sets EXECUTION_ADAPTER=sendai gets a clear, actionable
     error (SendAINotConfiguredError with the migration path spelled
     out) instead of a silent failure or a surprise OKX call.

HOW TO COMPLETE THIS ADAPTER

Replace ``_NOT_IMPLEMENTED_REASON`` raise with:
  1. Build a Jupiter quote via SendAI SDK
  2. Sign + submit the swap tx
  3. Wait for on-chain confirmation
  4. Parse the realized amounts from the tx receipt
  5. Return SwapOutcome with venue="sendai" + tx_hash + to_amount_raw

The contract guarantees match OKX's adapter — the bot doesn't care
which venue executed the swap, only that the SwapOutcome carries the
realized fill so PnL is computed from real on-chain data.
"""

from __future__ import annotations

import os

from executors.base import SwapAttempt, SwapOutcome

_NOT_IMPLEMENTED_REASON = (
    "SendAI Solana Agent Kit execution adapter is a v0.3 deliverable. "
    "The adapter surface (SwapAttempt/SwapOutcome contract) is shipped; "
    "the HTTP wire to SendAI is not. To enable: set SENDAI_API_KEY in "
    ".env, run `python -m executors.sendai_adapter --setup`, and follow "
    "the migration notes in executors/sendai_adapter.py docstring. Until "
    "then, use EXECUTION_ADAPTER=okx (the default)."
)


class SendAINotConfiguredError(RuntimeError):
    """Raised when SendAIExecutor.swap() is called before the v0.3 wire
    lands OR before SENDAI_API_KEY is set. Carries the actionable
    migration path in the error message."""


class SendAIExecutor:
    """ExecutionAdapter backed by SendAI Solana Agent Kit.

    Stub implementation — see module docstring. Constructing the adapter
    succeeds (the contract is real); calling :meth:`swap` raises
    :class:`SendAINotConfiguredError` until v0.3 wires the HTTP layer.
    """

    venue_name: str = "sendai"

    def __init__(self, api_key: str | None = None, rpc_url: str | None = None) -> None:
        # Accept config but don't validate yet — when the real wire
        # lands, this is where credentials get checked.
        self._api_key = api_key or os.environ.get("SENDAI_API_KEY") or ""
        self._rpc_url = rpc_url or os.environ.get("SENDAI_RPC_URL") or ""

    def swap(self, attempt: SwapAttempt) -> SwapOutcome:
        """Stub — raises SendAINotConfiguredError until v0.3.

        The signature is committed to the contract; only the body
        changes when the integration lands. Returning a SwapOutcome
        with ok=False here would silently hide the gap from callers,
        so we raise instead — loud failure is the correct UX for an
        unimplemented venue.
        """
        raise SendAINotConfiguredError(_NOT_IMPLEMENTED_REASON)


__all__ = ["SendAIExecutor", "SendAINotConfiguredError"]
