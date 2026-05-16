"""Top-of-funnel install + register telemetry.

The platform's only pre-S33 signal was a `sessions` row, created AFTER a
successful tool call. People who fail to install — or never call a tool —
produced zero signal. This package records install/register events so the
funnel (and a defensible "how many users / wallets" number) is observable.

Public surface:
    - :data:`KNOWN_TELEMETRY_EVENTS`
    - :class:`TelemetryStore`
    - :func:`record_event`
    - :func:`telemetry_summary`
"""

from __future__ import annotations

from gecko_core.telemetry.store import (
    KNOWN_TELEMETRY_EVENTS,
    TelemetryStore,
    record_event,
    telemetry_summary,
)

__all__ = [
    "KNOWN_TELEMETRY_EVENTS",
    "TelemetryStore",
    "record_event",
    "telemetry_summary",
]
