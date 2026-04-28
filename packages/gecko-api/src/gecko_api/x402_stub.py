"""Stub facilitator client for local dev and tests.

When ``X402_MODE=stub`` we don't talk to a real facilitator. This client
implements the same async ``FacilitatorClient`` protocol the x402 library
expects (verify / settle / get_supported) and auto-confirms anything thrown
at it. The middleware code path is identical to live mode — only the client
swaps — so a live deploy doesn't reveal any new control flow.

Stub-mode tx signatures are clearly marked so they never pass for on-chain
artifacts (`stub-<hex>`). They get persisted to ``sessions.x402_tx_signature``
just like live signatures so downstream code can be agnostic.
"""

from __future__ import annotations

import uuid

from x402.http.facilitator_client_base import FacilitatorClient
from x402.schemas import (
    PaymentPayload,
    PaymentRequirements,
    SettleResponse,
    SupportedKind,
    SupportedResponse,
    VerifyResponse,
)
from x402.schemas.v1 import PaymentPayloadV1, PaymentRequirementsV1


class StubFacilitatorClient(FacilitatorClient):
    """Always-succeed facilitator. NOT for production."""

    def __init__(self, network: str = "solana-devnet") -> None:
        self._network = network

    async def verify(
        self,
        payload: PaymentPayload | PaymentPayloadV1,
        requirements: PaymentRequirements | PaymentRequirementsV1,
    ) -> VerifyResponse:
        return VerifyResponse(is_valid=True, payer="stub-payer")

    async def settle(
        self,
        payload: PaymentPayload | PaymentPayloadV1,
        requirements: PaymentRequirements | PaymentRequirementsV1,
    ) -> SettleResponse:
        return SettleResponse(
            success=True,
            payer="stub-payer",
            transaction=f"stub-{uuid.uuid4().hex}",
            network=self._network,
        )

    def get_supported(self) -> SupportedResponse:
        # Mirror the route's scheme/network so x402ResourceServer initializes
        # cleanly without ever calling a real /supported endpoint.
        return SupportedResponse(
            kinds=[
                SupportedKind(
                    x402_version=2,
                    scheme="exact",
                    network=self._network,
                ),
            ],
        )


__all__ = ["StubFacilitatorClient"]
