"""Formal ``X402Client`` Protocol — the narrow seam every facilitator honors.

S13-PAY-01 lifted the Protocol out of ``x402_client`` so that:

  * Adding a new facilitator (Cloudflare in S15) is a single class +
    factory entry, not a 3-class refactor.
  * The (network, mode) → client routing in ``factory.py`` can import a
    Protocol type without re-importing the four concrete clients (which
    would re-introduce the cycle that previously forced
    ``Provenance.payment`` to be typed as ``dict | None``).

Two new class attrs every conforming client carries:

  * ``supported_networks: tuple[str, ...]`` — the network ids this client
    will accept on ``charge()``. Empty tuple = "any" (used by the stub).
    The factory asserts ``intent.network in client.supported_networks``
    before dispatch so a CDP-only field can never leak into the Solana
    path.
  * ``facilitator_id: str`` — the stable string surfaced on receipts and
    in ``bb doctor`` output. One of:
      ``"frames-solana"`` | ``"cdp-base"`` | ``"frames"`` | ``"stub"``
      | ``"http-cloudflare"`` (reserved, S15).

The Protocol stays narrow on purpose: ``charge`` settles a single intent,
``verify`` reports the on-chain confirmation status of a previously-
emitted tx signature. Anything fan-out / multi-leg / recurrence-shaped
lives one layer up in a router (Theme 2 of the web3-engineer S13+ memo).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Protocol, runtime_checkable

# Re-exported from ``gecko_core.models`` — defined there to keep the
# Provenance.payment field typeable without an import cycle.
from gecko_core.models import PaymentReceipt

if TYPE_CHECKING:
    # PaymentIntent / PaymentResult depend on ``gecko_core.models.Tier``;
    # importing them under TYPE_CHECKING keeps the module importable from
    # leaf consumers while the Protocol's ``charge`` / ``verify``
    # signatures stay precise.
    from gecko_core.payments.models import PaymentIntent, PaymentResult

# ---------------------------------------------------------------------------
# Confirmation status — the verify() return shape.
#
# Mirrors the on-chain states the gate cares about, intentionally coarse:
# the payments lane reports "did it land?", everything else (block, slot,
# fee) is exposed by the facilitator's own explorer URL.
# ---------------------------------------------------------------------------


ConfirmationStatus = Literal[
    "pending",
    "confirmed",
    "finalized",
    "failed",
    "unknown",
]


# ---------------------------------------------------------------------------
# X402Client Protocol.
# ---------------------------------------------------------------------------


@runtime_checkable
class X402Client(Protocol):
    """The narrow contract every facilitator honors.

    Class attrs:
      * ``supported_networks`` — networks this client will accept.
        Empty tuple means "any" (stub mode).
      * ``facilitator_id`` — stable id surfaced on receipts + ``bb doctor``.

    Methods:
      * ``charge(intent)`` — settle a single intent. Returns
        :class:`PaymentResult`. Raises typed errors on failure (we do
        NOT catch-and-rephrase facilitator errors).
      * ``verify(tx_signature)`` — report confirmation status of a
        previously-emitted tx. Cheap, idempotent, no side effects.
    """

    supported_networks: tuple[str, ...]
    facilitator_id: str

    async def charge(self, intent: PaymentIntent) -> PaymentResult: ...

    async def verify(self, tx_signature: str) -> ConfirmationStatus: ...


__all__ = [
    "ConfirmationStatus",
    "PaymentReceipt",
    "X402Client",
]
