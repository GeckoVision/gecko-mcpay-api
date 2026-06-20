"""Continuous Launch-Firewall monitor — ingest swaps, recompute, write the cache.

Step 3 of the Launch Firewall build order. This is the orchestrator that turns
the realtime swap stream into pre-computed verdicts:

    swap/pool event ─▶ TokenState (per mint) ─▶ to_snapshot ─▶ assess_wash_risk
                                                          └▶ safety_gate ─▶ cache

The serve path (``/safety``) then reads the cache and returns the pre-computed
``gate`` in single-digit ms — no network on the warm path.

Scope of this step: the in-memory orchestration + the cache write. The live wire
(``HeliusWebSocketClient.subscribe_program`` → ``ingest_swap``) lands in step 6;
until then the monitor is driven by recorded fixtures (the sandbox
``defense_harness``) — which is exactly how we get a free, mainnet-spend-free
attack→detection proof first (Pattern B).

Hotpath isolation: ``pydantic`` + stdlib + sibling hotpath modules only. No db /
rag / orchestration. The static ``SafetyBlock`` is accepted as an opaque
duck-typed object (or ``None``) and carried as a dict — the monitor never imports
the orchestration models.
"""

from __future__ import annotations

import logging
from typing import Any

from gecko_core.trade_agent.hotpath.precomputed import (
    PrecomputedSafety,
    SafetyStore,
    safety_gate,
)
from gecko_core.trade_agent.hotpath.snipe_features import ParsedSwap
from gecko_core.trade_agent.hotpath.snipe_gate import TipFloor, assess_snipe
from gecko_core.trade_agent.hotpath.token_state import SwapEvent, TokenState
from gecko_core.trade_agent.hotpath.wash_signals import PoolSnapshot, assess_wash_risk

logger = logging.getLogger(__name__)

# Per-tier freshness: market/flow signals churn fast, so verdicts are short-TTL.
DEFAULT_TTL_S = 30.0
DEFAULT_WINDOW_S = 300.0
DEFAULT_MAX_SWAPS = 500


class LaunchMonitor:
    """Owns per-mint :class:`TokenState` and writes :class:`PrecomputedSafety` to
    a shared :class:`SafetyStore`. One instance is shared between the ingest task
    and the FastAPI app (via ``app.state``) so the serve path reads what the
    monitor wrote — step 4 wires that.
    """

    def __init__(
        self,
        store: SafetyStore,
        *,
        default_ttl_s: float = DEFAULT_TTL_S,
        window_s: float = DEFAULT_WINDOW_S,
        max_swaps: int = DEFAULT_MAX_SWAPS,
        cex_funders: frozenset[str] = frozenset(),
    ) -> None:
        self._store = store
        self._states: dict[str, TokenState] = {}
        self._default_ttl_s = default_ttl_s
        self._window_s = window_s
        self._max_swaps = max_swaps
        self._cex_funders = cex_funders

    # -- watchlist ---------------------------------------------------------- #

    def track(self, mint: str, *, pool_created_ts: int | None = None) -> TokenState:
        """Add ``mint`` to the watchlist (idempotent); returns its state."""
        st = self._states.get(mint)
        if st is None:
            st = TokenState(
                mint,
                pool_created_ts=pool_created_ts,
                max_swaps=self._max_swaps,
                cex_funders=self._cex_funders,
            )
            self._states[mint] = st
        elif pool_created_ts is not None and st.pool_created_ts is None:
            st.pool_created_ts = pool_created_ts
        return st

    def is_tracked(self, mint: str) -> bool:
        return mint in self._states

    def untrack(self, mint: str) -> None:
        """Drop a mint that has graduated out of launch mode (frees memory)."""
        self._states.pop(mint, None)

    @property
    def tracked_count(self) -> int:
        return len(self._states)

    # -- ingest (realtime, O(1)) ------------------------------------------- #

    def ingest_swap(self, mint: str, swap: SwapEvent) -> None:
        """Record a reserve-derived swap (auto-tracks the mint if new)."""
        self.track(mint).ingest_swap(swap)

    def ingest_parsed_swap(self, mint: str, swap: ParsedSwap) -> None:
        """Record a signer-level parsed swap for the snipe gate (auto-tracks)."""
        self.track(mint).ingest_parsed_swap(swap)

    def update_pool(self, mint: str, pool: PoolSnapshot) -> None:
        self.track(mint).update_pool(pool)

    def set_wallet_funding(
        self,
        mint: str,
        wallet: str,
        *,
        funder: str | None,
        funded_ts: int | None = None,
        funded_amount: float | None = None,
    ) -> None:
        self.track(mint).set_wallet_funding(
            wallet, funder=funder, funded_ts=funded_ts, funded_amount=funded_amount
        )

    # -- recompute (on cadence / on event) --------------------------------- #

    async def recompute(
        self,
        mint: str,
        now: float,
        *,
        static_block: Any | None = None,
        tip_floor: TipFloor | None = None,
        ttl_s: float | None = None,
    ) -> PrecomputedSafety | None:
        """Score ``mint`` from its current state and write the verdict to cache.

        ``static_block`` is the optional ``SafetyBlock``-shaped static read
        (honeypot / mcap / holders). When ``None`` the verdict rests on the flow
        (wash) read alone — which is still decisive: ``safety_gate`` blocks on a
        ``manipulated`` wash read even with no static layer. Returns the written
        :class:`PrecomputedSafety`, or ``None`` if the mint isn't tracked.
        """
        st = self._states.get(mint)
        if st is None:
            return None

        snap = st.to_snapshot(now, window_s=self._window_s)
        wash = assess_wash_risk(snap)
        snipe_snap = st.to_snipe_snapshot(now)
        snipe = assess_snipe(snipe_snap, tip_floor) if snipe_snap is not None else None
        gate = safety_gate(static_block, wash=wash, snipe=snipe)

        if static_block is not None:
            safety_dict = static_block.model_dump(mode="json")
        else:
            # No static read yet — be explicit (fail-OPEN), never fake "checked".
            safety_dict = {
                "checked": False,
                "rug_flags": ["static_read_pending"],
                "source": "monitor",
            }

        pc = PrecomputedSafety(
            mint=mint,
            gate=gate,
            safety=safety_dict,
            wash=wash,
            snipe=snipe,
            computed_at_epoch=now,
            source="monitor",
        )
        await self._store.set(mint, pc, ttl_s or self._default_ttl_s)
        logger.debug(
            "launch_monitor.recompute mint=%s gate=%s wash=%s",
            mint,
            gate,
            wash.label if wash is not None else None,
        )
        return pc
