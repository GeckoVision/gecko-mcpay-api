"""Launch-Firewall latency harness (step 5) — measure, don't assert.

Reports the three latencies the architecture deliberately keeps separate (never
conflated):

1. **warm-serve** — what /safety returns on a cache hit: a dict read + freshness
   check + ``to_response``. This is the real "<400ms" number; expect sub-ms.
2. **cold engine overhead** — serve_safety's own work on a miss (model build +
   gate + cache set), with the source read stubbed to instant. The REAL cold
   latency = this + the source round-trip (~310ms-4s, network-bound), which this
   harness does NOT measure (no creds offline) — we say so rather than fake it.
3. **detection** — events from attack-start to the gate flipping to ``block`` in
   the cache (the real Block-Zero KPI). Measured against the fixture attack.

Run:
    uv run python sandbox/launch_firewall/latency_harness.py
"""

from __future__ import annotations

import asyncio
import time

from gecko_api.safety_fast import serve_safety
from gecko_core.orchestration.trade_panel import safety_check as sc
from gecko_core.trade_agent.hotpath.cache import HotpathCache
from gecko_core.trade_agent.hotpath.launch_monitor import LaunchMonitor
from scenarios import brca_bait_pools, brca_inflate_then_drain


def _pct(vals_ns: list[int], q: float) -> float:
    """Percentile in milliseconds (nearest-rank)."""
    s = sorted(vals_ns)
    idx = min(len(s) - 1, max(0, round(q * (len(s) - 1))))
    return s[idx] / 1e6


def _row(label: str, vals_ns: list[int]) -> str:
    p50, p90, p99 = _pct(vals_ns, 0.50), _pct(vals_ns, 0.90), _pct(vals_ns, 0.99)
    mx = max(vals_ns) / 1e6
    return f"  {label:<26} {p50:>8.4f} {p90:>8.4f} {p99:>8.4f} {mx:>8.4f}"


def _drive_attack(mon: LaunchMonitor, mint: str, created: int) -> None:
    for ev in brca_inflate_then_drain(created_ts=created):
        mon.ingest_swap(mint, ev)
    for pool in brca_bait_pools():
        mon.update_pool(mint, pool)


async def main(warm_iters: int = 2000, cold_iters: int = 500) -> None:
    store = HotpathCache()
    mon = LaunchMonitor(store)
    now = 100_000.0
    created = int(now - 120)

    # ---- warm-serve: preload, then hammer the cache ---------------------- #
    mon.track("WARM", pool_created_ts=created)
    _drive_attack(mon, "WARM", created)
    await mon.recompute("WARM", now)
    warm_ns: list[int] = []
    for _ in range(warm_iters):
        t0 = time.perf_counter_ns()
        await serve_safety("WARM", store, mon, now=now)
        warm_ns.append(time.perf_counter_ns() - t0)

    # ---- cold engine overhead: source stubbed instant, unique mints ------ #
    async def _instant(*_a: object, **_k: object):
        from gecko_core.orchestration.trade_panel.models import SafetyBlock

        return SafetyBlock(checked=True, rug_flags=[])

    orig = sc.evaluate_contract_safety
    sc.evaluate_contract_safety = _instant  # type: ignore[assignment]
    cold_ns: list[int] = []
    try:
        for i in range(cold_iters):
            t0 = time.perf_counter_ns()
            await serve_safety(f"COLD{i}", store, mon, now=now)
            cold_ns.append(time.perf_counter_ns() - t0)
    finally:
        sc.evaluate_contract_safety = orig  # type: ignore[assignment]

    # ---- detection: events until the cache shows block ------------------- #
    dstore = HotpathCache()
    dmon = LaunchMonitor(dstore)
    dmon.track("DET", pool_created_ts=created)
    swaps = brca_inflate_then_drain(created_ts=created)
    pools = brca_bait_pools()
    for p in pools:
        dmon.update_pool("DET", p)
    detect_event = None
    for n, ev in enumerate(swaps, start=1):
        dmon.ingest_swap("DET", ev)
        pc = await dmon.recompute("DET", now)
        if pc and pc.gate == "block":
            detect_event = n
            break

    print("\n  Launch Firewall — latency (ms)\n")
    print(f"  {'path':<26} {'p50':>8} {'p90':>8} {'p99':>8} {'max':>8}")
    print(f"  {'-' * 26} {'-' * 8} {'-' * 8} {'-' * 8} {'-' * 8}")
    print(_row(f"warm-serve (n={warm_iters})", warm_ns))
    print(_row(f"cold-overhead (n={cold_iters})", cold_ns))
    print(
        f"\n  detection: gate→block after {detect_event} swap events (attack = {len(swaps)} events)"
    )
    print(
        "\n  NOTE: real cold latency = cold-overhead + source round-trip "
        "(~310ms-4s, network-bound, NOT measured offline)."
    )
    print("  The <400ms target is met by the warm path; reasoning never sits on the request.\n")


if __name__ == "__main__":
    asyncio.run(main())
