#!/usr/bin/env python3
"""Backtest API — Phase 1 of the hosted agent flow (spec
`private/specs/2026-06-03-agent-flow-hosting-design.md`).

A thin FastAPI surface over `backtest_strategy.run_backtest`. The app's Strategy
Forge POSTs a strategy_id + gate/exit overrides; we run the SAME rigor harness
the live bot's rules bind to (Pattern-C) and return the verdict envelope the UI
renders as a card. Runs server-side → the user needs NO Python locally.

Run:
    uv run uvicorn backtest_api:app --host 0.0.0.0 --port 8270
    # (from contest_bot/, with majors data ingested)

Endpoints:
    GET  /healthz                 → {"ok": true, "coins": [...]}  (data presence)
    POST /backtest                → verdict envelope (see BacktestRequest)
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

app = FastAPI(title="Gecko Backtest API", version="0.1.0")

_ALLOWED = {"trend_breakout", "mean_reversion"}


class BacktestRequest(BaseModel):
    strategy_id: str = Field("trend_breakout", description="trend_breakout | mean_reversion")
    entry_gates: dict | None = Field(None, description="overrides merged onto the spec entry_gates")
    exit: dict | None = Field(None, description="overrides merged onto the spec exit stack")
    coins: list[str] | None = Field(None, description="default: the ingested majors universe")
    fee_pct: float = Field(0.20, ge=0.0, le=2.0, description="round-trip fee %% (default 0.20 OKX)")
    both: bool = Field(False, description="also run the other strategy + orthogonality rho")


@app.get("/healthz")
def healthz() -> dict:
    cov = os.path.join(bt.DATA_DIR, "coverage.json")
    coins: list[str] = []
    if os.path.exists(cov):
        import json

        with open(cov) as f:
            coins = list(json.load(f).get("coins", {}))
    return {"ok": bool(coins), "coins": coins, "data_dir": bt.DATA_DIR}


@app.post("/backtest")
def backtest(req: BacktestRequest) -> dict:
    if req.strategy_id not in _ALLOWED:
        raise HTTPException(422, f"unknown strategy_id {req.strategy_id!r}; allowed: {sorted(_ALLOWED)}")
    try:
        return bt.run_backtest(
            strategy_id=req.strategy_id,
            entry_gates=req.entry_gates,
            exit_overrides=req.exit,
            coins=req.coins,
            fee_pct=req.fee_pct,
            both=req.both,
        )
    except ValueError as e:  # data not ingested
        raise HTTPException(503, str(e)) from e
