"""Offline self-test — falsify the adapter + harness logic WITHOUT a fork.

Pattern B discipline: prove every offline-testable piece before the live fork run
(which is the founder-executed final check, not the debug tool). This exercises:

  1. tx_parser.parse_swap_tx against a RECORDED-SHAPE fork getTransaction payload
     (a co-buy carrying a Jito tip + a shared ALT + a custom program) → asserts the
     adapter extracts signer / slot / tip_lamports / alt_addresses / program_ids /
     is_buy exactly as the live wire will.
  2. the full ingest → recompute path: synthetic ParsedSwaps + reserve SwapEvents
     that mirror the 4-in-1 attack → LaunchMonitor → asserts gate == "block" with
     the expected snipe signals fired (the same engine the live adapter drives).
  3. the organic control through the same path → asserts NOT a block.
  4. defense_harness._assert_attack / _assert_organic against synthetic verdicts.

Everything here is pure + in-process. The ONLY thing it does not cover is the
actual signed-tx submission + the websocket round-trip — those need the live fork
(run_fork_demo.sh). This is the honest line: logic VALIDATED here; wire NEEDS the
fork.

Run:
    uv run python sandbox/launch_firewall/fork_selftest.py
"""

from __future__ import annotations

import asyncio
from typing import Any, Literal

import defense_harness as dh
from gecko_core.trade_agent.hotpath.cache import HotpathCache
from gecko_core.trade_agent.hotpath.launch_monitor import LaunchMonitor
from gecko_core.trade_agent.hotpath.snipe_features import ParsedSwap
from gecko_core.trade_agent.hotpath.token_state import SwapEvent
from gecko_core.trade_agent.hotpath.tx_parser import parse_swap_tx

# A real Jito tip account (hotpath.jito.JITO_TIP_ACCOUNTS) — what fork_attack tips.
TIP_ACCT = "96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5"
SYSTEM = "11111111111111111111111111111111"
SPL_TOKEN = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
# Our mock swap routes through SPL transfer (no AMM) — to the firewall that program
# set is "established" (SPL Token + System), so the attack does NOT rely on the
# unknown_program tell. We include a custom program to show the parser captures it.
CUSTOM_PROG = "Snipe1111111111111111111111111111111111111"


def _recorded_fork_tx(*, signer: str, slot: int, tip: bool, alt: str | None) -> dict[str, Any]:
    """A getTransaction(jsonParsed) payload shaped like surfpool/Helius returns.

    Mirrors what fork_attack's co-buy tx looks like on the wire: the sniper is the
    fee payer (signer+writable), spends SOL (preBalances > postBalances at index 0),
    optionally transfers to a Jito tip account, and references a shared ALT.
    """
    instructions: list[dict[str, Any]] = [
        # base-out leg: SPL transfer (pool authority → sniper) — established prog
        {"programId": SPL_TOKEN, "parsed": {"type": "transfer"}},
        # quote-in leg: System transfer (sniper spends SOL) — drives is_buy
        {
            "programId": SYSTEM,
            "parsed": {
                "type": "transfer",
                "info": {"source": signer, "destination": "poolAuth", "lamports": 500_000_000},
            },
        },
        {"programId": CUSTOM_PROG, "accounts": [], "data": ""},
    ]
    if tip:
        instructions.append(
            {
                "programId": SYSTEM,
                "parsed": {
                    "type": "transfer",
                    "info": {"source": signer, "destination": TIP_ACCT, "lamports": 2_000_000},
                },
            }
        )
    message: dict[str, Any] = {
        "accountKeys": [
            {"pubkey": signer, "signer": True, "writable": True},
            {"pubkey": "poolAuth", "signer": False, "writable": True},
            {"pubkey": SPL_TOKEN, "signer": False, "writable": False},
        ],
        "instructions": instructions,
    }
    if alt is not None:
        message["addressTableLookups"] = [
            {"accountKey": alt, "writableIndexes": [0], "readonlyIndexes": [1]}
        ]
    # signer at index 0 spends 0.5 SOL (+ tip if present) → negative delta = buy
    spent = 500_000_000 + (2_000_000 if tip else 0) + 5_000  # + fee
    return {
        "result": {
            "slot": slot,
            "value": {
                "transaction": {"message": message},
                "meta": {
                    "err": None,
                    "preBalances": [2_000_000_000, 0, 0],
                    "postBalances": [2_000_000_000 - spent, 0, 0],
                    "innerInstructions": [],
                },
                "blockTime": 1_700_000_000 + slot,
            },
        }
    }


