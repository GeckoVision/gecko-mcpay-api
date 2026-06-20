"""Snipe-feature builder — the parsed-tx → SnipeSnapshot bridge (B1 reachability).

The B1 snipe gate (:mod:`snipe_gate`) is the brain; this is the bridge that fills
its :class:`SnipeSnapshot` from already-parsed transactions. It is the answer to
the honest "wired ≠ reaches the model" gap (Pattern E): with this builder, a real
fresh launch's parsed swaps produce a non-null ``SnipeBlock`` end-to-end.

**Pattern B discipline:** this is the *free local simulation* layer. It is a pure
function over a list of :class:`ParsedSwap` — no network, no RPC. The live Helius
(enhanced-tx / parsed-tx) fetch is a thin adapter that maps the provider's wire
shape onto :class:`ParsedSwap`; that adapter is the only piece that costs anything
to run, and it can be swapped/recorded (vcr-style) without touching this logic.

What a ``ParsedSwap`` carries is exactly the four things the firewall fuses that
no single-tx scanner sees: **who** (signer), **when** (slot), **how** (tip account
paid + program routed through), and **how much** (notional). Aggregating across
swaps for one mint is what turns isolated transactions into a launch-integrity
read.

Hotpath-clean: ``pydantic`` + stdlib only.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from gecko_core.trade_agent.hotpath.program_reputation import has_unknown_program
from gecko_core.trade_agent.hotpath.snipe_gate import (
    FRESH_WALLET_MAX_AGE_S,
    SnipeSnapshot,
)

LAMPORTS_PER_SOL = 1_000_000_000


class ParsedSwap(BaseModel):
    """One already-parsed swap on the launch pool (the adapter target shape).

    The live adapter maps a Helius enhanced/parsed transaction onto this:
    ``signer`` = feePayer, ``slot`` from the tx, ``tip_lamports`` = sum of native
    transfers to a Jito tip account, ``program_ids`` from the instruction set,
    ``wallet_age_s`` from a creation-slot lookup (optional).
    """

    model_config = ConfigDict(extra="forbid")

    signer: str = Field(..., description="buyer/seller wallet (tx feePayer).")
    slot: int = Field(..., ge=0)
    is_buy: bool = Field(default=True, description="True = buy of the launch token.")
    notional_sol: float = Field(default=0.0, ge=0.0, description="SOL value of the swap.")
    tip_lamports: int = Field(
        default=0, ge=0, description="lamports paid to a Jito tip account (0 = no bundle)."
    )
    program_ids: list[str] = Field(
        default_factory=list, description="program ids the tx touched (for I2 attribution)."
    )
    wallet_age_s: float | None = Field(
        default=None, ge=0.0, description="signer account age at swap time (None = unknown)."
    )
    timestamp: float | None = Field(default=None, ge=0.0, description="block time (epoch s).")


def _percentile(values: list[float], pct: float) -> float | None:
    """Linear-interpolated percentile (pct in [0,1]); ``None`` for an empty list."""
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = pct * (len(ordered) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(ordered) - 1)
    frac = rank - lo
    return ordered[lo] + (ordered[hi] - ordered[lo]) * frac


def build_snipe_snapshot(
    mint: str,
    swaps: list[ParsedSwap],
    *,
    now: float | None = None,
    launch_time: float | None = None,
    lp_drained: bool = False,
) -> SnipeSnapshot:
    """Aggregate parsed swaps for one mint into a :class:`SnipeSnapshot`.

    Only **buys** drive the launch-integrity signals (a snipe is a coordinated buy
    cluster). ``now``/``launch_time`` set ``age_seconds`` so the gate's launch FP
    guard can fire. ``lp_drained`` is passed through (its detector — reserve-series
    drop + early-buyer exit — is a separate upstream signal not computed here).
    """
    buys = [s for s in swaps if s.is_buy]

    buyers = {s.signer for s in buys}
    buyer_count = len(buyers)

    # most distinct buyers seen in any single slot (the co-buy cluster)
    per_slot: dict[int, set[str]] = {}
    for s in buys:
        per_slot.setdefault(s.slot, set()).add(s.signer)
    max_slot_unique_buyers = max((len(v) for v in per_slot.values()), default=0)

    jito_bundle_buys = sum(1 for s in buys if s.tip_lamports > 0)

    # fresh-wallet count is per distinct buyer, not per swap (a sniper loops one wallet)
    fresh_buyers = {
        s.signer
        for s in buys
        if s.wallet_age_s is not None and s.wallet_age_s < FRESH_WALLET_MAX_AGE_S
    }
    fresh_wallet_buyers = len(fresh_buyers)

    # distinct buyers whose tx routed through a first-seen/unknown program (I2)
    unknown_program_buyers = {
        s.signer for s in buys if s.program_ids and has_unknown_program(s.program_ids)
    }
    unknown_program_buys = len(unknown_program_buyers)

    tips_sol = [s.tip_lamports / LAMPORTS_PER_SOL for s in buys if s.tip_lamports > 0]
    max_buy_tip_sol = max(tips_sol) if tips_sol else None

    notionals = [s.notional_sol for s in buys if s.notional_sol > 0]
    notional_p50 = _percentile(notionals, 0.50)
    notional_p95 = _percentile(notionals, 0.95)

    age_seconds: float | None = None
    if launch_time is None:
        ts = [s.timestamp for s in buys if s.timestamp is not None]
        launch_time = min(ts) if ts else None
    if now is not None and launch_time is not None:
        age_seconds = max(0.0, now - launch_time)

    return SnipeSnapshot(
        mint=mint,
        age_seconds=age_seconds,
        buyer_count=buyer_count,
        max_slot_unique_buyers=max_slot_unique_buyers,
        jito_bundle_buys=jito_bundle_buys,
        fresh_wallet_buyers=fresh_wallet_buyers,
        unknown_program_buys=unknown_program_buys,
        max_buy_tip_sol=max_buy_tip_sol,
        notional_p50=notional_p50,
        notional_p95=notional_p95,
        lp_drained=lp_drained,
    )


__all__ = ["LAMPORTS_PER_SOL", "ParsedSwap", "build_snipe_snapshot"]
