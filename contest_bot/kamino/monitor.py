"""Yield-safety monitor — the profit-vault's verdict layer (S42).

This is the PRODUCT, not Kamino. Kamino is swappable plumbing; the monitor is
the verification/safety wedge applied to yield. It answers, on cadence, one
question per position:

    "Is this yield still worth the risk, RIGHT NOW — or do we pull the user out?"

Two things make it more than a dashboard number:

1. HURDLE RATE. Founder's principle (2026-06-04): there is no sense taking
   smart-contract / depeg / spread risk for a yield that loses to a risk-free
   alternative. A Brazilian CDB at ~103% CDI nets ~12% APY after IR. So the
   default fiat-aware hurdle is 12% — below it, we do NOT recommend the position.
   A crypto-only user (no fiat CDB access) has a far lower hurdle (idle USDC / a
   plain lend ~5-6%). The hurdle is per-user, and the monitor enforces it:
   a position whose PROJECTED net APY drops below the user's hurdle is flagged
   to ROTATE or EXIT — we don't keep you in something that no longer beats your
   own benchmark.

2. NO-FLOOR PROTECTION. A leveraged spread can invert (borrow > yield) and then
   leverage multiplies the LOSS. The monitor catches the crossover and exits.
   (Verified live 2026-06-04: the classic "stable loop" was already inverted —
   USDC borrow 8.08% > supply 6.32% — so a 4x loop netted ~+1%, not 30%.)

Pure decision function over a `LeverageStrategy` snapshot → a `VaultVerdict`.
No network here; the caller refreshes live rates and feeds them in.
"""

from __future__ import annotations

from dataclasses import dataclass

from kamino.multiply import LeverageStrategy, leverage_to_clear

# ── Hurdle presets ──────────────────────────────────────────────────────
# Net-of-tax annual return the position must beat to justify its risk.


@dataclass(frozen=True)
class Hurdle:
    apy: float
    label: str
    note: str


# ~103% CDI after IR (Brazilian risk-free fiat benchmark). The default for a
# user who COULD instead hold a CDB — below this, taking crypto risk is "for nothing".
FIAT_CDB_BR = Hurdle(0.12, "fiat_cdb_br", "≈103% CDI net of IR — beat it or hold a CDB")
# A crypto-only user's realistic floor: idle USDC earns 0; a plain Kamino lend ~5-6%.
CRYPTO_ONLY = Hurdle(0.055, "crypto_only", "plain USDC lend floor; idle = 0%")


def hurdle_for(profile: str) -> Hurdle:
    """Map a user profile to its default hurdle. Fiat-aware profiles use the CDB bar."""
    return CRYPTO_ONLY if profile == "crypto_only" else FIAT_CDB_BR


# Actions, most severe first.
EXIT = "EXIT"  # close the position now (spread inverted, or below hurdle with no fix)
DELEVERAGE = "DELEVERAGE"  # reduce leverage (LTV too close to liquidation)
ROTATE = "ROTATE"  # move to a strategy/leverage that clears the hurdle
HOLD = "HOLD"  # all clear


@dataclass(frozen=True)
class VaultVerdict:
    action: str
    reason: str
    net_apy: float
    clears_hurdle: bool
    suggested_leverage: float | None = None  # for ROTATE: the leverage that would clear the hurdle


def apply_min_hold_lock(action: str, *, reason: str, locked: bool, safety: bool) -> dict:
    """Min-hold lock (S48): "don't liquidate before it's worth it."

    A Multiply position has a break-even holding period (kamino.multiply.min_hold_period)
    before accrued yield clears its round-trip cost. Until then we must NOT exit for
    OPTIMIZATION reasons (ROTATE to a better yield, or a yield-driven DELEVERAGE on
    non-dangerous spread compression) — that just realizes the cost for nothing.

    SAFETY exits ALWAYS override the lock: depeg (Pegana DEPEG/CRITICAL), liquidation-
    distance breach, deep spread inversion. The caller classifies `safety`.

    Returns {action, locked, override?, deferred_reason?}:
      - safety=True               → pass the action through, tag `override`=reason.
      - locked & action in {ROTATE, DELEVERAGE} & not safety → downgrade to HOLD,
        tag `deferred_reason`=reason.
      - otherwise                 → pass through unchanged.
    """
    if safety:
        return {"action": action, "locked": locked, "override": reason}
    if locked and action in (ROTATE, DELEVERAGE):
        return {"action": HOLD, "locked": True, "deferred_reason": reason}
    return {"action": action, "locked": locked}


