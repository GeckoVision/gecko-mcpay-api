"""FastAPI service wrapping gecko-core for the V2 web app at app.geckovision.tech.

Routes:
    POST /research       — kick off a research session
    GET  /sessions/{id}  — fetch a session's three documents
    POST /sessions/{id}/ask — follow-up question
    GET  /sessions/{id}/sources — list indexed sources

Auto-generated OpenAPI docs at /docs and /redoc.

This is a thin transport layer — all logic in gecko_core. See the
`software-engineer` agent in .claude/agents/ for boundary rules.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import gecko_core
from gecko_core.models import AskResult, ResearchResult, SourceInfo, Tier


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    load_dotenv()
    yield


app = FastAPI(
    title="Gecko API",
    description="Builder Bootstrap Platform — backend for app.geckovision.tech.",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — allow the web app
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://app.geckovision.tech",
        "https://geckovision.tech",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


class ResearchRequest(BaseModel):
    idea: str = Field(..., min_length=10, max_length=500)
    tier: Tier = "basic"
    urls: list[str] | None = None


class AskRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=500)


@app.post("/research", response_model=ResearchResult)
async def research(req: ResearchRequest) -> ResearchResult:
    """Run the full discover → index → pay → generate workflow."""
    try:
        return await gecko_core.research(idea=req.idea, tier=req.tier, urls=req.urls)
    except NotImplementedError as e:
        raise HTTPException(status_code=501, detail=str(e)) from e


@app.post("/sessions/{session_id}/ask", response_model=AskResult)
async def ask(session_id: str, req: AskRequest) -> AskResult:
    """Follow-up question grounded in the session's knowledge base."""
    try:
        return await gecko_core.ask(session_id=session_id, question=req.question)
    except NotImplementedError as e:
        raise HTTPException(status_code=501, detail=str(e)) from e


@app.get("/sessions/{session_id}/sources", response_model=list[SourceInfo])
async def sources(session_id: str) -> list[SourceInfo]:
    """List all indexed sources for a session."""
    try:
        return await gecko_core.sources(session_id=session_id)
    except NotImplementedError as e:
        raise HTTPException(status_code=501, detail=str(e)) from e


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "payments": os.environ.get("X402_MODE", "stub")}


def run() -> None:
    """Entry point for `gecko-api` command."""
    uvicorn.run(
        "gecko_api.main:app",
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8000")),
        reload=os.environ.get("RELOAD") == "1",
    )
