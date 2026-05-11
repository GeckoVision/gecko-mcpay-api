"""DE-4 — Bootstrap script for the ``gecko_trade_agent`` Mongo DB.

Creates 5 collections + their indexes idempotently on first run; a no-op
on subsequent runs. The DB is NEW: separate from ``gecko_rag`` (chunks)
and ``gecko_cache`` (TTL caches). Per
``docs/strategy/2026-05-11-trade-vertical-expansion.md`` §3 and §6.

Collections
-----------
- ``agent_state`` — one doc per agent: spec snapshot, mode, status,
  last_verdict_id, daily_loss_pct, circuit_breaker.
- ``agent_positions`` — open + recently-closed positions.
- ``agent_journal`` — append-only event log (TTL 90d on ``ts``).
- ``agent_verdict_cache`` — cached oracle verdicts keyed by
  (agent_id, idea_hash) (TTL 24h on ``cached_at``).
- ``agent_hotpath_snapshot`` — last-seen price / account state per
  (agent_id, mint) for warm-start (TTL 5 min on ``seen_at``).

Idempotency
-----------
- ``create_collection`` is guarded by an existence check (CollectionInvalid
  is also caught defensively).
- ``create_index`` is naturally idempotent on identical specs.
- ``collMod`` for validators runs every time (cheap; sets validator to
  the same shape; ``validationLevel="moderate"`` so existing docs aren't
  rejected).

Exit codes
----------
0 — success.
1 — env missing (no MONGODB_URI / MONGO_URI).
2 — connection failure (server unreachable / auth failure).
3 — index or collection creation failure.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from typing import Any

logger = logging.getLogger("bootstrap_trade_agent")

TRADE_AGENT_DB = "gecko_trade_agent"  # single source of truth; NOT env-configurable.

# --- Index specs ----------------------------------------------------------

# Each entry: (collection, keys, options-dict). Motor's create_index accepts
# the same kwargs as PyMongo's.
INDEX_SPECS: list[tuple[str, list[tuple[str, int]], dict[str, Any]]] = [
    # agent_state
    ("agent_state", [("agent_id", 1)], {"unique": True, "name": "agent_id_unique"}),
    (
        "agent_state",
        [("user_wallet", 1), ("status", 1)],
        {"name": "user_wallet_status"},
    ),
    # agent_positions
    (
        "agent_positions",
        [("agent_id", 1), ("status", 1)],
        {"name": "agent_id_status"},
    ),
    (
        "agent_positions",
        [("agent_id", 1), ("opened_at", -1)],
        {"name": "agent_id_opened_at_desc"},
    ),
    # agent_journal — append-only event log; TTL 90 days on `ts`.
    (
        "agent_journal",
        [("agent_id", 1), ("ts", -1)],
        {"name": "agent_id_ts_desc"},
    ),
    (
        "agent_journal",
        [("ts", 1)],
        {"name": "ts_ttl_90d", "expireAfterSeconds": 60 * 60 * 24 * 90},
    ),
    # agent_verdict_cache — cached verdicts; TTL 24h on `cached_at`.
    (
        "agent_verdict_cache",
        [("agent_id", 1), ("idea_hash", 1)],
        {"name": "agent_id_idea_hash"},
    ),
    (
        "agent_verdict_cache",
        [("cached_at", 1)],
        {"name": "cached_at_ttl_24h", "expireAfterSeconds": 60 * 60 * 24},
    ),
    # agent_hotpath_snapshot — warm-start cache; TTL 5 min on `seen_at`.
    (
        "agent_hotpath_snapshot",
        [("agent_id", 1), ("mint", 1)],
        {"name": "agent_id_mint"},
    ),
    (
        "agent_hotpath_snapshot",
        [("seen_at", 1)],
        {"name": "seen_at_ttl_5m", "expireAfterSeconds": 60 * 5},
    ),
]

COLLECTIONS: tuple[str, ...] = (
    "agent_state",
    "agent_positions",
    "agent_journal",
    "agent_verdict_cache",
    "agent_hotpath_snapshot",
)

# --- Schema validators ----------------------------------------------------
# Minimal top-level required fields per design spec §3. validationLevel is
# "moderate" so pre-existing docs aren't rejected on validator install.

VALIDATORS: dict[str, dict[str, Any]] = {
    "agent_state": {
        "$jsonSchema": {
            "bsonType": "object",
            "required": ["agent_id", "spec_id", "mode", "status"],
            "properties": {
                "agent_id": {"bsonType": "string"},
                "spec_id": {"bsonType": "string"},
                "mode": {"enum": ["advisor", "trader"]},
                "status": {
                    "enum": ["starting", "running", "paused", "stopped", "halted"]
                },
                "user_wallet": {"bsonType": ["string", "null"]},
            },
        }
    },
    "agent_positions": {
        "$jsonSchema": {
            "bsonType": "object",
            "required": ["agent_id", "position_id", "status", "opened_at"],
            "properties": {
                "agent_id": {"bsonType": "string"},
                "position_id": {"bsonType": "string"},
                "status": {"enum": ["open", "closed", "liquidated"]},
                "opened_at": {"bsonType": ["date", "double", "long", "int"]},
            },
        }
    },
    "agent_journal": {
        "$jsonSchema": {
            "bsonType": "object",
            "required": ["agent_id", "ts", "event"],
            "properties": {
                "agent_id": {"bsonType": "string"},
                "ts": {"bsonType": "date"},
                "event": {"bsonType": "string"},
            },
        }
    },
    "agent_verdict_cache": {
        "$jsonSchema": {
            "bsonType": "object",
            "required": ["agent_id", "idea_hash", "cached_at"],
            "properties": {
                "agent_id": {"bsonType": "string"},
                "idea_hash": {"bsonType": "string"},
                "cached_at": {"bsonType": "date"},
            },
        }
    },
    "agent_hotpath_snapshot": {
        "$jsonSchema": {
            "bsonType": "object",
            "required": ["agent_id", "mint", "seen_at"],
            "properties": {
                "agent_id": {"bsonType": "string"},
                "mint": {"bsonType": "string"},
                "seen_at": {"bsonType": "date"},
            },
        }
    },
}


def _mongo_uri() -> str | None:
    uri = os.environ.get("MONGODB_URI") or os.environ.get("MONGO_URI")
    if not uri or uri == "__unset__":
        return None
    return uri


def _redact_uri(uri: str) -> str:
    """Drop creds from a mongo URI for log lines."""
    if "@" not in uri:
        return uri
    scheme, _, rest = uri.partition("://")
    _, _, host = rest.partition("@")
    return f"{scheme}://<redacted>@{host}"


async def _ensure_collection(
    db: Any, name: str, dry_run: bool
) -> tuple[bool, bool]:
    """Return (created, existed)."""
    existing = await db.list_collection_names()
    if name in existing:
        logger.info("collection.exists name=%s", name)
        return (False, True)
    if dry_run:
        logger.info("WOULD CREATE collection name=%s", name)
        return (True, False)
    try:
        await db.create_collection(name)
        logger.info("collection.created name=%s", name)
        return (True, False)
    except Exception as exc:  # pymongo.errors.CollectionInvalid etc.
        # Race: another process created it between list and create.
        from pymongo.errors import CollectionInvalid

        if isinstance(exc, CollectionInvalid):
            logger.info("collection.exists name=%s (race)", name)
            return (False, True)
        raise


async def _ensure_index(
    db: Any,
    collection: str,
    keys: list[tuple[str, int]],
    options: dict[str, Any],
    dry_run: bool,
) -> tuple[bool, bool]:
    """Return (created, existed). create_index is idempotent on identical spec."""
    coll = db[collection]
    name = options.get("name", "_".join(f"{k}_{v}" for k, v in keys))
    # Probe existing indexes for an exact-name match.
    existed = False
    try:
        existing = await coll.index_information()
        if name in existing:
            existed = True
    except Exception:
        # Collection may not exist yet under dry-run; treat as not-existing.
        existing = {}

    if existed:
        logger.info("index.exists collection=%s name=%s", collection, name)
        return (False, True)

    if dry_run:
        logger.info(
            "WOULD CREATE index collection=%s name=%s keys=%s opts=%s",
            collection,
            name,
            keys,
            {k: v for k, v in options.items() if k != "name"},
        )
        return (True, False)

    await coll.create_index(keys, **options)
    logger.info("index.created collection=%s name=%s", collection, name)
    return (True, False)


async def _apply_validator(db: Any, collection: str, dry_run: bool) -> None:
    validator = VALIDATORS.get(collection)
    if validator is None:
        return
    if dry_run:
        logger.info("WOULD APPLY validator collection=%s level=moderate", collection)
        return
    try:
        await db.command(
            "collMod",
            collection,
            validator=validator,
            validationLevel="moderate",
        )
        logger.info("validator.applied collection=%s level=moderate", collection)
    except Exception as exc:
        # Validators are best-effort; log but don't fail the bootstrap.
        logger.warning(
            "validator.skipped collection=%s reason=%s", collection, exc
        )


async def bootstrap(dry_run: bool) -> int:
    uri = _mongo_uri()
    if not uri:
        logger.error("env.missing var=MONGODB_URI or MONGO_URI")
        return 1
    logger.info(
        "bootstrap.start db=%s uri=%s dry_run=%s",
        TRADE_AGENT_DB,
        _redact_uri(uri),
        dry_run,
    )

    try:
        from motor.motor_asyncio import AsyncIOMotorClient
    except ImportError:
        logger.error("import.failure motor not installed")
        return 2

    client = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=10_000)
    try:
        # Force a round-trip to detect connection failure early.
        await client.admin.command("ping")
    except Exception as exc:
        logger.error("connection.failure error=%s", exc)
        client.close()
        return 2

    db = client[TRADE_AGENT_DB]

    coll_created = 0
    coll_existed = 0
    idx_created = 0
    idx_existed = 0

    try:
        for name in COLLECTIONS:
            try:
                created, existed = await _ensure_collection(db, name, dry_run)
            except Exception as exc:
                logger.error("collection.failure name=%s error=%s", name, exc)
                return 3
            coll_created += int(created)
            coll_existed += int(existed)

        for collection, keys, options in INDEX_SPECS:
            try:
                created, existed = await _ensure_index(
                    db, collection, keys, options, dry_run
                )
            except Exception as exc:
                logger.error(
                    "index.failure collection=%s opts=%s error=%s",
                    collection,
                    options,
                    exc,
                )
                return 3
            idx_created += int(created)
            idx_existed += int(existed)

        for name in COLLECTIONS:
            await _apply_validator(db, name, dry_run)
    finally:
        client.close()

    logger.info(
        "bootstrap_trade_agent.done collections=%d indexes=%d created=%d existed=%d",
        len(COLLECTIONS),
        len(INDEX_SPECS),
        coll_created + idx_created,
        coll_existed + idx_existed,
    )
    return 0


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Bootstrap the gecko_trade_agent Mongo DB (collections + indexes). "
            "Idempotent."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log what would be created without writing.",
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Set log level to INFO."
    )
    return parser.parse_args(argv)


async def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    return await bootstrap(dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
