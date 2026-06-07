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

import base64
import json
import subprocess
from dataclasses import dataclass, field, replace
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

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
    # The memecoin-slippage guard (Phase 2): reject a Jupiter quote whose price
    # impact exceeds this many bps. 100 bps = 1.0%. Enforced at the QUOTE level by
    # JupiterSwapExecutionAdapter BEFORE any TEE broadcast — the honest fail-closed
    # posture for thin-liquidity tokens where we can't yet rely on a Jito bundle
    # for MEV protection (see web3 #7 / the irreversible line in the e2e plan).
    max_price_impact_bps: float = 100.0


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


def with_global_kill(policy: TradeSafetyPolicy, global_kill: bool) -> TradeSafetyPolicy:
    """Fold the operator-wide global kill-switch into a per-agent policy.

    The control plane stores the global flag separately (agent_store.is_global_kill);
    the running monolith calls this right before `dispatch()` so a single global flip
    engages `kill_switch` on EVERY agent's gate at once — without mutating the stored
    per-agent policy. `check_order` stays pure (no I/O); the flag is resolved here.
    """
    if not global_kill or policy.kill_switch:
        return policy
    return replace(policy, kill_switch=True)


def basedbid_policy(
    *,
    max_notional_usd: float = 25.0,
    max_daily_loss_usd: float = 10.0,
    allowed_symbols: tuple[str, ...] = (),
    require_verified_strategy: bool = True,
    extra_venues: tuple[str, ...] = (),
) -> TradeSafetyPolicy:
    """Per-agent policy helper that ENABLES the based.bid (arena) venue.

    `"basedbid"` is deliberately NOT in `TradeSafetyPolicy.allowed_venues` by
    default — an arena LBP/Flash buy is real-money + thin-liquidity exposed, so
    opting in is explicit and per-agent. Defaults mirror the conservative Jupiter
    posture (small notional, tight loss cap)."""
    return TradeSafetyPolicy(
        max_notional_usd=max_notional_usd,
        max_daily_loss_usd=max_daily_loss_usd,
        allowed_venues=("basedbid", *extra_venues),
        allowed_symbols=allowed_symbols,
        require_verified_strategy=require_verified_strategy,
    )


def kamino_policy(
    *,
    max_notional_usd: float = 100.0,
    max_daily_loss_usd: float = 25.0,
    allowed_symbols: tuple[str, ...] = (),
    require_verified_strategy: bool = True,
    extra_venues: tuple[str, ...] = (),
) -> TradeSafetyPolicy:
    """Per-agent policy helper that ENABLES the Kamino (vault deposit/withdraw) venue.

    `"kamino"` is deliberately NOT in `TradeSafetyPolicy.allowed_venues` by default
    — a lending deposit moves real USDC, so opting in is explicit and per-agent."""
    return TradeSafetyPolicy(
        max_notional_usd=max_notional_usd,
        max_daily_loss_usd=max_daily_loss_usd,
        allowed_venues=("kamino", *extra_venues),
        allowed_symbols=allowed_symbols,
        require_verified_strategy=require_verified_strategy,
    )


def jupiter_swap_policy(
    *,
    max_notional_usd: float = 25.0,
    max_daily_loss_usd: float = 10.0,
    max_price_impact_bps: float = 100.0,
    allowed_symbols: tuple[str, ...] = (),
    require_verified_strategy: bool = True,
    extra_venues: tuple[str, ...] = (),
) -> TradeSafetyPolicy:
    """Per-agent policy helper that ENABLES the Jupiter swap venue.

    `"jupiter"` is deliberately NOT in `TradeSafetyPolicy.allowed_venues` by
    default — a swap venue is real-money + memecoin-slippage exposed, so opting in
    is explicit and per-agent. Defaults here are deliberately CONSERVATIVE (small
    notional, tight loss cap, 1% price-impact ceiling) — the Phase-2 honest posture
    of "small notional + hard price-impact reject" while MEV (Jito bundle) support
    on the TEE broadcast path is unconfirmed.
    """
    return TradeSafetyPolicy(
        max_notional_usd=max_notional_usd,
        max_daily_loss_usd=max_daily_loss_usd,
        allowed_venues=("jupiter", *extra_venues),
        allowed_symbols=allowed_symbols,
        require_verified_strategy=require_verified_strategy,
        max_price_impact_bps=max_price_impact_bps,
    )


