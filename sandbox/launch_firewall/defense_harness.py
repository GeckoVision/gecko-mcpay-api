"""Launch-Firewall Attack-vs-Defense sandbox — fixture-fed 3-way demo.

Replays scripted scenarios through the REAL ``LaunchMonitor`` + ``HotpathCache``
+ ``safety_gate`` and prints the verdict the firewall would serve. No validator,
no mainnet spend — the free local simulation (Pattern B) that proves "our real
engine catches our real attack" before any live wire / on-chain attack bot.

The 3-way (the concentration-detector proof):

    ATTACK   → block        — the loud snipe: every automation tell on
    EVASION  → block|caution — the slot-spread snipe: EVERY automation tell OFF,
                              float still captured. Previously this reached clean;
                              ``concentrated_capture`` now raises it off the floor
                              (suspicious→caution alone; block with a corroborator).
    ORGANIC  → not block     — a genuine diverse fair launch.

The EVASION leg is the whole point: it proves the firewall has no known
clean-evasion at launch — the residual concentration fingerprint catches the one
snipe that turns every high-precision automation tell off.

Run:
    uv run python sandbox/launch_firewall/defense_harness.py
"""

from __future__ import annotations

import asyncio
from typing import Any

from gecko_core.trade_agent.hotpath.cache import HotpathCache
from gecko_core.trade_agent.hotpath.launch_monitor import LaunchMonitor
from scenarios import (
    brca_bait_pools,
    brca_inflate_then_drain,
    evasion_launch_parsed,
    loud_snipe_parsed,
    organic_launch,
    organic_launch_parsed,
)


async def _run_scenario(name: str, mint: str, *, kind: str) -> dict[str, Any]:
    store = HotpathCache()
    mon = LaunchMonitor(store)
    now = 100_000.0
    created = int(now - 120)  # 2 minutes old — at launch (FP-guard window)
    mon.track(mint, pool_created_ts=created)

    if kind == "attack":
        # the loud snipe through the snipe-gate path + the wash/bait market data
        for ps in loud_snipe_parsed(created_ts=created):
            mon.ingest_parsed_swap(mint, ps)
        for ev in brca_inflate_then_drain(created_ts=created):
            mon.ingest_swap(mint, ev)
        for pool in brca_bait_pools():
            mon.update_pool(mint, pool)
    elif kind == "evasion":
        # EVERY automation tell off; only the structural capture remains. Fed
        # purely on the parsed-tx path (the snipe gate), no bait pools — so the
        # verdict rests on concentrated_capture alone, exactly as on a real chain.
        for ps in evasion_launch_parsed(created_ts=created):
            mon.ingest_parsed_swap(mint, ps)
    else:  # organic
        for ps in organic_launch_parsed(created_ts=created):
            mon.ingest_parsed_swap(mint, ps)
        for ev in organic_launch(created_ts=created):
            mon.ingest_swap(mint, ev)

    await mon.recompute(mint, now)
    warm = await store.get(mint)  # the exact warm read /safety would serve
    resp = warm.to_response(now_epoch=now) if warm else {"gate": "MISS"}
    wash = resp.get("wash_risk") or {}
    snipe = resp.get("snipe") or {}
    return {
        "scenario": name,
        "gate": resp["gate"],
        "wash_label": wash.get("label"),
        "snipe_label": snipe.get("label"),
        "snipe_fired": ", ".join(snipe.get("fired_signals") or []) or "—",
    }


def _verdict(rows: list[dict[str, Any]]) -> tuple[bool, str]:
    attack = next(r for r in rows if r["scenario"].startswith("ATTACK"))
    evasion = next(r for r in rows if r["scenario"].startswith("EVASION"))
    organic = next(r for r in rows if r["scenario"].startswith("ORGANIC"))
    checks = [
        ("attack blocks", attack["gate"] == "block"),
        # the residual catch: the evasion must escalate OFF the clean floor
        ("evasion escalates (block|caution)", evasion["gate"] in ("block", "caution")),
        ("evasion fired concentrated_capture", "concentrated_capture" in evasion["snipe_fired"]),
        ("organic does not block", organic["gate"] != "block"),
    ]
    ok = all(passed for _, passed in checks)
    summary = " | ".join(f"{name}={'OK' if passed else 'FAIL'}" for name, passed in checks)
    return ok, summary


async def main() -> int:
    rows = [
        await _run_scenario("ATTACK loud snipe", "ATKxxxxxxx", kind="attack"),
        await _run_scenario("EVASION slot-spread", "EVAxxxxxxx", kind="evasion"),
        await _run_scenario("ORGANIC fair launch", "GOODxxxxxx", kind="organic"),
    ]
    print("\n  Launch Firewall — Attack vs Evasion vs Organic (fixture sandbox)\n")
    print(f"  {'scenario':<22} {'gate':<9} {'snipe':<14} fired")
    print(f"  {'-' * 22} {'-' * 9} {'-' * 14} {'-' * 30}")
    for r in rows:
        print(f"  {r['scenario']:<22} {r['gate']:<9} {r['snipe_label']!s:<14} {r['snipe_fired']}")
    print()
    ok, summary = _verdict(rows)
    print(f"  RESULT: {summary}")
    if ok:
        print(
            "  PASS: firewall blocks the loud snipe, catches the slot-spread evasion "
            "off the clean floor, and passes the real launch\n"
        )
        return 0
    print("  FAIL: unexpected — investigate thresholds\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
