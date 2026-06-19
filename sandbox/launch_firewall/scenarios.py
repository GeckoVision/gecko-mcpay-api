"""Attack/benign scenario generators for the Launch-Firewall sandbox.

Pure fixture builders — each returns a list of (kind, payload) events the
defense harness replays into the real ``LaunchMonitor``. No I/O, no validator;
this is the free local simulation (Pattern B) that falsifies the firewall before
any mainnet spend. The same scenarios are reused by the real-validator path
(step 6) by translating these events into on-chain transactions.
"""

from __future__ import annotations

from gecko_core.trade_agent.hotpath.token_state import SwapEvent
from gecko_core.trade_agent.hotpath.wash_signals import PoolSnapshot


def brca_inflate_then_drain(created_ts: int = 0) -> list[SwapEvent]:
    """The BrCA headline: 38 tiny buys from 3 bot wallets, price climbing, 0 sells."""
    out: list[SwapEvent] = []
    price = 1.0
    for i in range(38):
        out.append(
            SwapEvent(
                ts=float(created_ts + i),
                wallet=f"bot{i % 3}",
                side="buy",
                notional_usd=30.0,
                price_usd=price,
            )
        )
        price *= 1.01
    return out


def brca_bait_pools() -> list[PoolSnapshot]:
    """The deep 'truth' pool + a thin dead satellite quoting far above the index."""
    return [
        PoolSnapshot(
            pool_addr="deep_pool", spot_price_usd=1.45, tvl_usd=400_000.0, swap_count_5m=38
        ),
        PoolSnapshot(pool_addr="bait_pool_xx", spot_price_usd=3.5, tvl_usd=200.0, swap_count_5m=0),
    ]


def organic_launch(created_ts: int = 0) -> list[SwapEvent]:
    """A genuine fair launch: many unique buyers, fat-tailed sizes, real sells."""
    out: list[SwapEvent] = []
    for i in range(60):
        out.append(
            SwapEvent(
                ts=float(created_ts + i),
                wallet=f"u{i}",
                side="buy",
                notional_usd=100.0 + i * 50,
                price_usd=1.0,
            )
        )
    for i in range(20):
        out.append(
            SwapEvent(
                ts=float(created_ts + 60 + i),
                wallet=f"s{i}",
                side="sell",
                notional_usd=120.0,
                price_usd=1.0,
            )
        )
    return out
