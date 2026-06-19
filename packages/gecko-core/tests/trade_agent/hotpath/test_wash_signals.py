"""Unit tests for the pure Launch-Firewall wash/bot scorers.

Step 1 of the Launch Firewall build order. These test the pure helpers directly
with synthetic snapshots (per `feedback_lighter_tests`: no over-simulation, no
network, no monkeypatching — the module is pure by design). Each test maps to a
signal or a false-positive guard so a failure points at exactly one rule.
"""

from __future__ import annotations

from gecko_core.trade_agent.hotpath.wash_signals import (
    FirewallSnapshot,
    FlowWindow,
    PoolSnapshot,
    WalletSnapshot,
    assess_wash_risk,
)

# --------------------------------------------------------------------------- #
# Builders                                                                     #
# --------------------------------------------------------------------------- #


def _brca_window() -> FlowWindow:
    """The BrCA headline: 38 buys / 0 sells, tiny uniform sizes, price climbing."""
    return FlowWindow(
        buy_count=38,
        sell_count=0,
        buy_vol_usd=1_140.0,
        sell_vol_usd=0.0,
        unique_buyers=3,
        unique_sellers=0,
        notional_p50=30.0,
        notional_p95=35.0,  # p95/p50 = 1.17 < 1.5 → uniform
        price_open=1.0,
        price_close=1.4,  # +40%
    )


def _organic_hype_window() -> FlowWindow:
    """A real hyped fair launch: buy-heavy, but many buyers + fat-tailed sizes."""
    return FlowWindow(
        buy_count=120,
        sell_count=2,
        buy_vol_usd=85_000.0,
        sell_vol_usd=900.0,
        unique_buyers=95,  # many distinct buyers
        unique_sellers=2,
        notional_p50=120.0,
        notional_p95=4_000.0,  # p95/p50 = 33 → fat-tailed
        price_open=1.0,
        price_close=1.5,
    )


# --------------------------------------------------------------------------- #
# Fail-OPEN                                                                    #
# --------------------------------------------------------------------------- #


def test_no_inputs_returns_none_fail_open():
    snap = FirewallSnapshot(mint="X")
    assert assess_wash_risk(snap) is None


def test_empty_window_only_is_no_inputs():
    snap = FirewallSnapshot(mint="X", window=FlowWindow())  # 0 buys, 0 sells
    assert assess_wash_risk(snap) is None


def test_benign_flow_returns_clean_not_none():
    snap = FirewallSnapshot(mint="X", age_seconds=10_000.0, window=_organic_hype_window())
    block = assess_wash_risk(snap)
    assert block is not None
    assert block.label == "clean"
    assert block.score == 0.0
    assert block.fired_signals == []
    assert block.reasons  # carries the positive note


# --------------------------------------------------------------------------- #
# F1 — thin-pool buy-loop                                                      #
# --------------------------------------------------------------------------- #


def test_f1_fires_on_brca_pattern():
    # Aged token so the launch cap doesn't apply — pure F1 behavior.
    snap = FirewallSnapshot(mint="BrCA", age_seconds=10_000.0, window=_brca_window())
    block = assess_wash_risk(snap)
    assert block is not None
    assert "thin_pool_buy_loop" in block.fired_signals
    assert block.label == "elevated"  # single signal → elevated


def test_f1_does_not_fire_on_organic_hype():
    snap = FirewallSnapshot(mint="HYPE", age_seconds=10_000.0, window=_organic_hype_window())
    block = assess_wash_risk(snap)
    assert block is not None
    assert "thin_pool_buy_loop" not in block.fired_signals


def test_f1_requires_rising_price():
    w = _brca_window().model_copy(update={"price_close": 1.0})  # flat price
    snap = FirewallSnapshot(mint="X", age_seconds=10_000.0, window=w)
    block = assess_wash_risk(snap)
    assert block is not None
    assert "thin_pool_buy_loop" not in block.fired_signals


# --------------------------------------------------------------------------- #
# F5 — multi-pool price bait                                                   #
# --------------------------------------------------------------------------- #


