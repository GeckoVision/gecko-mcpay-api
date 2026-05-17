"""Telemetry persistence layer (S33-#73).

`TelemetryStore` is the single seam between gecko-core business logic and
the Supabase `telemetry_events` table. Async surface; the underlying
supabase-py client is sync, so calls are dispatched via asyncio.to_thread
to avoid blocking the event loop — same pattern as `SessionStore`.

The write path (POST /events in gecko-api) is intentionally unauthenticated
and must work before a wallet exists. The table is service-role-only at the
DB layer (RLS deny-all for anon); see
`infra/supabase/migrations/20260516120000_telemetry_events.sql`.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, cast

from postgrest.types import CountMethod
from supabase import Client

from gecko_core.db import create_supabase_client

logger = logging.getLogger(__name__)

TELEMETRY_TABLE = "telemetry_events"

KNOWN_TELEMETRY_EVENTS: frozenset[str] = frozenset(
    {
        "install_started",
        "install_ok",
        "install_error",
        "register",
    }
)
"""Known telemetry event types.

These are the values the install funnel emits today. The
`telemetry_events.event_type` column is deliberately free-text (no SQL
CHECK constraint) — telemetry taxonomies evolve and we do not want a
migration per new event type. This constant is documentation + a soft
guard: an unknown `event_type` is still inserted, but `record_event`
logs a warning so a typo in a producer surfaces in the logs.
"""


class TelemetryStore:
    """Async wrapper over the Supabase `telemetry_events` table."""

    def __init__(self, client: Client) -> None:
        self._client = client

    @classmethod
    def from_env(cls) -> TelemetryStore:
        """Build a store using SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY.

        Server-side only. Never call this from gecko-mcpay-app.
        """
        return cls(create_supabase_client())

    async def record_event(
        self,
        event_type: str,
        *,
        wallet_address: str | None = None,
        email: str | None = None,
        installer_tag: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Insert one telemetry row.

        Unknown `event_type` values are allowed — the column is free-text by
        design — but a warning is logged so producer typos are visible.
        Failures are swallowed with a logged error: telemetry must never
        break the caller (the install funnel is best-effort).
        """
        if event_type not in KNOWN_TELEMETRY_EVENTS:
            logger.warning(
                "telemetry.record_event unknown event_type=%r (still inserted)",
                event_type,
            )

        payload: dict[str, Any] = {
            "event_type": event_type,
            "metadata": metadata or {},
        }
        if wallet_address is not None:
            payload["wallet_address"] = wallet_address
        if email is not None:
            payload["email"] = email
        if installer_tag is not None:
            payload["installer_tag"] = installer_tag

        def _insert() -> None:
            self._client.table(TELEMETRY_TABLE).insert(payload).execute()

        try:
            await asyncio.to_thread(_insert)
        except Exception:
            # Best-effort: a telemetry write failure must not surface to the
            # caller. Log and move on.
            logger.exception("telemetry.record_event insert failed event_type=%r", event_type)

    async def telemetry_summary(self) -> dict[str, Any]:
        """Roll up the install funnel — the investor-facing query.

        Returns counts for the known install events, the install-success
        rate, and distinct registered-wallet / email counts. Email *values*
        are never returned — only a count.
        """

        def _count(filters: dict[str, Any]) -> int:
            q = self._client.table(TELEMETRY_TABLE).select(
                "id", count=CountMethod.exact, head=True
            )
            for col, val in filters.items():
                q = q.eq(col, val)
            res = q.execute()
            return int(res.count or 0)

        def _distinct(column: str) -> int:
            # Pull the column for rows where it is non-null, dedupe in
            # Python. The partial index keeps wallet_address rows small;
            # email is low-cardinality at funnel scale. If the table grows
            # past ~100k rows this should move to a SQL `count(distinct)`
            # RPC — documented here so the upgrade path is obvious.
            res = (
                self._client.table(TELEMETRY_TABLE)
                .select(column)
                .not_.is_(column, "null")
                .execute()
            )
            rows = cast(list[dict[str, Any]], res.data or [])
            return len({r[column] for r in rows if r.get(column)})

        def _gather() -> dict[str, Any]:
            install_started = _count({"event_type": "install_started"})
            install_ok = _count({"event_type": "install_ok"})
            install_error = _count({"event_type": "install_error"})
            distinct_wallets = _distinct("wallet_address")
            distinct_emails = _distinct("email")

            attempts = install_started or (install_ok + install_error)
            success_rate = (install_ok / attempts) if attempts else 0.0

            return {
                "install_started": install_started,
                "install_ok": install_ok,
                "install_error": install_error,
                "install_success_rate": round(success_rate, 4),
                "distinct_registered_wallets": distinct_wallets,
                "distinct_emails": distinct_emails,
            }

        return await asyncio.to_thread(_gather)


async def record_event(
    event_type: str,
    *,
    wallet_address: str | None = None,
    email: str | None = None,
    installer_tag: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Module-level convenience wrapper — builds a store from env and inserts.

    Thin transport layers (gecko-api POST /events) call this so they never
    touch the Supabase client directly.
    """
    store = TelemetryStore.from_env()
    await store.record_event(
        event_type,
        wallet_address=wallet_address,
        email=email,
        installer_tag=installer_tag,
        metadata=metadata,
    )


async def telemetry_summary() -> dict[str, Any]:
    """Module-level convenience wrapper for the install-funnel rollup."""
    store = TelemetryStore.from_env()
    return await store.telemetry_summary()
