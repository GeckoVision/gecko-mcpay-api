"""Creator payout settlement on cite — Sprint 14 S14-PARA-02.

When a Paragraph-sourced chunk lands in the verdict's RAG context (the
``Citation`` carries ``creator_handle`` + ``creator_wallet``), Gecko
fires a small payout to the creator's wallet via the X402Client
Protocol seam (``gecko_core.payments.factory.resolve_client``).

Default per-cite amount is **$0.005**, configurable via
``CREATOR_PAYOUT_PER_CITE``. Stub mode simulates the settle (no real
charge); live mode lands an on-chain USDC transfer to the creator's
0x address via the CDP Facilitator on Base mainnet.

Aggregation:
- Multiple cites for the same creator (handle + wallet) batch into a
  single payout intent. Saves the per-call facilitator fee for
  high-citation Paragraph posts.
- Each citation's ``creator_payout_usd`` is set to its **share** of
  the aggregated total (always == per-cite amount), and the
  Provenance.payment receipt carries the tx hash so the verdict
  renderer can surface it.

Settlement target:
- Base mainnet USDC (eip155:8453) via the CDP Facilitator. The
  X402Client Protocol seam abstracts this — the resolver picks the
  right concrete client based on the active mode + network.

Failure policy:
- A failed payout does **not** halt the verdict render. The citation
  stays in the report with ``creator_payout_usd=None`` and the gate
  logs the error. Treating the cite as "free" is the correct
  fallback — the founder paid for the research, not for the payout's
  on-chain success.
"""

from __future__ import annotations

import logging
import os
import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

from gecko_core.models import Citation, PaymentReceipt
from gecko_core.payments.factory import resolve_client
from gecko_core.payments.models import PaymentIntent, PaymentResult

if TYPE_CHECKING:
    from gecko_core.payments.protocol import X402Client

logger = logging.getLogger(__name__)


# Per-cite payout default. Set deliberately low ($0.005) so a research
# session with 20 cited Paragraph posts costs the founder $0.10 in
# creator payouts — bounded against the per-session $0.30 cap from
# S14-PARA-03 (`GECKO_CREATOR_PAYOUT_CAP`).
DEFAULT_PER_CITE_USD: Decimal = Decimal("0.005")

CREATOR_PAYOUT_PER_CITE_ENV = "CREATOR_PAYOUT_PER_CITE"


def resolve_per_cite_amount_usd(env: dict[str, str] | None = None) -> Decimal:
    """Read ``CREATOR_PAYOUT_PER_CITE`` from env; fall back to $0.005.

    Non-numeric, zero, or negative values fall back to the default —
    we never emit a $0 intent (the gate would reject it).
    """
    raw = (env if env is not None else os.environ).get(CREATOR_PAYOUT_PER_CITE_ENV, "").strip()
    if not raw:
        return DEFAULT_PER_CITE_USD
    try:
        value = Decimal(raw)
    except Exception:
        logger.warning(
            "%s=%r is not a valid decimal; using default %s USD",
            CREATOR_PAYOUT_PER_CITE_ENV,
            raw,
            DEFAULT_PER_CITE_USD,
        )
        return DEFAULT_PER_CITE_USD
    if value <= 0:
        return DEFAULT_PER_CITE_USD
    return value


def _is_paragraph_cite(citation: Citation) -> bool:
    """True iff this citation is eligible for a creator payout.

    Eligibility = a paid-provider citation with a non-empty
    ``creator_wallet``. The handle alone isn't enough — without a
    wallet we have nothing to settle against. Provider-name check is
    case-insensitive so a future ``paragraph-staging`` provider stays
    eligible without code changes.
    """
    if not citation.creator_wallet:
        return False
    name = (citation.provenance.provider_name or "").lower()
    return name.startswith("paragraph")


def _group_by_creator(citations: list[Citation]) -> dict[tuple[str, str], list[int]]:
    """Group eligible citations by (handle, wallet) → list of indices.

    Multiple cites for the same author batch into a single payout
    intent at settle time. Returning indices (not Citation refs) lets
    the caller mutate the original list in place once payouts return.
    """
    groups: dict[tuple[str, str], list[int]] = {}
    for idx, cite in enumerate(citations):
        if not _is_paragraph_cite(cite):
            continue
        handle = cite.creator_handle or ""
        wallet = cite.creator_wallet or ""
        groups.setdefault((handle, wallet), []).append(idx)
    return groups


