"""Launch-Firewall Attack-vs-Defense sandbox — fixture-fed demo (step 3).

Replays scripted attack/benign scenarios through the REAL ``LaunchMonitor`` +
``HotpathCache`` + ``safety_gate`` and prints the verdict the firewall would
serve. No validator, no mainnet spend — the free local simulation (Pattern B)
that proves "our real engine catches our real attack" before the live wire
(step 6) and the on-chain attack bot (step 7).

Run:
    uv run python sandbox/launch_firewall/defense_harness.py
"""

from __future__ import annotations

import asyncio

from gecko_core.trade_agent.hotpath.cache import HotpathCache
from gecko_core.trade_agent.hotpath.launch_monitor import LaunchMonitor
from scenarios import brca_bait_pools, brca_inflate_then_drain, organic_launch


async def _run_scenario(name: str, mint: str, *, attack: bool) -> dict:
    store = HotpathCache()
    mon = LaunchMonitor(store)
    now = 100_000.0
    created = int(now - 120)  # 2 minutes old — at launch
    mon.track(mint, pool_created_ts=created)

    if attack:
        for ev in brca_inflate_then_drain(created_ts=created):
            mon.ingest_swap(mint, ev)
        for pool in brca_bait_pools():
            mon.update_pool(mint, pool)
    else:
        for ev in organic_launch(created_ts=created):
            mon.ingest_swap(mint, ev)

    await mon.recompute(mint, now)
    warm = await store.get(mint)  # the exact warm read /safety would serve
    resp = warm.to_response(now_epoch=now) if warm else {"gate": "MISS"}
    wash = resp.get("wash_risk") or {}
    return {
        "scenario": name,
        "gate": resp["gate"],
        "wash_label": wash.get("label"),
        "fired": ", ".join(wash.get("fired_signals") or []) or "—",
    }


async def main() -> None:
    rows = [
        await _run_scenario("BrCA inflate-then-drain", "BrCAxxxxxx", attack=True),
        await _run_scenario("Organic fair launch", "GOODxxxxxx", attack=False),
    ]
    print("\n  Launch Firewall — Attack vs Defense (fixture sandbox)\n")
    print(f"  {'scenario':<28} {'gate':<9} {'wash':<12} fired")
    print(f"  {'-' * 28} {'-' * 9} {'-' * 12} {'-' * 30}")
    for r in rows:
        print(f"  {r['scenario']:<28} {r['gate']:<9} {r['wash_label']!s:<12} {r['fired']}")
    print()
    # The money shot: the attack is blocked, the real launch is not.
    attack = next(r for r in rows if r["scenario"].startswith("BrCA"))
    clean = next(r for r in rows if r["scenario"].startswith("Organic"))
    print(f"  RESULT: attack→{attack['gate']}  |  organic→{clean['gate']}")
    if attack["gate"] == "block" and clean["gate"] != "block":
        print("  ✅ firewall blocks the manufactured launch, passes the real one\n")
    else:
        print("  ❌ unexpected — investigate thresholds\n")


if __name__ == "__main__":
    asyncio.run(main())
