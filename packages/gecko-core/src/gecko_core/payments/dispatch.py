"""Single-entry x402 dispatcher for the 12-skill manifest (S20-B3).

Per CLAUDE.md (Pattern A + facilitator neutrality):

  * One dispatcher routes ALL 12 skills declared in
    :mod:`gecko_core.skills.registry`. No per-skill ``if`` ladders.
  * Chain + facilitator are read from env via the existing
    :mod:`gecko_core.payments.networks` resolver. The dispatcher never
    hard-codes ``frames`` / ``cdp`` — :func:`resolve_client` picks the
    right facilitator from the configured network + mode.

The dispatcher does the bare minimum a 402 surface needs:

  1. No ``X-PAYMENT`` header → return an :class:`AuthResult` whose
     ``accepts`` block matches the shape ``/.well-known/x402`` already
     advertises (one entry per configured network), so a payer-side
     client can reuse the same parser.
  2. ``X-PAYMENT`` header present → decode it, extract whatever
     tx-signature-shaped field the wire protocol carries, hand it to
     ``X402Client.verify`` from the existing Protocol. ``confirmed`` /
     ``finalized`` / ``pending`` → ok; everything else → fail with the
     facilitator's verdict surfaced verbatim (per S12.5 lesson — never
     catch-and-rephrase).
  3. Replays of the same ``X-PAYMENT`` header inside the LRU window
     short-circuit to the cached :class:`AuthResult` (idempotency).

Out of scope here (separate tickets):

  * B4 — credit-pack JWT issuance + redemption.
  * B5 — wiring per-skill handlers to gecko-core entrypoints.
  * B6 — recorded-fixture contract tests against live facilitators.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import os
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

from gecko_core.payments.factory import resolve_client
from gecko_core.payments.networks import resolve_network
from gecko_core.skills.registry import Skill, get_skill

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public types.
# ---------------------------------------------------------------------------


ChainKind = Literal["solana", "base"]


@dataclass(frozen=True)
class AuthResult:
    """Outcome of :meth:`X402Dispatcher.authorize`.

    ``ok`` distinguishes the green path from any 402 — the caller picks
    HTTP 200 vs 402 from this single bit. ``accepts`` is non-None only on
    the unpaid 402 branch (caller serializes it as the ``PAYMENT-REQUIRED``
    header, mirroring what the existing middleware does for ``/research``).
    """

    ok: bool
    error_detail: str | None = None
    accepts: list[dict[str, Any]] | None = None
    tx_signature: str | None = None
    chain: ChainKind | None = None


# ---------------------------------------------------------------------------
# Helpers — wire-amount conversion + chain inference + payload decode.
# ---------------------------------------------------------------------------


# USDC has 6 decimals on both Solana and Base — the only token Gecko prices
# in today. If/when we add a token with different decimals, lift this into
# a per-network table keyed off the asset address.
_USDC_DECIMALS: int = 6


def price_usd_to_wire_amount(price_usd: Decimal, *, decimals: int = _USDC_DECIMALS) -> int:
    """Convert a USD price (Decimal) into the integer wire amount.

    USDC on Solana + Base both use 6 decimals — ``Decimal("0.01")`` →
    ``10_000``. We keep this one helper so no inline ``int(price * 1e6)``
    drift creeps into the dispatcher or the manifest builder.
    """
    if price_usd < 0:
        raise ValueError(f"price_usd must be >= 0; got {price_usd!r}")
    scaled = price_usd * (Decimal(10) ** decimals)
    # Quantize to integer — Decimal rounds half-even by default, fine for
    # USDC. Anything fractional past the scale point is a price-table bug.
    return int(scaled.to_integral_value())


def _infer_chain(network_name: str) -> ChainKind:
    """Map the friendly network name back to the coarse chain kind.

    The Skill manifest exposes ``chain`` ("solana" | "base") on the wire;
    inside the dispatcher we work with the friendly name + CAIP-2 chain
    id so the existing ``resolve_client`` factory keeps doing the routing.
    """
    if network_name.startswith("solana"):
        return "solana"
    if network_name.startswith("base"):
        return "base"
    # Defensive — ``resolve_network`` already rejects unknown values.
    raise ValueError(f"cannot infer chain from network={network_name!r}")


def _decode_x_payment(header_value: str) -> dict[str, Any]:
    """Decode a base64-JSON ``X-PAYMENT`` header into a dict.

    The x402 wire format is ``base64(json(payload))``. We surface decode
    errors verbatim so the caller can return a clear 402 ``error_detail``.
    """
    try:
        raw = base64.b64decode(header_value, validate=False)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"X-PAYMENT not valid base64: {exc}") from exc
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"X-PAYMENT not valid JSON: {exc}") from exc
    if not isinstance(decoded, dict):
        raise ValueError(f"X-PAYMENT must decode to a JSON object; got {type(decoded).__name__}")
    return decoded


def _extract_tx_signature(payload: Mapping[str, Any]) -> str:
    """Pull the tx-signature-shaped field out of a decoded X-PAYMENT.

    The exact key varies by scheme. We probe the common locations
    (``payload.transaction``, ``payload.signature``, top-level
    ``transaction`` / ``signature``) and return the first non-empty
    string — the underlying ``X402Client.verify`` is responsible for
    deciding whether the value is confirmable.
    """
    inner = payload.get("payload")
    if isinstance(inner, Mapping):
        for key in ("transaction", "signature", "tx", "tx_signature"):
            v = inner.get(key)
            if isinstance(v, str) and v:
                return v
    for key in ("transaction", "signature", "tx", "tx_signature"):
        v = payload.get(key)
        if isinstance(v, str) and v:
            return v
    raise ValueError(
        "X-PAYMENT payload missing a tx-signature field "
        "(expected payload.transaction or payload.signature)"
    )


# ---------------------------------------------------------------------------
# Idempotency cache — process-local LRU keyed on the raw X-PAYMENT header.
# ---------------------------------------------------------------------------


# 256 entries is plenty for a single-process surface — replays land within
# seconds of the first call in practice. When we add a session-store-backed
# idempotency table (B5+) this LRU becomes a write-through cache in front
# of it and the contract on the dispatcher doesn't change.
_IDEMPOTENCY_CACHE_MAX: int = 256
_idempotency_cache: OrderedDict[tuple[str, str], AuthResult] = OrderedDict()


def _idempotency_get(skill_name: str, x_payment: str) -> AuthResult | None:
    key = (skill_name, x_payment)
    cached = _idempotency_cache.get(key)
    if cached is not None:
        # LRU touch — moving to the end keeps recently-replayed payments
        # warm against eviction.
        _idempotency_cache.move_to_end(key)
    return cached


def _idempotency_put(skill_name: str, x_payment: str, result: AuthResult) -> None:
    key = (skill_name, x_payment)
    _idempotency_cache[key] = result
    _idempotency_cache.move_to_end(key)
    while len(_idempotency_cache) > _IDEMPOTENCY_CACHE_MAX:
        _idempotency_cache.popitem(last=False)


def _idempotency_clear() -> None:
    """Test-only — drops the LRU. NOT exported."""
    _idempotency_cache.clear()


# ---------------------------------------------------------------------------
# Dispatcher.
# ---------------------------------------------------------------------------


class X402Dispatcher:
    """One x402 gate that fronts every paid skill in the registry.

    Reads chain + facilitator config from the process environment at
    instantiation time:

      * ``X402_MODE``        — ``stub`` | ``live`` | ``frames`` | ``cdp``.
      * ``X402_CHAIN``       — optional override (``solana`` | ``base``);
                               normally inferred from ``X402_NETWORK``.
      * ``X402_NETWORK``     — friendly network name (defaults to
                               ``solana-devnet`` per ``resolve_network``).
      * ``X402_FACILITATOR_URL`` — optional override of the per-network
                               default facilitator URL.
      * ``X402_OPERATOR_WALLET`` — payee address advertised on accepts.
                               Falls back to ``GECKO_WALLET_ADDRESS`` /
                               ``GECKO_WALLET_ADDRESS_BASE`` so existing
                               deploys keep working without env churn.
    """

    def __init__(self) -> None:
        self._mode = os.environ.get("X402_MODE", "stub")
        net = resolve_network(os.environ.get("X402_NETWORK"))
        self._network = net
        self._chain: ChainKind = os.environ.get("X402_CHAIN", "").strip().lower() or _infer_chain(
            net.name
        )  # type: ignore[assignment]
        if self._chain not in ("solana", "base"):
            raise ValueError(f"X402_CHAIN={self._chain!r} unsupported; expected 'solana' or 'base'")
        self._facilitator_url = os.environ.get("X402_FACILITATOR_URL") or net.facilitator_url
        # Operator wallet — explicit env wins, then chain-keyed fallbacks
        # so existing devnet/Base deploys don't need to set a new var.
        explicit = os.environ.get("X402_OPERATOR_WALLET")
        if explicit:
            self._pay_to = explicit
        elif self._chain == "base":
            self._pay_to = (
                os.environ.get("GECKO_WALLET_ADDRESS_BASE")
                or os.environ.get("GECKO_WALLET_ADDRESS")
                or ""
            )
        else:
            self._pay_to = os.environ.get("GECKO_WALLET_ADDRESS", "")

    # ------------------------------------------------------------------
    # Public API.
    # ------------------------------------------------------------------

    async def authorize(
        self,
        skill_name: str,
        request_headers: Mapping[str, str],
    ) -> AuthResult:
        """Resolve the 402 state for one skill request.

        Returns an :class:`AuthResult` the caller serializes into either
        a 200 (``ok=True``) or a 402 (``ok=False``). Never raises on
        protocol-level failure — those flow back via ``error_detail``.
        Raises :class:`KeyError` only on an unknown ``skill_name`` (the
        caller should already have mapped to 404 before calling).
        """
        skill = get_skill(skill_name)

        # Header lookup is case-insensitive — Starlette / httpx normalize
        # but we accept both for safety with ad-hoc TestClient callers.
        x_payment = self._lookup_header(request_headers, "X-PAYMENT")

        if not x_payment:
            return AuthResult(ok=False, accepts=[self._build_accepts_entry(skill)])

        # Idempotency — replay of the same header skips re-verify.
        cached = _idempotency_get(skill_name, x_payment)
        if cached is not None:
            return cached

        # Decode the wire payload. Decode errors are 402, not 500 — the
        # client sent a malformed header.
        try:
            decoded = _decode_x_payment(x_payment)
            tx_signature = _extract_tx_signature(decoded)
        except ValueError as exc:
            return AuthResult(ok=False, error_detail=f"x402 verify failed: {exc}")

        # Hand off to the existing X402Client Protocol — factory picks the
        # right facilitator from (mode, network) without us hard-coding.
        client = resolve_client(network_id=self._network.name, mode=self._mode)
        try:
            status = await client.verify(tx_signature)
        except Exception as exc:
            # Per the operating principles: do NOT catch-and-rephrase
            # facilitator errors. We wrap with the verb so the caller can
            # tell it came from verify, but the underlying message is
            # preserved for the 402 body.
            return AuthResult(ok=False, error_detail=f"x402 verify failed: {exc}")

        if status not in ("confirmed", "finalized", "pending"):
            return AuthResult(
                ok=False,
                error_detail=f"x402 verify failed: facilitator returned status={status!r}",
            )

        result = AuthResult(ok=True, tx_signature=tx_signature, chain=self._chain)
        _idempotency_put(skill_name, x_payment, result)
        return result

    async def authorize_with_credit_token(
        self,
        skill_name: str,
        bearer_token: str,
    ) -> AuthResult:
        """Resolve a 402 against a credit-pack JWT instead of an X-PAYMENT.

        Verifies the JWT's signature + expiry, decrements the Mongo
        balance by :func:`skill_token_cost`, and returns an
        :class:`AuthResult` whose ``tx_signature`` reuses the JWT's
        ``jti`` (the original settlement tx signature) so downstream
        telemetry keeps a single ID across pay paths.

        ``error_detail`` is populated verbatim from the underlying
        verify / decrement failure (no catch-and-rephrase, per S12.5).
        """
        from gecko_core.db.mongo_credit_tokens import (
            CreditTokenRevoked,
            InsufficientCredit,
            decrement_credit_pack,
        )
        from gecko_core.payments.credit_token import (
            CreditTokenError,
            CreditTokenExpired,
            CreditTokenInvalid,
            verify_credit_token,
        )

        skill = get_skill(skill_name)
        if skill.dispatch_kind == "credit":
            return AuthResult(
                ok=False,
                error_detail=(
                    "credit-pack skill cannot be paid with a credit-pack JWT "
                    "— send X-PAYMENT instead"
                ),
            )

        try:
            claims = verify_credit_token(bearer_token)
        except CreditTokenExpired as exc:
            return AuthResult(ok=False, error_detail=f"credit token expired: {exc}")
        except CreditTokenInvalid as exc:
            return AuthResult(ok=False, error_detail=f"credit token invalid signature: {exc}")
        except CreditTokenError as exc:
            return AuthResult(ok=False, error_detail=f"credit token error: {exc}")

        try:
            cost = skill_token_cost(skill)
        except ValueError as exc:
            return AuthResult(ok=False, error_detail=str(exc))

        try:
            await decrement_credit_pack(claims.jti, tokens_used=cost)
        except InsufficientCredit as exc:
            return AuthResult(ok=False, error_detail=f"credit pack exhausted: {exc}")
        except CreditTokenRevoked as exc:
            return AuthResult(ok=False, error_detail=f"credit token revoked: {exc}")
        except KeyError as exc:
            return AuthResult(ok=False, error_detail=f"credit pack not found: {exc}")

        # Pattern A: chain comes from claims, never inferred from env.
        return AuthResult(ok=True, tx_signature=claims.jti, chain=claims.chain)

    # ------------------------------------------------------------------
    # Internal helpers.
    # ------------------------------------------------------------------

    @staticmethod
    def _lookup_header(headers: Mapping[str, str], name: str) -> str | None:
        """Case-insensitive header lookup.

        ``Starlette.Headers`` already normalizes, but a plain ``dict``
        from a TestClient or unit test may use any casing.
        """
        lowered = name.lower()
        for k, v in headers.items():
            if k.lower() == lowered:
                return v
        return None

    def _build_accepts_entry(self, skill: Skill) -> dict[str, Any]:
        """Construct one ``accepts[]`` entry for the PaymentRequired blob.

        Mirrors the shape ``/.well-known/x402`` already advertises per
        route, plus the integer ``amount`` field x402-spec wants on the
        wire. The CAIP-2 ``network`` value comes from
        :data:`NetworkConfig.chain_id` so a CDP-only field can never
        leak into a Solana entry (and vice versa).
        """
        return {
            "scheme": "exact",
            "network": self._network.chain_id,
            "chain": self._chain,
            "amount": price_usd_to_wire_amount(skill.price_usd),
            "asset": "USDC",
            "decimals": _USDC_DECIMALS,
            "price": f"${skill.price_usd}",
            "payTo": self._pay_to,
            "facilitatorUrl": self._facilitator_url,
            "skill": skill.name,
            "resource": skill.url_path,
        }


# ---------------------------------------------------------------------------
# Credit-pack JWT authorization (S20-B4).
#
# A holder of a valid credit-pack JWT can spend the bundled token cap of
# any non-credit-pack skill against their pack. The dispatcher's job:
#
#   1. Verify the JWT's signature + expiry (via gecko_core.payments.credit_token).
#   2. Atomically decrement the Mongo-side balance by skill_token_cost(skill).
#   3. Return an AuthResult whose tx_signature reuses the JWT's jti so
#      downstream telemetry (X-Payment-Tx-Signature header, ledger writes)
#      keeps a single ID across x402 and credit-pack settlements.
#
# Per Pattern A: the chain comes off the JWT claims, never hardcoded.
# ---------------------------------------------------------------------------


def skill_token_cost(skill: Skill) -> int:
    """Tokens a single invocation of ``skill`` consumes against a credit pack.

    For retrieval / debate / pipeline skills this is the bundled output
    cap (``Skill.bundled_output_tokens``). The credit pack itself
    (``dispatch_kind == "credit"``) is NOT redeemable against another
    credit pack — paying for credit with credit would be circular.
    """
    if skill.dispatch_kind == "credit":
        raise ValueError(
            f"skill {skill.name!r} has dispatch_kind=credit and cannot be "
            "redeemed against a credit pack — pay with x402"
        )
    return int(skill.bundled_output_tokens or 0)


__all__ = [
    "AuthResult",
    "ChainKind",
    "X402Dispatcher",
    "price_usd_to_wire_amount",
    "skill_token_cost",
]