def test_tx_parser_on_fork_shape() -> list[str]:
    """parse_swap_tx must extract the snipe-gate facts from a fork-shaped tx."""
    fails: list[str] = []
    tx = _recorded_fork_tx(signer="Sniper1", slot=4242, tip=True, alt="SharedALT111")
    ps = parse_swap_tx(tx, timestamp=1700.0)
    if ps is None:
        return ["parse_swap_tx returned None on a valid fork-shaped buy tx"]
    if ps.signer != "Sniper1":
        fails.append(f"signer: expected Sniper1, got {ps.signer}")
    if ps.slot != 4242:
        fails.append(f"slot: expected 4242, got {ps.slot}")
    if not ps.is_buy:
        fails.append("is_buy: expected True (signer spent SOL)")
    if ps.tip_lamports != 2_000_000:
        fails.append(f"tip_lamports: expected 2_000_000, got {ps.tip_lamports}")
    if "SharedALT111" not in ps.alt_addresses:
        fails.append(f"alt_addresses: expected SharedALT111, got {ps.alt_addresses}")
    if CUSTOM_PROG not in ps.program_ids or SPL_TOKEN not in ps.program_ids:
        fails.append(f"program_ids: missing expected programs, got {ps.program_ids}")
    # a no-tip, no-ALT tx should parse with tip=0, empty ALTs
    tx2 = _recorded_fork_tx(signer="Sniper2", slot=4243, tip=False, alt=None)
    ps2 = parse_swap_tx(tx2, timestamp=1701.0)
    if ps2 is None or ps2.tip_lamports != 0 or ps2.alt_addresses:
        fails.append(f"no-tip/no-alt tx parsed wrong: {ps2}")
    return fails


async def _drive_attack(mon: LaunchMonitor, mint: str, now: float, created: int) -> None:
    """Synthetic 4-in-1 attack via the SAME ingest API the live adapter calls."""
    shared_alt = "SharedALT111"
    snipers = ["Sniper0", "Sniper1", "Sniper2", "Sniper3"]
    # same-slot co-buy: all 4 in ONE slot; sniper0 carries the Jito tip; all share ALT
    for i, s in enumerate(snipers):
        mon.ingest_parsed_swap(
            mint,
            ParsedSwap(
                signer=s,
                slot=1000,  # ONE slot → co-buy cluster
                is_buy=True,
                notional_sol=0.5,
                tip_lamports=2_000_000 if i == 0 else 0,  # one bundle
                program_ids=[SPL_TOKEN, SYSTEM],  # established route (no unknown-prog crutch)
                alt_addresses=[shared_alt],  # shared rig
                wallet_age_s=120.0,  # fresh: funded seconds before launch
                timestamp=float(created + 1),
            ),
        )
    # reserve side: inflate (one-sided buys, price climbing, tiny uniform notional)
    price = 1.0
    for i in range(38):
        mon.ingest_swap(
            mint,
            SwapEvent(
                ts=float(created + i),
                wallet="pool:P",
                side="buy",
                notional_usd=30.0,
                price_usd=price,
            ),
        )
        price *= 1.01
    # drain: the inflate-then-drain tail → set lp_drained (the adapter's DrainWatcher)
    mon.track(mint).lp_drained = True


async def test_attack_blocks() -> list[str]:
    store = HotpathCache()
    mon = LaunchMonitor(store)
    now = 100_000.0
    created = int(now - 120)
    mon.track(mint := "ATTACK", pool_created_ts=created)
    await _drive_attack(mon, mint, now, created)
    pc = await mon.recompute(mint, now)
    fails: list[str] = []
    if pc is None:
        return ["recompute returned None for the attack"]
    if pc.gate != "block":
        fails.append(f"attack gate: expected block, got {pc.gate}")
    fired = set(pc.snipe.fired_signals) if pc.snipe else set()
    for want in (
        "jito_bundle_snipe",
        "same_slot_co_buy",
        "fresh_wallet_swarm",
        "shared_alt_rig",
        "lp_drain",
    ):
        if want not in fired:
            fails.append(f"attack snipe signal missing: {want} (fired={sorted(fired)})")
    return fails


