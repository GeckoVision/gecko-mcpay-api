"""W1 — Information-MEV scoring surface (assess_information_mev).

Packages PR #136's raw manipulation flags into a named 0–1 severity read.
These tests pin the score bands + the fail-OPEN contract, and assert the BrCA
real-number case (the token DexView rated "Normal") lands as 'manipulated'.
"""

from __future__ import annotations

from gecko_core.orchestration.trade_panel.models import InformationMEVBlock
from gecko_core.orchestration.trade_panel.safety_check import (
    assess_information_mev,
    compute_manipulation_signals,
)
from gecko_core.sources.coingecko import OnchainTokenMarket


def test_large_cap_low_ratio_not_flagged() -> None:
    """JUP-like: $585M mcap / $2.0M liq = 0.34% ratio but tradable => NO flag.

    Regression for the live-gallery false positive — a low ratio alone must not
    trip the manipulation read when absolute liquidity is healthy (the rest of a
    large cap's depth lives on CEXes the on-chain source can't see).
    """
    market = OnchainTokenMarket(market_cap_usd=584_680_000.0, total_reserve_in_usd=2_000_000.0)
    _, _, ratio, flags = compute_manipulation_signals(market)
    assert ratio is not None and ratio < 1.0  # ratio IS low...
    assert flags == []  # ...but absolute liquidity is healthy => no flag


def test_thin_small_cap_flagged() -> None:
    """BrCA-like: $26.65M mcap / $160K liq = 0.60% + thin absolute => thin flag."""
    market = OnchainTokenMarket(market_cap_usd=26_650_000.0, total_reserve_in_usd=160_400.0)
    _, _, ratio, flags = compute_manipulation_signals(market)
    assert ratio is not None
    assert "thin_liquidity_vs_mcap" in flags
    assert "fake_market_cap" not in flags  # 0.60% is above the fake-mcap floor


def test_brca_real_numbers_score_manipulated() -> None:
    """BrCA: $26.31M mcap / $22.4K liq (0.085%) + 77% top holder => manipulated."""
    block = assess_information_mev(
        market_cap_usd=26_310_000.0,
        liquidity_usd=22_400.0,
        ratio_pct=0.085,
        manip_flags=["thin_liquidity_vs_mcap", "fake_market_cap"],
        top_holder_pct=0.77,
    )
    assert isinstance(block, InformationMEVBlock)
    assert block.label == "manipulated"
    # fake_market_cap (0.7) + concentration (0.25), capped at 1.0 => 0.95
    assert block.score == 0.95
    joined = " ".join(block.reasons).lower()
    assert "fake-market-cap" in joined
    assert "single-wallet" in joined


def test_fake_mcap_alone_is_manipulated() -> None:
    block = assess_information_mev(
        market_cap_usd=5_000_000.0,
        liquidity_usd=8_000.0,
        ratio_pct=0.16,
        manip_flags=["thin_liquidity_vs_mcap", "fake_market_cap"],
        top_holder_pct=0.10,
    )
    assert block is not None
    assert block.label == "manipulated"
    assert block.score == 0.7


def test_thin_liquidity_alone_is_elevated() -> None:
    block = assess_information_mev(
        market_cap_usd=2_000_000.0,
        liquidity_usd=12_000.0,
        ratio_pct=0.6,
        manip_flags=["thin_liquidity_vs_mcap"],
        top_holder_pct=0.10,
    )
    assert block is not None
    assert block.label == "elevated"
    assert block.score == 0.4


def test_concentration_alone_is_elevated() -> None:
    """Deep liquidity but a single wallet holds the float => elevated, not clean."""
    block = assess_information_mev(
        market_cap_usd=50_000_000.0,
        liquidity_usd=5_000_000.0,
        ratio_pct=10.0,
        manip_flags=[],
        top_holder_pct=0.60,
    )
    assert block is not None
    assert block.label == "elevated"
    assert block.score == 0.25


def test_deep_liquidity_is_clean() -> None:
    block = assess_information_mev(
        market_cap_usd=100_000_000.0,
        liquidity_usd=20_000_000.0,
        ratio_pct=20.0,
        manip_flags=[],
        top_holder_pct=0.05,
    )
    assert block is not None
    assert block.label == "clean"
    assert block.score == 0.0
    # A clean read still carries an explanatory reason (positive read is info).
    assert block.reasons
    assert "no manipulation signals" in block.reasons[0].lower()


def test_fail_open_none_when_no_inputs() -> None:
    """No ratio AND no holder read => None (fail-OPEN), never a fabricated clean."""
    block = assess_information_mev(
        market_cap_usd=None,
        liquidity_usd=None,
        ratio_pct=None,
        manip_flags=[],
        top_holder_pct=None,
    )
    assert block is None


def test_concentration_only_inputs_still_assessed() -> None:
    """Holder read present but no market ratio => still assessable, not None."""
    block = assess_information_mev(
        market_cap_usd=None,
        liquidity_usd=None,
        ratio_pct=None,
        manip_flags=[],
        top_holder_pct=0.80,
    )
    assert block is not None
    assert block.label == "elevated"
