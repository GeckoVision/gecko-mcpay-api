"""Payment domain types.

Decimals only for money. Never floats.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from gecko_core.models import Tier


class PaymentIntent(BaseModel):
    """A request to charge for a session. `intent_id` is the idempotency key."""

    intent_id: str = Field(..., min_length=1)
    session_id: UUID
    tier: Tier
    amount_usd: Decimal

    model_config = {"frozen": True}


class PaymentResult(BaseModel):
    """The outcome of `X402Client.charge`. Mirror shape across stub/live/frames."""

    intent_id: str
    status: Literal["success", "failed"]
    tx_signature: str | None = None
    error: str | None = None

    model_config = {"frozen": True}


class PaymentRequiredError(Exception):
    """Raised when the payment gate fails. Halts the workflow before ingestion."""

    def __init__(
        self,
        session_id: UUID,
        tier: Tier,
        intent_id: str,
        reason: str,
    ) -> None:
        super().__init__(
            f"HTTP 402: payment required for session {session_id} "
            f"(tier={tier}, intent={intent_id}): {reason}"
        )
        self.session_id = session_id
        self.tier = tier
        self.intent_id = intent_id
        self.reason = reason


__all__ = ["PaymentIntent", "PaymentRequiredError", "PaymentResult"]
