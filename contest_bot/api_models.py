"""Response models for the Gecko Agent Control Plane (`agent_api.py`).

These exist ONLY to make `/openapi.json` carry response schemas so the app can
codegen a typed client (every endpoint was `-> dict` → codegen yielded `any`).

Design rules (do NOT break the live payloads):
  * Every model sets `extra="allow"` — FastAPI's response_model coercion would
    otherwise DROP keys not declared here. Several endpoints return dynamic /
    variant shapes (`stale`, `board: []`, `allocation: null`, error branches,
    empty VerdictEnvelope), and those extra/variant keys MUST survive untouched.
  * Every variant-specific field is Optional with a default, so the honest-empty
    AND the populated branch both validate without a 500.
  * Handlers keep returning plain dicts; we only declare `response_model=` on the
    decorator and let FastAPI coerce. The models document the KNOWN fields for
    codegen; `extra="allow"` guarantees nothing real is filtered out.

No behavior change — typing only. PAPER + X402_MODE=stub.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

# Permissive base: keep every real key, never 500 on a variant branch.
_CFG = ConfigDict(extra="allow")


# ── /healthz ──────────────────────────────────────────────────────────────
class HealthzResponse(BaseModel):
    model_config = _CFG
    ok: bool = True
    data_coins: list[str] = []
    n_agents: int = 0


# ── /market-temp ──────────────────────────────────────────────────────────
class CoinTemp(BaseModel):
    model_config = _CFG
    net: float = 0.0
    mentions: int = 0


class MarketTempResponse(BaseModel):
    """Populated OR honest-empty/stale. Populated carries temp/label/btc_net/
    drivers/coins/divergences/updated_at; cold start returns
    `{temp, label, stale, drivers}`. Both validate."""

    model_config = _CFG
    temp: float = 0.0
    label: str = "neutral"
    drivers: list[str] = []
    # populated-only (Optional → cold branch validates)
    btc_net: float | None = None
    coins: dict[str, CoinTemp] | None = None
    divergences: list[str] | None = None
    updated_at: str | None = None
    # stale/empty-only
    stale: bool | None = None


# ── /vault ────────────────────────────────────────────────────────────────
class VaultLot(BaseModel):
    model_config = _CFG
    source: str
    principal_usd: float
    leverage: float
    net_apy: float
    liquidation_drop_pct: float
    correlated: bool
    # S47 item #5 — human label/description + the "$1000 → +$100 in N" projection.
    # Optional so the honest-empty shape (lots: []) and any older payload still validate.
    label: str | None = None
    description: str | None = None
    target_principal_usd: float | None = None
    target_gain_usd: float | None = None
    days_to_target: float | None = None  # None when net_apy ≤ 0 (never reaches a positive target)
    projected_balance_1y: float | None = None
    # S48 — Pegana peg-risk signal for this lot's collateral. None when Pegana is
    # down or the asset isn't peg-tracked (honest-empty); state ∈ PEGGED|DRIFT|DEPEG|CRITICAL.
    peg_state: str | None = None
    peg_discount: float | None = None  # signed; negative = below intrinsic


class VaultSnapshot(BaseModel):
    model_config = _CFG
    profile: str
    allocation_usd: float
    hurdle_apy: float
    lots: list[VaultLot] = []


class VaultVerdict(BaseModel):
    model_config = _CFG
    source: str
    principal_usd: float
    action: str  # EXIT | DELEVERAGE | ROTATE | HOLD
    reason: str
    net_apy: float
    suggested_leverage: float | None = None
    # S48 — Pegana peg-risk signal that may have driven this verdict (None = no signal)
    peg_state: str | None = None
    peg_discount: float | None = None


class AllocationLiveLeg(BaseModel):
    model_config = _CFG
    submitted: bool | None = None
    tx_hash: str | None = None
    detail: str | None = None


class AllocationDeposit(BaseModel):
    model_config = _CFG
    source: str
    amount: float
    monitor: str | None = None
    live: AllocationLiveLeg | None = None


class AllocationDenied(BaseModel):
    model_config = _CFG
    source: str
    amount: float
    reasons: list[str] = []


class AllocationReport(BaseModel):
    model_config = _CFG
    deposited: list[AllocationDeposit] = []
    denied: list[AllocationDenied] = []
    allocation_usd: float | None = None
    error: str | None = None


class VaultMarketTemp(BaseModel):
    model_config = _CFG
    label: str | None = None
    predicted_drawdown: float | None = None
    stale: bool = False


class VaultResponse(BaseModel):
    model_config = _CFG
    snapshot: VaultSnapshot
    verdicts: list[VaultVerdict] = []
    allocation: AllocationReport | None = None
    market_temp: VaultMarketTemp


# ── /vault/catalog ─────────────────────────────────────────────────────────
class CatalogOption(BaseModel):
    """One pickable Kamino market, profile-filtered + cost-aware ranked. The app's
    portfolio-picker row. `min_hold_days` is the break-even hold (don't liquidate
    before this); null when the position never clears its round-trip cost."""

    model_config = _CFG
    name: str
    net_apy: float
    net_apy_after_cost: float
    leverage: float
    liquidation_drop_pct: float
    min_hold_days: float | None = None


class CatalogResponse(BaseModel):
    model_config = _CFG
    profile: str  # canonical (aliases normalized): conservative | Balanced | aggressive
    options: list[CatalogOption] = []
    source: str  # "live" | "fallback"
    cost_pct: float  # round-trip cost used for ranking (fraction of equity)
    horizon_years: float


# ── /arena/board ──────────────────────────────────────────────────────────
class ArenaRow(BaseModel):
    """Bucketed-only by design — NO raw floats cross the wire."""

    model_config = _CFG
    name: str
    band: str  # surviving+ | surviving | at-risk | eliminated
    risk_bucket: str  # contained | moderate | high | extreme
    bars: int


class ArenaBoardResponse(BaseModel):
    """Three variants: cached / live (?live=1) / error. All carry `board`; the
    rest are variant-specific Optionals so every branch validates."""

    model_config = _CFG
    board: list[ArenaRow] = []
    kpi: str | None = None
    n: int | None = None
    updated_at: str | None = None
    stale: bool | None = None
    note: str | None = None
    live: bool | None = None
    error: str | None = None


# ── /backtest (VerdictEnvelope) ───────────────────────────────────────────
class RigorBlock(BaseModel):
    model_config = _CFG
    cpcv_median_sharpe: float | None = None
    cpcv_ci: list[float] | None = None
    cpcv_pct_paths_negative: float | None = None
    pbo: float | None = None
    avoidance_pbo: float | None = None
    dsr: float | None = None


class PerSymbolStat(BaseModel):
    model_config = _CFG
    n: int
    mean_net_pct: float
    ci: list[float]
    ci_excludes_0: bool


class VerdictEnvelope(BaseModel):
    """Populated OR empty (`{strategy_id, n_trades, verdict: null, note}`).
    Every populated-only field is Optional so the empty branch validates."""

    model_config = _CFG
    strategy_id: str | None = None
    verdict: str | None = None  # DEPLOY | PAPER ONLY | REJECT | null
    n_trades: int = 0
    note: str | None = None
    # populated-only
    s5_paper_continue: bool | None = None
    rationale: list[str] | None = None
    n_variants: int | None = None
    fee_pct: float | None = None
    win_rate: float | None = None
    mean_net_pct: float | None = None
    total_net_pct: float | None = None
    rigor: RigorBlock | None = None
    per_symbol: dict[str, PerSymbolStat] | None = None
    symbols_ci_excludes_0: Any | None = None


class BacktestResponse(BaseModel):
    model_config = _CFG
    coins: list[str] = []
    fee_pct: float
    strategies: list[VerdictEnvelope] = []
    orthogonality_rho: float | None = None


# ── /agents (deploy / list / get) ─────────────────────────────────────────
class AgentPolicy(BaseModel):
    model_config = _CFG
    kill_switch: bool | None = None


class AgentDoc(BaseModel):
    model_config = _CFG
    agent_id: str
    user_id: str
    spec: dict[str, Any] = {}
    verdict: str | None = None
    status: str  # deployed | running | stopped
    venue: str | None = None
    universe: list[str] = []
    strategy_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    policy: AgentPolicy | None = None


class AgentStateDoc(BaseModel):
    model_config = _CFG
    agent_id: str
    state: dict[str, Any] = {}
    updated_at: str | None = None


class DeployResponse(BaseModel):
    model_config = _CFG
    agent_id: str
    status: str = "deployed"
    launch: str


class AgentListResponse(BaseModel):
    model_config = _CFG
    agents: list[AgentDoc] = []


class AgentExecutionStatus(BaseModel):
    """Per-agent execution/custody posture for the app (web3.md §2c). Honest
    paper defaults: `dry_run=True` / `live=False` until founder-flipped."""

    model_config = _CFG
    venue: str = "paper"  # paper | jupiter | basedbid | okx
    dry_run: bool = True
    live: bool = False
    custody: str = "none"  # okx_tee | privy_embedded | none


class AgentDetailResponse(BaseModel):
    model_config = _CFG
    agent: AgentDoc
    state: AgentStateDoc | None = None
    execution: AgentExecutionStatus | None = None


# ── orchestrator + start/stop/kill ────────────────────────────────────────
class RunningAgent(BaseModel):
    model_config = _CFG
    agent_id: str
    port: int


class OrchestratorResponse(BaseModel):
    model_config = _CFG
    running: list[RunningAgent] = []
    max_per_user: int


class StartAgentResponse(BaseModel):
    model_config = _CFG
    agent_id: str
    port: int
    status: str = "running"
    already: bool | None = None


class StopAgentResponse(BaseModel):
    model_config = _CFG
    agent_id: str
    status: str = "stopped"
    process_killed: bool


class KillAgentResponse(BaseModel):
    model_config = _CFG
    agent_id: str
    kill_switch: bool


class GlobalKillResponse(BaseModel):
    model_config = _CFG
    scope: str = "global"
    kill_switch: bool


# ── /wallet ───────────────────────────────────────────────────────────────
class WalletResponse(BaseModel):
    """Signer identity + custody backend for the App's wallet surface.

    `signer_pubkey` is the PUBLIC key ONLY — resolved best-effort from env or
    the `onchainos` CLI; never a private key / mnemonic (the #1 invariant).
    Cold/unconfigured backend → `{signer_pubkey: null, custody: "none",
    status: "unconfigured", x402_mode}` (honest-empty, never 500)."""

    model_config = _CFG
    signer_pubkey: str | None = None
    custody: str = "none"  # okx_tee | privy_embedded | none
    status: str = "unconfigured"  # ok | logged_out | unconfigured | error
    x402_mode: str = "stub"
    # variant-only (Optional → cold branch validates)
    note: str | None = None


# ── /wallet/balance ───────────────────────────────────────────────────────
class WalletBalance(BaseModel):
    model_config = _CFG
    token: str
    amount: float


class WalletBalanceResponse(BaseModel):
    """Best-effort SOL + USDC for the signer. Honest-empty + `stale: true`
    when no balance source is reachable; never blocks/crashes the endpoint."""

    model_config = _CFG
    pubkey: str | None = None
    balances: list[WalletBalance] = []
    stale: bool = True
    note: str | None = None


# ── /receipts ─────────────────────────────────────────────────────────────
class PaymentReceipt(BaseModel):
    """One x402-paid oracle call. In stub mode `tx_sig` carries a `stub-`
    prefix so a stub sig can never pass for an on-chain artifact; `mode`
    surfaces the X402 posture so the App labels it honestly."""

    model_config = _CFG
    mode: str  # stub | live | frames
    idea_hash: str | None = None
    tier: str | None = None
    amount_usd: float | None = None
    tx_sig: str | None = None
    ts: str | None = None


class ReceiptsResponse(BaseModel):
    """Paid-call history. Honest-empty `[]` on a cold/unconfigured backend
    (no receipt store wired); `stale` flags a best-effort/degraded read."""

    model_config = _CFG
    receipts: list[PaymentReceipt] = []
    n: int = 0
    mode: str = "stub"
    stale: bool | None = None
    note: str | None = None
