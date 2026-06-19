"""Warm-serve latency guardrail (Launch Firewall step 5).

Not a benchmark — a regression guard. It asserts the warm /safety path stays
network-free and cheap (a dict read + freshness check + to_response). A generous
CI-safe p99 bound catches the failure mode where someone accidentally
reintroduces a network call on the warm path; the real number lives in
``sandbox/launch_firewall/latency_harness.py``.
"""

from __future__ import annotations

import os
import time

os.environ.setdefault("X402_MODE", "stub")
os.environ.setdefault("GECKO_WALLET_ADDRESS", "STUB_WALLET_ADDRESS_NOT_FOR_LIVE")
os.environ.setdefault("TAVILY_API_KEY", "test-stub-key")

from gecko_api.safety_fast import serve_safety
from gecko_core.trade_agent.hotpath.cache import HotpathCache
from gecko_core.trade_agent.hotpath.launch_monitor import LaunchMonitor
from gecko_core.trade_agent.hotpath.token_state import SwapEvent
from gecko_core.trade_agent.hotpath.wash_signals import PoolSnapshot

WARM_P99_BOUND_MS = 50.0  # loose: CI is noisy; the real number is ~sub-ms


async def test_warm_serve_p99_under_bound() -> None:
    store = HotpathCache()
    mon = LaunchMonitor(store)
    now = 100_000.0
    created = int(now - 120)
    mon.track("WARM", pool_created_ts=created)
    price = 1.0
    for i in range(38):
        mon.ingest_swap(
            "WARM",
            SwapEvent(
                ts=float(created + i),
                wallet=f"b{i % 3}",
                side="buy",
                notional_usd=30.0,
                price_usd=price,
            ),
        )
        price *= 1.01
    # Deep "truth" pool + dead overpriced satellite → F1 + F5 → manipulated → block.
    mon.update_pool(
        "WARM",
        PoolSnapshot(pool_addr="deep", spot_price_usd=1.45, tvl_usd=400_000.0, swap_count_5m=38),
    )
    mon.update_pool(
        "WARM", PoolSnapshot(pool_addr="bait", spot_price_usd=3.5, tvl_usd=200.0, swap_count_5m=0)
    )
    await mon.recompute("WARM", now)

    samples: list[int] = []
    for _ in range(300):
        t0 = time.perf_counter_ns()
        resp = await serve_safety("WARM", store, mon, now=now)
        samples.append(time.perf_counter_ns() - t0)
    assert resp["gate"] == "block"  # still serving the right verdict
    assert resp["source"] == "monitor"

    samples.sort()
    p99_ms = samples[min(len(samples) - 1, round(0.99 * (len(samples) - 1)))] / 1e6
    assert p99_ms < WARM_P99_BOUND_MS, f"warm p99 {p99_ms:.3f}ms exceeded {WARM_P99_BOUND_MS}ms"
