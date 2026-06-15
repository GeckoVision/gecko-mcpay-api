"""V1 verdict-loop — session-gated POST /v1/research.

First-user validation surface. A signed-in user requests a Gecko verdict; the
web app renders the envelope (pass/defer + surviving dissent + citations). This
is the SAME panel the unauthenticated `/trade_research` ($0.25 basic) handler in
`main.py` runs — the difference is the session gate (`require_session`) and that
this surface is meant for the logged-in app, not the public x402 catalog.

X402_MODE stays stub for this route: stub mode runs the panel and returns the
verdict with no real payment wiring. Charging is a later task.

Tier: this handler is synchronous (JSON in / JSON out) and FORCES basic. The
basic panel fits inside an HTTP request; the pro panel runs 80-100s and exceeds
typical HTTP timeouts, so pro-tier needs the SSE/streaming pattern as a
follow-up. A caller that sends `tier="pro"` is coerced to basic (the `tier`
field stays on the request model for forward-compat) so the app can't
accidentally trigger a 504.

Thin transport: the panel + LLM config live in core / `main.py`. This module
parses input, gates on the session, calls core, and returns the pydantic model.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from gecko_core.models import Tier
from gecko_core.orchestration.trade_panel import run_trade_panel_with_retrieval
from gecko_core.orchestration.trade_panel.models import TradePanelVerdict
from pydantic import BaseModel, Field

from ._session import SessionCtx, require_session

router = APIRouter(prefix="/v1", tags=["research"])


class ResearchRequest(BaseModel):
    """Request shape for POST /v1/research.

    Mirrors `gecko_api.main.TradeResearchRequest` (defined there, not imported,
    to avoid a circular import: `main` imports this router at module load). The
    fields and constraints are kept identical so the two surfaces stay in sync.
    """

    idea: str = Field(..., min_length=3, max_length=2000)
    protocol: str = Field(..., min_length=1, max_length=64)
    vertical: str = Field(default="dex", min_length=1, max_length=64)
    tier: Tier = "basic"
    mint: str | None = Field(
        default=None,
        min_length=32,
        max_length=44,
        description=(
            "Optional SPL mint address. When set, the contract-safety check "
            "fires on it directly (safety.checked=true) instead of trying to "
            "base58-decode the protocol string. Use this for token queries."
        ),
    )


def _research_llm_config() -> dict[str, Any]:
    """Reuse `main._trade_panel_llm_config` — the router-aware (OpenRouter in
    prod) AG2 config the existing `/trade_research` handler builds. Imported
    lazily to avoid a circular import at module load. Wrapped in a module-level
    function so tests can monkeypatch it without touching `main`."""
    from gecko_api.main import _trade_panel_llm_config

    return _trade_panel_llm_config()


@router.post("/research", response_model=TradePanelVerdict)
async def research(
    req: ResearchRequest,
    ctx: Annotated[SessionCtx, Depends(require_session)],
) -> TradePanelVerdict:
    """Run the trade panel for a signed-in user and return the verdict envelope.

    401 (via `require_session`) when the Bearer session token is missing/bad.
    Defaults to basic tier; see the module docstring for why pro needs SSE.
    """
    llm_config = _research_llm_config()
    # pro tier (80-100s) exceeds sync HTTP timeout — force basic until the SSE path lands
    tier: Tier = "basic"
    # Phase 2.1 — ENV-gated live-news injection. Default OFF (returns None →
    # byte-identical to today). When GECKO_NEWS_PROVIDER=okx AND the OKX news
    # key/url are provisioned, the sentiment_analyst voice sees live headlines
    # instead of degrading to a constant `neutral`. Fail-OPEN by construction.
    from gecko_core.orchestration.trade_panel.news_factory import build_news_provider

    try:
        verdict = await run_trade_panel_with_retrieval(
            idea=req.idea,
            protocol=req.protocol,
            vertical=req.vertical,
            tier=tier,
            llm_config=llm_config,
            mint=req.mint,
            news_provider=build_news_provider(),
        )
    except Exception as exc:
        # One-line user-facing message; class name only, never the message
        # (it can leak MONGODB_URI, API keys, internal paths) — same redaction
        # contract as the `/trade_research` handler in main.py.
        raise HTTPException(
            status_code=500,
            detail=(
                f"research failed ({type(exc).__name__}) — "
                "retry in a minute; if it persists, run `gecko-mcp doctor`"
            ),
        ) from None

    return verdict
