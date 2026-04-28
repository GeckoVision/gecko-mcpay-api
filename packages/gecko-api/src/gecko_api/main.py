"""FastAPI service wrapping gecko-core for the V2 web app at app.geckovision.tech.

Routes (V2 — agent-native):
    POST /research              — gated by x402, $20 (basic tier)
    POST /research/pro          — gated by x402, $75 (pro tier; 501 NotImplemented)
    POST /sessions/{id}/ask     — FREE follow-up question
    GET  /sessions/{id}/sources — FREE list indexed sources
    GET  /healthz               — FREE liveness + payment mode
    GET  /.well-known/x402      — FREE route catalog per x402 convention

Middleware order matters: CORS first, then x402. Browser callers can't read
402 response headers if x402 wraps CORS.

This is a thin transport layer — all business logic lives in `gecko_core`.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

import gecko_core
import uvicorn
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from gecko_core.models import AskResult, ResearchResult, SourceInfo, Tier
from gecko_core.sessions.store import SessionStore
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.responses import JSONResponse
from x402 import x402ResourceServer
from x402.http.facilitator_client import HTTPFacilitatorClient
from x402.http.facilitator_client_base import FacilitatorClient, FacilitatorConfig
from x402.http.middleware.fastapi import PaymentMiddlewareASGI
from x402.http.types import PaymentOption, RouteConfig
from x402.mechanisms.svm.exact import ExactSvmServerScheme

from gecko_api.auth import verify_frames_token
from gecko_api.settings import Settings
from gecko_api.x402_stub import StubFacilitatorClient

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# x402 wiring — built once at import time so the same RouteConfig dict is
# shared with /.well-known/x402.
# ---------------------------------------------------------------------------


def _build_facilitator(settings: Settings) -> FacilitatorClient:
    """Pick the right facilitator client for the configured mode.

    Stub returns a fake settle. Live and frames talk to a real facilitator
    over HTTP. Same protocol both sides; the rest of the stack doesn't care.
    """
    if settings.x402_mode == "stub":
        return StubFacilitatorClient(network=settings.x402_network)
    # Live + frames both go through HTTPFacilitatorClient. Frames-specific
    # auth headers can be wired later via FacilitatorConfig.create_headers.
    assert settings.x402_facilitator_url is not None  # checked in Settings.from_env
    return HTTPFacilitatorClient(FacilitatorConfig(url=settings.x402_facilitator_url))


def _build_routes(settings: Settings) -> dict[str, RouteConfig]:
    pay_to = settings.gecko_wallet_address or "STUB_WALLET_ADDRESS_NOT_FOR_LIVE"
    return {
        "POST /research": RouteConfig(
            accepts=[
                PaymentOption(
                    scheme="exact",
                    pay_to=pay_to,
                    price=settings.research_basic_price,
                    network=settings.x402_network,
                ),
            ],
            description="Run a Builder Bootstrap research session (basic tier)",
        ),
        "POST /research/pro": RouteConfig(
            accepts=[
                PaymentOption(
                    scheme="exact",
                    pay_to=pay_to,
                    price=settings.research_pro_price,
                    network=settings.x402_network,
                ),
            ],
            description="Run a Builder Bootstrap research session (pro tier)",
        ),
    }


def _build_resource_server(facilitator: FacilitatorClient) -> x402ResourceServer:
    server = x402ResourceServer(facilitator)
    # Wildcard registration covers both "solana-devnet" / "solana-mainnet"
    # (V1 names) and the CAIP-2 form returned post-normalization.
    scheme: Any = ExactSvmServerScheme()  # type: ignore[no-untyped-call]
    server.register("solana:*", scheme)
    server.register("solana-devnet", scheme)
    server.register("solana-mainnet", scheme)
    return server


# Module-level so the lifespan + the /.well-known endpoint share one config.
_settings = Settings.from_env()
_facilitator = _build_facilitator(_settings)
_routes_config = _build_routes(_settings)
_resource_server = _build_resource_server(_facilitator)

# Strong refs to background tasks so they aren't GC'd mid-flight. Tasks
# remove themselves from the set in their done callback.
_BACKGROUND_TASKS: set[asyncio.Task[None]] = set()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    load_dotenv()
    logger.info("gecko-api starting (X402_MODE=%s)", _settings.x402_mode)
    yield


# Rate limiter: prefer Authorization header as the bucket key (so a single
# user can't share rate by spoofing IPs); fall back to remote address for
# unauthenticated paths. The limiter is exposed via app.state for slowapi's
# decorator + handler.
def _rate_limit_key(request: Request) -> str:
    auth = request.headers.get("authorization")
    if auth:
        return auth
    return get_remote_address(request)


limiter = Limiter(key_func=_rate_limit_key)


app = FastAPI(
    title="Gecko API",
    description="Builder Bootstrap Platform — backend for app.geckovision.tech.",
    version="0.2.0",
    lifespan=lifespan,
)
app.state.limiter = limiter


async def _rate_limit_handler(request: Request, exc: Exception) -> JSONResponse:
    # slowapi raises RateLimitExceeded; the handler signature must accept
    # the base Exception type for FastAPI's exception_handlers registry.
    detail = str(exc) if isinstance(exc, RateLimitExceeded) else "rate limited"
    return JSONResponse(status_code=429, content={"detail": detail})


app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)

# CORS FIRST, then x402. Browsers need to be able to read the 402 headers.
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
    # Expose the 402-related headers so browser-side clients can react.
    expose_headers=["X-PAYMENT-RESPONSE", "X-PAYMENT", "WWW-Authenticate"],
)

app.add_middleware(
    PaymentMiddlewareASGI,
    routes=_routes_config,
    server=_resource_server,
)


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class ResearchRequest(BaseModel):
    idea: str = Field(..., min_length=10, max_length=500)
    tier: Tier = "basic"
    urls: list[str] | None = None
    auto_approve: bool = True
    # Phase B5 v1 — optional project envelope. v1 always pays from main wallet;
    # `paid_from_wallet_address` is recorded as "<frames_username>:main" for
    # audit. v2 will replace this with the per-project Privy wallet address.
    project_id: str | None = None
    frames_username: str | None = None


class AskRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=500)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _route_price_usd(route: str) -> float:
    """Pull the advertised USD price for a route from the x402 config.

    Strips the `$` prefix and parses to float. Used by handlers to record
    price_usd on the session so margin can be computed.
    """
    cfg = _routes_config.get(route)
    if cfg is None:
        return 0.0
    accepts = cfg.accepts if isinstance(cfg.accepts, list) else [cfg.accepts]
    if not accepts:
        return 0.0
    raw = str(accepts[0].price).lstrip("$")
    try:
        return float(raw)
    except ValueError:
        return 0.0


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.post("/research", status_code=202)
async def research(req: ResearchRequest, request: Request) -> dict[str, Any]:
    """Kick off a research session. Returns 202 + session_id immediately.

    The full pipeline runs as a background task — frames.ag's /x402/fetch
    upstream timeout is ~30s, but the workflow takes 60-90s. By returning
    fast we let payment settle synchronously while research keeps running;
    the client polls GET /sessions/{id}/result for completion.
    """
    # Create the session row up front so the client has a handle to poll.
    store = SessionStore.from_env()
    session_id: UUID = await store.create(idea=req.idea, tier="basic")

    # Persist the price the user just paid so the economics view is accurate
    # even before the background task finishes.
    payload = getattr(request.state, "payment_payload", None)
    if payload is not None:
        try:
            await store.set_tx_signature(session_id, "pending-settle")
            await store.set_price(session_id, _route_price_usd("POST /research"))
        except Exception as exc:  # pragma: no cover — best-effort
            logger.warning("failed to persist payment marker: %s", exc)

    # Phase B5 v1 — attach project + record paying wallet for audit.
    if req.project_id:
        try:
            project_uuid = UUID(req.project_id)
            paid_from = f"{req.frames_username}:main" if req.frames_username else None
            await store.set_session_project(
                session_id,
                project_uuid,
                paid_from_wallet_address=paid_from,
            )
        except (ValueError, Exception) as exc:  # pragma: no cover — best-effort
            logger.warning("failed to attach project_id %s: %s", req.project_id, exc)

    task = asyncio.create_task(_run_research_background(session_id, req))
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)

    return {
        "session_id": str(session_id),
        "status": "processing",
        "poll_url": f"/sessions/{session_id}/result",
    }


async def _run_research_background(session_id: UUID, req: ResearchRequest) -> None:
    """Run the gecko_core workflow under an existing session_id.

    Persists the result to sessions.result_json on success or sessions.
    error_message on failure. Errors here never crash the request — the
    client polls /sessions/{id}/result and sees a 500-with-detail or
    a 425 still-processing.
    """
    store = SessionStore.from_env()
    try:
        result = await gecko_core.research(
            idea=req.idea,
            tier="basic",
            urls=req.urls,
            auto_approve=True,
            skip_payment_gate=True,
            session_id=session_id,
        )
        await store.set_result(session_id, result.model_dump(mode="json"))
        await store.update_status(session_id, "complete")
    except NotImplementedError as exc:
        logger.warning("research session %s not implemented: %s", session_id, exc)
        await store.set_error(session_id, f"NotImplemented: {exc}")
    except Exception as exc:
        logger.exception("research session %s failed", session_id)
        await store.set_error(session_id, f"{type(exc).__name__}: {exc}")


@app.post("/research/pro", response_model=ResearchResult)
async def research_pro(req: ResearchRequest, request: Request) -> ResearchResult:
    """Pro tier — Phase 7, deferred. Returns 501 after payment verifies."""
    # Phase 7 will replace this with the AutoGen GroupChat workflow.
    raise HTTPException(
        status_code=501,
        detail="pro tier orchestration not yet implemented (Phase 7)",
    )


@app.post("/sessions/{session_id}/ask", response_model=AskResult)
async def ask(session_id: str, req: AskRequest) -> AskResult:
    """Free follow-up. Once a session is paid for, queries are unlimited."""
    try:
        return await gecko_core.ask(session_id=session_id, question=req.question)
    except NotImplementedError as e:
        raise HTTPException(status_code=501, detail=str(e)) from e


@app.get("/sessions/{session_id}/sources", response_model=list[SourceInfo])
async def sources(session_id: str) -> list[SourceInfo]:
    """Free — list all indexed sources for a session."""
    try:
        return await gecko_core.sources(session_id=session_id)
    except NotImplementedError as e:
        raise HTTPException(status_code=501, detail=str(e)) from e


@app.get("/sessions/{session_id}/result")
async def session_result(session_id: str) -> dict[str, Any]:
    """Poll for the async ResearchResult.

    Status semantics:
        - 200 + ResearchResult JSON: workflow complete
        - 425 Too Early: still processing — poll again in a few seconds
        - 500 + {error}: workflow failed (see the `error` field)
        - 404: session not found
    """
    try:
        sid = UUID(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid session_id") from exc

    store = SessionStore.from_env()
    record = await store.get(sid)
    if record is None:
        raise HTTPException(status_code=404, detail="session not found")

    if record.status == "failed":
        msg = await store.get_error(sid)
        raise HTTPException(
            status_code=500,
            detail={"status": "failed", "error": msg or "unknown failure"},
        )

    result = await store.get_result(sid)
    if result is None:
        # Still processing — let the client retry. 425 "Too Early" is the
        # cleanest fit; some HTTP clients balk at non-standard codes, so
        # include a retry hint in the body too.
        raise HTTPException(
            status_code=425,
            detail={"status": record.status, "retry_after_seconds": 5},
        )

    return result


@app.get("/sessions/{session_id}/economics")
async def session_economics(session_id: str) -> dict[str, Any]:
    """Per-session unit economics: price charged vs real costs incurred.

    Free read — surfaces what's already on the `sessions` row (price_usd,
    cost_*_usd, generated cost_total_usd and margin_usd, plus the x402 tx
    signature). Useful for the demo dashboard and for pre-mainnet pricing
    decisions on devnet.
    """
    try:
        sid = UUID(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid session_id") from exc
    store = SessionStore.from_env()
    econ = await store.get_economics(sid)
    if econ is None:
        raise HTTPException(status_code=404, detail="session not found")
    payload = econ.model_dump(mode="json")
    return payload


@app.get("/sessions/spent-by-project/{project_id}")
async def sessions_spent_by_project(project_id: str) -> dict[str, Any]:
    """Free — total spend + session count for a project.

    Used by the gecko-mcp api_client as a pre-flight budget check before
    paying. Best-effort guarantee: this is *not* a hard ceiling in v1
    (frames.ag policy is per-wallet, not per-project). v2 replaces this
    with on-chain isolation via project-scoped Privy wallets.
    """
    try:
        pid = UUID(project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid project_id") from exc
    store = SessionStore.from_env()
    spent, count = await store._project_spend(pid)
    return {
        "project_id": str(pid),
        "total_spent_usd": spent,
        "sessions_count": count,
    }


# ---------------------------------------------------------------------------
# /projects — bearer-authenticated CRUD for per-user project envelopes.
#
# All four endpoints require frames.ag bearer auth (verify_frames_token).
# Username is derived server-side from the verified token; the client never
# declares its own identity. Rate-limited at 60/min per Authorization header.
# ---------------------------------------------------------------------------


class ProjectCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    budget_usd: float | None = Field(default=None, ge=0)


class ProjectOut(BaseModel):
    project_id: str
    name: str
    budget_usd: float | None = None
    wallet_address: str | None = None
    wallet_provider: str | None = None
    created_at: str | None = None


def _project_row_to_out(row: dict[str, Any]) -> ProjectOut:
    return ProjectOut(
        project_id=str(row["id"]),
        name=str(row.get("name", "")),
        budget_usd=_float_or_none(row.get("budget_usd")),
        wallet_address=row.get("wallet_address"),
        wallet_provider=row.get("wallet_provider"),
        created_at=str(row["created_at"]) if row.get("created_at") is not None else None,
    )


def _float_or_none(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


@app.post("/projects", status_code=201)
@limiter.limit("60/minute")
async def create_project(
    request: Request,
    body: ProjectCreateRequest,
    username: str = Depends(verify_frames_token),
) -> dict[str, Any]:
    store = SessionStore.from_env()
    try:
        project_id = await store.create_project(
            username=username,
            name=body.name,
            budget_usd=body.budget_usd,
        )
    except Exception as exc:
        # Likely (frames_username, name) unique-constraint violation → 409.
        msg = str(exc).lower()
        if "duplicate" in msg or "unique" in msg or "23505" in msg:
            raise HTTPException(status_code=409, detail="project name already exists") from exc
        logger.exception("create_project failed for %s/%s", username, body.name)
        raise HTTPException(status_code=500, detail="could not create project") from exc

    record = await store.get_project(username=username, name=body.name)
    if record is None:
        # Should not happen — the insert just succeeded.
        return {
            "project_id": str(project_id),
            "name": body.name,
            "budget_usd": body.budget_usd,
            "wallet_address": None,
            "wallet_provider": "frames-policy",
            "created_at": None,
        }
    return _project_row_to_out(record).model_dump()


@app.get("/projects")
@limiter.limit("60/minute")
async def list_projects(
    request: Request,
    username: str = Depends(verify_frames_token),
) -> list[dict[str, Any]]:
    store = SessionStore.from_env()
    rows = await store.list_projects(username=username)
    out: list[dict[str, Any]] = []
    for row in rows:
        try:
            pid = UUID(str(row["id"]))
        except (KeyError, ValueError):
            continue
        spent, count = await store._project_spend(pid)
        item = _project_row_to_out(row).model_dump()
        item["total_spent_usd"] = spent
        item["sessions_count"] = count
        out.append(item)
    return out


@app.get("/projects/{name}")
@limiter.limit("60/minute")
async def get_project(
    name: str,
    request: Request,
    username: str = Depends(verify_frames_token),
) -> dict[str, Any]:
    store = SessionStore.from_env()
    record = await store.get_project(username=username, name=name)
    if record is None:
        raise HTTPException(status_code=404, detail="project not found")
    pid = UUID(str(record["id"]))
    spent = await store.project_total_spent(pid)
    remaining = await store.project_budget_remaining(pid)
    sessions = await store.list_project_sessions(pid, limit=5)
    payload = _project_row_to_out(record).model_dump()
    payload["total_spent_usd"] = spent
    payload["budget_remaining_usd"] = remaining
    payload["sessions"] = [
        {
            "id": str(s.get("id", "")),
            "idea": s.get("idea"),
            "status": s.get("status"),
            "cost_total_usd": _float_or_none(s.get("cost_total_usd")) or 0.0,
            "created_at": str(s["created_at"]) if s.get("created_at") is not None else None,
        }
        for s in sessions
    ]
    return payload


@app.delete("/projects/{name}", status_code=204)
@limiter.limit("60/minute")
async def delete_project(
    name: str,
    request: Request,
    username: str = Depends(verify_frames_token),
) -> None:
    store = SessionStore.from_env()
    deleted = await store.delete_project(username=username, name=name)
    if not deleted:
        raise HTTPException(status_code=404, detail="project not found")
    return None


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "payments": _settings.x402_mode}


@app.get("/.well-known/x402")
async def well_known_x402() -> dict[str, Any]:
    """x402 discovery endpoint.

    Returns the route catalog (price, network, payTo, scheme) so an agent
    can introspect what's payable here without first eating a 402.
    """
    catalog: list[dict[str, Any]] = []
    for pattern, route in _routes_config.items():
        accepts = route.accepts if isinstance(route.accepts, list) else [route.accepts]
        catalog.append(
            {
                "route": pattern,
                "description": route.description,
                "accepts": [
                    {
                        "scheme": opt.scheme,
                        "network": opt.network,
                        "price": opt.price,
                        "payTo": opt.pay_to,
                        "maxTimeoutSeconds": opt.max_timeout_seconds,
                    }
                    for opt in accepts
                ],
            }
        )
    return {
        "x402_version": 2,
        "mode": _settings.x402_mode,
        "routes": catalog,
    }


def run() -> None:
    """Entry point for `gecko-api` command."""
    uvicorn.run(
        "gecko_api.main:app",
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8000")),
        reload=os.environ.get("RELOAD") == "1",
    )
