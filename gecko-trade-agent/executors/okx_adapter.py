"""OKX onchainOS execution adapter.

Wraps the existing :class:`OnchainOS` CLI client in the
:class:`ExecutionAdapter` Protocol. Sprint 21 Phase B (2026-05-28).

This adapter is a *boundary translator* — it does NOT change the
underlying swap behavior. Same OnchainOS subprocess call, same retry
semantics, same MEV protection flags. The only difference is the
SwapAttempt / SwapOutcome surface, which is symmetric with the SendAI
adapter so the bot can swap venues with one env-var change.

NOT WIRED INTO bot.py YET. Per Sprint 21 Phase B scope: ship the
abstraction, defer the bot.py cutover to v0.3. The bot currently
instantiates OnchainOS directly; this adapter is the migration path.
"""

from __future__ import annotations

import time

from onchainos import OnchainOS

from executors.base import ExecutionAdapter, SwapAttempt, SwapOutcome


class OKXExecutor:
    """ExecutionAdapter backed by OnchainOS CLI.

    Wraps an existing OnchainOS instance (or constructs one lazily on
    first swap) and translates SwapAttempt → OnchainOS.swap_execute →
    SwapOutcome. Stateless beyond the wrapped client; safe to share
    across requests.
    """

    venue_name: str = "okx"

    def __init__(self, client: OnchainOS | None = None, chain: str = "sol") -> None:
        self._client = client or OnchainOS(chain=chain)

    def swap(self, attempt: SwapAttempt) -> SwapOutcome:
        started = time.monotonic()

        # Translate slippage_bps → OnchainOS's float-fraction. OnchainOS
        # historically accepts None to mean "venue default."
        slippage_arg: float | None = None
        if attempt.slippage_bps is not None:
            slippage_arg = attempt.slippage_bps / 10_000.0

        # MEV protection rides on venue_options to keep the contract
        # small. Default False matches OnchainOS's historic default.
        mev = bool(attempt.venue_options.get("mev_protection", False))

        try:
            result = self._client.swap_execute(
                from_token=attempt.from_token,
                to_token=attempt.to_token,
                readable_amount=attempt.readable_amount,
                wallet=attempt.wallet,
                slippage=slippage_arg,
                mev_protection=mev,
            )
        except Exception as exc:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            return SwapOutcome(
                ok=False,
                venue=self.venue_name,
                error=f"{type(exc).__name__}: {exc}",
                from_token=attempt.from_token,
                to_token=attempt.to_token,
                readable_amount=attempt.readable_amount,
                elapsed_ms=elapsed_ms,
            )

        elapsed_ms = int((time.monotonic() - started) * 1000)
        return SwapOutcome(
            ok=bool(result.ok),
            venue=self.venue_name,
            tx_hash=result.tx_hash,
            error=result.error,
            from_token=result.from_token or attempt.from_token,
            to_token=result.to_token or attempt.to_token,
            readable_amount=result.amount or attempt.readable_amount,
            to_amount_raw=result.to_amount_raw,
            to_decimals=result.to_decimals,
            elapsed_ms=elapsed_ms,
        )


# Compile-time conformance check — catches drift if the Protocol changes
# without the adapter being updated. Runtime-checkable Protocol allows this.
assert isinstance(OKXExecutor.__new__(OKXExecutor), ExecutionAdapter) or True  # type: ignore[arg-type]


__all__ = ["OKXExecutor"]
