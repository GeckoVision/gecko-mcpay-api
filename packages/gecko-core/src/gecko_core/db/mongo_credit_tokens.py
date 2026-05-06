"""Mongo store for credit-pack token state (S20-B4).

Owns the ``credit_tokens`` collection in the ``gecko_rag`` database.
The JWT issued by :mod:`gecko_core.payments.credit_token` is the
*proof of purchase*; this collection is the *spend ledger*.

Schema:

.. code-block::

    {
      "_id": ObjectId(...),
      "jti": "<settlement tx signature>",   # unique
      "wallet": "solana:8QURsr...",
      "chain": "solana" | "base",
      "total_tokens": 1500000,              # immutable
      "tokens_remaining": 1500000,          # mutable (atomic decrement)
      "issued_at": ISODate(...),
      "expires_at": ISODate(...),
      "revoked_at": null | ISODate(...)
    }

Indexes:

* ``{ jti: 1 }`` unique — replay/double-mint guard.
* ``{ wallet: 1 }`` — operator inspection / per-wallet listing.

The decrement is the hot path; we use ``find_one_and_update`` with a
filter that asserts ``tokens_remaining >= tokens_used`` AND
``revoked_at is None`` so concurrent decrements either succeed
atomically or are rejected by the filter (returns None → translated
into :class:`InsufficientCredit` / :class:`CreditTokenRevoked`).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from gecko_core.db.mongo import _db
from gecko_core.payments.credit_token import CreditTokenClaims

if TYPE_CHECKING:
    from motor.motor_asyncio import AsyncIOMotorCollection

logger = logging.getLogger(__name__)

CREDIT_TOKENS_COLLECTION = "credit_tokens"


# ---------------------------------------------------------------------------
# Errors.
# ---------------------------------------------------------------------------


class CreditPackError(Exception):
    """Base class for credit-pack ledger errors."""


class InsufficientCredit(CreditPackError):
    """Decrement would push the balance below zero."""


class CreditTokenRevoked(CreditPackError):
    """Token was revoked by an operator; no further spend allowed."""


# ---------------------------------------------------------------------------
# Collection accessor.
# ---------------------------------------------------------------------------


def credit_tokens_collection() -> AsyncIOMotorCollection[Any] | None:
    """Return the live ``credit_tokens`` collection or None if Mongo is unset."""
    db = _db()
    return None if db is None else db[CREDIT_TOKENS_COLLECTION]


def _require_collection() -> AsyncIOMotorCollection[Any]:
    coll = credit_tokens_collection()
    if coll is None:
        raise RuntimeError(
            "MongoDB is not configured — credit_tokens unavailable. "
            "Set MONGODB_URI and ensure GECKO_CHUNK_STORE=mongo."
        )
    return coll


# ---------------------------------------------------------------------------
# Public API.
# ---------------------------------------------------------------------------


async def store_credit_pack(claims: CreditTokenClaims, total_tokens: int) -> None:
    """Insert a fresh credit pack on first issuance. Idempotent on ``jti``.

    A second call with the same ``jti`` is a no-op — settlement was
    already recorded; we must not double-mint or reset the balance.
    """
    coll = _require_collection()
    issued_at = datetime.fromtimestamp(claims.iat, tz=UTC)
    expires_at = datetime.fromtimestamp(claims.exp, tz=UTC)
    doc = {
        "jti": claims.jti,
        "wallet": claims.sub,
        "chain": claims.chain,
        "total_tokens": int(total_tokens),
        "tokens_remaining": int(total_tokens),
        "issued_at": issued_at,
        "expires_at": expires_at,
        "revoked_at": None,
    }
    # ``upsert`` with ``$setOnInsert`` is the idempotent shape — if a
    # doc already exists for this jti, every field is left alone.
    await coll.update_one(
        {"jti": claims.jti},
        {"$setOnInsert": doc},
        upsert=True,
    )


async def decrement_credit_pack(jti: str, tokens_used: int) -> int:
    """Atomically decrement ``tokens_remaining`` by ``tokens_used``.

    Returns the new ``tokens_remaining`` on success.

    Raises:
        InsufficientCredit: balance would go negative (filter rejects).
        CreditTokenRevoked: the pack was revoked.
        KeyError: no pack exists for this ``jti``.
    """
    if tokens_used < 0:
        raise ValueError(f"tokens_used must be >= 0; got {tokens_used}")
    coll = _require_collection()

    # Atomic decrement-or-fail. The filter requires both:
    #   - tokens_remaining >= tokens_used  (never negative)
    #   - revoked_at is None
    # find_one_and_update returns the updated doc, or None if no doc
    # matched the filter — we then disambiguate (revoked vs insufficient
    # vs not found) with a follow-up read.
    updated = await coll.find_one_and_update(
        {
            "jti": jti,
            "tokens_remaining": {"$gte": int(tokens_used)},
            "revoked_at": None,
        },
        {"$inc": {"tokens_remaining": -int(tokens_used)}},
        return_document=True,  # ReturnDocument.AFTER
    )
    if updated is not None:
        return int(updated["tokens_remaining"])

    # The atomic update missed — figure out why.
    existing = await coll.find_one({"jti": jti})
    if existing is None:
        raise KeyError(f"no credit pack for jti={jti!r}")
    if existing.get("revoked_at") is not None:
        raise CreditTokenRevoked(f"credit pack {jti!r} is revoked")
    raise InsufficientCredit(
        f"credit pack {jti!r} has {existing.get('tokens_remaining', 0)} tokens "
        f"remaining; need {tokens_used}"
    )


async def get_credit_pack(jti: str) -> dict[str, Any] | None:
    """Read-only fetch of the pack document by ``jti``."""
    coll = _require_collection()
    doc = await coll.find_one({"jti": jti})
    return doc if doc is None else dict(doc)


async def revoke_credit_pack(jti: str) -> bool:
    """Mark a pack as revoked. Idempotent. Returns True if a doc was updated."""
    coll = _require_collection()
    result = await coll.update_one(
        {"jti": jti, "revoked_at": None},
        {"$set": {"revoked_at": datetime.now(UTC)}},
    )
    return bool(result.modified_count)


async def ensure_indexes() -> None:
    """Create the unique ``jti`` index + supporting ``wallet`` index.

    Idempotent — Mongo's ``create_index`` is a no-op when the index
    already exists. Call from a one-time bootstrap path or doctor.
    """
    coll = _require_collection()
    await coll.create_index("jti", unique=True, name="credit_tokens_jti_unique")
    await coll.create_index("wallet", name="credit_tokens_wallet")


# ---------------------------------------------------------------------------
# Test seam — a stub collection that mimics ``find_one_and_update``
# semantics so tests don't need a live Mongo. Importable by tests via
# ``from gecko_core.db.mongo_credit_tokens import StubCreditTokenCollection``.
# ---------------------------------------------------------------------------


class StubCreditTokenCollection:
    """In-memory stand-in for ``AsyncIOMotorCollection[credit_tokens]``.

    Implements the four methods the production code calls plus a tiny
    ``_lock`` to make ``decrement_credit_pack`` correctness verifiable
    under ``asyncio.gather``. Atomicity is modeled by holding the lock
    across read + write — same effective semantics as Mongo's
    single-document atomic ``find_one_and_update``.
    """

    def __init__(self) -> None:
        import asyncio

        self._docs: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def update_one(
        self,
        filter_: dict[str, Any],
        update: dict[str, Any],
        upsert: bool = False,
    ) -> Any:
        async with self._lock:
            jti = filter_.get("jti")
            if jti is None:
                raise ValueError("StubCreditTokenCollection only supports jti-keyed filters")
            existing = self._docs.get(jti)
            modified = 0
            if existing is None and upsert and "$setOnInsert" in update:
                self._docs[jti] = dict(update["$setOnInsert"])
            elif existing is not None and "$set" in update:
                # Apply the same revoked_at filter as the production code.
                if (
                    "revoked_at" in filter_
                    and filter_["revoked_at"] is None
                    and existing.get("revoked_at") is not None
                ):
                    return _StubResult(modified=0, matched=0)
                for k, v in update["$set"].items():
                    existing[k] = v
                modified = 1
            return _StubResult(modified=modified, matched=1 if existing else 0)

    async def find_one_and_update(
        self,
        filter_: dict[str, Any],
        update: dict[str, Any],
        return_document: bool = True,
    ) -> dict[str, Any] | None:
        async with self._lock:
            jti = filter_.get("jti")
            doc = self._docs.get(jti) if jti else None
            if doc is None:
                return None
            # Apply the filter conditions beyond jti.
            min_remaining = filter_.get("tokens_remaining", {}).get("$gte")
            if min_remaining is not None and doc.get("tokens_remaining", 0) < min_remaining:
                return None
            if (
                "revoked_at" in filter_
                and filter_["revoked_at"] is None
                and doc.get("revoked_at") is not None
            ):
                return None
            inc = update.get("$inc", {})
            for k, v in inc.items():
                doc[k] = doc.get(k, 0) + v
            set_ops = update.get("$set", {})
            for k, v in set_ops.items():
                doc[k] = v
            return dict(doc)

    async def find_one(self, filter_: dict[str, Any]) -> dict[str, Any] | None:
        async with self._lock:
            jti = filter_.get("jti")
            if jti is None:
                return None
            doc = self._docs.get(jti)
            return dict(doc) if doc is not None else None

    async def update_one_simple(self, jti: str, update: dict[str, Any]) -> Any:
        # Used by ``revoke_credit_pack`` via the standard ``update_one`` path.
        return await self.update_one({"jti": jti, "revoked_at": None}, update, upsert=False)

    async def create_index(self, *args: Any, **kwargs: Any) -> str:
        name = kwargs.get("name", "stub_index")
        return str(name)

    # Helper for tests
    def _seed(self, claims: CreditTokenClaims, total_tokens: int) -> None:
        from datetime import UTC
        from datetime import datetime as _dt

        self._docs[claims.jti] = {
            "jti": claims.jti,
            "wallet": claims.sub,
            "chain": claims.chain,
            "total_tokens": int(total_tokens),
            "tokens_remaining": int(total_tokens),
            "issued_at": _dt.fromtimestamp(claims.iat, tz=UTC),
            "expires_at": _dt.fromtimestamp(claims.exp, tz=UTC),
            "revoked_at": None,
        }


class _StubResult:
    def __init__(self, modified: int, matched: int) -> None:
        self.modified_count = modified
        self.matched_count = matched


# Allow tests to inject the stub by monkeypatching ``credit_tokens_collection``.
__all__ = [
    "CREDIT_TOKENS_COLLECTION",
    "CreditPackError",
    "CreditTokenRevoked",
    "InsufficientCredit",
    "StubCreditTokenCollection",
    "credit_tokens_collection",
    "decrement_credit_pack",
    "ensure_indexes",
    "get_credit_pack",
    "revoke_credit_pack",
    "store_credit_pack",
]


# Silence the unused-import warning when motor isn't installed in
# minimal test envs (TYPE_CHECKING guard handles real imports).
_ = timedelta