# ── execution-adapter seam (custody-neutral; real path is a gated stub) ──
@dataclass
class ExecResult:
    ok: bool
    detail: str
    paper: bool = True
    fill_price: float | None = None
    # Phase 2 real-swap fields (default None so paper/stub callers are unaffected):
    submitted: bool = False  # True only when an on-chain broadcast actually fired
    tx_hash: str | None = None  # TEE/CLI-returned tx hash (tracking only — verify on-chain)


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


# ── Jupiter swap sidecar bridge (mirrors kamino/devnet_harness.build_unsigned_kamino_tx) ──
# Mainnet token mints the swap adapter needs. USDC is the canonical quote leg; SOL
# (wrapped) is the native base. Notional→base-units uses these decimals.
_USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
_USDC_DECIMALS = 6

# The Solana System Program — the `--to` target onchainos requires. For a swap the
# real program targets are inside the (already-built) tx; `--to` is just the CLI's
# required destination arg, so we use a benign well-known address. (The Kamino path
# passes the klend program; a Jupiter swap routes through many programs, so there is
# no single meaningful `--to` — System Program is the inert placeholder.)
_SOL_SYSTEM_PROGRAM = "11111111111111111111111111111111"

_SWAP_SIDECAR_DIR = Path(__file__).resolve().parent / "swap-sidecar"
_SWAP_SIDECAR_BUILD = _SWAP_SIDECAR_DIR / "build_swap_tx.ts"


class SwapSidecarError(RuntimeError):
    """The TS swap sidecar failed. Carries the sidecar's verbatim error envelope so
    failures propagate unrephrased (CLAUDE.md: surface failures verbatim)."""


