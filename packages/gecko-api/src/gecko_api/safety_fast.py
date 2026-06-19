"""Warm-first serve path for POST /safety (Launch Firewall step 4).

The endpoint now reads a PRE-COMPUTED verdict from the shared cache (written by
the continuous ``LaunchMonitor``) and returns it in single-digit ms. On a cold
miss it falls back to the existing on-demand ``evaluate_contract_safety`` read
(now internally concurrent), writes the result to the cache, and ARMS the monitor
watchlist so the *next* query for that mint is warm.

This is where the "<400ms" question dissolves: the warm path does zero reasoning
and zero network — it's a dict read + a freshness check. The cold path is the
old behavior, bounded and fail-OPEN, never a 5xx.

Kept FastAPI-free so it can be unit-tested without a TestClient; ``main`` injects
the shared store + monitor from ``app.state``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

# Serve a pre-computed verdict at most this stale before forcing a recompute.
WARM_MAX_AGE_S = 30.0
# TTL for a cold-miss verdict written to the cache.
COLD_TTL_S = 30.0
# Bound on the on-demand fallback (the 4 now-concurrent source calls).
COLD_TIMEOUT_S = 4.0


async def serve_safety(
    mint: str,
    store: Any,
    monitor: Any | None = None,
    *,
    now: float | None = None,
) -> dict[str, Any]:
    """Return the served ``/safety`` payload for ``mint`` (warm-first)."""
    from gecko_core.trade_agent.hotpath.precomputed import PrecomputedSafety, safety_gate

    ts = now if now is not None else time.time()

    # -- warm path: a fresh pre-computed verdict is a dict read -------------- #
    try:
        pc = await store.get(mint)
    except Exception:  # pragma: no cover - defensive; cache must never 5xx
        pc = None
    if pc is not None and pc.is_fresh(ts, WARM_MAX_AGE_S):
        return pc.to_response(now_epoch=ts)

    # -- cold miss: on-demand read (concurrent inside), then arm + cache ----- #
    from gecko_core.orchestration.trade_panel import safety_check as sc
    from gecko_core.orchestration.trade_panel.models import SafetyBlock

    try:
        block = await asyncio.wait_for(
            sc.evaluate_contract_safety(target=mint, mint=mint), timeout=COLD_TIMEOUT_S
        )
    except Exception:
        block = SafetyBlock.unavailable(reason="safety_check_error")

    gate = safety_gate(block)
    cold = PrecomputedSafety(
        mint=mint,
        gate=gate,
        safety=block.model_dump(mode="json"),
        wash=None,
        computed_at_epoch=ts,
        source="ondemand",
    )
    # Best-effort: cache the cold result + arm the monitor so the next hit is
    # warm. A cache/monitor failure must never sink the response.
    try:
        await store.set(mint, cold, COLD_TTL_S)
        if monitor is not None:
            monitor.track(mint)
    except Exception:  # pragma: no cover - defensive
        logger.debug("safety_fast.cache_arm_failed mint=%s", mint)

    return cold.to_response(now_epoch=ts)
