#!/usr/bin/env python3
"""Agent control plane — Phase 2 of the hosted agent flow.

Extends the Phase-1 backtest surface with deploy/list/get/stop for hosted
single-tenant paper agents. The app calls:

    POST /backtest            → rigor verdict (Phase 1)
    POST /agents              → deploy a StrategySpec (refused if verdict==REJECT)
    GET  /agents              → list deployed agents
    GET  /agents/{id}         → registry doc + latest runtime state mirror
    POST /agents/{id}/stop    → mark stopped

A deployed agent is run by the orchestrator (`launch_agent.sh <agent_id>`), which
reads the spec from the registry, sets env, and starts the monolith with
GECKO_AGENT_ID + a Mongo state backend. Paper-only.

Run:
    uv run uvicorn agent_api:app --host 0.0.0.0 --port 8271   # from contest_bot/
"""

from __future__ import annotations

import os
import sys

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import backtest_strategy as bt  # noqa: E402
from agent_orchestrator import MAX_AGENTS_PER_USER, AgentOrchestrator  # noqa: E402
from agent_store import (  # noqa: E402
    AgentRegistry,
    AgentStateStore,
    is_global_kill,
    set_global_kill,
)
from api_models import (  # noqa: E402
    AgentDetailResponse,
    AgentListResponse,
    ArenaBoardResponse,
    BacktestResponse,
    DeployResponse,
    GlobalKillResponse,
    HealthzResponse,
    KillAgentResponse,
    MarketTempResponse,
    OrchestratorResponse,
    ReceiptsResponse,
    StartAgentResponse,
    StopAgentResponse,
    VaultResponse,
    WalletBalanceResponse,
    WalletResponse,
)

app = FastAPI(title="Gecko Agent Control Plane", version="0.4.0")

