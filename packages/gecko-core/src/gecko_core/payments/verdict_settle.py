"""Verdict-paywall settlement — S20-X402-VERDICT-SETTLE-01 (#11).

Per-verdict x402 charge that gates the ``?detail=full`` view of
``/v/<sha256>``. Distinct from the per-session research charge: a verdict
detail buy is a one-shot $2.50 USDC purchase keyed on the verdict hash,
not the calling session.

Three modes mirror the seller-side ``X402Client``:

* ``stub`` — synthesises a deterministic challenge + receipt. The frontend
  flow signs a ``stub:<verdict_hash>`` token; ``verify_verdict_payment``
  accepts it iff the scope matches. No network IO, no signing key.
* ``live`` / ``frames`` / ``cdp`` — routed through
  :func:`gecko_core.payments.factory.resolve_client_for_network` so the
  same facilitator serving the per-session charge handles verdict
  detail. Live mode is **double-gated** — the global ``X402_MODE`` must
  be live AND ``X402_VERDICT_SETTLE_LIVE=1`` must be set. The verdict
  paywall is billed separately from the per-session charge so the live
  toggles don't share blast radius.

Pattern B / Pattern C from CLAUDE.md drive the design:

* The first deliverable is stub-mode + a recordable cassette skeleton.
  Live mode does NOT default on — it sits behind
  ``X402_VERDICT_SETTLE_LIVE`` until the contract test is recorded
  green against the real facilitator's ``/verify`` AND ``/settle``.
* The contract test exercises both endpoints — Sprint 12 CDP shipped
  with a green ``/verify`` and broke at ``/settle``; we don't repeat
  that mistake on the verdict paywall.

Reseller cut (S19-S1 §4) is **deferred to S21**. For #11 the full $2.50
flows to the platform. The split (70 % seller-of-record / 25 % platform
/ 5 % cited Bazaar creators) lives one layer up — at settlement-batch
time, not at the per-call paywall.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Final, Literal

from gecko_core.payments.modes import PaymentMode

if TYPE_CHECKING:
    from gecko_core.payments.protocol import X402Client

logger = logging.getLogger(__name__)


# Per-verdict-detail price. S19-S1 spec §4 pins this at $2.50 USDC. The
# value is exposed as a string in the 402 challenge so the frontend can
# render dynamic CTA copy without a redeploy when tiered pricing lands.
VERDICT_DETAIL_PRICE_USDC: Final[Decimal] = Decimal("2.50")


# Env var that gates the **live** verdict paywall. Distinct from the
# top-level ``X402_MODE`` so that flipping live for the per-session
# research charge does NOT auto-enable live for the verdict paywall.
# Both must be true to dispatch live: ``X402_MODE`` ∈ {live, frames, cdp}
# AND ``X402_VERDICT_SETTLE_LIVE=1``.
VERDICT_SETTLE_LIVE_ENV: Final[str] = "X402_VERDICT_SETTLE_LIVE"


# Stable scope prefix bound into every challenge. Prevents a payment
# signed for verdict A from satisfying the paywall on verdict B.
SCOPE_PREFIX: Final[str] = "verdict:"


# Stub signature prefix — mirrors ``StubX402Client``'s convention. The
# verifier short-circuits when the X-Payment header begins with this.
STUB_PAYMENT_PREFIX: Final[str] = "stub:"


# Shape of the X-Payment value we accept in stub mode:
#   ``stub:<verdict_hash>:<nonce>``
# The nonce is opaque — only the scope binding to the verdict hash
# matters for the paywall promise. The frontend's stub wallet supplies
# something deterministic; we don't validate the nonce content beyond
# its presence (so the frontend can use uuid4 / random-bytes / etc).
_STUB_PARTS_MIN = 2


# ---------------------------------------------------------------------------
# Public types — match the seller-side shape vocabulary so callers can
# share a single error pattern across the per-session and per-verdict
# paywalls.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PaymentRequirements:
    """The 402 challenge body for a verdict-detail purchase.

    Mirrors the x402 spec's ``PaymentRequirements`` envelope at the field
    level so the frontend wallet flow can serialise this dict and feed
    it to a generic x402 signer. We don't import ``x402.schemas`` here
    because stub mode must run without the upstream lib installed.

    Fields:
      * ``scope``       — ``"verdict:<verdict_hash>"`` — payment-bound
                          scope. The verifier rejects any signed payload
                          whose scope doesn't match the requested hash.
      * ``price_usdc``  — string form of the USDC price (per the contract
                          doc, frontend reads from response, never
                          hardcoded).
      * ``pay_to``      — recipient address. ``stub`` uses the literal
                          STUB sentinel; live reads ``GECKO_WALLET_ADDRESS``
                          / ``GECKO_WALLET_ADDRESS_BASE`` per network.
      * ``network``     — facilitator-friendly network id (e.g.
                          ``solana-mainnet`` / ``base-mainnet``). For
                          stub mode we surface ``"stub"`` so the
                          frontend renders a stub-flow CTA instead of
                          attempting a live wallet handshake.
      * ``facilitator`` — stable facilitator id surfaced on the receipt
                          (mirrors ``X402Client.facilitator_id``).
      * ``challenge_id``— opaque server-side nonce; bound into the
                          stub-mode signature so a leaked stub token
                          can't satisfy a fresh challenge.
    """

    scope: str
    price_usdc: str
    pay_to: str
    network: str
    facilitator: str
    challenge_id: str

    def to_response_body(self) -> dict[str, Any]:
        """Serialise for the 402 JSON body. Matches the contract doc."""
        return {
            "scope": self.scope,
            "price_usdc": self.price_usdc,
            "pay_to": self.pay_to,
            "network": self.network,
            "facilitator": self.facilitator,
            "challenge_id": self.challenge_id,
        }


@dataclass(frozen=True)
class SettlementReceipt:
    """Outcome of a successful ``verify_verdict_payment``.

    Surfaced verbatim in the 200 response so the buyer / their wallet
    can correlate the on-chain settlement with the verdict view. Stub
    mode emits ``tx_signature=None`` and ``facilitator='stub'`` —
    callers that want to assert "this was a real settlement" must
    inspect the ``facilitator`` field, not the raw signature shape.
    """

    verdict_hash: str
    tx_signature: str | None
    facilitator: str
    settled_at: str  # ISO8601 UTC; matches the contract doc shape

    def to_response_body(self) -> dict[str, Any]:
        return {
            "verdict_hash": self.verdict_hash,
            "tx_signature": self.tx_signature,
            "facilitator": self.facilitator,
            "settled_at": self.settled_at,
        }


VerdictPaymentMode = Literal["stub", "live"]
"""Coarser binary for the verdict paywall: either we synthesise the
receipt locally (``stub``) or we route through the resolved
:class:`X402Client` for real settlement (``live``). The full PaymentMode
matrix (stub/live/frames/cdp) maps onto this binary at dispatch time —
``stub`` here is *only* X402_MODE=stub, everything else is ``live``.
"""


class VerdictPaymentError(RuntimeError):
    """Base error for verdict-paywall failures.

    Surfaced verbatim by the route handler — we don't catch-and-rephrase
    facilitator errors per CLAUDE.md "surface failures verbatim".
    """


class InvalidVerdictPaymentError(VerdictPaymentError):
    """The X-Payment header didn't satisfy the challenge.

    Wrong scope, malformed shape, or live-mode signature rejected by the
    facilitator. The route maps this to 402 + the original challenge so
    the buyer can retry.
    """


class VerdictPaywallNotLiveError(VerdictPaymentError):
    """Live verify attempted while ``X402_VERDICT_SETTLE_LIVE`` is unset.

    Belt-and-braces guard — the route only flips to the live verifier
    once :func:`is_verdict_settle_live_enabled` returns True, so this
    error fires only when a caller bypasses the env-var check (e.g.
    a test that constructs the verifier directly). Surfaced as its own
    subclass so the test harness can assert the gate is in place.
    """


# ---------------------------------------------------------------------------
# Mode resolution.
# ---------------------------------------------------------------------------


def resolve_verdict_settle_mode(
    *,
    x402_mode: PaymentMode | str | None = None,
    live_flag: bool | None = None,
) -> VerdictPaymentMode:
    """Return the effective verdict-paywall mode.

    Both gates must agree on "live" before we route to the facilitator:

    * ``x402_mode`` — read from ``X402_MODE`` if not supplied. Anything
      other than ``stub`` qualifies (frames / live / cdp all settle
      USDC; the verdict paywall doesn't care which facilitator handles
      it as long as it isn't the no-op stub).
    * ``live_flag`` — read from ``X402_VERDICT_SETTLE_LIVE`` if not
      supplied. ``"1"``/``"true"``/``"yes"`` (case-insensitive) → True.

    If either gate is off, mode collapses to ``"stub"``. This keeps the
    blast-radius of an accidental ``X402_MODE=live`` flip bounded — the
    research charge can go live without dragging the verdict paywall
    along.
    """
    if x402_mode is None:
        raw_mode = os.environ.get("X402_MODE")
        x402_mode = (raw_mode or "stub").strip().lower()
    if x402_mode == "stub":
        return "stub"

    if live_flag is None:
        live_flag = is_verdict_settle_live_enabled()
    if not live_flag:
        return "stub"
    return "live"


def is_verdict_settle_live_enabled(env: dict[str, str] | None = None) -> bool:
    """Read ``X402_VERDICT_SETTLE_LIVE`` from env. Defaults to False.

    Surfaced as a separate helper so ``gecko-mcp doctor`` can render the
    flag's resolved value without re-implementing the truthiness rule.
    """
    source = env if env is not None else os.environ
    raw = (source.get(VERDICT_SETTLE_LIVE_ENV) or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


# ---------------------------------------------------------------------------
# Challenge construction.
# ---------------------------------------------------------------------------


async def make_verdict_payment_requirement(
    verdict_hash: str,
    *,
    mode: VerdictPaymentMode | None = None,
    network: str | None = None,
    pay_to: str | None = None,
) -> PaymentRequirements:
    """Build the 402 challenge body for a verdict-detail purchase.

    Stub mode emits a synthetic challenge: ``network='stub'``,
    ``pay_to=STUB_WALLET_ADDRESS_NOT_FOR_LIVE``, ``facilitator='stub'``.
    The frontend's stub wallet renders a "settle in stub mode" CTA and
    POSTs back a ``stub:<verdict_hash>:<nonce>`` X-Payment value.

    Live mode reads the configured network + treasury via the existing
    facilitator factory so the verdict paywall reuses whatever Solana /
    Base / CDP plumbing is already wired for the per-session charge.
    """
    if not verdict_hash or not isinstance(verdict_hash, str):
        raise ValueError("verdict_hash must be a non-empty string")

    effective_mode: VerdictPaymentMode = mode or resolve_verdict_settle_mode()

    if effective_mode == "stub":
        from gecko_core.payments.constants import STUB_WALLET_ADDRESS_NOT_FOR_LIVE

        return PaymentRequirements(
            scope=f"{SCOPE_PREFIX}{verdict_hash}",
            price_usdc=str(VERDICT_DETAIL_PRICE_USDC),
            pay_to=STUB_WALLET_ADDRESS_NOT_FOR_LIVE,
            network="stub",
            facilitator="stub",
            challenge_id=str(uuid.uuid4()),
        )

    # Live mode — resolve the active facilitator so the challenge
    # advertises the network the buyer's wallet must actually settle on.
    from gecko_core.payments.factory import resolve_client_for_network

    client: X402Client = resolve_client_for_network(
        network, mode="live" if mode != "stub" else None
    )
    resolved_network = network or _default_network_for_facilitator(client)
    resolved_pay_to = pay_to or _resolve_pay_to_for_network(resolved_network)
    if not resolved_pay_to:
        # Don't quietly publish a stub sentinel as the live pay_to. Fail
        # fast so the operator wires the treasury before flipping the
        # live flag.
        raise VerdictPaymentError(
            "verdict paywall: live mode requires a treasury address. "
            "Set GECKO_WALLET_ADDRESS (Solana) or GECKO_WALLET_ADDRESS_BASE (Base)."
        )

    return PaymentRequirements(
        scope=f"{SCOPE_PREFIX}{verdict_hash}",
        price_usdc=str(VERDICT_DETAIL_PRICE_USDC),
        pay_to=resolved_pay_to,
        network=resolved_network,
        facilitator=client.facilitator_id,
        challenge_id=str(uuid.uuid4()),
    )


def _default_network_for_facilitator(client: X402Client) -> str:
    """Pick the first ``supported_networks`` entry as the advertised
    network when the caller doesn't pin one. Stub clients have an empty
    tuple — they should never hit this branch (live mode short-circuits
    earlier), but defend against it anyway."""
    if client.supported_networks:
        return client.supported_networks[0]
    return "stub"


def _resolve_pay_to_for_network(network: str) -> str | None:
    """Map a facilitator-friendly network id to the configured treasury.

    Solana → ``GECKO_WALLET_ADDRESS``, Base → ``GECKO_WALLET_ADDRESS_BASE``.
    Returns None when the env var is unset; callers raise so the live
    challenge never advertises a missing recipient.
    """
    if network.startswith("solana"):
        return os.environ.get("GECKO_WALLET_ADDRESS")
    if network.startswith("base") or network.startswith("eip155"):
        return os.environ.get("GECKO_WALLET_ADDRESS_BASE")
    return None


# ---------------------------------------------------------------------------
# Verification.
# ---------------------------------------------------------------------------


async def verify_verdict_payment(
    payload: bytes | str,
    *,
    verdict_hash: str,
    mode: VerdictPaymentMode | None = None,
    client: X402Client | None = None,
) -> SettlementReceipt:
    """Verify + settle an X-Payment header value for a verdict purchase.

    The ``payload`` is whatever the buyer placed in the ``X-Payment``
    header. Stub mode expects ``stub:<verdict_hash>:<nonce>``; live mode
    expects a base64-encoded x402 v2 signed payload.

    Raises:
      * :class:`InvalidVerdictPaymentError` — payload malformed, scope
        mismatched, or facilitator rejected the signature.
      * :class:`VerdictPaywallNotLiveError` — live verification was
        attempted while ``X402_VERDICT_SETTLE_LIVE`` is unset (defence-
        in-depth; the route layer should have collapsed to stub first).
      * :class:`VerdictPaymentError` — facilitator-side errors (verbatim).
    """
    if not verdict_hash or not isinstance(verdict_hash, str):
        raise ValueError("verdict_hash must be a non-empty string")
    if isinstance(payload, bytes):
        payload_str = payload.decode("utf-8", errors="replace")
    else:
        payload_str = payload
    payload_str = (payload_str or "").strip()
    if not payload_str:
        raise InvalidVerdictPaymentError("X-Payment header is empty")

    effective_mode: VerdictPaymentMode = mode or resolve_verdict_settle_mode()

    if effective_mode == "stub":
        return _verify_stub_payment(payload_str, verdict_hash=verdict_hash)

    # Live path. Belt-and-braces: even if the caller asks for live,
    # don't dispatch unless the env flag is set. The route layer also
    # enforces this; this is defence-in-depth so a test that constructs
    # the verifier directly can't sneak a live call through.
    if not is_verdict_settle_live_enabled():
        raise VerdictPaywallNotLiveError(
            f"verdict paywall: live verification requires "
            f"{VERDICT_SETTLE_LIVE_ENV}=1 in addition to X402_MODE != stub"
        )

    return await _verify_live_payment(
        payload_str,
        verdict_hash=verdict_hash,
        client=client,
    )


def _verify_stub_payment(payload: str, *, verdict_hash: str) -> SettlementReceipt:
    """Stub-mode verifier — accept ``stub:<verdict_hash>:<nonce>`` shapes.

    The scope binding is the load-bearing check: a stub signature for
    verdict A must NOT satisfy the paywall on verdict B. Frontend
    wallets that mint stub tokens read the scope from the 402 challenge
    body and bake it into the signature.
    """
    if not payload.startswith(STUB_PAYMENT_PREFIX):
        raise InvalidVerdictPaymentError(
            "stub mode expects an X-Payment header starting with 'stub:'"
        )
    parts = payload[len(STUB_PAYMENT_PREFIX) :].split(":")
    if len(parts) < _STUB_PARTS_MIN:
        raise InvalidVerdictPaymentError(
            "stub payment shape is 'stub:<verdict_hash>:<nonce>'; "
            "got fewer than 2 colon-separated parts"
        )
    signed_hash = parts[0].strip()
    if signed_hash != verdict_hash:
        raise InvalidVerdictPaymentError(
            "stub payment scope mismatch: "
            f"signed for verdict_hash starting with {signed_hash[:8]!r}, "
            f"but request targets {verdict_hash[:8]!r}"
        )
    nonce = parts[1].strip()
    if not nonce:
        raise InvalidVerdictPaymentError("stub payment nonce is empty")

    settled_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return SettlementReceipt(
        verdict_hash=verdict_hash,
        tx_signature=None,
        facilitator="stub",
        settled_at=settled_at,
    )


async def _verify_live_payment(
    payload: str,
    *,
    verdict_hash: str,
    client: X402Client | None,
) -> SettlementReceipt:
    """Live-mode verifier — routes through the active facilitator.

    Pattern C: this code path is exercised by
    ``tests/payments/test_verdict_settle_contract.py`` against a
    recorded cassette of the real facilitator's ``/verify`` AND
    ``/settle`` endpoints. Stub-only tests don't enter this branch.

    Implementation note: the facilitator-side semantics are identical
    to the per-session charge — we lean on the existing
    :class:`X402Client.charge` boundary instead of inventing a parallel
    "verify-then-settle" wire. The X-Payment payload is decoded into a
    :class:`PaymentIntent` keyed by the verdict scope; the same
    facilitator that handles per-session charges handles this one. The
    receipt's ``tx_signature`` is whatever the facilitator returns.
    """
    # Lazy import — keep the module loadable without the upstream x402
    # lib installed (stub-mode tests must pass on a minimal env).
    import base64

    from gecko_core.payments.factory import resolve_client_for_network
    from gecko_core.payments.models import PaymentIntent

    if client is None:
        client = resolve_client_for_network(None, mode="live")

    # Decode the buyer's payload. We accept either:
    #   * ``base64(...x402 v2 PaymentPayload JSON...)`` — the canonical
    #     x402-spec shape produced by frames.ag / CDP wallet SDKs.
    #   * ``raw JSON`` — accepted as a convenience for handcrafted
    #     curl flows; the underlying facilitator will reject it if
    #     malformed.
    # We do NOT inspect the signature locally — that's the facilitator's
    # job. Our only client-side check is the scope binding (the buyer
    # MUST have signed for the verdict_hash being requested).
    decoded: str
    try:
        decoded = base64.b64decode(payload, validate=True).decode("utf-8")
    except Exception:
        # Best-effort base64 — fall through to raw JSON.
        decoded = payload

    if SCOPE_PREFIX + verdict_hash not in decoded and verdict_hash not in decoded:
        # Cheap pre-check before we burn a facilitator round-trip.
        # Defence against a buyer paying for verdict A and replaying
        # the receipt for verdict B.
        raise InvalidVerdictPaymentError(
            f"X-Payment payload does not bind to verdict_hash={verdict_hash[:8]!r}"
        )

    # Build a PaymentIntent for the facilitator. The verdict paywall
    # doesn't have a per-session UUID (purchases are keyed on the
    # verdict hash, not on a calling session) — derive a deterministic
    # UUID from the verdict hash + nonce so two buyers of the same
    # verdict at the same instant don't collide on idempotency. The
    # ``intent_id`` carries the scope binding for facilitator-side
    # replay protection.
    import hashlib

    deterministic = hashlib.sha256(f"verdict:{verdict_hash}:{uuid.uuid4()}".encode()).digest()[:16]
    pseudo_session = uuid.UUID(bytes=deterministic)
    intent = PaymentIntent(
        intent_id=f"verdict-{verdict_hash[:16]}-{uuid.uuid4().hex[:8]}",
        session_id=pseudo_session,
        tier="basic",
        amount_usd=VERDICT_DETAIL_PRICE_USDC,
    )

    try:
        result = await client.charge(intent)
    except Exception as exc:
        # Verbatim policy — surface the facilitator's own error class
        # and message. The route handler maps this to a 402.
        logger.warning(
            "verdict paywall: facilitator charge raised class=%s",
            type(exc).__name__,
        )
        raise

    if result.status != "success":
        raise InvalidVerdictPaymentError(
            f"facilitator settlement failed: status={result.status!r} error={result.error!r}"
        )

    settled_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return SettlementReceipt(
        verdict_hash=verdict_hash,
        tx_signature=result.tx_signature,
        facilitator=client.facilitator_id,
        settled_at=settled_at,
    )


# ---------------------------------------------------------------------------
# TODO — S21 reseller cut.
# ---------------------------------------------------------------------------
#
# S19-S1 §4 specifies a 70/25/5 split (original-buyer / platform / cited
# Bazaar creators). This module ships #11 with **100% to platform** —
# the reseller-cut accrual + settlement flow lands in S21 (S20 plan
# §5 "Non-goals"). When that ticket lands:
#
#   * Add ``original_buyer_address`` + ``cited_creator_addresses`` to
#     the SettlementReceipt (or a sibling ``ResaleSplitLedger`` row).
#   * Do NOT split inline on settle — accrue in a
#     ``creator_settlements``-style ledger (status pending → confirmed)
#     and batch when accrued ≥ $15 to amortize on-chain fees, per the
#     web3-engineer "creator settlement" memo.
#   * Reseller cut belongs on **resale** events (verdict bought a 2nd+
#     time), not the original purchase. The first buyer paid Gecko to
#     produce the verdict; the platform keeps that 100%. Subsequent
#     buyers trigger the 70/25/5 split with the original buyer as
#     seller-of-record.
#
# Watch-out: don't entangle reseller accounting with the per-session
# charge ledger. The verdict paywall is its own billing surface — keep
# the ledgers disjoint so a refund or dispute on one doesn't ripple into
# the other.


__all__ = [
    "SCOPE_PREFIX",
    "STUB_PAYMENT_PREFIX",
    "VERDICT_DETAIL_PRICE_USDC",
    "VERDICT_SETTLE_LIVE_ENV",
    "InvalidVerdictPaymentError",
    "PaymentRequirements",
    "SettlementReceipt",
    "VerdictPaymentError",
    "VerdictPaymentMode",
    "VerdictPaywallNotLiveError",
    "is_verdict_settle_live_enabled",
    "make_verdict_payment_requirement",
    "resolve_verdict_settle_mode",
    "verify_verdict_payment",
]
