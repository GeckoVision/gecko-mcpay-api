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
from pydantic import BaseModel, Field

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import backtest_strategy as bt  # noqa: E402
from agent_store import AgentRegistry, AgentStateStore  # noqa: E402

app = FastAPI(title="Gecko Agent Control Plane", version="0.2.0")

_ALLOWED = {"trend_breakout", "mean_reversion"}
_registry = AgentRegistry()
_state = AgentStateStore()


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
    try:
        agent_id = _registry.deploy(req.spec, user_id=req.user_id, verdict=req.verdict)
    except ValueError as e:  # REJECT verdict
        raise HTTPException(409, str(e)) from e
    return {"agent_id": agent_id, "status": "deployed",
            "launch": f"bash launch_agent.sh {agent_id}"}


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
    if not _registry.set_status(agent_id, "stopped"):
        raise HTTPException(404, f"no agent {agent_id!r}")
    return {"agent_id": agent_id, "status": "stopped"}
