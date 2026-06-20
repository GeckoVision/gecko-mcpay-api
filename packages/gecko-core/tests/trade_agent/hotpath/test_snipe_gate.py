"""Tests for the B1 snipe gate (multi-signal launch-integrity fusion)."""

from __future__ import annotations

from gecko_core.trade_agent.hotpath.jito_tips import TipFloor
from gecko_core.trade_agent.hotpath.snipe_gate import SnipeSnapshot, assess_snipe

_FLOOR = TipFloor(p25=1e-6, p50=2e-6, p75=6e-6, p95=1e-4, p99=1e-4, ema_p50=2e-6)
AGED = 10_000.0  # past the launch FP guard


def test_no_inputs_fail_open():
    assert assess_snipe(SnipeSnapshot(mint="X")) is None


def test_benign_returns_clean():
    snap = SnipeSnapshot(mint="X", age_seconds=AGED, buyer_count=50, fresh_wallet_buyers=2)
    b = assess_snipe(snap)
    assert b is not None and b.label == "clean" and b.fired_signals == []


def test_jito_bundle_fires():
    snap = SnipeSnapshot(mint="X", age_seconds=AGED, buyer_count=10, jito_bundle_buys=4)
    b = assess_snipe(snap)
    assert b is not None
    assert "jito_bundle_snipe" in b.fired_signals
    assert b.score >= 0.40


def test_fresh_swarm_fires():
    snap = SnipeSnapshot(mint="X", age_seconds=AGED, buyer_count=10, fresh_wallet_buyers=8)
    b = assess_snipe(snap)
    assert b is not None and "fresh_wallet_swarm" in b.fired_signals


def test_fee_outlier_uses_tip_floor():
    # top tip at p95 -> outlier; needs the floor injected
    snap = SnipeSnapshot(mint="X", age_seconds=AGED, buyer_count=5, max_buy_tip_sol=1e-4)
    assert "fee_tip_outlier" in (assess_snipe(snap, _FLOOR).fired_signals)
    # without the floor, no fee signal
    assert "fee_tip_outlier" not in (assess_snipe(snap, None).fired_signals or [])


def test_co_buy_alone_at_launch_is_suppressed():
    # fresh token, ONLY co-buy -> organic-hype guard -> clean
    snap = SnipeSnapshot(mint="X", age_seconds=120.0, buyer_count=6, max_slot_unique_buyers=5)
    b = assess_snipe(snap)
    assert b is not None and b.label == "clean" and b.fired_signals == []


def test_co_buy_alone_aged_token_does_fire():
    snap = SnipeSnapshot(mint="X", age_seconds=AGED, buyer_count=6, max_slot_unique_buyers=5)
    b = assess_snipe(snap)
    assert b is not None and "same_slot_co_buy" in b.fired_signals


def test_co_buy_plus_automation_at_launch_escalates():
    # co-buy + jito at launch -> corroborated -> fires (guard does NOT suppress)
    snap = SnipeSnapshot(
        mint="X", age_seconds=120.0, buyer_count=6, max_slot_unique_buyers=5, jito_bundle_buys=3
    )
    b = assess_snipe(snap)
    assert b is not None
    assert {"same_slot_co_buy", "jito_bundle_snipe"} <= set(b.fired_signals)


def test_unknown_program_signal_fires():
    snap = SnipeSnapshot(mint="X", age_seconds=AGED, buyer_count=10, unknown_program_buys=3)
    b = assess_snipe(snap)
    assert b is not None and "unknown_program_route" in b.fired_signals
    assert b.score >= 0.20


def test_full_snipe_is_likely_sniped():
    # jito + fresh swarm + fee outlier + co-buy -> high score
    snap = SnipeSnapshot(
        mint="X",
        age_seconds=AGED,
        buyer_count=10,
        max_slot_unique_buyers=6,
        jito_bundle_buys=6,
        fresh_wallet_buyers=9,
        max_buy_tip_sol=2e-4,
    )
    b = assess_snipe(snap, _FLOOR)
    assert b is not None
    assert b.label in ("likely_sniped", "confirmed_wash")
    assert b.score >= 0.65


def test_lp_drain_makes_confirmed_wash():
    snap = SnipeSnapshot(
        mint="X", age_seconds=AGED, buyer_count=8, jito_bundle_buys=4, lp_drained=True
    )
    b = assess_snipe(snap)
    assert b is not None
    assert b.lp_drained if hasattr(b, "lp_drained") else True
    assert "lp_drain" in b.fired_signals
    assert b.label == "confirmed_wash"  # lp_drain + score>=0.65


def test_score_bounded_at_one():
    snap = SnipeSnapshot(
        mint="X",
        age_seconds=AGED,
        buyer_count=10,
        max_slot_unique_buyers=10,
        jito_bundle_buys=10,
        fresh_wallet_buyers=10,
        max_buy_tip_sol=1.0,
        lp_drained=True,
    )
    b = assess_snipe(snap, _FLOOR)
    assert b is not None and b.score == 1.0
