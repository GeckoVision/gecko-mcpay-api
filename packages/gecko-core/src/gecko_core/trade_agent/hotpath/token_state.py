"""Rolling per-mint state for the Launch Firewall — turns a swap stream into a
pure :class:`FirewallSnapshot` the scorer can read.

Step 2 of the Launch Firewall build order. The continuous monitor (step 3) feeds
each on-chain swap / pool update into a :class:`TokenState`; on cadence it calls
:meth:`TokenState.to_snapshot` and hands the result to
:func:`gecko_core.trade_agent.hotpath.wash_signals.assess_wash_risk`.

Design constraints (hotpath isolation):

* **Stdlib + pydantic + sibling hotpath modules only.** No db / rag / orchestration.
* **Bounded memory.** Swaps live in a ``deque(maxlen=…)`` ring buffer; a launch
  can spray thousands of sybil wallets, so we retain only the most recent N swaps
  and derive per-wallet aggregates from that window. Per-token memory is O(N).
* **Pure derivation.** :meth:`to_snapshot` takes ``now`` explicitly (no clock
  call inside) so it is deterministic and trivially testable. The caller stamps
  the time.

This is an accumulator, not a scorer — it carries NO thresholds. All judgement
lives in ``wash_signals`` (Pattern A: one place for the rules).
"""

from __future__ import annotations

from collections import deque
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from gecko_core.trade_agent.hotpath.wash_signals import (
    FirewallSnapshot,
    FlowWindow,
    PoolSnapshot,
    WalletSnapshot,
)

Side = Literal["buy", "sell"]


class SwapEvent(BaseModel):
    """One observed DEX swap (the realtime unit the monitor ingests)."""

    model_config = ConfigDict(extra="forbid")

    ts: float = Field(..., description="Unix epoch seconds the swap landed.")
    wallet: str = Field(..., description="Signer / maker wallet.")
    side: Side = Field(..., description="'buy' (base in) or 'sell' (base out).")
    notional_usd: float = Field(..., ge=0.0, description="Trade size in USD.")
    price_usd: float | None = Field(default=None, ge=0.0, description="Execution price in USD.")
    pool_addr: str | None = Field(default=None, description="Pool the swap hit.")


def _percentile(sorted_vals: list[float], pct: float) -> float | None:
    """Nearest-rank percentile of an already-sorted list; None if empty."""
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    # nearest-rank: rank = ceil(pct * n), 1-indexed.
    import math

    rank = max(1, math.ceil(pct * len(sorted_vals)))
    return sorted_vals[min(rank, len(sorted_vals)) - 1]


class _WalletFunding(BaseModel):
    """Batch-filled funding provenance for a wallet (set by the F4 batch pass)."""

    model_config = ConfigDict(extra="forbid")

    funder: str | None = None
    funded_ts: int | None = None
    funded_amount: float | None = None