async def settle_creator_payouts(
    *,
    session_id: UUID,
    citations: list[Citation],
    client: X402Client | None = None,
    per_cite_usd: Decimal | None = None,
) -> list[Citation]:
    """Fire creator payouts for every Paragraph-sourced citation.

    Returns a NEW list of Citation objects; the input list is not
    mutated. Each eligible citation gains a ``creator_payout_usd`` and
    a ``Provenance.payment`` receipt; non-eligible citations pass
    through verbatim.

    ``client`` is injected for testing — production callers pass
    ``None`` and the function resolves through the X402Client factory
    so stub/live/CDP mode toggling Just Works.
    """
    if not citations:
        return list(citations)

    per_cite = per_cite_usd if per_cite_usd is not None else resolve_per_cite_amount_usd()
    groups = _group_by_creator(citations)
    if not groups:
        return list(citations)

    resolved_client: X402Client = client if client is not None else resolve_client()

    # Settle in deterministic order (stable for snapshot tests).
    updated: dict[int, Citation] = {}
    for (handle, _wallet), idxs in sorted(groups.items()):
        amount_total = per_cite * Decimal(len(idxs))
        intent = PaymentIntent(
            intent_id=f"creator-payout-{session_id}-{handle or 'anon'}-{uuid.uuid4().hex[:8]}",
            session_id=session_id,
            tier="basic",
            amount_usd=amount_total,
        )
        try:
            result: PaymentResult = await resolved_client.charge(intent)
        except Exception as exc:
            # Verbatim policy — log the error class only (no body); the
            # surrounding pipeline keeps the cite in the report with a
            # null payout.
            logger.warning(
                "creator payout failed session=%s handle=%s class=%s",
                session_id,
                handle,
                type(exc).__name__,
            )
            continue

        if result.status != "success":
            logger.info(
                "creator payout returned status=%s for handle=%s; cite kept without payout",
                result.status,
                handle,
            )
            continue

        receipt: PaymentReceipt = {
            "intent_id": intent.intent_id,
            "status": "success",
            "tx_signature": result.tx_signature,
            "facilitator_id": getattr(resolved_client, "facilitator_id", "unknown"),
            "network": getattr(resolved_client, "supported_networks", ("unknown",))[0]
            if getattr(resolved_client, "supported_networks", ())
            else "unknown",
            "error": None,
        }
        for idx in idxs:
            cite = citations[idx]
            new_provenance = cite.provenance.model_copy(update={"payment": receipt})
            updated[idx] = cite.model_copy(
                update={
                    "creator_payout_usd": float(per_cite),
                    "provenance": new_provenance,
                }
            )

    if not updated:
        return list(citations)

    return [updated.get(i, c) for i, c in enumerate(citations)]


def aggregate_creator_payouts(citations: list[Citation]) -> dict[str, Any]:
    """Return per-handle totals + a grand total for `bb economics` rendering.

    Output shape:
        {
            "total_usd": Decimal,
            "per_creator": [
                {"handle": "@author1", "wallet": "0x...", "amount_usd": Decimal,
                 "tx_signature": "0x...", "cite_count": int},
                ...
            ],
        }

    The ``cost_creator_usd`` line item that ``bb economics`` exposes is
    derived from this aggregate.
    """
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for cite in citations:
        if cite.creator_payout_usd is None or not cite.creator_wallet:
            continue
        key = (cite.creator_handle or "", cite.creator_wallet or "")
        entry = by_key.setdefault(
            key,
            {
                "handle": cite.creator_handle or "",
                "wallet": cite.creator_wallet or "",
                "amount_usd": Decimal("0"),
                "tx_signature": None,
                "cite_count": 0,
            },
        )
        entry["amount_usd"] += Decimal(str(cite.creator_payout_usd))
        entry["cite_count"] += 1
        receipt = cite.provenance.payment
        if receipt and entry["tx_signature"] is None:
            entry["tx_signature"] = receipt.get("tx_signature")

    per_creator = sorted(by_key.values(), key=lambda r: (-r["cite_count"], r["handle"]))
    total = sum((entry["amount_usd"] for entry in per_creator), start=Decimal("0"))
    return {"total_usd": total, "per_creator": per_creator}


__all__ = [
    "CREATOR_PAYOUT_PER_CITE_ENV",
    "DEFAULT_PER_CITE_USD",
    "aggregate_creator_payouts",
    "resolve_per_cite_amount_usd",
    "settle_creator_payouts",
]