def build_unsigned_swap_tx(
    *,
    input_mint: str,
    output_mint: str,
    amount_base_units: str,
    slippage_bps: int,
    owner_pubkey: str,
    cluster: str = "mainnet",
    api_base: str | None = None,
    node_bin: str = "node",
    timeout_s: float = 60.0,
) -> dict[str, Any]:
    """Shell out to the swap sidecar (`node build_swap_tx.ts`) to build an UNSIGNED
    Jupiter swap tx. Returns the parsed JSON envelope (unsignedTxBase64 + quote).

    The sidecar NEVER signs and NEVER holds a key. Python (the adapter) gates on
    the quote, then optionally hands the unsigned tx to the delegated OKX-TEE
    signer. The request payload is sent on stdin as JSON. Mirrors
    `kamino.devnet_harness.build_unsigned_kamino_tx`.
    """
    if not _SWAP_SIDECAR_BUILD.exists():
        raise SwapSidecarError(
            f"swap sidecar not found at {_SWAP_SIDECAR_BUILD}. "
            f"It has no runtime deps (native fetch on Node >=22) — ensure the file exists."
        )
    payload: dict[str, Any] = {
        "cluster": cluster,
        "inputMint": input_mint,
        "outputMint": output_mint,
        "amountBaseUnits": str(amount_base_units),
        "slippageBps": int(slippage_bps),
        "ownerPubkey": owner_pubkey,
    }
    if api_base:
        payload["apiBase"] = api_base
    proc = subprocess.run(
        [node_bin, str(_SWAP_SIDECAR_BUILD)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=str(_SWAP_SIDECAR_DIR),
        timeout=timeout_s,
    )
    out = (proc.stdout or "").strip()
    parsed: dict[str, Any] | None = None
    if out:
        try:
            parsed = json.loads(out.splitlines()[-1])
        except json.JSONDecodeError:
            parsed = None
    if parsed is not None and parsed.get("ok") is False:
        raise SwapSidecarError(f"{parsed.get('error', 'Error')}: {parsed.get('message', out)}")
    if proc.returncode != 0 or parsed is None:
        raise SwapSidecarError(
            f"swap sidecar exited {proc.returncode}; stdout={out!r} stderr={(proc.stderr or '').strip()!r}"
        )
    return parsed


def _b64_to_b58(b64: str) -> str:
    """base64 wire tx → base58 (the form onchainos `--unsigned-tx` expects).

    CANONICAL impl (item #6, 2026-06-05): kamino/live_executor.py and basedbid_exec.py
    both import this — do NOT redeclare a copy anywhere else."""
    raw = base64.b64decode(b64)
    try:
        import base58

        return base58.b58encode(raw).decode()
    except ImportError:  # solana-py ships based58
        import based58

        return based58.b58encode(raw).decode()


class JupiterSwapExecutionAdapter:
    """Real-money SWAP execution via Jupiter + the proven OKX-TEE broadcast path.

    Flow (mirrors KaminoLiveExecutor, generalized to swaps):
      1. swap sidecar (Jupiter quote+swap) builds an UNSIGNED tx + returns the quote
      2. QUOTE-LEVEL GUARD — reject if price impact > policy.max_price_impact_bps OR
         the min-out (otherAmountThreshold) is below tolerance. (memecoin-slippage guard)
      3. DOUBLE GATE — submit ONLY when `dry_run=False AND confirm=True` (armed +
         confirmed). Anything else is a build-only dry run that NEVER broadcasts.
      4. live submit via `onchainos.wallet_contract_call(--unsigned-tx)` (OKX TEE
         signs + scans + broadcasts; custody never leaves the TEE).

    ⚠️ Like the Kamino path, under the OKX per-tx policy limit `contract-call`
    broadcasts DIRECTLY — `dry_run=False, confirm=True` IS the irreversible line.

    `DelegatedExecutionAdapter` remains the refusing-stub default; this adapter is
    constructed explicitly, per-agent, with a Jupiter-enabled policy. It conforms to
    the `ExecutionAdapter` Protocol (`venue` + `place_order`).
    """

    venue = "jupiter"

    def __init__(
        self,
        owner_pubkey: str,
        policy: TradeSafetyPolicy,
        *,
        output_mint: str,
        input_mint: str = _USDC_MINT,
        input_decimals: int = _USDC_DECIMALS,
        slippage_bps: int = 50,
        dry_run: bool = True,
        cluster: str = "mainnet",
        api_base: str | None = None,
        node_bin: str = "node",
        onchainos_bin: str = "onchainos",
        # injected for tests; defaults to the real bridge / CLI wrapper
        build_fn: Any = None,
        onchainos_client: Any = None,
    ) -> None:
        self.owner = owner_pubkey
        self.policy = policy
        self.output_mint = output_mint
        self.input_mint = input_mint
        self.input_decimals = input_decimals
        self.slippage_bps = slippage_bps
        self.dry_run = dry_run
        self.cluster = cluster
        self.api_base = api_base
        self._node = node_bin
        self._onchainos_bin = onchainos_bin
        self._build_fn = build_fn or build_unsigned_swap_tx
        self._onchainos = onchainos_client  # lazy-init in _submit if None
        self.last_build: dict[str, Any] | None = None

    def _to_base_units(self, notional_usd: float) -> str:
        """USD notional → input-mint base units (USDC: 6 decimals). String, no float
        rounding — same discipline as the Kamino sidecar's toBaseUnits."""
        q = Decimal(str(notional_usd)) * (Decimal(10) ** self.input_decimals)
        return str(int(q))

    def place_order(self, order: Order, ref_price: float, *, confirm: bool = False) -> ExecResult:
        """Build → quote-guard → (double-gated) submit. `confirm` defaults False so
        even an armed (dry_run=False) adapter never broadcasts without explicit
        per-call confirmation — the second gate."""
        # 1. build the unsigned tx + quote via the sidecar (cheap; no money)
        amount_base = self._to_base_units(order.notional_usd)
        try:
            build = self._build_fn(
                input_mint=self.input_mint,
                output_mint=self.output_mint,
                amount_base_units=amount_base,
                slippage_bps=self.slippage_bps,
                owner_pubkey=self.owner,
                cluster=self.cluster,
                api_base=self.api_base,
                node_bin=self._node,
            )
        except SwapSidecarError as e:
            # surface the sidecar's verbatim error (CLAUDE.md)
            return ExecResult(ok=False, detail=f"swap sidecar build failed: {e}", paper=False)
        if not build.get("ok"):
            return ExecResult(ok=False, detail=f"swap sidecar build failed: {build}", paper=False)
        self.last_build = build
        quote = build.get("quote") or {}

        # 2. quote-level guard (the memecoin-slippage guard) — fail-closed
        guard = self._quote_guard(quote, amount_base)
        if guard is not None:
            return ExecResult(ok=False, detail=f"quote-guard denied: {guard}", paper=False)

        # 3. the double gate — submit ONLY when explicitly armed AND confirmed
        will_submit = (not self.dry_run) and confirm
        if not will_submit:
            why = "dry_run" if self.dry_run else "confirm=False"
            route = ",".join(quote.get("route") or []) or "?"
            return ExecResult(
                ok=True,
                detail=(
                    f"built+ready (NOT submitted: {why}); out={quote.get('outAmount')} "
                    f"impact={quote.get('priceImpactPct')} route=[{route}]"
                ),
                paper=False,
                submitted=False,
            )

        # 4. live submit via OKX TEE (broadcasts directly under policy limit)
        return self._submit(build["unsignedTxBase64"], quote)

    def _quote_guard(self, quote: dict[str, Any], amount_base: str) -> str | None:
        """Return a deny-reason string if the quote violates the guard, else None.

        Two checks:
          (a) price impact > policy.max_price_impact_bps
          (b) min-out (otherAmountThreshold) <= 0 or absent — no enforceable floor.
        Both are fail-closed: a malformed/zero quote is rejected, never traded on.
        """
        # (a) price impact
        try:
            impact_pct = Decimal(str(quote.get("priceImpactPct", "0") or "0"))
        except (InvalidOperation, TypeError):
            return f"unparseable priceImpactPct {quote.get('priceImpactPct')!r}"
        impact_bps = impact_pct * Decimal(10000)
        cap_bps = Decimal(str(self.policy.max_price_impact_bps))
        if impact_bps > cap_bps:
            return (
                f"price impact {impact_bps:.1f} bps > cap {cap_bps:.1f} bps "
                f"(priceImpactPct={impact_pct})"
            )
        # (b) min-out floor must exist and be positive (Jupiter sets it from slippageBps)
        thresh_raw = quote.get("otherAmountThreshold")
        try:
            thresh = int(str(thresh_raw)) if thresh_raw not in (None, "") else 0
        except (ValueError, TypeError):
            return f"unparseable otherAmountThreshold {thresh_raw!r}"
        if thresh <= 0:
            return f"min-out (otherAmountThreshold) is {thresh} — no enforceable slippage floor"
        return None

    def _submit(self, unsigned_tx_b64: str, quote: dict[str, Any]) -> ExecResult:
        """Hand the unsigned tx to the delegated OKX TEE for sign+scan+broadcast.
        Errors are surfaced verbatim, never faked-success (CLAUDE.md)."""
        b58 = _b64_to_b58(unsigned_tx_b64)
        client = self._onchainos
        if client is None:
            # Lazy import keeps trade_safety import-light (no onchainos at module load).
            from onchainos import OnchainOS

            client = OnchainOS(chain="solana")
        resp = client.wallet_contract_call(to=_SOL_SYSTEM_PROGRAM, unsigned_tx=b58)
        if not isinstance(resp, dict) or resp.get("error"):
            return ExecResult(
                ok=False,
                detail=f"contract-call error: {resp}",
                paper=False,
                submitted=False,
            )
        if resp.get("ok") is False:
            return ExecResult(
                ok=False, detail=f"contract-call returned ok=false: {resp}", paper=False
            )
        raw_data = resp.get("data")
        data: dict[str, Any] = raw_data if isinstance(raw_data, dict) else {}
        tx_hash = data.get("txHash") or resp.get("txHash")
        return ExecResult(
            ok=True,
            detail="submitted swap via OKX TEE (txHash for tracking only — verify on-chain)",
            paper=False,
            submitted=True,
            tx_hash=tx_hash,
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
