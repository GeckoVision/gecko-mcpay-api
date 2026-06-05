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


@app.get("/healthz")
def healthz() -> dict:
    cov = os.path.join(bt.DATA_DIR, "coverage.json")
    coins: list[str] = []
    if os.path.exists(cov):
        import json

        with open(cov) as f:
            coins = list(json.load(f).get("coins", {}))
    return {"ok": True, "data_coins": coins, "n_agents": len(_registry.list_agents())}


@app.get("/market-temp")
def market_temp() -> dict:
    """The current market-temperature read (risk-on/off) the app shows + bots
    consume. Served from the cached snapshot a refresh worker writes; neutral/
    stale if none yet. See refresh_market_temp.py."""
    import market_temp as mt

    return mt.load_snapshot()


@app.get("/vault")
def vault(profile: str = "conservative", demo_profit: float = 0.0) -> dict:
    """The profit-vault state the app tile reads: per-profile allocation, each lot's
    net APY + liquidation buffer, and the live yield-safety monitor verdict per lot.
    The monitor's downside input is the SAME market-temp read that gates trades
    (the unification). Honest-empty until the agent allocates real profit; pass
    ?demo_profit=100&profile=moderate to preview the shape. Paper only."""
    import market_temp as mt
    from kamino import vault_gate as vg
    from kamino import vault_orchestrator as vo
    from kamino.monitor import hurdle_for

    snap = mt.load_snapshot()
    dd = vo.predicted_drawdown_from_market_temp(snap)
    hurdle = hurdle_for(profile)
    orch = vo.VaultOrchestrator(
        profile=profile,
        policy=vg.VaultPolicy(max_allocation_usd=1_000_000.0, hurdle=hurdle),
        hurdle=hurdle,
    )
    allocation = orch.allocate_profit(demo_profit, predicted_drawdown_pct=dd) if demo_profit > 0 else None
    return {
        "snapshot": orch.snapshot(),
        "verdicts": orch.monitor_tick(predicted_drawdown_pct=dd),
        "allocation": allocation,
        "market_temp": {"label": snap.get("label"), "predicted_drawdown": dd, "stale": snap.get("stale", False)},
    }


@app.get("/arena/board")
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


@app.post("/backtest")
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


@app.post("/agents")
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


@app.post("/agents/{agent_id}/start")
def start_agent(agent_id: str) -> dict:
    try:
        return _orch.start(agent_id)
    except KeyError as e:
        raise HTTPException(404, str(e)) from e
    except PermissionError as e:  # per-user cap
        raise HTTPException(429, str(e)) from e
    except RuntimeError as e:  # no free port
        raise HTTPException(503, str(e)) from e


@app.get("/orchestrator")
def orchestrator_status() -> dict:
    return {"running": _orch.list_running(), "max_per_user": MAX_AGENTS_PER_USER}


@app.get("/agents")
def list_agents(user_id: str | None = None) -> dict:
    return {"agents": _registry.list_agents(user_id)}


@app.get("/agents/{agent_id}")
def get_agent(agent_id: str) -> dict:
    doc = _registry.get(agent_id)
    if not doc:
        raise HTTPException(404, f"no agent {agent_id!r}")
    return {"agent": doc, "state": _state.get_state(agent_id)}


@app.post("/agents/{agent_id}/stop")
def stop_agent(agent_id: str) -> dict:
    if not _registry.get(agent_id):
        raise HTTPException(404, f"no agent {agent_id!r}")
    killed = _orch.stop(agent_id)  # kills the running process (if any) + status→stopped
    return {"agent_id": agent_id, "status": "stopped", "process_killed": killed}


@app.post("/agents/{agent_id}/kill")
def kill_agent(agent_id: str, engaged: bool = True) -> dict:
    """SOFT kill-switch (web3 #4): engage `policy.kill_switch` so the safety gate
    denies EVERY new order for this agent — WITHOUT killing the running process (it
    keeps managing/closing existing positions, just opens nothing new). Pass
    ?engaged=false to disarm. For a hard process stop, use /stop."""
    if not _registry.get(agent_id):
        raise HTTPException(404, f"no agent {agent_id!r}")
    _registry.set_kill(agent_id, engaged)
    return {"agent_id": agent_id, "kill_switch": engaged}


@app.post("/kill")
def global_kill(engaged: bool = True) -> dict:
    """GLOBAL kill-switch — the operator-wide panic button. Engages the safety gate
    for EVERY agent at once (each agent's dispatch checks this flag in addition to
    its per-agent flag). Pass ?engaged=false to disarm."""
    set_global_kill(engaged)
    return {"scope": "global", "kill_switch": engaged}


@app.get("/kill")
def global_kill_status() -> dict:
    """Read the global kill-switch state (for the operator dashboard)."""
    return {"scope": "global", "kill_switch": is_global_kill()}
