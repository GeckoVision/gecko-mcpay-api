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


def test_alt_clustering_survives_wallet_rotation():
    # THE deep-vein probe: 3 "unrelated" buyers (no shared funder, aged wallets,
    # via Raydium) that share ONE custom ALT = same operator rig. Funder-graph
    # clustering would miss this; ALT-identity catches it.
    rig_alt = "ALT_sn1per_rig_1111111111111111111111111111111"
    swaps = [
        _swap(
            f"Rot{i}",
            500,
            program_ids=[RAYDIUM],
            alt_addresses=[rig_alt],
            wallet_age_s=5e6,  # aged — defeats fresh-wallet signal
            notional_sol=1.0,
            timestamp=1000.0,
        )
        for i in range(3)
    ]
    snap = build_snipe_snapshot("MINT", swaps, now=1030.0, launch_time=1000.0)
    assert snap.shared_alt_buyers == 3
    block = assess_snipe(snap)
    assert block is not None and "shared_alt_rig" in block.fired_signals


def test_distinct_alts_do_not_cluster():
    swaps = [
        _swap(f"W{i}", 500, alt_addresses=[f"ALT_{i}"], wallet_age_s=5e6, notional_sol=0.5)
        for i in range(4)
    ]
    snap = build_snipe_snapshot("MINT", swaps, now=1030.0, launch_time=1000.0)
    assert snap.shared_alt_buyers == 0


def test_end_to_end_organic_launch_stays_clean():
    # 30 distinct aged wallets, no tips, all via Raydium, spread across slots.
    swaps = [
        _swap(f"R{i}", 500 + i, program_ids=[RAYDIUM], wallet_age_s=5e6, notional_sol=0.5)
        for i in range(30)
    ]
    snap = build_snipe_snapshot("MINT", swaps, now=1030.0, launch_time=1000.0)
    block = assess_snipe(snap)
    assert block is not None and block.label == "clean"


# --- concentrated-capture feature extraction + the offline evasion probe ------ #


def test_top_buyer_share_and_one_sided_computed_from_buys_and_sells():
    # 2 dominant buyers + 1 minor; one small sell -> top-5 share high, one-sided < 1.
    swaps = [
        _swap("A", 1, notional_sol=4.0),
        _swap("A", 2, notional_sol=4.0),
        _swap("B", 3, notional_sol=2.0),
        _swap("C", 4, notional_sol=0.5),
        _swap("A", 5, is_buy=False, notional_sol=1.0),  # a sell -> two-sided component
    ]
    snap = build_snipe_snapshot("X", swaps)
    assert snap.buy_count == 4 and snap.buyer_count == 3
    # total buy notional 10.5; top-5 (all 3 buyers) = all of it
    assert snap.top_buyer_share == 1.0
    # one_sided = 10.5 / (10.5 + 1.0)
    assert snap.one_sided_ratio is not None and abs(snap.one_sided_ratio - (10.5 / 11.5)) < 1e-9


def test_top_buyer_share_caps_at_top_five():
    # 7 equal buyers -> top-5 share = 5/7 (concentration is bounded by the top set).
    swaps = [_swap(f"W{i}", i, notional_sol=1.0) for i in range(7)]
    snap = build_snipe_snapshot("X", swaps)
    assert snap.top_buyer_share is not None and abs(snap.top_buyer_share - 5 / 7) < 1e-9


def test_one_sided_ratio_none_without_volume():
    # no notional anywhere -> ratio undefined (None), never a divide-by-zero.
    swaps = [_swap("A", 1, notional_sol=0.0)]
    snap = build_snipe_snapshot("X", swaps)
    assert snap.one_sided_ratio is None and snap.top_buyer_share is None


def test_offline_evasion_fires_concentrated_capture():
    # THE evasion via the BUILDER (offline path, Pattern B): slot-SPREAD (distinct
    # slots), NO Jito tip, NO shared ALT, multi-hop funded (modeled as aged wallets
    # with no shared funder/ALT), RANDOMIZED sizing, one-sided accumulation, few
    # wallets buying MANY times. Every high-precision automation tell is OFF; only
    # the structural capture fingerprint remains.
    sizes = {
        "W0": [2.1, 1.7, 2.4, 1.9],
        "W1": [3.2, 2.8, 3.5],
        "W2": [1.1, 0.9, 1.3],
        "W3": [0.7, 0.6],
        "W4": [0.5, 0.55],
        "W5": [0.3],  # 6th buyer buys once -> buyer_count >= MIN_CONC_BUYERS
    }
    swaps = []
    slot = 1000
    for w, szs in sizes.items():
        for sz in szs:
            slot += 3  # DISTINCT slots — defeats same_slot_co_buy
            swaps.append(
                _swap(
                    w,
                    slot,
                    notional_sol=sz,
                    program_ids=[RAYDIUM],  # established program — no unknown-program tell
                    wallet_age_s=5e6,  # aged — no fresh-swarm tell
                    timestamp=1000.0 + slot,
                )
            )
    snap = build_snipe_snapshot("MINT", swaps, now=1000.0 + slot + 30, launch_time=1000.0)

    # the OLD automation signals must all be quiet (this is the evasion's whole point)
    assert snap.max_slot_unique_buyers < 3  # co-buy off
    assert snap.jito_bundle_buys == 0  # tip off
    assert snap.shared_alt_buyers == 0  # ALT off
    assert snap.fresh_wallet_buyers == 0  # fresh-swarm off
    assert snap.unknown_program_buys == 0  # unknown-program off

    # but the residual fires
    block = assess_snipe(snap)
    assert block is not None
    assert "concentrated_capture" in block.fired_signals
    # this synthetic capture is concentrated enough to be extreme -> block alone
    assert block.label in ("likely_sniped", "confirmed_wash")


def test_offline_diverse_crowd_stays_clean_via_builder():
    # FP guard via the builder: 40 unique buyers, fat-tailed sizes, ~1 buy each,
    # genuine two-sided sells -> concentration low, diversity-deficit low -> clean.
    swaps = []
    slot = 1000
    sizes = [0.2, 0.3, 0.5, 0.8, 1.2, 2.0, 3.5, 0.4, 0.6, 1.0]
    for i in range(40):
        slot += 2
        swaps.append(
            _swap(
                f"U{i}",
                slot,
                notional_sol=sizes[i % len(sizes)],
                program_ids=[RAYDIUM],
                wallet_age_s=5e6,
                timestamp=1000.0 + slot,
            )
        )
    # a handful buy a second time (organic) + real sells (price discovery)
    for i in range(15):
        slot += 2
        swaps.append(_swap(f"U{i}", slot, is_buy=False, notional_sol=0.8, program_ids=[RAYDIUM]))
    snap = build_snipe_snapshot("MINT", swaps, now=1000.0 + slot + 30, launch_time=1000.0)
    assert snap.top_buyer_share is not None and snap.top_buyer_share < 0.60
    assert snap.one_sided_ratio is not None and snap.one_sided_ratio < 0.90
    block = assess_snipe(snap)
    assert block is not None
    assert "concentrated_capture" not in block.fired_signals
    assert block.label == "clean"
