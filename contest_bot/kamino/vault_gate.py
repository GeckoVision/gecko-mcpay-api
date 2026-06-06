"""Vault safety gate (S44) — the profit-vault's deny-default rail.

The same wedge as `trade_safety` (keep the agent from blowing up), applied to
yield. Every vault op (deposit / rebalance / withdraw) passes this gate BEFORE any
adapter touches a chain. It composes the S42 monitor: you may NOT deposit INTO a
position the monitor would EXIT, and you may not exceed the user's allocation cap.

Deny is the default; the verdict lists EVERY reason so the UI shows the full
picture. No network, no signing — this is pure policy. Live custody stays gated in
the adapter (devnet/stub now; OKX-TEE/Privy later, founder-gated).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from kamino.monitor import EXIT, FIAT_CDB_BR, Hurdle, evaluate
from kamino.multiply import LeverageStrategy

DEPOSIT = "deposit"
WITHDRAW = "withdraw"
REBALANCE = "rebalance"


@dataclass
class VaultPolicy:
    """The user's (or fintech's) yield guardrails — the vault analogue of
    TradeSafetyPolicy. `max_allocation_usd=0` disables the vault entirely."""

    max_allocation_usd: float = 0.0  # ceiling on total capital in the vault
    max_single_deposit_usd: float = 0.0  # 0 = no per-op cap beyond the allocation ceiling
    allowed_yield_sources: tuple[str, ...] = ()  # empty = allow any modeled source
    max_leverage: float = 10.0  # refuse openers above this (eMode ceilings cap real ones lower)
    kill_switch: bool = False  # operator/fintech hard stop
    hurdle: Hurdle = field(default_factory=lambda: FIAT_CDB_BR)


@dataclass
class VaultGateVerdict:
    allow: bool
    reasons: list[str] = field(default_factory=list)
    monitor_action: str | None = None  # the S42 monitor verdict action, if a strategy was judged


def vault_check(
    op: str,
    amount_usd: float,
    policy: VaultPolicy,
    *,
    strategy: LeverageStrategy | None = None,
    current_allocation_usd: float = 0.0,
    predicted_drawdown_pct: float | None = None,
    peg_state: dict | None = None,
) -> VaultGateVerdict:
    """The gate. `strategy` is the position being deposited into / held (None for a
    plain withdrawal). For deposits into a LEVERAGED strategy, the monitor must not
    say EXIT — we never add capital to a position we'd be pulling out of.

    `peg_state` (S48) is the Pegana `{state, discount, ...}` for the leg's
    collateral. Deny-default: NEVER deposit into a leg whose asset is
    DRIFT/DEPEG/CRITICAL — adding capital to a depegging collateral is the exact
    failure the signal exists to prevent. None / PEGGED / UNKNOWN = no veto."""
    reasons: list[str] = []
    monitor_action: str | None = None

    if policy.kill_switch:
        reasons.append("vault kill_switch engaged")
    if policy.max_allocation_usd <= 0:
        reasons.append("vault disabled (max_allocation_usd is 0)")
    if amount_usd <= 0:
        reasons.append("non-positive amount")

    if op in (DEPOSIT, REBALANCE):
        # S48 — deny a deposit into a leg whose collateral is off-peg.
        if peg_state:
            ps = str(peg_state.get("state") or "").upper()
            if ps in ("DRIFT", "DEPEG", "CRITICAL"):
                disc = peg_state.get("discount")
                disc_s = f" disc={disc:+.2%}" if isinstance(disc, (int, float)) else ""
                reasons.append(f"collateral off-peg (peg_{ps}{disc_s}) — no deposit into a depegging leg")
        if current_allocation_usd + amount_usd > policy.max_allocation_usd:
            reasons.append(
                f"would exceed allocation cap: ${current_allocation_usd:.2f}+${amount_usd:.2f} "
                f"> ${policy.max_allocation_usd:.2f}"
            )
        if policy.max_single_deposit_usd and amount_usd > policy.max_single_deposit_usd:
            reasons.append(f"deposit ${amount_usd:.2f} > per-op cap ${policy.max_single_deposit_usd:.2f}")
        if strategy is not None:
            if strategy.leverage > policy.max_leverage:
                reasons.append(f"leverage {strategy.leverage:.1f}x > cap {policy.max_leverage:.1f}x")
            if policy.allowed_yield_sources and strategy.yield_source not in policy.allowed_yield_sources:
                reasons.append(f"yield source {strategy.yield_source!r} not allowed")
            # the wedge: don't deposit into a position the monitor would exit/deleverage
            v = evaluate(
                strategy,
                hurdle=policy.hurdle,
                predicted_drawdown_pct=predicted_drawdown_pct,
                peg_state=peg_state,
            )
            monitor_action = v.action
            if v.action == EXIT:
                reasons.append(f"monitor says EXIT before depositing: {v.reason}")

    return VaultGateVerdict(allow=not reasons, reasons=reasons, monitor_action=monitor_action)