def test_f5_fires_on_dead_overpriced_satellite_pool():
    snap = FirewallSnapshot(
        mint="X",
        age_seconds=10_000.0,
        index_price_usd=5.8,
        pools=[
            PoolSnapshot(
                pool_addr="deep_pool", spot_price_usd=5.8, tvl_usd=500_000.0, swap_count_5m=40
            ),
            PoolSnapshot(
                pool_addr="bait_pool_aaaa", spot_price_usd=10.2, tvl_usd=300.0, swap_count_5m=0
            ),
        ],
    )
    block = assess_wash_risk(snap)
    assert block is not None
    assert "multi_pool_price_bait" in block.fired_signals


def test_f5_excludes_clmm_pool_from_bait_flag():
    snap = FirewallSnapshot(
        mint="X",
        age_seconds=10_000.0,
        index_price_usd=5.8,
        pools=[
            PoolSnapshot(
                pool_addr="clmm_out_of_range",
                spot_price_usd=10.2,
                tvl_usd=300.0,
                swap_count_5m=0,
                is_clmm=True,  # out-of-range CLMM is not a fake bait pool
            ),
        ],
    )
    block = assess_wash_risk(snap)
    assert block is not None
    assert "multi_pool_price_bait" not in block.fired_signals


def test_f5_does_not_fire_when_overpriced_pool_is_active():
    # High dispersion but the pool is deep + trading → not dead bait.
    snap = FirewallSnapshot(
        mint="X",
        age_seconds=10_000.0,
        index_price_usd=5.8,
        pools=[
            PoolSnapshot(pool_addr="busy", spot_price_usd=10.2, tvl_usd=50_000.0, swap_count_5m=25),
        ],
    )
    block = assess_wash_risk(snap)
    assert block is not None
    assert "multi_pool_price_bait" not in block.fired_signals


# --------------------------------------------------------------------------- #
# F2 — wash / self-trade                                                       #
# --------------------------------------------------------------------------- #


def test_f2_fires_on_balanced_churn_with_no_inflow():
    snap = FirewallSnapshot(
        mint="X",
        age_seconds=10_000.0,
        net_fresh_inflow_usd=0.0,
        wallets=[
            WalletSnapshot(
                address="washer_aaaa", buy_vol_usd=10_000.0, sell_vol_usd=9_500.0, round_trips=6
            ),
        ],
    )
    block = assess_wash_risk(snap)
    assert block is not None
    assert "wash_self_trade" in block.fired_signals


def test_f2_mm_guard_suppresses_when_fresh_capital_enters():
    # Same balanced churn, but real net inflow → looks like MM, not wash.
    snap = FirewallSnapshot(
        mint="X",
        age_seconds=10_000.0,
        net_fresh_inflow_usd=12_000.0,  # > 5% of wallet volume
        wallets=[
            WalletSnapshot(
                address="mm_aaaa", buy_vol_usd=10_000.0, sell_vol_usd=9_500.0, round_trips=6
            ),
        ],
    )
    block = assess_wash_risk(snap)
    assert block is not None
    assert "wash_self_trade" not in block.fired_signals


def test_f2_does_not_fire_on_one_directional_wallet():
    snap = FirewallSnapshot(
        mint="X",
        age_seconds=10_000.0,
        net_fresh_inflow_usd=0.0,
        wallets=[
            WalletSnapshot(
                address="buyer_aaaa", buy_vol_usd=10_000.0, sell_vol_usd=0.0, round_trips=6
            ),
        ],
    )
    block = assess_wash_risk(snap)
    assert block is not None
    assert "wash_self_trade" not in block.fired_signals


# --------------------------------------------------------------------------- #
# F4 — common-funder sybil                                                     #
# --------------------------------------------------------------------------- #


def _sybil_wallets(funder: str = "fresh_funder") -> list[WalletSnapshot]:
    # 6 buyers, all funded by one fresh wallet, ~identical amounts, pre-launch.
    return [
        WalletSnapshot(
            address=f"sybil_{i}",
            buy_vol_usd=500.0,
            funder=funder,
            funded_ts=1_000_000,
            funded_amount=2.0,
        )
        for i in range(6)
    ]


