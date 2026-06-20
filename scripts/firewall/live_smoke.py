#!/usr/bin/env python
"""Launch-firewall live-payload smoke — the Pattern-E reachability proof.

This is the one check that turns the firewall from "live-ready" into "live": it
runs the REAL data path against mainnet for a few minutes and asserts that a real
new launch pool produces a non-null verdict in the cache. Passing this discharges
the `swap_parser` "fixture-only, live jsonParsed unverified" caveat and is the
gate before flipping `GECKO_FIREWALL_ENABLED=1` in prod.

What it does (READ-ONLY — no money path, no signing, no x402):
  1. build the SAME components the API lifespan builds: HotpathCache → LaunchMonitor
     → LaunchRunner (Helius ws) → PoolDiscovery (logsSubscribe on AMM inits)
  2. run for --minutes, recomputing verdicts on a cadence
  3. report discovery + ingest stats, then assert: ≥1 pool discovered, ≥1 swap
     observed, ≥1 non-null verdict reached the cache.

Usage:
    HELIUS_API_KEY=<key> uv run python scripts/firewall/live_smoke.py --minutes 10

Exit 0 = the firewall observes real launches and emits verdicts live (flip-ready).
Exit 1 = something in the live path is dark; do NOT flip the flag — read the stats.

Honest scope: this proves F1+F5 (reserve-derived) reach a verdict live. F2/F4 +
the full snipe gate need the parsed-tx (signer) stream — a later sprint — so a
"clean" verdict here is expected for most pools; the proof is that the path is
WIRED end-to-end, not that any given launch is malicious.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import sys
import time


def _fmt(d: dict[str, object]) -> str:
    return " ".join(f"{k}={v}" for k, v in d.items())


async def run_smoke(minutes: float, recompute_s: float) -> int:
    # Force the firewall on for THIS process only (build_runner/build_discovery
    # gate on it). We do not touch any deployed env.
    os.environ["GECKO_FIREWALL_ENABLED"] = "1"

    key = (os.environ.get("HELIUS_API_KEY") or "").strip()
    if not key or key == "__unset__":
        print("FAIL: HELIUS_API_KEY is not set — the live smoke needs a real key.")
        return 1

    from gecko_core.trade_agent.hotpath.cache import HotpathCache
    from gecko_core.trade_agent.hotpath.launch_monitor import LaunchMonitor
    from gecko_core.trade_agent.hotpath.launch_runner import build_runner
    from gecko_core.trade_agent.hotpath.pool_discovery_runner import build_discovery

    store = HotpathCache()
    monitor = LaunchMonitor(store)
    runner = build_runner(monitor)
    if runner is None:
        print("FAIL: build_runner returned None (firewall gated off or no key).")
        return 1
    discovery = build_discovery(runner)
    if discovery is None:
        print("FAIL: build_discovery returned None.")
        return 1

    ws = runner.ws_client
    if hasattr(ws, "start"):
        await ws.start()
    await runner.start()
    await discovery.start()
    print(
        f"smoke: started — watching {len(discovery._program_ids)} AMM programs "
        f"for {minutes:.0f} min (recompute every {recompute_s:.0f}s)"
    )

    deadline = time.monotonic() + minutes * 60.0
    verdicts_seen = 0
    try:
        while time.monotonic() < deadline:
            await asyncio.sleep(recompute_s)
            await runner.recompute_all()
            # Count how many tracked mints currently have a verdict in the cache.
            mints = {tp.mint for tp in runner._pools.values()}
            verdicts_seen = sum(1 for m in mints if (await store.get(m)) is not None)
            print(
                "smoke: "
                + _fmt(
                    {
                        **discovery.stats,
                        "runner_pools": runner.tracked_pools,
                        "verdicts_in_cache": verdicts_seen,
                        "remaining_s": int(deadline - time.monotonic()),
                    }
                )
            )
    finally:
        await discovery_stop(discovery)
        await runner.stop()
        if hasattr(ws, "stop"):
            await ws.stop()

    # --- assertions: the path must be WIRED end-to-end ---------------------- #
    stats = discovery.stats
    mints = {tp.mint for tp in runner._pools.values()}
    sample = []
    for m in list(mints)[:5]:
        pc = await store.get(m)
        if pc is not None:
            label = getattr(getattr(pc, "wash", None), "label", None)
            sample.append(f"{m[:8]}…→gate={pc.gate} wash={label}")

    print("\n=== SMOKE RESULT ===")
    print(_fmt({**stats, "runner_pools": runner.tracked_pools, "verdicts_in_cache": verdicts_seen}))
    for s in sample:
        print("  verdict:", s)

    checks = {
        "pool discovered": stats.get("tracked", 0) > 0,
        "swap observed (a verdict requires ingest)": verdicts_seen > 0,
    }
    ok = all(checks.values())
    print()
    for name, passed in checks.items():
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
    if not ok:
        print(
            "\nRESULT: FAIL — the live path did not produce a verdict in this window.\n"
            "Do NOT flip GECKO_FIREWALL_ENABLED in prod. Likely causes: no new pools\n"
            "launched in the window (try a longer --minutes at a busy time), the\n"
            "init-log markers need extending for the live AMM log shape, or the\n"
            "swap_parser vault payload differs live (inspect a tracked mint)."
        )
        return 1
    print("\nRESULT: PASS — firewall observes real launches and emits verdicts live. Flip-ready.")
    return 0


async def discovery_stop(discovery: object) -> None:
    # PoolDiscovery has no stop() (subs die with the ws); unsubscribe best-effort.
    for sub in getattr(discovery, "_sub_ids", []):
        unsub = getattr(getattr(discovery, "_ws", None), "unsubscribe", None)
        if unsub is not None:
            with contextlib.suppress(Exception):
                await unsub(sub)


def main() -> int:
    ap = argparse.ArgumentParser(description="Launch-firewall live-payload smoke")
    ap.add_argument("--minutes", type=float, default=10.0, help="how long to watch (default 10)")
    ap.add_argument(
        "--recompute-s", type=float, default=15.0, help="recompute cadence (default 15)"
    )
    args = ap.parse_args()
    return asyncio.run(run_smoke(args.minutes, args.recompute_s))


if __name__ == "__main__":
    sys.exit(main())
