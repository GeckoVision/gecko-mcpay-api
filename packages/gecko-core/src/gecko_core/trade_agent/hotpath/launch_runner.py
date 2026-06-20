"""Live ingest runner — wire Helius vault subscriptions into the monitor (step 6).

Connects the realtime stream to the firewall: for each tracked pool it subscribes
to the pool's two token-vault accounts via ``HeliusWebSocketClient`` (jsonParsed),
turns each balance update into a swap + pool snapshot (``swap_parser``), feeds the
``LaunchMonitor``, and recomputes verdicts on a cadence so the cache stays warm.

**Env-gated OFF by default** (``GECKO_FIREWALL_ENABLED``). The reserve-delta
inference + the exact Helius payload shape are verified offline against fixtures
(Pattern B/C) but NOT yet against a live stream; gating prevents an unverified
parser from poisoning prod verdicts. Flip on only after the live-payload smoke.

Hotpath isolation: ``pydantic``/stdlib + sibling hotpath modules only. The
callback logic (``_on_vault_event``) is a plain coroutine so it can be driven
directly with recorded notifications in tests — no websocket required.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
from collections.abc import Callable
from typing import Any

from gecko_core.trade_agent.hotpath.cache import HotpathCache
from gecko_core.trade_agent.hotpath.launch_monitor import DEFAULT_TTL_S, LaunchMonitor
from gecko_core.trade_agent.hotpath.swap_parser import PoolReserveTracker, parse_vault_balance

logger = logging.getLogger(__name__)

RECOMPUTE_INTERVAL_S = 5.0


def is_firewall_enabled() -> bool:
    """True only when GECKO_FIREWALL_ENABLED is explicitly truthy (default OFF).

    Treats the SSM ``__unset__`` sentinel + blank as off (house convention).
    """
    val = (os.environ.get("GECKO_FIREWALL_ENABLED") or "").strip().lower()
    return val in {"1", "true", "yes", "on"}


class _TrackedPool:
    __slots__ = ("mint", "sub_ids", "tracker")

    def __init__(self, mint: str, tracker: PoolReserveTracker) -> None:
        self.mint = mint
        self.tracker = tracker
        self.sub_ids: list[int] = []


class LaunchRunner:
    """Owns the websocket subscriptions + the recompute loop for the firewall."""

    def __init__(
        self,
        monitor: LaunchMonitor,
        ws_client: object,
        *,
        recompute_interval_s: float = RECOMPUTE_INTERVAL_S,
        ttl_s: float = DEFAULT_TTL_S,
        now: Callable[[], float] = time.time,
    ) -> None:
        self._mon = monitor
        self._ws = ws_client
        self._pools: dict[str, _TrackedPool] = {}  # keyed by pool_addr
        self._recompute_interval_s = recompute_interval_s
        self._ttl_s = ttl_s
        self._now = now
        self._recompute_task: asyncio.Task[None] | None = None
        self._running = False

    @property
    def tracked_pools(self) -> int:
        return len(self._pools)

    @property
    def ws_client(self) -> object:
        """The shared websocket client (so discovery multiplexes on one connection)."""
        return self._ws

    async def track_pool(
        self,
        *,
        mint: str,
        pool_addr: str,
        base_vault: str,
        quote_vault: str,
        quote_usd_per_unit: float = 1.0,
        pool_created_ts: int | None = None,
    ) -> None:
        """Register a pool: arm the monitor + subscribe both vault accounts."""
        if pool_addr in self._pools:
            return
        self._mon.track(mint, pool_created_ts=pool_created_ts)
        tracker = PoolReserveTracker(
            pool_addr,
            base_vault=base_vault,
            quote_vault=quote_vault,
            quote_usd_per_unit=quote_usd_per_unit,
        )
        tp = _TrackedPool(mint, tracker)
        self._pools[pool_addr] = tp

        # The accountSubscribe notification does NOT echo the account pubkey, so
        # the SUBSCRIPTION identity is authoritative: bind each callback to the
        # vault it watches and stamp that pubkey onto the parsed balance.
        async def _cb_base(
            params: dict[str, Any], _pool: str = pool_addr, _vault: str = base_vault
        ) -> None:
            await self._on_vault_event(_pool, params, vault=_vault)

        async def _cb_quote(
            params: dict[str, Any], _pool: str = pool_addr, _vault: str = quote_vault
        ) -> None:
            await self._on_vault_event(_pool, params, vault=_vault)

        # subscribe_account exists on HeliusWebSocketClient; duck-typed so tests
        # can pass a fake client.
        sub_a = await self._ws.subscribe_account(base_vault, _cb_base)  # type: ignore[attr-defined]
        sub_b = await self._ws.subscribe_account(quote_vault, _cb_quote)  # type: ignore[attr-defined]
        tp.sub_ids = [sub_a, sub_b]

    async def _on_vault_event(self, pool_addr: str, params: dict[str, Any], *, vault: str) -> None:
        """Callback for a vault account update — parse, feed the monitor.

        ``vault`` is the subscribed account's pubkey (authoritative), stamped onto
        the parsed balance so the tracker routes it to the right reserve.
        """
        tp = self._pools.get(pool_addr)
        if tp is None:
            return
        vb = parse_vault_balance(params, pubkey=vault)
        if vb is None:
            return
        if vb.pubkey != vault:
            vb = vb.model_copy(update={"pubkey": vault})
        swap, snapshot = tp.tracker.observe(vb, ts=self._now())
        self._mon.update_pool(tp.mint, snapshot)
        if swap is not None:
            self._mon.ingest_swap(tp.mint, swap)

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._recompute_task = asyncio.create_task(
            self._recompute_loop(), name="firewall-recompute"
        )

    async def stop(self) -> None:
        self._running = False
        if self._recompute_task is not None:
            self._recompute_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._recompute_task
            self._recompute_task = None

    async def recompute_all(self) -> None:
        """Recompute every tracked mint once (also the unit-test entry point)."""
        now = self._now()
        for tp in list(self._pools.values()):
            with contextlib.suppress(Exception):
                await self._mon.recompute(tp.mint, now, ttl_s=self._ttl_s)

    async def _recompute_loop(self) -> None:
        while self._running:
            await self.recompute_all()
            await asyncio.sleep(self._recompute_interval_s)


def build_runner(monitor: LaunchMonitor, *, api_key: str | None = None) -> LaunchRunner | None:
    """Construct a runner with a real Helius client, or None if not enabled/configured.

    Returns None when the firewall is gated off or no Helius key is available —
    the caller (lifespan) then simply doesn't start live ingest, and /safety keeps
    serving via the cold-miss path.
    """
    if not is_firewall_enabled():
        return None
    key = api_key or (os.environ.get("HELIUS_API_KEY") or "").strip()
    if not key or key == "__unset__":
        logger.warning("firewall enabled but HELIUS_API_KEY unset — live ingest disabled")
        return None
    from gecko_core.trade_agent.hotpath.helius import HeliusWebSocketClient

    return LaunchRunner(monitor, HeliusWebSocketClient(api_key=key))


__all__ = ["HotpathCache", "LaunchRunner", "build_runner", "is_firewall_enabled"]