def test_f4_fires_on_common_funder_cluster():
    snap = FirewallSnapshot(
        mint="X",
        age_seconds=10_000.0,
        pool_created_ts=1_010_000,  # within 24h of funded_ts
        wallets=_sybil_wallets(),
    )
    block = assess_wash_risk(snap)
    assert block is not None
    assert "common_funder_sybil" in block.fired_signals


def test_f4_cex_funder_is_not_a_sybil_cluster():
    snap = FirewallSnapshot(
        mint="X",
        age_seconds=10_000.0,
        pool_created_ts=1_010_000,
        wallets=_sybil_wallets(funder="binance_hot"),
        cex_funders=frozenset({"binance_hot"}),
    )
    block = assess_wash_risk(snap)
    assert block is not None
    assert "common_funder_sybil" not in block.fired_signals


def test_f4_needs_minimum_buyer_set():
    snap = FirewallSnapshot(
        mint="X",
        age_seconds=10_000.0,
        pool_created_ts=1_010_000,
        wallets=_sybil_wallets()[:3],  # below F4_MIN_BUYERS
    )
    block = assess_wash_risk(snap)
    assert block is not None
    assert "common_funder_sybil" not in block.fired_signals


# --------------------------------------------------------------------------- #
# Aggregation + launch FP guard                                               #
# --------------------------------------------------------------------------- #


def test_aged_token_two_signals_escalates_to_manipulated():
    # BrCA full picture, aged: F1 + F5 both fire → manipulated.
    snap = FirewallSnapshot(
        mint="BrCA",
        age_seconds=10_000.0,
        window=_brca_window(),
        index_price_usd=5.8,
        pools=[
            PoolSnapshot(
                pool_addr="bait_pool_aaaa", spot_price_usd=10.2, tvl_usd=300.0, swap_count_5m=0
            ),
        ],
    )
    block = assess_wash_risk(snap)
    assert block is not None
    assert set(block.fired_signals) >= {"thin_pool_buy_loop", "multi_pool_price_bait"}
    assert block.label == "manipulated"
    assert block.score >= 0.6


def test_launch_guard_caps_single_signal_at_elevated():
    # Same F1 pattern but freshly launched (< 1h) with only one signal → elevated.
    snap = FirewallSnapshot(mint="BrCA", age_seconds=120.0, window=_brca_window())
    block = assess_wash_risk(snap)
    assert block is not None
    assert block.fired_signals == ["thin_pool_buy_loop"]
    assert block.label == "elevated"  # capped, not manipulated, at launch


def test_launch_guard_does_not_cap_two_signals():
    # Two signals at launch is corroborated → manipulated stands.
    snap = FirewallSnapshot(
        mint="BrCA",
        age_seconds=120.0,
        window=_brca_window(),
        index_price_usd=5.8,
        pools=[
            PoolSnapshot(
                pool_addr="bait_pool_aaaa", spot_price_usd=10.2, tvl_usd=300.0, swap_count_5m=0
            ),
        ],
    )
    block = assess_wash_risk(snap)
    assert block is not None
    assert len(block.fired_signals) >= 2
    assert block.label == "manipulated"


def test_score_is_bounded_at_one():
    # All four signals fire → score clamps to 1.0.
    snap = FirewallSnapshot(
        mint="X",
        age_seconds=10_000.0,
        window=_brca_window(),
        index_price_usd=5.8,
        net_fresh_inflow_usd=0.0,
        pool_created_ts=1_010_000,
        pools=[
            PoolSnapshot(
                pool_addr="bait_pool_aaaa", spot_price_usd=10.2, tvl_usd=300.0, swap_count_5m=0
            ),
        ],
        wallets=[
            WalletSnapshot(
                address="washer_aaaa", buy_vol_usd=10_000.0, sell_vol_usd=9_500.0, round_trips=6
            ),
            *_sybil_wallets(),
        ],
    )
    block = assess_wash_risk(snap)
    assert block is not None
    assert block.score == 1.0
    assert block.label == "manipulated"
    assert len(block.fired_signals) == 4