async def test_organic_passes() -> list[str]:
    store = HotpathCache()
    mon = LaunchMonitor(store)
    now = 100_000.0
    created = int(now - 120)
    mon.track(mint := "ORGANIC", pool_created_ts=created)
    # distinct buyers, distinct slots, fat-tailed sizes, NO tip, NO shared ALT
    for i in range(8):
        mon.ingest_parsed_swap(
            mint,
            ParsedSwap(
                signer=f"User{i}",
                slot=2000 + i * 3,  # spread across slots → no co-buy cluster
                is_buy=True,
                notional_sol=0.2 + i * 0.4,  # fat-tailed
                tip_lamports=0,
                program_ids=[SPL_TOKEN, SYSTEM],
                alt_addresses=[],  # no shared rig
                wallet_age_s=None,  # unknown age (not asserted fresh)
                timestamp=float(created + i * 3),
            ),
        )
    # two-sided reserve flow, fat-tailed sizes (organic price discovery)
    for i in range(40):
        side: Literal["buy", "sell"] = "buy" if i % 3 != 0 else "sell"
        mon.ingest_swap(
            mint,
            SwapEvent(
                ts=float(created + i),
                wallet="pool:P",
                side=side,
                notional_usd=100.0 + i * 40,
                price_usd=1.0,
            ),
        )
    pc = await mon.recompute(mint, now)
    fails: list[str] = []
    if pc is None:
        return ["recompute returned None for organic"]
    if pc.gate == "block":
        fails.append(f"organic gate: expected not-block, got {pc.gate} (snipe={pc.snipe})")
    return fails


def test_harness_assertions() -> list[str]:
    """The defense_harness 2x2 assertion logic on synthetic verdict dicts."""
    fails: list[str] = []
    attack_v = {
        "gate": "block",
        "snipe_label": "confirmed_wash",
        "snipe_fired": ["jito_bundle_snipe", "same_slot_co_buy", "shared_alt_rig", "lp_drain"],
        "wash_label": "manipulated",
        "lp_drained": True,
    }
    ok, _ = dh._assert_attack(attack_v)
    if not ok:
        fails.append("_assert_attack rejected a valid block verdict")
    bad_attack = {"gate": "ok", "snipe_fired": []}
    ok, _ = dh._assert_attack(bad_attack)
    if ok:
        fails.append("_assert_attack accepted a non-block verdict")
    organic_v = {"gate": "ok", "snipe_label": "clean", "wash_label": "clean"}
    ok, _ = dh._assert_organic(organic_v)
    if not ok:
        fails.append("_assert_organic rejected a clean verdict")
    bad_organic = {"gate": "block", "snipe_label": "likely_sniped", "wash_label": "manipulated"}
    ok, _ = dh._assert_organic(bad_organic)
    if ok:
        fails.append("_assert_organic accepted a blocking verdict for the control")
    return fails


async def main() -> int:
    results: list[tuple[str, list[str]]] = []
    results.append(("tx_parser on fork-shaped tx", test_tx_parser_on_fork_shape()))
    results.append(("attack → gate=block + signals", await test_attack_blocks()))
    results.append(("organic → not-block", await test_organic_passes()))
    results.append(("harness 2x2 assertion logic", test_harness_assertions()))

    print("\n  Launch Firewall — fork self-test (offline, no validator)\n")
    all_ok = True
    for name, fails in results:
        if fails:
            all_ok = False
            print(f"  FAIL  {name}")
            for f in fails:
                print(f"          - {f}")
        else:
            print(f"  PASS  {name}")
    print()
    if all_ok:
        print("  ALL OFFLINE CHECKS PASS — attacker-tx parsing, ingest→block, and")
        print("  the 2x2 harness logic are validated. The live wire (ws round-trip +")
        print("  signed-tx submission) needs the fork: run_fork_demo.sh.\n")
        return 0
    print("  OFFLINE CHECKS FAILED — fix before the live fork run.\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
