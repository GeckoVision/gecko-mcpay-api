"""Payments — x402 on Solana with stub/live/frames modes.

Owned by `web3-engineer`. Stub by default; live mode requires explicit
env config. See `docs/implementation-plan.md` Phase 4.
"""

from gecko_core.payments.gate import run_payment_gate
from gecko_core.payments.models import (
    PaymentIntent,
    PaymentRequiredError,
    PaymentResult,
)
from gecko_core.payments.pricing import price_for
from gecko_core.payments.x402_client import (
    FramesX402Client,
    LiveX402Client,
    StubX402Client,
    X402Client,
    X402Mode,
    get_client,
)

__all__ = [
    "FramesX402Client",
    "LiveX402Client",
    "PaymentIntent",
    "PaymentRequiredError",
    "PaymentResult",
    "StubX402Client",
    "X402Client",
    "X402Mode",
    "get_client",
    "price_for",
    "run_payment_gate",
]