# Phase 0: the hosted app (app.geckovision.tech) calls this LOCAL control plane
# (GECKO_AGENT_CONTROL_URL=http://localhost:8271) — without CORS the browser blocks
# every request. Origins come from GECKO_APP_ORIGINS (comma-sep); default covers the
# prod app + common local dev ports. FastAPI already serves /openapi.json for codegen.
_DEFAULT_ORIGINS = (
    "https://app.geckovision.tech,https://geckovision.tech,"
    "http://localhost:3000,http://localhost:3001"
)
_ALLOWED_ORIGINS = [
    o.strip() for o in os.environ.get("GECKO_APP_ORIGINS", _DEFAULT_ORIGINS).split(",") if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

_ALLOWED = {"trend_breakout", "mean_reversion"}
_registry = AgentRegistry()
_state = AgentStateStore()
_orch = AgentOrchestrator(registry=_registry)


class BacktestRequest(BaseModel):
    strategy_id: str = "trend_breakout"
    entry_gates: dict | None = None
    exit: dict | None = None
    coins: list[str] | None = None
    fee_pct: float = Field(0.20, ge=0.0, le=2.0)
    both: bool = False


class DeployRequest(BaseModel):
    spec: dict = Field(..., description="a StrategySpec (strategy_id, universe, venue, entry_gates, exit, …)")
    user_id: str = "local"
    verdict: str | None = Field(None, description="the §5 verdict; deploy refused if 'REJECT'")


@app.get("/healthz", response_model=HealthzResponse)
def healthz() -> dict:
    cov = os.path.join(bt.DATA_DIR, "coverage.json")
    coins: list[str] = []
    if os.path.exists(cov):
        import json

        with open(cov) as f:
            coins = list(json.load(f).get("coins", {}))
    return {"ok": True, "data_coins": coins, "n_agents": len(_registry.list_agents())}


@app.get("/market-temp", response_model=MarketTempResponse)
def market_temp() -> dict:
    """The current market-temperature read (risk-on/off) the app shows + bots
    consume. Served from the cached snapshot a refresh worker writes; neutral/
    stale if none yet. See refresh_market_temp.py."""
    import market_temp as mt

    return mt.load_snapshot()


@app.get("/vault", response_model=VaultResponse)
def vault(
    profile: str = "conservative",
    demo_profit: float = 0.0,
    target_principal_usd: float = 1000.0,
    target_gain_usd: float = 100.0,
) -> dict:
    """The profit-vault state the app tile reads: per-profile allocation, each lot's
    net APY + liquidation buffer, and the live yield-safety monitor verdict per lot.
    The monitor's downside input is the SAME market-temp read that gates trades
    (the unification). Honest-empty until the agent allocates real profit; pass
    ?demo_profit=100&profile=moderate to preview the shape. Paper only."""
    import market_temp as mt
    from kamino import vault_gate as vg
    from kamino import vault_orchestrator as vo
    from kamino.monitor import hurdle_for

    # Normalize back-compat aliases (e.g. the V1 rename moderate→Balanced) before
    # validating, so old callers keep working. Then validate against the known
    # baskets — fail LOUD (422) instead of the old silent fallback to conservative
    # (defi.md must-build: the app must know it asked for something that doesn't
    # exist, not get a different basket back).
    profile = vo.normalize_profile(profile)
    if profile not in vo.PROFILE_BASKETS:
        raise HTTPException(
            422,
            f"unknown profile {profile!r}; allowed: {sorted(vo.PROFILE_BASKETS)}",
        )

    snap = mt.load_snapshot()
    dd = vo.predicted_drawdown_from_market_temp(snap)
    hurdle = hurdle_for(profile)
    # S48 — attach a live Pegana client so the depeg signal reaches the monitor/gate.
    # Best-effort: construction never raises; the client itself fails open if the
    # REST API is down (then the monitor falls back to the market-temp path).
    pegana_client = None
    if os.environ.get("GECKO_PEGANA_ENABLED", "0").lower() in ("1", "true", "yes", "on"):
        try:
            from pegana_feed import PeganaClient

            pegana_client = PeganaClient()
        except Exception:  # pragma: no cover — import/availability guard, fail-open
            pegana_client = None
    orch = vo.VaultOrchestrator(
        profile=profile,
        policy=vg.VaultPolicy(max_allocation_usd=1_000_000.0, hurdle=hurdle),
        hurdle=hurdle,
        pegana_client=pegana_client,
    )
    allocation = orch.allocate_profit(demo_profit, predicted_drawdown_pct=dd) if demo_profit > 0 else None
    return {
        "snapshot": orch.snapshot(
            target_principal_usd=target_principal_usd, target_gain_usd=target_gain_usd
        ),
        "verdicts": orch.monitor_tick(predicted_drawdown_pct=dd),
        "allocation": allocation,
        "market_temp": {"label": snap.get("label"), "predicted_drawdown": dd, "stale": snap.get("stale", False)},
    }


@app.get("/arena/board", response_model=ArenaBoardResponse)
def arena_board(live: bool = False) -> dict:
    """based.bid Battle Arena — verified-safe SURVIVAL board. Server-side BUCKETED
    (band + coarse risk bucket only; raw drawdown/return NEVER cross the wire, per the
    no-public-raw-floats rule). Read-only; survival is the KPI, not PnL.

    Serves the cached snapshot a refresh worker writes (refresh_arena_board.py) — the
    live build hits the throttled feed (~90s for 5 tokens), too slow per-request.
    Honest-empty + stale on a cold start. Pass ?live=1 to force a fresh build (slow;
    tokens from GECKO_ARENA_TOKENS NAME:mint,… or the hand-picked graduated default)."""
    import arena_score as asc

    if not live:
        snap = asc.load_board_snapshot()
        return {"kpi": "survival (bucketed) — not raw PnL", **snap}

    from strategies.basedbid_feed import BasedBidCandleProvider

    toks = None
    raw = os.environ.get("GECKO_ARENA_TOKENS", "").strip()
    if raw:
        toks = {p.split(":")[0]: p.split(":")[1] for p in raw.split(",") if ":" in p}
    try:
        board = asc.build_board(BasedBidCandleProvider(), toks, public=True)
    except Exception as e:  # never 500 the board; honest-empty on data error
        return {"board": [], "error": f"{type(e).__name__}", "note": "feed unavailable"}
    asc.save_board_snapshot(board)  # warm the cache for subsequent cheap reads
    return {"board": board, "kpi": "survival (bucketed) — not raw PnL", "n": len(board), "live": True}


@app.post("/backtest", response_model=BacktestResponse)
def backtest(req: BacktestRequest) -> dict:
    if req.strategy_id not in _ALLOWED:
        raise HTTPException(422, f"unknown strategy_id {req.strategy_id!r}")
    try:
        return bt.run_backtest(
            strategy_id=req.strategy_id, entry_gates=req.entry_gates, exit_overrides=req.exit,
            coins=req.coins, fee_pct=req.fee_pct, both=req.both,
        )
    except ValueError as e:
        raise HTTPException(503, str(e)) from e


@app.post("/agents", response_model=DeployResponse)
def deploy(req: DeployRequest) -> dict:
    sid = req.spec.get("strategy_id")
    if sid not in _ALLOWED:
        raise HTTPException(422, f"spec.strategy_id {sid!r} not in {sorted(_ALLOWED)}")
    # multi-tenant guard: cap deployed agents per user
    if len(_registry.list_agents(req.user_id)) >= MAX_AGENTS_PER_USER:
        raise HTTPException(429, f"user at agent cap ({MAX_AGENTS_PER_USER})")
    try:
        agent_id = _registry.deploy(req.spec, user_id=req.user_id, verdict=req.verdict)
    except ValueError as e:  # REJECT verdict
        raise HTTPException(409, str(e)) from e
    return {"agent_id": agent_id, "status": "deployed",
            "launch": f"bash launch_agent.sh {agent_id}"}


@app.post("/agents/{agent_id}/start", response_model=StartAgentResponse)
def start_agent(agent_id: str) -> dict:
    try:
        return _orch.start(agent_id)
    except KeyError as e:
        raise HTTPException(404, str(e)) from e
    except PermissionError as e:  # per-user cap
        raise HTTPException(429, str(e)) from e
    except RuntimeError as e:  # no free port
        raise HTTPException(503, str(e)) from e


@app.get("/orchestrator", response_model=OrchestratorResponse)
def orchestrator_status() -> dict:
    return {"running": _orch.list_running(), "max_per_user": MAX_AGENTS_PER_USER}


@app.get("/agents", response_model=AgentListResponse)
def list_agents(user_id: str | None = None) -> dict:
    return {"agents": _registry.list_agents(user_id)}


def _execution_status(doc: dict) -> dict:
    """Per-agent execution/custody status the app displays (web3.md §2c/§2d).

    Honest defaults: the hosted flow is PAPER until founder-flipped (the default
    `DelegatedExecutionAdapter` refuses live orders), so `dry_run=True` / `live=False`
    unless the spec explicitly says otherwise. `venue` comes off the registry doc /
    spec; `custody` reports the configured signing backend (okx_tee | privy_embedded |
    none) without ever exposing a key."""
    spec = doc.get("spec") or {}
    venue = doc.get("venue") or spec.get("venue") or "paper"
    # dry_run defaults True (paper-safe). Honor an explicit spec flag if present.
    raw_dry = spec.get("dry_run")
    dry_run = True if raw_dry is None else bool(raw_dry)
    try:
        _pk, custody, _status = _resolve_signer()
    except Exception:
        custody = "none"
    return {"venue": venue, "dry_run": dry_run, "live": (not dry_run), "custody": custody}


@app.get("/agents/{agent_id}", response_model=AgentDetailResponse)
def get_agent(agent_id: str) -> dict:
    doc = _registry.get(agent_id)
    if not doc:
        raise HTTPException(404, f"no agent {agent_id!r}")
    return {
        "agent": doc,
        "state": _state.get_state(agent_id),
        "execution": _execution_status(doc),
    }


@app.post("/agents/{agent_id}/stop", response_model=StopAgentResponse)
def stop_agent(agent_id: str) -> dict:
    if not _registry.get(agent_id):
        raise HTTPException(404, f"no agent {agent_id!r}")
    killed = _orch.stop(agent_id)  # kills the running process (if any) + status→stopped
    return {"agent_id": agent_id, "status": "stopped", "process_killed": killed}


# ── Wallet + payment surface (web3 — READ-only, never moves money) ─────────
#
# Hard invariant: a private key / mnemonic / seed MUST NEVER cross the wire,
# even in an error branch. `_PRIVKEYISH` names any field that could carry secret
# material; `_redact()` strips them recursively before anything is returned.
_PRIVKEYISH = frozenset(
    {
        "privatekey",
        "private_key",
        "privkey",
        "secret",
        "secretkey",
        "secret_key",
        "mnemonic",
        "seed",
        "seedphrase",
        "seed_phrase",
        "keypair",
        "secretkeyhex",
        "phrase",
        "passphrase",
    }
)


def _redact(obj: object) -> object:
    """Recursively drop any private-key-like field. Defense in depth: every
    wallet endpoint runs its return value through this before responding."""
    if isinstance(obj, dict):
        return {
            k: _redact(v)
            for k, v in obj.items()
            if str(k).replace("-", "").replace("_", "").lower() not in _PRIVKEYISH
        }
    if isinstance(obj, list):
        return [_redact(v) for v in obj]
    return obj


def _x402_mode() -> str:
    """Current x402 posture; defaults to stub (CLAUDE.md: pass X402_MODE through
    every payment-touching path; default stub if unset)."""
    return os.environ.get("X402_MODE", "stub")


def _resolve_signer() -> tuple[str | None, str, str]:
    """Best-effort resolve (signer_pubkey, custody, status). PUBLIC key only.

    Order: explicit env pubkey → OKX TEE via onchainos → Privy embedded env →
    none. Every branch is wrapped so a missing CLI / cold backend never crashes
    the endpoint; we return honest-empty instead."""
    # 1. Explicit public-key env (operator-set, no subprocess needed).
    for env_key in ("GECKO_SIGNER_PUBKEY", "GECKO_WALLET_PUBKEY", "SIGNER_PUBKEY"):
        val = os.environ.get(env_key, "").strip()
        if val:
            return val, "okx_tee", "ok"

    # 2. OKX TEE via onchainos CLI (best-effort, timeout-bounded inside wrapper).
    try:
        from onchainos import OnchainOS

        oc = OnchainOS(chain="solana")
        addr = oc.get_wallet_address()
        if addr:
            return str(addr), "okx_tee", "ok"
        # CLI reachable but no address → likely logged out.
        status = oc.wallet_status()
        if isinstance(status, dict) and "error" not in status:
            return None, "okx_tee", "logged_out"
    except Exception:  # CLI missing / import error / parse error — degrade quietly
        pass

    # 3. Privy embedded wallet (S26) — public address env only, never a key.
    for env_key in ("PRIVY_WALLET_ADDRESS", "GECKO_PRIVY_ADDRESS"):
        val = os.environ.get(env_key, "").strip()
        if val:
            return val, "privy_embedded", "ok"

    return None, "none", "unconfigured"


@app.get("/wallet", response_model=WalletResponse)
def wallet() -> dict:
    """Signer identity + custody backend for the App's wallet surface.

    Returns the PUBLIC signer pubkey ONLY (resolved best-effort from env or the
    onchainos CLI), which custody backend is configured (okx_tee | privy_embedded
    | none), a status, and the current x402 mode. NEVER returns a private key or
    mnemonic — the response is run through `_redact()` regardless. Honest-empty
    on a cold/unconfigured backend; never 500."""
    try:
        pubkey, custody, status = _resolve_signer()
    except Exception:  # belt-and-suspenders — endpoint must never crash
        pubkey, custody, status = None, "none", "error"
    out = {
        "signer_pubkey": pubkey,
        "custody": custody,
        "status": status,
        "x402_mode": _x402_mode(),
    }
    if pubkey is None:
        out["note"] = "no signer configured; the App renders before custody is wired"
    return _redact(out)


# Canonical Solana mints for the funding tile (public constants, not secrets).
_SOL_MINT = "So11111111111111111111111111111111111111112"
_USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


@app.get("/wallet/balance", response_model=WalletBalanceResponse)
def wallet_balance() -> dict:
    """Best-effort SOL + USDC for the signer (via onchainos). Honest-empty +
    `stale: true` when no balance source is reachable. Never blocks/crashes —
    a missing CLI or cold backend returns the empty shape, not a 500."""
    try:
        pubkey, custody, _status = _resolve_signer()
    except Exception:
        pubkey, custody = None, "none"

    if custody != "okx_tee" or pubkey is None:
        return _redact(
            {
                "pubkey": pubkey,
                "balances": [],
                "stale": True,
                "note": "no balance source wired for this custody backend",
            }
        )

    try:
        from onchainos import OnchainOS

        oc = OnchainOS(chain="solana")
        sol = oc.get_token_balance(_SOL_MINT)
        usdc = oc.get_token_balance(_USDC_MINT)
    except Exception:  # CLI missing / timeout / parse error — degrade to stale
        return _redact(
            {
                "pubkey": pubkey,
                "balances": [],
                "stale": True,
                "note": "balance source unavailable",
            }
        )

    balances = [
        {"token": "SOL", "amount": float(sol or 0.0)},
        {"token": "USDC", "amount": float(usdc or 0.0)},
    ]
    return _redact({"pubkey": pubkey, "balances": balances, "stale": False})


def _scan_receipts(limit: int) -> tuple[list[dict], bool]:
    """Best-effort: read paid-oracle-call records from the append-only artifact
    JSONL ledger (gecko_wrap.ArtifactLogger). Each `gate_call`/`gate_allow` row
    is one x402 stub-paid oracle invocation. Returns (receipts, stale).

    No dedicated on-chain receipt store exists on the control plane (the money
    path's `sessions.x402_tx_signature` lives in the gecko-api/Supabase backend,
    a different surface). So receipts are synthesized from the local ledger;
    honest-empty when no ledger files exist."""
    import glob
    import json as _json

    mode = _x402_mode()
    state_dir = os.environ.get("GECKO_STATE_DIR") or _HERE
    paths = sorted(glob.glob(os.path.join(state_dir, "artifact_*.jsonl")), reverse=True)
    if not paths:
        return [], False  # honest-empty, not stale — there simply are no calls yet

    receipts: list[dict] = []
    degraded = False
    for path in paths:
        if len(receipts) >= limit:
            break
        try:
            with open(path, encoding="utf-8") as f:
                lines = f.readlines()
        except OSError:
            degraded = True
            continue
        # newest-first within a file
        for line in reversed(lines):
            if len(receipts) >= limit:
                break
            line = line.strip()
            if not line:
                continue
            try:
                row = _json.loads(line)
            except (ValueError, _json.JSONDecodeError):
                degraded = True
                continue
            if row.get("kind") not in ("gate_call", "gate_allow"):
                continue
            payload = row.get("payload") or {}
            did = row.get("decision_id")
            receipts.append(
                {
                    "mode": mode,
                    "idea_hash": payload.get("idea_hash") or did,
                    "tier": payload.get("tier", "basic"),
                    "amount_usd": payload.get("amount_usd"),
                    # stub mode: synthesize a stub- sig from the decision id so it
                    # can NEVER be mistaken for an on-chain artifact.
                    "tx_sig": (f"stub-{did}" if mode == "stub" and did else payload.get("tx_sig")),
                    "ts": row.get("ts"),
                }
            )
    return receipts, degraded


@app.get("/receipts", response_model=ReceiptsResponse)
def receipts(limit: int = 50) -> dict:
    """Paid x402 oracle-call history for the App's payment surface. Reads the
    local artifact ledger best-effort; honest-empty `[]` on a cold backend (no
    receipt store wired). In stub mode tx sigs carry a `stub-` prefix and `mode`
    surfaces the posture so the App labels free stub calls honestly. Never 500."""
    limit = max(1, min(int(limit or 50), 500))
    try:
        rows, degraded = _scan_receipts(limit)
    except Exception:  # any unexpected error → honest-empty + stale, never crash
        rows, degraded = [], True
    out: dict = {"receipts": rows, "n": len(rows), "mode": _x402_mode()}
    if degraded:
        out["stale"] = True
        out["note"] = "receipt ledger partially unreadable; results may be incomplete"
    return _redact(out)


@app.post("/agents/{agent_id}/kill", response_model=KillAgentResponse)
def kill_agent(agent_id: str, engaged: bool = True) -> dict:
    """SOFT kill-switch (web3 #4): engage `policy.kill_switch` so the safety gate
    denies EVERY new order for this agent — WITHOUT killing the running process (it
    keeps managing/closing existing positions, just opens nothing new). Pass
    ?engaged=false to disarm. For a hard process stop, use /stop."""
    if not _registry.get(agent_id):
        raise HTTPException(404, f"no agent {agent_id!r}")
    _registry.set_kill(agent_id, engaged)
    return {"agent_id": agent_id, "kill_switch": engaged}


@app.post("/kill", response_model=GlobalKillResponse)
def global_kill(engaged: bool = True) -> dict:
    """GLOBAL kill-switch — the operator-wide panic button. Engages the safety gate
    for EVERY agent at once (each agent's dispatch checks this flag in addition to
    its per-agent flag). Pass ?engaged=false to disarm."""
    set_global_kill(engaged)
    return {"scope": "global", "kill_switch": engaged}


@app.get("/kill", response_model=GlobalKillResponse)
def global_kill_status() -> dict:
    """Read the global kill-switch state (for the operator dashboard)."""
    return {"scope": "global", "kill_switch": is_global_kill()}
