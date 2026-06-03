"""Pre-trade safety gate + execution-adapter seam — Phase 4 of the agent flow.

This module IS the wedge (per `memory/project_wedge_safety_api_2026_06_03`): a
**safety / verification layer for trading agents** — "keep my agent from blowing
up; is this strategy safe to trust with money." Every real-money order passes the
gate BEFORE any custody backend signs. The §5 rigor verdict is wired in as a hard
precondition: an unverified/REJECT strategy cannot trade real money.

Custody/signing itself is delegated (OKX TEE / Privy server-wallet, S26 — we never
hold a raw key; see `private/strategy/2026-06-03-nitro-enclaves-custody-verdict.md`).
This module does NOT sign or place real orders — the real adapter is a gated stub;
live dispatch is founder-gated (X402_MODE / PAPER_TRADE), never flipped here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

# strategy verdicts that may touch real money (from the §5 / DEPLOY gate)
_TRADEABLE_VERDICTS = {"DEPLOY"}  # PAPER ONLY / REJECT may NOT trade real money


@dataclass
class TradeSafetyPolicy:
    """The per-agent safety envelope — the user's (or fintech's) guardrails.
    Mirrors the S26 PermissionKey grid; this is what the safety API enforces."""

    max_notional_usd: float = 100.0
    max_daily_loss_usd: float = 25.0
    allowed_venues: tuple[str, ...] = ("okx", "okx_spot")
    allowed_symbols: tuple[str, ...] = ()  # empty = allow any symbol
    require_verified_strategy: bool = True  # strategy must hold a DEPLOY verdict
    kill_switch: bool = False  # operator/fintech hard stop


@dataclass
class Order:
    symbol: str
    venue: str
    notional_usd: float
    side: str = "buy"


@dataclass
class SafetyContext:
    strategy_verdict: str | None = None  # DEPLOY | PAPER ONLY | REJECT | None
    realized_loss_today_usd: float = 0.0  # positive number = loss so far today


@dataclass
class SafetyVerdict:
    allow: bool
    reasons: list[str] = field(default_factory=list)


def check_order(order: Order, policy: TradeSafetyPolicy, ctx: SafetyContext) -> SafetyVerdict:
    """The gate. Returns allow/deny + every reason it would deny (so the UI can
    show the full picture, not just the first failure). Deny is the default
    posture — any failed check blocks the order."""
    reasons: list[str] = []

    if policy.kill_switch:
        reasons.append("kill_switch engaged")
    if order.notional_usd <= 0:
        reasons.append("non-positive notional")
    if order.notional_usd > policy.max_notional_usd:
        reasons.append(f"notional ${order.notional_usd:.2f} > cap ${policy.max_notional_usd:.2f}")
    if order.venue not in policy.allowed_venues:
        reasons.append(f"venue {order.venue!r} not in allowed {policy.allowed_venues}")
    if policy.allowed_symbols and order.symbol not in policy.allowed_symbols:
        reasons.append(f"symbol {order.symbol!r} not in allowed set")
    # daily-loss circuit breaker: once today's loss hits the cap, no new positions
    if ctx.realized_loss_today_usd >= policy.max_daily_loss_usd:
        reasons.append(
            f"daily loss ${ctx.realized_loss_today_usd:.2f} >= cap ${policy.max_daily_loss_usd:.2f}"
        )
    # the verification wedge: real money only behind a passing rigor verdict
    if policy.require_verified_strategy and ctx.strategy_verdict not in _TRADEABLE_VERDICTS:
        reasons.append(
            f"strategy verdict {ctx.strategy_verdict!r} is not DEPLOY "
            "(unverified strategies cannot trade real money)"
        )
    return SafetyVerdict(allow=not reasons, reasons=reasons)


# ── execution-adapter seam (custody-neutral; real path is a gated stub) ──
@dataclass
class ExecResult:
    ok: bool
    detail: str
    paper: bool = True
    fill_price: float | None = None


@runtime_checkable
class ExecutionAdapter(Protocol):
    venue: str

    def place_order(self, order: Order, ref_price: float) -> ExecResult: ...


class PaperExecutionAdapter:
    """Simulated fill at the reference price — the only adapter that 'executes'
    anything today. PAPER_TRADE behavior, unchanged."""

    venue = "paper"

    def place_order(self, order: Order, ref_price: float) -> ExecResult:
        return ExecResult(ok=True, detail="paper fill", paper=True, fill_price=ref_price)


class DelegatedExecutionAdapter:
    """Real-money execution via a DELEGATED custody backend (OKX TEE agent-trade /
    Privy server-wallet — we hold a scoped credential, never a raw key). v0 is a
    REFUSING STUB: real dispatch is founder-gated and not implemented here, so this
    can never place a live order. Flipping to live is a deliberate, separate step
    behind X402_MODE/PAPER_TRADE + the S26 Privy policy."""

    def __init__(self, venue: str = "okx", live: bool = False) -> None:
        self.venue = venue
        self._live = live

    def place_order(self, order: Order, ref_price: float) -> ExecResult:
        return ExecResult(
            ok=False,
            detail="real-money execution is founder-gated (stub) — wire OKX-delegated / Privy first",
            paper=False,
        )


def dispatch(
    order: Order, policy: TradeSafetyPolicy, ctx: SafetyContext, adapter: ExecutionAdapter,
    ref_price: float,
) -> ExecResult:
    """Safe rails: run the safety gate FIRST; only a clean verdict reaches the
    execution adapter. A denied order never touches custody/execution."""
    verdict = check_order(order, policy, ctx)
    if not verdict.allow:
        return ExecResult(ok=False, detail="safety-gate denied: " + "; ".join(verdict.reasons), paper=adapter.venue == "paper")
    return adapter.place_order(order, ref_price)
