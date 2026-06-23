"""Launch-Firewall Attack-vs-Defense harness — 3-way fixture + live-fork assertion.

Two modes:

* ``--mode fixture`` (default, runs NOW, no validator): replays scripted scenarios
  through the REAL ``LaunchMonitor`` + ``HotpathCache`` + ``safety_gate`` and prints
  the verdict the firewall would serve. The free local simulation (Pattern B) that
  proves "our real engine catches our real attack" with zero spend. The 3-way (the
  concentration-detector proof):

      ATTACK   → block        — the loud snipe: every automation tell on.
      EVASION  → block|caution — the slot-spread snipe: EVERY automation tell OFF,
                                 float still captured. Previously this reached clean;
                                 ``concentrated_capture`` now raises it off the floor
                                 (suspicious→caution alone; block with a corroborator).
      ORGANIC  → not block     — a genuine diverse fair launch.

  The EVASION leg is the whole point: it proves the firewall has no known
  clean-evasion at launch — the residual concentration fingerprint catches the one
  snipe that turns every high-precision automation tell off.

* ``--mode fork``: reads the LIVE verdict the fork adapter wrote
  (``/tmp/gecko-lf-fork-verdict.json``) after a real attack/organic run on the
  surfpool fork, and asserts:
      ATTACK  → gate == "block"        with the expected snipe signals fired
      ORGANIC → gate in {ok, unknown}  and wash in {clean, elevated}
  Run the attack first (fork_attack.py), captured by the adapter (fork_adapter.py),
  then run this with ``--mode fork`` to print PASS/FAIL.

Run:
    uv run python sandbox/launch_firewall/defense_harness.py                 # fixture 3-way
    uv run python sandbox/launch_firewall/defense_harness.py --mode fork     # assert live verdict
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
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

FORK_VERDICT_PATH = Path("/tmp/gecko-lf-fork-verdict.json")

# The snipe signals the 4-in-1 fork attack manufactures. The block is robust to
# any ONE of these missing on a given run (the gate fuses weights), so we assert
# the GATE plus "at least the high-precision automation tells fired", not an exact
# set — honest about per-run variance on a live fork.
EXPECTED_ATTACK_SIGNALS = {
    "jito_bundle_snipe",  # one co-buy carried a Jito tip transfer
    "same_slot_co_buy",  # 4 buyers in one slot
    "fresh_wallet_swarm",  # snipers funded seconds before launch (see fidelity note)
    "shared_alt_rig",  # all snipers referenced one ALT
    "lp_drain",  # inflate-then-drain tail
}


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
    resp: dict[str, Any] = warm.to_response(now_epoch=now) if warm else {"gate": "MISS"}
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


async def run_fixture() -> int:
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


def _assert_attack(v: dict[str, Any]) -> tuple[bool, list[str]]:
    notes: list[str] = []
    ok = True
    if v.get("gate") != "block":
        ok = False
        notes.append(f"expected gate=block, got {v.get('gate')!r}")
    fired = set(v.get("snipe_fired") or [])
    overlap = fired & EXPECTED_ATTACK_SIGNALS
    if not overlap:
        ok = False
        notes.append(f"no expected snipe signals fired; got {sorted(fired)}")
    else:
        notes.append(f"snipe fired: {sorted(fired)}")
    # the two highest-precision automation tells should be present in a clean run
    for high in ("jito_bundle_snipe", "shared_alt_rig"):
        if high not in fired:
            notes.append(f"NOTE: {high} did not fire (per-run variance / fidelity gap)")
    return ok, notes


def _assert_organic(v: dict[str, Any]) -> tuple[bool, list[str]]:
    notes: list[str] = []
    ok = True
    # 'unknown' is fail-OPEN (no static read on the fork) — acceptable as
    # not-a-block; 'caution'/'block' on the organic control is a real failure.
    if v.get("gate") in ("block", "caution"):
        ok = False
        notes.append(f"organic control should not escalate; got gate={v.get('gate')!r}")
    wash = v.get("wash_label")
    if wash not in (None, "clean", "elevated"):
        ok = False
        notes.append(f"organic wash should be clean/elevated, got {wash!r}")
    notes.append(f"gate={v.get('gate')!r} wash={wash!r} snipe={v.get('snipe_label')!r}")
    return ok, notes


def run_fork() -> int:
    if not FORK_VERDICT_PATH.exists():
        print(
            f"\n  no live verdict at {FORK_VERDICT_PATH}.\n"
            "  Run the fork flow first (see run_fork_demo.sh help):\n"
            "    fork_pool.py → fork_adapter.py (background) → fork_attack.py\n",
            file=sys.stderr,
        )
        return 2
    v = json.loads(FORK_VERDICT_PATH.read_text())
    scenario = "attack" if (v.get("snipe_fired") or v.get("gate") == "block") else "organic"
    # Prefer the explicit scenario marker the attack writer leaves, if present.
    for marker in ("/tmp/gecko-lf-fork-attack.json", "/tmp/gecko-lf-fork-organic.json"):
        if Path(marker).exists():
            scenario = "attack" if "attack" in marker else "organic"

    print("\n  Launch Firewall — LIVE fork verdict assertion\n")
    print(f"  mint={v.get('mint')}")
    print(f"  gate={v.get('gate')!r}  snipe={v.get('snipe_label')!r}  wash={v.get('wash_label')!r}")
    print(f"  snipe_fired={v.get('snipe_fired')}")
    print(f"  wash_fired={v.get('wash_fired')}  lp_drained={v.get('lp_drained')}\n")

    if scenario == "attack":
        ok, notes = _assert_attack(v)
    else:
        ok, notes = _assert_organic(v)
    for n in notes:
        print(f"    - {n}")
    print()
    if ok:
        print(f"  PASS: live {scenario} verdict matches the expected firewall behavior\n")
        return 0
    print(f"  FAIL: live {scenario} verdict did not match expectations\n")
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Launch-Firewall attack-vs-defense harness")
    ap.add_argument("--mode", default="fixture", choices=["fixture", "fork"])
    args = ap.parse_args()
    if args.mode == "fork":
        return run_fork()
    return asyncio.run(run_fixture())


if __name__ == "__main__":
    raise SystemExit(main())