class TokenState:
    """Mutable rolling state for one mint. Not a pydantic model (it holds a deque
    and is mutated in place by the monitor)."""

    __slots__ = ("_funding", "_pools", "_swaps", "cex_funders", "mint", "pool_created_ts")

    def __init__(
        self,
        mint: str,
        *,
        pool_created_ts: int | None = None,
        max_swaps: int = 500,
        cex_funders: frozenset[str] = frozenset(),
    ) -> None:
        self.mint = mint
        self.pool_created_ts = pool_created_ts
        self.cex_funders = cex_funders
        self._swaps: deque[SwapEvent] = deque(maxlen=max_swaps)
        self._pools: dict[str, PoolSnapshot] = {}
        self._funding: dict[str, _WalletFunding] = {}

    # -- ingest (realtime, O(1)) -------------------------------------------- #

    def ingest_swap(self, ev: SwapEvent) -> None:
        """Record a swap. O(1) append to the bounded ring buffer."""
        self._swaps.append(ev)

    def update_pool(self, pool: PoolSnapshot) -> None:
        """Upsert a pool's latest state (keyed by ``pool_addr``)."""
        self._pools[pool.pool_addr] = pool

    def set_wallet_funding(
        self,
        wallet: str,
        *,
        funder: str | None,
        funded_ts: int | None = None,
        funded_amount: float | None = None,
    ) -> None:
        """Attach one-hop funding provenance for a wallet (the F4 batch pass)."""
        self._funding[wallet] = _WalletFunding(
            funder=funder, funded_ts=funded_ts, funded_amount=funded_amount
        )

    # -- derive (on cadence, pure) ------------------------------------------ #

    def _build_window(self, now: float, window_s: float) -> FlowWindow | None:
        lo = now - window_s
        rows = [s for s in self._swaps if s.ts >= lo]
        if not rows:
            return None
        buys = [s for s in rows if s.side == "buy"]
        sells = [s for s in rows if s.side == "sell"]
        notionals = sorted(s.notional_usd for s in rows)
        priced = [s for s in rows if s.price_usd is not None]
        price_open = priced[0].price_usd if priced else None
        price_close = priced[-1].price_usd if priced else None
        return FlowWindow(
            buy_count=len(buys),
            sell_count=len(sells),
            buy_vol_usd=sum(s.notional_usd for s in buys),
            sell_vol_usd=sum(s.notional_usd for s in sells),
            unique_buyers=len({s.wallet for s in buys}),
            unique_sellers=len({s.wallet for s in sells}),
            notional_p50=_percentile(notionals, 0.50),
            notional_p95=_percentile(notionals, 0.95),
            price_open=price_open,
            price_close=price_close,
        )

    def _build_wallets(self) -> list[WalletSnapshot]:
        """Per-wallet aggregates over the retained swap window."""
        buy_vol: dict[str, float] = {}
        sell_vol: dict[str, float] = {}
        buy_n: dict[str, int] = {}
        sell_n: dict[str, int] = {}
        for s in self._swaps:
            if s.side == "buy":
                buy_vol[s.wallet] = buy_vol.get(s.wallet, 0.0) + s.notional_usd
                buy_n[s.wallet] = buy_n.get(s.wallet, 0) + 1
            else:
                sell_vol[s.wallet] = sell_vol.get(s.wallet, 0.0) + s.notional_usd
                sell_n[s.wallet] = sell_n.get(s.wallet, 0) + 1
        wallets = set(buy_vol) | set(sell_vol)
        out: list[WalletSnapshot] = []
        for w in wallets:
            fund = self._funding.get(w)
            # round_trips ≈ paired buy↔sell count (the wash churn proxy).
            round_trips = min(buy_n.get(w, 0), sell_n.get(w, 0))
            out.append(
                WalletSnapshot(
                    address=w,
                    buy_vol_usd=buy_vol.get(w, 0.0),
                    sell_vol_usd=sell_vol.get(w, 0.0),
                    round_trips=round_trips,
                    funder=fund.funder if fund else None,
                    funded_ts=fund.funded_ts if fund else None,
                    funded_amount=fund.funded_amount if fund else None,
                )
            )
        # Cap to top-N by total volume — only the volume-carriers matter.
        out.sort(key=lambda w: w.buy_vol_usd + w.sell_vol_usd, reverse=True)
        return out

    def _index_price(self) -> float | None:
        """Liquidity-weighted price across pools — the single source of truth."""
        num = 0.0
        den = 0.0
        for p in self._pools.values():
            if p.spot_price_usd is None or p.tvl_usd is None or p.tvl_usd <= 0:
                continue
            num += p.spot_price_usd * p.tvl_usd
            den += p.tvl_usd
        return (num / den) if den > 0 else None

    def to_snapshot(
        self,
        now: float,
        *,
        window_s: float = 300.0,
        max_wallets: int = 200,
    ) -> FirewallSnapshot:
        """Build the pure :class:`FirewallSnapshot` the scorer consumes.

        ``now`` is supplied by the caller (no clock call here) so the derivation
        is deterministic. ``net_fresh_inflow_usd`` is approximated as window
        buy-volume minus sell-volume (net external capital this window) — the F2
        MM-vs-wash guard input; refined when a true inflow source lands.
        """
        window = self._build_window(now, window_s)
        wallets = self._build_wallets()[:max_wallets]
        age = None
        if self.pool_created_ts is not None:
            age = max(0.0, now - float(self.pool_created_ts))
        net_inflow = None
        if window is not None:
            net_inflow = window.buy_vol_usd - window.sell_vol_usd
        return FirewallSnapshot(
            mint=self.mint,
            age_seconds=age,
            window=window,
            pools=list(self._pools.values()),
            wallets=wallets,
            index_price_usd=self._index_price(),
            net_fresh_inflow_usd=net_inflow,
            pool_created_ts=self.pool_created_ts,
            cex_funders=self.cex_funders,
        )