def evaluate(
    strategy: LeverageStrategy,
    hurdle: Hurdle = FIAT_CDB_BR,
    ltv_warn_buffer: float = 0.03,
    predicted_drawdown_pct: float | None = None,
    liq_safety_factor: float = 0.6,
) -> VaultVerdict:
    """Decide what to do with a live position. Severity order: liquidation-risk
    and spread-inversion (capital-preservation) outrank the hurdle (opportunity).

    1. Spread inverted (borrow > yield) → EXIT. Leverage is multiplying a loss;
       the un-leveraged base would do better. No floor.
    2. ORACLE-PREDICTED downside vs the liquidation buffer (price-liquidatable
       assets only). `predicted_drawdown_pct` is the SAME downside prediction our
       trading Oracle / market-temp produces for the collateral leg — we watch the
       vault the way we watch a trade. The buffer is `strategy.liquidation_drop_pct`
       (e.g. 10x → 10% kills it, 5x → 20% margin). If the predicted move would
       breach the buffer → EXIT; if it's within `liq_safety_factor` of it → DELEVERAGE.
    3. Static LTV proximity (no prediction supplied) → DELEVERAGE.
    4. Net APY below the user's hurdle → ROTATE to the leverage that clears it,
       or EXIT if no safe leverage can (capped at the eMode ceiling).
    5. Else HOLD.
    """
    net = strategy.net_apy
    clears = net >= hurdle.apy

    # 1. Capital-preservation: inverted spread under leverage = bleeding.
    if strategy.leverage > 1.0 and strategy.spread_inverted:
        return VaultVerdict(
            EXIT,
            f"spread inverted (borrow {strategy.borrow_rate:.2%} > yield "
            f"{strategy.collateral_yield:.2%}) — leverage multiplies the loss; no floor",
            net,
            clears,
        )

    # 2. Oracle-predicted downside vs the liquidation buffer (the founder's insight:
    #    1000x10 dies on a 10% drop; 5x survives to 20%). Volatile/uncorrelated only —
    #    correlated pairs move together, so a market drop doesn't change the ratio.
    if not strategy.correlated and predicted_drawdown_pct is not None and strategy.leverage > 1.0:
        buffer = strategy.liquidation_drop_pct
        if predicted_drawdown_pct >= buffer:
            return VaultVerdict(
                EXIT,
                f"Oracle predicts ~{predicted_drawdown_pct:.0%} downside ≥ "
                f"{buffer:.0%} liquidation buffer at {strategy.leverage:.0f}x — exit before liquidation",
                net,
                clears,
            )
        if predicted_drawdown_pct >= buffer * liq_safety_factor:
            return VaultVerdict(
                DELEVERAGE,
                f"Oracle predicts ~{predicted_drawdown_pct:.0%} downside, within "
                f"{liq_safety_factor:.0%} of the {buffer:.0%} buffer at {strategy.leverage:.0f}x — cut leverage",
                net,
                clears,
            )

    # 3. Static LTV proximity (price-liquidatable assets only, no prediction).
    if not strategy.correlated and strategy.ltv_headroom <= ltv_warn_buffer:
        return VaultVerdict(
            DELEVERAGE,
            f"operating LTV {strategy.operating_ltv:.2%} within {ltv_warn_buffer:.0%} of "
            f"liquidation {strategy.liquidation_ltv:.2%} on a volatile asset",
            net,
            clears,
        )

    # 3. Hurdle: is the yield even worth the risk?
    if not clears:
        target = leverage_to_clear(strategy, hurdle.apy)
        if target is None or (not strategy.correlated):
            # can't safely lever to clear it, or doing so adds price risk → get out
            return VaultVerdict(
                EXIT,
                f"net {net:.2%} < hurdle {hurdle.apy:.2%} ({hurdle.label}) and no safe "
                f"leverage clears it — taking risk for nothing; exit to lend/CDB",
                net,
                clears,
            )
        return VaultVerdict(
            ROTATE,
            f"net {net:.2%} < hurdle {hurdle.apy:.2%} ({hurdle.label}); rotate to "
            f"~{target:.1f}x on this correlated pair to clear it",
            net,
            clears,
            suggested_leverage=target,
        )

    return VaultVerdict(
        HOLD, f"net {net:.2%} ≥ hurdle {hurdle.apy:.2%} ({hurdle.label})", net, clears
    )
