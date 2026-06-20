"""End-to-end attack→detection proof for the Launch Firewall monitor (step 3).

Drives a full BrCA-shaped attack (thin-pool buy-loop + multi-pool price bait)
through the REAL monitor + the REAL HotpathCache, then asserts the cache holds a
`block` verdict readable as a warm hit. This is the Pattern-E reachability probe
at the monitor boundary: not "each layer works alone" but "an attack actually
reaches the served cache as a block".
"""

from __future__ import annotations

import pytest
from gecko_core.trade_agent.hotpath.cache import HotpathCache
from gecko_core.trade_agent.hotpath.launch_monitor import LaunchMonitor
from gecko_core.trade_agent.hotpath.token_state import SwapEvent
from gecko_core.trade_agent.hotpath.wash_signals import PoolSnapshot
from pydantic import BaseModel


class _FakeStaticBlock(BaseModel):
    """A clean static SafetyBlock stand-in (has model_dump; gate reads attrs)."""

    checked: bool = True
    honeypot: bool = False
    rug_flags: list[str] = []
    information_mev: None = None


def _run_brca_attack(mon: LaunchMonitor, mint: str, *, created_ts: int) -> None:
    """38 tiny buys from 3 wallets, price climbing, + a dead overpriced bait pool."""
    price = 1.0
    for i in range(38):
        mon.ingest_swap(
            mint,
            SwapEvent(
                ts=float(created_ts + i),
                wallet=f"bot{i % 3}",
                side="buy",
                notional_usd=30.0,
                price_usd=price,
            ),
        )
        price *= 1.01  # ~+45% over the loop
    # The deep "truth" pool + a thin dead satellite quoting way above the index.
    mon.update_pool(
        mint,
        PoolSnapshot(
            pool_addr="deep_pool", spot_price_usd=1.45, tvl_usd=400_000.0, swap_count_5m=38
        ),
    )
    mon.update_pool(
        mint,
        PoolSnapshot(pool_addr="bait_pool_xx", spot_price_usd=3.5, tvl_usd=200.0, swap_count_5m=0),
    )


@pytest.mark.asyncio
async def test_brca_attack_reaches_cache_as_block():
    store = HotpathCache()
    mon = LaunchMonitor(store)
    now = 100_000.0
    created = int(now - 120)  # 2 minutes old — at launch
    mon.track("BrCA", pool_created_ts=created)
    _run_brca_attack(mon, "BrCA", created_ts=created)

    pc = await mon.recompute("BrCA", now)
    assert pc is not None
    assert pc.gate == "block"
    assert pc.wash is not None
    assert pc.wash.label == "manipulated"
    assert {"thin_pool_buy_loop", "multi_pool_price_bait"} <= set(pc.wash.fired_signals)

    # The warm read: what /safety would serve, straight from the cache.
    warm = await store.get("BrCA")
    assert warm is not None
    resp = warm.to_response(now_epoch=now)
    assert resp["gate"] == "block"
    assert resp["wash_risk"]["label"] == "manipulated"
    assert resp["source"] == "monitor"


@pytest.mark.asyncio
async def test_clean_token_with_static_block_serves_ok():
    store = HotpathCache()
    mon = LaunchMonitor(store)
    now = 100_000.0
    mon.track("CLEAN", pool_created_ts=int(now - 50_000))  # aged, established
    # Organic flow: many buyers, fat-tailed sizes, some sells.
    for i in range(60):
        mon.ingest_swap(
            "CLEAN",
            SwapEvent(
                ts=now - 200 + i,
                wallet=f"u{i}",
                side="buy",
                notional_usd=100.0 + i * 50,
                price_usd=1.0,
            ),
        )
    for i in range(20):
        mon.ingest_swap(
            "CLEAN",
            SwapEvent(
                ts=now - 100 + i, wallet=f"s{i}", side="sell", notional_usd=120.0, price_usd=1.0
            ),
        )
    pc = await mon.recompute("CLEAN", now, static_block=_FakeStaticBlock())
    assert pc is not None
    assert pc.wash is not None
    assert pc.wash.label == "clean"
    assert pc.gate == "ok"


@pytest.mark.asyncio
async def test_no_static_block_clean_flow_is_unknown():
    # No static read + benign flow → fail-OPEN 'unknown', never a fake 'ok'.
    store = HotpathCache()
    mon = LaunchMonitor(store)
    now = 100_000.0
    mon.track("X", pool_created_ts=int(now - 50_000))
    mon.ingest_swap(
        "X", SwapEvent(ts=now - 10, wallet="a", side="buy", notional_usd=100.0, price_usd=1.0)
    )
    pc = await mon.recompute("X", now)
    assert pc is not None
    assert pc.gate == "unknown"


@pytest.mark.asyncio
async def test_recompute_untracked_returns_none():
    store = HotpathCache()
    mon = LaunchMonitor(store)
    assert await mon.recompute("nope", 1.0) is None


@pytest.mark.asyncio
async def test_track_untrack_lifecycle():
    store = HotpathCache()
    mon = LaunchMonitor(store)
    mon.track("A")
    mon.ingest_swap("B", SwapEvent(ts=1.0, wallet="w", side="buy", notional_usd=1.0))  # auto-track
    assert mon.tracked_count == 2
    assert mon.is_tracked("A") and mon.is_tracked("B")
    mon.untrack("A")
    assert not mon.is_tracked("A")
    assert mon.tracked_count == 1


@pytest.mark.asyncio
async def test_parsed_swaps_fold_snipe_into_block():
    """THE keystone probe: signer-level parsed swaps → snipe verdict → cache block.

    A fresh launch sniped by 4 fresh wallets co-buying one slot via Jito bundles
    through a custom program reaches the served cache as `block` — the parsed-tx
    path lighting up the snipe gate end-to-end through the real monitor.
    """
    from gecko_core.trade_agent.hotpath.snipe_features import LAMPORTS_PER_SOL, ParsedSwap

    store = HotpathCache()
    mon = LaunchMonitor(store)
    now = 1030.0
    mon.track("MINT", pool_created_ts=1000)  # 30s-old launch
    sniper_prog = "Sn1per1111111111111111111111111111111111111"
    for i in range(4):
        mon.ingest_parsed_swap(
            "MINT",
            ParsedSwap(
                signer=f"W{i}",
                slot=500,
                is_buy=True,
                notional_sol=1.0,
                tip_lamports=int(2e-4 * LAMPORTS_PER_SOL),
                program_ids=[sniper_prog],
                wallet_age_s=120.0,
                timestamp=1000.0,
            ),
        )
    pc = await mon.recompute("MINT", now)
    assert pc is not None
    assert pc.snipe is not None
    assert pc.snipe.label in ("likely_sniped", "confirmed_wash")
    assert pc.gate == "block"
    # and it's served warm with the snipe block attached
    served = pc.to_response(now)
    assert served["gate"] == "block" and served["snipe"] is not None


@pytest.mark.asyncio
async def test_no_parsed_swaps_leaves_snipe_absent():
    store = HotpathCache()
    mon = LaunchMonitor(store)
    now = 100_000.0
    mon.track("X", pool_created_ts=int(now - 50_000))
    pc = await mon.recompute("X", now)
    assert pc is not None and pc.snipe is None  # fail-OPEN: no fabricated verdict
