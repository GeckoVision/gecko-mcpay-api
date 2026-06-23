"""Launch-Firewall attack bot (step 7).

Drives a manipulation scenario against the Defense and reports detection latency
(events from attack-start to the cache gate flipping to ``block``).

Two modes:

* ``--fixture`` (default, runnable now): replays a scripted scenario through the
  REAL ``LaunchMonitor`` in-process — no validator, no spend. This is the proof
  that our real engine catches our real attack pattern, and it measures the
  Block-Zero KPI (detection in N events). Same path the CI gate exercises.

* ``--onchain`` (scaffold): the live-fidelity path against ``validator.sh`` — seed
  a real AMM pool on the local test-validator, run a wash/MEV attacker signing
  real (local) transactions, and let the monitor consume the validator's
  ``programSubscribe`` stream. This is the remaining live build (it deploys a
  program + signs txs); it is intentionally NOT auto-run. See README + the
  architecture synthesis for the wiring (HeliusWebSocketClient → ws://127.0.0.1:8900).

Run:
    uv run python sandbox/launch_firewall/attack_bot.py            # fixture (brca)
    uv run python sandbox/launch_firewall/attack_bot.py --scenario evasion
    uv run python sandbox/launch_firewall/attack_bot.py --scenario organic
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from gecko_core.trade_agent.hotpath.cache import HotpathCache
from gecko_core.trade_agent.hotpath.launch_monitor import LaunchMonitor
from scenarios import (
    brca_bait_pools,
    brca_inflate_then_drain,
    evasion_launch_parsed,
    organic_launch_parsed,
)


async def _run_swapevent_scenario(mon: LaunchMonitor, mint: str, swaps: list, now: float) -> int:
    """Latency loop for the wash-path (SwapEvent) scenarios — block-at-event N."""
    print(f"  ({len(swaps)} SwapEvents)\n")
    detect_at = None
    for n, ev in enumerate(swaps, start=1):
        mon.ingest_swap(mint, ev)
        pc = await mon.recompute(mint, now)
        if pc and pc.gate == "block" and detect_at is None:
            detect_at = n
            print(
                f"  gate->BLOCK at event {n}/{len(swaps)}  "
                f"(wash={pc.wash.label if pc.wash else None}, "
                f"signals={pc.wash.fired_signals if pc.wash else []})"
            )
            break
    if detect_at is None:
        final = await mon.recompute(mint, now)
        gate = final.gate if final else "?"
        print(f"  no block — final gate={gate} (expected for an organic launch)")
    return 0


async def _run_parsed_scenario(mon: LaunchMonitor, mint: str, swaps: list, now: float) -> int:
    """Latency loop for the snipe-path (ParsedSwap) scenarios — the evasion path.

    The concentrated-capture fingerprint needs the full early window to read the
    float, so this reports the gate ESCALATING off the clean floor (the residual
    catch) and the event at which ``concentrated_capture`` first fires.
    """
    print(f"  ({len(swaps)} ParsedSwaps — snipe-gate path)\n")
    escalate_at = None
    for n, ps in enumerate(swaps, start=1):
        mon.ingest_parsed_swap(mint, ps)
        pc = await mon.recompute(mint, now)
        fired = pc.snipe.fired_signals if (pc and pc.snipe) else []
        if pc and "concentrated_capture" in fired and escalate_at is None:
            escalate_at = n
            print(
                f"  gate->{pc.gate.upper()} at event {n}/{len(swaps)}  "
                f"(snipe={pc.snipe.label if pc.snipe else None}, signals={fired})"
            )
    if escalate_at is None:
        final = await mon.recompute(mint, now)
        gate = final.gate if final else "?"
        snipe = final.snipe.label if (final and final.snipe) else None
        print(f"  no escalation — final gate={gate} snipe={snipe} (expected for organic)")
    return 0


async def run_fixture(scenario: str) -> int:
    store = HotpathCache()
    mon = LaunchMonitor(store)
    now = 100_000.0
    created = int(now - 120)
    mint = "VICTIM"
    mon.track(mint, pool_created_ts=created)

    print(f"\n  attack_bot --fixture --scenario {scenario}")
    if scenario == "brca":
        for p in brca_bait_pools():
            mon.update_pool(mint, p)
        return await _run_swapevent_scenario(
            mon, mint, brca_inflate_then_drain(created_ts=created), now
        )
    if scenario == "evasion":
        # THE evasion: every automation tell off; concentrated_capture is the catch.
        return await _run_parsed_scenario(mon, mint, evasion_launch_parsed(created_ts=created), now)
    if scenario == "organic":
        # control on the same (snipe) path the evasion uses — must NOT escalate.
        return await _run_parsed_scenario(mon, mint, organic_launch_parsed(created_ts=created), now)
    print(f"unknown scenario: {scenario}", file=sys.stderr)
    return 2


def run_onchain() -> int:
    raise NotImplementedError(
        "On-chain attack path is the remaining live-fidelity build (step 7). "
        "Prereqs: `bash validator.sh` running, an AMM pool seeded on the local "
        "validator, and the monitor wired to ws://127.0.0.1:8900 via "
        "HeliusWebSocketClient.subscribe_program. See README. Deliberately not "
        "auto-run: it deploys a program and signs transactions. The live signed-tx "
        "rig (fork_pool.py + fork_attack.py) lives on the feat/firewall-fork-demo "
        "branch; its --scenario evasion should manufacture the footprint that "
        "scenarios.evasion_launch_parsed models (slot-spread, no tip, no ALT, "
        "multi-hop funding, randomized sizing, one-sided float capture)."
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Launch-Firewall attack bot")
    ap.add_argument("--onchain", action="store_true", help="live validator path (scaffold)")
    ap.add_argument("--scenario", default="brca", choices=["brca", "evasion", "organic"])
    args = ap.parse_args()
    if args.onchain:
        return run_onchain()
    return asyncio.run(run_fixture(args.scenario))


if __name__ == "__main__":
    raise SystemExit(main())
