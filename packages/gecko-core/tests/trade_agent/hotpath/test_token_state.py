"""Tests for the rolling per-mint TokenState accumulator (step 2).

Covers: window aggregation, percentiles, liquidity-weighted index price, wallet
aggregation + round-trips, time-window filtering, and an end-to-end reachability
check (a BrCA-shaped swap stream → to_snapshot → assess_wash_risk actually fires
the thin-pool buy-loop signal — Pattern E at the snapshot boundary).
"""

from __future__ import annotations

from gecko_core.trade_agent.hotpath.token_state import SwapEvent, TokenState
from gecko_core.trade_agent.hotpath.wash_signals import PoolSnapshot, assess_wash_risk


def _buy(ts, wallet, usd, price):
    return SwapEvent(ts=ts, wallet=wallet, side="buy", notional_usd=usd, price_usd=price)


def _sell(ts, wallet, usd, price):
    return SwapEvent(ts=ts, wallet=wallet, side="sell", notional_usd=usd, price_usd=price)


# --------------------------------------------------------------------------- #
# Window aggregation                                                           #
# --------------------------------------------------------------------------- #


def test_empty_state_window_is_none():
    st = TokenState("X")
    snap = st.to_snapshot(now=1000.0)
    assert snap.window is None
    assert snap.wallets == []
    assert snap.index_price_usd is None


def test_window_counts_and_prices():
    st = TokenState("X")
    st.ingest_swap(_buy(100.0, "a", 30.0, 1.0))
    st.ingest_swap(_buy(110.0, "b", 30.0, 1.2))
    st.ingest_swap(_sell(120.0, "c", 50.0, 1.4))
    snap = st.to_snapshot(now=130.0, window_s=300.0)
    assert snap.window is not None
    assert snap.window.buy_count == 2
    assert snap.window.sell_count == 1
    assert snap.window.buy_vol_usd == 60.0
    assert snap.window.sell_vol_usd == 50.0
    assert snap.window.unique_buyers == 2
    assert snap.window.price_open == 1.0  # earliest priced
    assert snap.window.price_close == 1.4  # latest priced
    # net fresh inflow proxy = buy_vol - sell_vol
    assert snap.net_fresh_inflow_usd == 10.0


def test_window_filters_old_swaps():
    st = TokenState("X")
    st.ingest_swap(_buy(100.0, "a", 30.0, 1.0))  # old
    st.ingest_swap(_buy(900.0, "b", 30.0, 1.1))  # in window
    snap = st.to_snapshot(now=1000.0, window_s=300.0)  # window = [700, 1000]
    assert snap.window is not None
    assert snap.window.buy_count == 1
    assert snap.window.unique_buyers == 1


def test_percentiles_reflect_size_spread():
    st = TokenState("X")
    for i in range(20):
        st.ingest_swap(_buy(100.0 + i, f"w{i}", 30.0, 1.0))
    st.ingest_swap(_buy(200.0, "whale", 5000.0, 1.0))  # one fat trade
    snap = st.to_snapshot(now=300.0)
    assert snap.window is not None
    assert snap.window.notional_p50 == 30.0
    assert snap.window.notional_p95 is not None
    assert snap.window.notional_p95 >= 30.0  # spread exists


# --------------------------------------------------------------------------- #
# Index price + wallets                                                        #
# --------------------------------------------------------------------------- #


def test_index_price_is_liquidity_weighted():
    st = TokenState("X")
    st.update_pool(PoolSnapshot(pool_addr="deep", spot_price_usd=5.8, tvl_usd=500_000.0))
    st.update_pool(PoolSnapshot(pool_addr="bait", spot_price_usd=10.2, tvl_usd=300.0))
    snap = st.to_snapshot(now=100.0)
    assert snap.index_price_usd is not None
    # heavily weighted toward the deep pool, NOT the max price
    assert 5.8 <= snap.index_price_usd < 5.81


def test_wallet_round_trips_and_volumes():
    st = TokenState("X")
    # washer: 3 buys + 3 sells = 3 round-trips, balanced
    for i in range(3):
        st.ingest_swap(_buy(100.0 + i, "washer", 1000.0, 1.0))
        st.ingest_swap(_sell(100.5 + i, "washer", 1000.0, 1.0))
    snap = st.to_snapshot(now=200.0)
    washer = next(w for w in snap.wallets if w.address == "washer")
    assert washer.buy_vol_usd == 3000.0
    assert washer.sell_vol_usd == 3000.0
    assert washer.round_trips == 3


def test_wallet_funding_attached():
    st = TokenState("X")
    st.ingest_swap(_buy(100.0, "sybil1", 500.0, 1.0))
    st.set_wallet_funding("sybil1", funder="F", funded_ts=1000, funded_amount=2.0)
    snap = st.to_snapshot(now=200.0)
    sybil = next(w for w in snap.wallets if w.address == "sybil1")
    assert sybil.funder == "F"
    assert sybil.funded_ts == 1000
    assert sybil.funded_amount == 2.0


def test_age_seconds_from_pool_creation():
    st = TokenState("X", pool_created_ts=1000)
    st.ingest_swap(_buy(1100.0, "a", 30.0, 1.0))
    snap = st.to_snapshot(now=1300.0)
    assert snap.age_seconds == 300.0


def test_max_swaps_bounds_memory():
    st = TokenState("X", max_swaps=10)
    for i in range(50):
        st.ingest_swap(_buy(100.0 + i, f"w{i}", 30.0, 1.0))
    snap = st.to_snapshot(now=10_000.0, window_s=100_000.0)
    assert snap.window is not None
    assert snap.window.buy_count == 10  # ring buffer dropped the oldest 40


# --------------------------------------------------------------------------- #
# End-to-end reachability: stream → snapshot → scorer fires                    #
# --------------------------------------------------------------------------- #


def test_brca_stream_reaches_scorer_and_fires():
    """A BrCA-shaped stream (many tiny buys from few wallets, price climbing, no
    sells) must produce a snapshot that the scorer flags. Proves the accumulator
    feeds the scorer correctly — not just that each works alone."""
    st = TokenState("BrCA", pool_created_ts=0)
    price = 1.0
    for i in range(38):
        wallet = f"bot{i % 3}"  # only 3 distinct buyers
        st.ingest_swap(_buy(float(i), wallet, 30.0, price))
        price *= 1.01  # climbs ~+45% over 38 trades
    # Aged so the launch cap doesn't apply — assert F1 fires outright.
    snap = st.to_snapshot(now=10_000.0, window_s=100_000.0)
    block = assess_wash_risk(snap)
    assert block is not None
    assert "thin_pool_buy_loop" in block.fired_signals
