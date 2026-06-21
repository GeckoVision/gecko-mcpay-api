"""Pool discovery — the missing wire that makes the firewall watch real launches.

`LaunchRunner` can stream a pool's vaults, but nothing tells it which pools exist.
This is that feed: subscribe to `logsSubscribe` on the major AMM program ids, and
when a new-pool init lands, fetch the parsed tx, resolve `(mint, base/quote vault)`
(`pool_resolver`), and call `runner.track_pool(...)`.

`processed` commitment on the logs sub → we hear the init at/near Block 0, which is
exactly the snipe window. Resolution then reads the (now-confirmed) tx.

**Env-gated OFF** with the rest of the firewall (`build_discovery` returns None
unless `is_firewall_enabled()` + a Helius key). De-dup by signature + pool key,
a hard cap on concurrent tracked pools (bounds Helius credit burn), and fail-OPEN
on every resolution error. Hotpath-clean: `httpx`/`pydantic`/stdlib + sibling
hotpath modules only.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from typing import Any

from gecko_core.trade_agent.hotpath.helius_rpc import TxFetcher, make_tx_fetcher
from gecko_core.trade_agent.hotpath.launch_runner import LaunchRunner, is_firewall_enabled
from gecko_core.trade_agent.hotpath.pool_resolver import (
    ResolvedPool,
    extract_logs,
    extract_signature,
    is_pool_init_log,
    resolve_from_parsed_tx,
)
from gecko_core.trade_agent.hotpath.program_reputation import (
    ESTABLISHED_PROGRAMS,  # noqa: F401  (kept for callers wiring a custom watch set)
)

logger = logging.getLogger(__name__)

# AMM/launchpad programs whose pool-init we watch. Subset of the established set
# that actually CREATE launch pools (not the token/system programs). Pattern A.
WATCHED_AMM_PROGRAMS: tuple[str, ...] = (
    "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",  # Raydium AMM v4
    "CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C",  # Raydium CPMM
    "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P",  # Pump.fun bonding curve
    "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA",  # PumpSwap AMM
    "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo",  # Meteora DLMM
)

DEFAULT_MAX_POOLS = 200


class PoolDiscovery:
    """Watches AMM-init logs and registers new pools with the LaunchRunner."""

    def __init__(
        self,
        runner: LaunchRunner,
        ws_client: object,
        fetch_tx: TxFetcher,
        *,
        program_ids: tuple[str, ...] = WATCHED_AMM_PROGRAMS,
        max_pools: int = DEFAULT_MAX_POOLS,
        now: Callable[[], float] = time.time,
    ) -> None:
        self._runner = runner
        self._ws = ws_client
        self._fetch_tx = fetch_tx
        self._program_ids = program_ids
        self._max_pools = max_pools
        self._now = now
        self._seen_sigs: set[str] = set()
        self._tracked: set[str] = set()
        self._sub_ids: list[int] = []
        self._stats = {"inits_seen": 0, "resolved": 0, "tracked": 0, "skipped_cap": 0, "failed": 0}

    @property
    def stats(self) -> dict[str, int]:
        return {**self._stats, "tracked_now": len(self._tracked)}

    async def start(self) -> None:
        """Subscribe to init logs for every watched program."""
        for pid in self._program_ids:

            async def _cb(params: dict[str, Any], _pid: str = pid) -> None:
                await self._on_log(params, _pid)

            sub = await self._ws.subscribe_logs([pid], _cb)  # type: ignore[attr-defined]
            self._sub_ids.append(sub)

    async def _on_log(self, params: dict[str, Any], program_id: str) -> None:
        logs = extract_logs(params)
        if not is_pool_init_log(logs):
            return
        sig = extract_signature(params)
        if not sig or sig in self._seen_sigs:
            return
        self._seen_sigs.add(sig)
        self._stats["inits_seen"] += 1

        if len(self._tracked) >= self._max_pools:
            self._stats["skipped_cap"] += 1
            logger.info("discovery.cap_reached max=%d sig=%s", self._max_pools, sig[:16])
            return

        tx = await self._fetch_tx(sig)
        if tx is None:
            self._stats["failed"] += 1
            return
        created_ts = tx.get("blockTime") if isinstance(tx.get("blockTime"), int) else None
        resolved: ResolvedPool | None = resolve_from_parsed_tx(
            tx, signature=sig, created_ts=created_ts
        )
        if resolved is None:
            self._stats["failed"] += 1
            return
        self._stats["resolved"] += 1
        if resolved.pool_addr in self._tracked:
            return
        try:
            await self._runner.track_pool(
                mint=resolved.mint,
                pool_addr=resolved.pool_addr,
                base_vault=resolved.base_vault,
                quote_vault=resolved.quote_vault,
                quote_usd_per_unit=resolved.quote_usd_per_unit,
                pool_created_ts=resolved.pool_created_ts,
            )
        except Exception as exc:  # fail-OPEN: never let one bad pool kill discovery
            self._stats["failed"] += 1
            logger.warning(
                "discovery.track_failed mint=%s err=%s", resolved.mint, type(exc).__name__
            )
            return
        self._tracked.add(resolved.pool_addr)
        self._stats["tracked"] += 1
        logger.info(
            "discovery.tracked mint=%s pool=%s program=%s",
            resolved.mint,
            resolved.pool_addr[:24],
            program_id[:8],
        )


def build_discovery(
    runner: LaunchRunner | None,
    *,
    api_key: str | None = None,
    http_base: str = "https://mainnet.helius-rpc.com",
) -> PoolDiscovery | None:
    """Construct discovery for a live runner, or None if gated off / no runner.

    Mirrors `launch_runner.build_runner` gating — the lifespan starts discovery
    only when the firewall is enabled and a runner exists.
    """
    if runner is None or not is_firewall_enabled():
        return None
    key = api_key or (os.environ.get("HELIUS_API_KEY") or "").strip()
    if not key or key == "__unset__":
        return None
    return PoolDiscovery(runner, runner.ws_client, make_tx_fetcher(key, http_base=http_base))


__all__ = [
    "DEFAULT_MAX_POOLS",
    "WATCHED_AMM_PROGRAMS",
    "PoolDiscovery",
    "build_discovery",
]
