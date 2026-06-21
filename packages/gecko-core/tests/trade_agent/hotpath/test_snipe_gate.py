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


def test_shared_alt_signal_fires():
    snap = SnipeSnapshot(mint="X", age_seconds=AGED, buyer_count=10, shared_alt_buyers=4)
    b = assess_snipe(snap)
    assert b is not None and "shared_alt_rig" in b.fired_signals
    assert b.score >= 0.25


def test_lone_shared_alt_buyer_does_not_fire():
    # a single buyer "sharing" with nobody isn't a cluster
    snap = SnipeSnapshot(mint="X", age_seconds=AGED, buyer_count=10, shared_alt_buyers=1)
    b = assess_snipe(snap)
    assert b is not None and "shared_alt_rig" not in b.fired_signals


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


# --- concentrated_capture: the residual that survives every automation tell off - #
# A MODERATE captured float: top-5 hold 72% of buy notional, 95% one-sided, 6
# wallets buying 18 times (diversity-deficit 3.0). Every other tell is OFF.
def _moderate_capture(**over):
    base = dict(
        mint="X",
        age_seconds=AGED,
        buyer_count=6,
        buy_count=18,
        top_buyer_share=0.72,
        one_sided_ratio=0.95,
    )
    base.update(over)
    return SnipeSnapshot(**base)


def test_concentrated_capture_lone_reaches_suspicious():
    # THE evasion, all automation tells off -> previously clean, now fires -> suspicious.
    b = assess_snipe(_moderate_capture())
    assert b is not None
    assert b.fired_signals == ["concentrated_capture"]
    assert b.label == "suspicious"  # the honest win: raises the floor from clean


def test_concentrated_capture_plus_one_corroborator_blocks():
    # + a couple fresh wallets (4/6 fresh) -> corroborated -> block (likely_sniped).
    b = assess_snipe(_moderate_capture(fresh_wallet_buyers=4))
    assert b is not None
    assert {"concentrated_capture", "fresh_wallet_swarm"} <= set(b.fired_signals)
    assert b.label == "likely_sniped"


def test_concentrated_capture_corroborated_by_any_weak_tell_blocks():
    # the weakest corroborator (a small co-buy of 3) still escalates to block.
    b = assess_snipe(_moderate_capture(max_slot_unique_buyers=3))
    assert b is not None
    assert {"concentrated_capture", "same_slot_co_buy"} <= set(b.fired_signals)
    assert b.label == "likely_sniped"


def test_extreme_concentration_blocks_alone():
    # near-single-wallet (88% top-5), near-zero-sell (99% one-sided) -> block alone.
    b = assess_snipe(
        SnipeSnapshot(
            mint="X",
            age_seconds=AGED,
            buyer_count=6,
            buy_count=20,
            top_buyer_share=0.88,
            one_sided_ratio=0.99,
        )
    )
    assert b is not None
    assert b.fired_signals == ["concentrated_capture"]
    assert b.label == "likely_sniped"  # extreme tier escalates a lone signal


def test_concentrated_capture_lone_at_launch_is_suspicious_not_block():
    # launch FP guard: a hyped fair launch is also concentrated early; lone
    # moderate concentration at <1h -> suspicious (caution), never block.
    b = assess_snipe(_moderate_capture(age_seconds=120.0))
    assert b is not None
    assert b.fired_signals == ["concentrated_capture"]
    assert b.label == "suspicious"


def test_extreme_concentration_blocks_even_at_launch():
    # no fair launch shows a near-single-wallet zero-sell capture, even at launch.
    b = assess_snipe(
        SnipeSnapshot(
            mint="X",
            age_seconds=120.0,
            buyer_count=6,
            buy_count=20,
            top_buyer_share=0.88,
            one_sided_ratio=0.99,
        )
    )
    assert b is not None and b.label == "likely_sniped"


def test_concentration_with_lp_drain_is_confirmed_wash():
    # corroborated concentration + the drain tail -> confirmed_wash (strongest).
    b = assess_snipe(_moderate_capture(fresh_wallet_buyers=4, lp_drained=True))
    assert b is not None and b.label == "confirmed_wash"


# --- FP guards: must NOT fire on legitimate launch shapes --------------------- #
def test_fp_diverse_organic_crowd_does_not_fire():
    # many unique buyers, ~1 buy each (low diversity-deficit), some sells.
    snap = SnipeSnapshot(
        mint="X",
        age_seconds=AGED,
        buyer_count=40,
        buy_count=44,  # ratio 1.1 < DIV_T
        top_buyer_share=0.28,  # < CONC_T
        one_sided_ratio=0.70,  # < ONESIDE_T
    )
    b = assess_snipe(snap)
    assert b is not None
    assert "concentrated_capture" not in b.fired_signals


def test_fp_two_sided_market_maker_does_not_fire():
    # an MM is two-sided -> one_sided_ratio low -> no fire, even if concentrated.
    snap = _moderate_capture(one_sided_ratio=0.55)
    b = assess_snipe(snap)
    assert b is not None
    assert "concentrated_capture" not in b.fired_signals


def test_fp_small_fair_launch_each_buys_once_does_not_fire():
    # 5 distinct buyers each buying once: high concentration + one-sided, BUT the
    # diversity-deficit is ~1.0 (< DIV_T) -> the discriminator holds -> no fire.
    snap = SnipeSnapshot(
        mint="X",
        age_seconds=AGED,
        buyer_count=5,
        buy_count=5,  # ratio 1.0 < DIV_T -> diverse, not a capture loop
        top_buyer_share=0.65,
        one_sided_ratio=0.95,
    )
    b = assess_snipe(snap)
    assert b is not None
    assert "concentrated_capture" not in b.fired_signals


def test_fp_below_min_buyers_does_not_fire():
    # a 4-buyer pool is noise — never fire, even at extreme concentration.
    snap = SnipeSnapshot(
        mint="X",
        age_seconds=AGED,
        buyer_count=4,
        buy_count=20,
        top_buyer_share=0.95,
        one_sided_ratio=0.99,
    )
    b = assess_snipe(snap)
    assert b is not None
    assert "concentrated_capture" not in b.fired_signals
    assert b.label != "likely_sniped"  # extreme guard also respects MIN_CONC_BUYERS


def test_concentration_missing_features_does_not_fire():
    # reserve-only / partial snapshots (no top_buyer_share) -> never fire.
    snap = SnipeSnapshot(mint="X", age_seconds=AGED, buyer_count=10, buy_count=30)
    b = assess_snipe(snap)
    assert b is not None
    assert "concentrated_capture" not in b.fired_signals
