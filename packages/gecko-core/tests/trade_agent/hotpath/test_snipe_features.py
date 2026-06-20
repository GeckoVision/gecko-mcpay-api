"""Tests for the parsed-tx → SnipeSnapshot bridge + the end-to-end snipe probe."""

from __future__ import annotations

from gecko_core.trade_agent.hotpath.jito_tips import TipFloor
from gecko_core.trade_agent.hotpath.snipe_features import (
    LAMPORTS_PER_SOL,
    ParsedSwap,
    build_snipe_snapshot,
)
from gecko_core.trade_agent.hotpath.snipe_gate import assess_snipe

RAYDIUM = "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"
SNIPER_PROG = "Sn1perPr0gram1111111111111111111111111111111"
_FLOOR = TipFloor(p25=1e-6, p50=2e-6, p75=6e-6, p95=1e-4, p99=1e-4, ema_p50=2e-6)


def _swap(signer, slot, **kw):
    return ParsedSwap(signer=signer, slot=slot, **kw)


def test_empty_swaps_make_empty_snapshot():
    snap = build_snipe_snapshot("X", [])
    assert snap.buyer_count == 0 and snap.jito_bundle_buys == 0
    assert assess_snipe(snap) is None  # nothing to assess -> fail-OPEN


def test_only_buys_count_toward_signals():
    swaps = [
        _swap("A", 10, is_buy=True),
        _swap("B", 10, is_buy=False),  # a sell — ignored
    ]
    snap = build_snipe_snapshot("X", swaps)
    assert snap.buyer_count == 1


def test_co_buy_is_per_slot_distinct():
    swaps = [_swap(w, 100) for w in ("A", "B", "C")] + [_swap("A", 101)]
    snap = build_snipe_snapshot("X", swaps)
    assert snap.max_slot_unique_buyers == 3  # slot 100 had 3 distinct buyers


def test_fresh_wallets_counted_per_distinct_buyer():
    # one fresh wallet looping 3 buys = 1 fresh buyer, not 3
    swaps = [_swap("A", s, wallet_age_s=60.0) for s in (1, 2, 3)]
    swaps.append(_swap("B", 4, wallet_age_s=10_000_000.0))  # aged
    snap = build_snipe_snapshot("X", swaps)
    assert snap.buyer_count == 2 and snap.fresh_wallet_buyers == 1


def test_jito_and_tip_extracted_from_lamports():
    swaps = [
        _swap("A", 1, tip_lamports=int(2e-4 * LAMPORTS_PER_SOL)),
        _swap("B", 2, tip_lamports=0),
    ]
    snap = build_snipe_snapshot("X", swaps)
    assert snap.jito_bundle_buys == 1
    assert snap.max_buy_tip_sol is not None and abs(snap.max_buy_tip_sol - 2e-4) < 1e-9


def test_unknown_program_attribution():
    swaps = [
        _swap("A", 1, program_ids=[RAYDIUM]),  # established
        _swap("B", 2, program_ids=[SNIPER_PROG]),  # custom -> unknown
    ]
    snap = build_snipe_snapshot("X", swaps)
    assert snap.unknown_program_buys == 1


def test_age_seconds_from_launch_time():
    swaps = [_swap("A", 1, timestamp=1000.0)]
    snap = build_snipe_snapshot("X", swaps, now=1120.0)  # launch inferred = 1000
    assert snap.age_seconds == 120.0


def test_end_to_end_probe_fresh_launch_snipe_is_caught():
    # THE reachability probe (Pattern E): synthetic fresh launch, 4 fresh wallets
    # co-buying in one slot, all via Jito bundles through a custom sniper program.
    swaps = [
        _swap(
            f"W{i}",
            500,
            tip_lamports=int(2e-4 * LAMPORTS_PER_SOL),
            program_ids=[SNIPER_PROG],
            wallet_age_s=120.0,
            notional_sol=1.0,
            timestamp=1000.0,
        )
        for i in range(4)
    ]
    snap = build_snipe_snapshot("MINT", swaps, now=1030.0)  # 30s-old launch
    block = assess_snipe(snap, _FLOOR)
    assert block is not None
    assert block.label in ("likely_sniped", "confirmed_wash")
    assert {"jito_bundle_snipe", "fresh_wallet_swarm", "same_slot_co_buy"} <= set(
        block.fired_signals
    )
    assert "unknown_program_route" in block.fired_signals  # I2 fed the verdict


def test_end_to_end_organic_launch_stays_clean():
    # 30 distinct aged wallets, no tips, all via Raydium, spread across slots.
    swaps = [
        _swap(f"R{i}", 500 + i, program_ids=[RAYDIUM], wallet_age_s=5e6, notional_sol=0.5)
        for i in range(30)
    ]
    snap = build_snipe_snapshot("MINT", swaps, now=1030.0, launch_time=1000.0)
    block = assess_snipe(snap)
    assert block is not None and block.label == "clean"
