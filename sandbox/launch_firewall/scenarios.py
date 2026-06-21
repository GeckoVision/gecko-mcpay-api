"""Attack/benign scenario generators for the Launch-Firewall sandbox.

Pure fixture builders — each returns a list of (kind, payload) events the
defense harness replays into the real ``LaunchMonitor``. No I/O, no validator;
this is the free local simulation (Pattern B) that falsifies the firewall before
any mainnet spend. The same scenarios are reused by the real-validator path
(step 6) by translating these events into on-chain transactions.
"""

from __future__ import annotations

from gecko_core.trade_agent.hotpath.snipe_features import LAMPORTS_PER_SOL, ParsedSwap
from gecko_core.trade_agent.hotpath.token_state import SwapEvent
from gecko_core.trade_agent.hotpath.wash_signals import PoolSnapshot

# An established AMM program id (Raydium) — a buy routed through it carries NO
# unknown-program tell, so parsed-swap scenarios that use it isolate the signal
# under test instead of tripping the I2 first-seen-program flag by accident.
_RAYDIUM = "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"
_SNIPER_PROG = "Sn1perPr0gram1111111111111111111111111111111"


def brca_inflate_then_drain(created_ts: int = 0) -> list[SwapEvent]:
    """The BrCA headline: 38 tiny buys from 3 bot wallets, price climbing, 0 sells."""
    out: list[SwapEvent] = []
    price = 1.0
    for i in range(38):
        out.append(
            SwapEvent(
                ts=float(created_ts + i),
                wallet=f"bot{i % 3}",
                side="buy",
                notional_usd=30.0,
                price_usd=price,
            )
        )
        price *= 1.01
    return out


def brca_bait_pools() -> list[PoolSnapshot]:
    """The deep 'truth' pool + a thin dead satellite quoting far above the index."""
    return [
        PoolSnapshot(
            pool_addr="deep_pool", spot_price_usd=1.45, tvl_usd=400_000.0, swap_count_5m=38
        ),
        PoolSnapshot(pool_addr="bait_pool_xx", spot_price_usd=3.5, tvl_usd=200.0, swap_count_5m=0),
    ]


def organic_launch(created_ts: int = 0) -> list[SwapEvent]:
    """A genuine fair launch: many unique buyers, fat-tailed sizes, real sells."""
    out: list[SwapEvent] = []
    for i in range(60):
        out.append(
            SwapEvent(
                ts=float(created_ts + i),
                wallet=f"u{i}",
                side="buy",
                notional_usd=100.0 + i * 50,
                price_usd=1.0,
            )
        )
    for i in range(20):
        out.append(
            SwapEvent(
                ts=float(created_ts + 60 + i),
                wallet=f"s{i}",
                side="sell",
                notional_usd=120.0,
                price_usd=1.0,
            )
        )
    return out


# --------------------------------------------------------------------------- #
# Parsed-swap (signer-level) generators — the snipe-gate path                  #
# --------------------------------------------------------------------------- #
# The snipe gate fires only from ParsedSwap (signer / slot / tip / program /
# notional). These mirror the SwapEvent scenarios above for the snipe leg of the
# 3-way harness: a LOUD snipe (every automation tell on), the EVASION (every
# automation tell OFF, float still captured), and an organic control.


def loud_snipe_parsed(created_ts: int = 0) -> list[ParsedSwap]:
    """The obvious snipe: 4 fresh wallets co-buy ONE slot via Jito bundles through
    a custom sniper program. Every high-precision automation tell fires."""
    return [
        ParsedSwap(
            signer=f"W{i}",
            slot=500,  # same slot -> co-buy cluster
            is_buy=True,
            notional_sol=1.0,
            tip_lamports=int(2e-4 * LAMPORTS_PER_SOL),  # Jito bundle tip
            program_ids=[_SNIPER_PROG],  # first-seen custom program
            wallet_age_s=120.0,  # fresh wallet swarm
            timestamp=float(created_ts),
        )
        for i in range(4)
    ]


def evasion_launch_parsed(created_ts: int = 0) -> list[ParsedSwap]:
    """THE evasion: every high-precision automation tell OFF, float still captured.

    Slot-SPREAD (distinct slots), NO Jito tip, NO shared ALT, multi-hop funded
    (modeled as aged wallets with no shared funder/ALT), RANDOMIZED sizing, and a
    FEW wallets buying MANY times one-sided (the diversity-deficit). This is a
    MODERATE capture — concentrated enough that ``concentrated_capture`` fires but
    NOT extreme — so it lands at ``suspicious`` ALONE (the floor-raise) and would
    escalate to ``block`` with any corroborator. No co-buy / tip / ALT / fresh /
    unknown-program tell fires.
    """
    # 2 dominant wallets accumulate; 4 minor wallets take small bites. Jittered,
    # non-uniform sizes; each buy on its own slot.
    sizes: dict[str, list[float]] = {
        "C0": [2.0, 1.8, 2.2, 1.9, 2.1],
        "C1": [1.7, 1.9, 1.6, 2.0],
        "C2": [0.4, 0.5],
        "C3": [0.3, 0.45],
        "C4": [0.35],
        "C5": [0.3],
    }
    out: list[ParsedSwap] = []
    slot = 500
    for wallet, szs in sizes.items():
        for sz in szs:
            slot += 5  # DISTINCT slots — defeats same_slot_co_buy
            out.append(
                ParsedSwap(
                    signer=wallet,
                    slot=slot,
                    is_buy=True,
                    notional_sol=sz,
                    tip_lamports=0,  # NO Jito tip
                    program_ids=[_RAYDIUM],  # established program — no I2 tell
                    alt_addresses=[],  # NO shared ALT
                    wallet_age_s=5_000_000.0,  # aged — no fresh swarm
                    timestamp=float(created_ts) + (slot - 500),
                )
            )
    # a couple of small sells -> one_sided just under 1.0 (still >= ONESIDE_T),
    # keeping the capture MODERATE (not the extreme zero-sell tier).
    for _ in range(2):
        slot += 5
        out.append(
            ParsedSwap(
                signer="C0",
                slot=slot,
                is_buy=False,
                notional_sol=0.6,
                program_ids=[_RAYDIUM],
                timestamp=float(created_ts) + (slot - 500),
            )
        )
    return out


def organic_launch_parsed(created_ts: int = 0) -> list[ParsedSwap]:
    """The snipe-path control: many distinct aged wallets, ~1 buy each, fat-tailed
    sizes, genuine two-sided sells, spread slots, no tips/ALT. Must NOT fire."""
    sizes = [0.2, 0.3, 0.5, 0.8, 1.2, 2.0, 3.5, 0.4, 0.6, 1.0]
    out: list[ParsedSwap] = []
    slot = 500
    for i in range(40):
        slot += 2
        out.append(
            ParsedSwap(
                signer=f"U{i}",
                slot=slot,
                is_buy=True,
                notional_sol=sizes[i % len(sizes)],
                program_ids=[_RAYDIUM],
                wallet_age_s=5_000_000.0,
                timestamp=float(created_ts) + (slot - 500),
            )
        )
    # real price discovery: genuine two-sided sells from a spread of wallets
    for i in range(15):
        slot += 2
        out.append(
            ParsedSwap(
                signer=f"U{i}",
                slot=slot,
                is_buy=False,
                notional_sol=0.8,
                program_ids=[_RAYDIUM],
                timestamp=float(created_ts) + (slot - 500),
            )
        )
    return out
