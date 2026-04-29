"""Gecko MCP server.

Exposes three tools (the contract for the Claude Code skill bootstrap):

    gecko_research — full discover -> index -> pay -> generate workflow
    gecko_ask      — follow-up question against an existing session
    gecko_sources  — list indexed sources for a session

Thin transport layer. v2: the server no longer imports `gecko_core` directly.
It is just another HTTP client of `gecko-api`, paying through the same x402
gate as any other agent. All real work happens server-side; this module
parses MCP arguments, calls `GeckoAPIClient`, and JSON-serializes the result.

Environment:
    GECKO_API_URL — base URL for `gecko-api`. Default:
                    ``https://api.geckovision.tech`` (production). Override
                    to ``http://localhost:8000`` for local dev.
"""

from __future__ import annotations

import json
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from gecko_mcp.api_client import GeckoAPIClient
from gecko_mcp.clawrouter_supervisor import warm_clawrouter

server: Server = Server("gecko-mcp")

# Lazy module-level client — built on first tool call so server startup
# succeeds even if the API is down or env is incomplete (Claude Code's MCP
# bootstrap must not fail because of transient network issues).
_client: GeckoAPIClient | None = None


def _get_client() -> GeckoAPIClient:
    global _client
    if _client is None:
        _client = GeckoAPIClient()
    return _client


_RESEARCH_DESCRIPTION = (
    "Run the full Builder Bootstrap workflow for a startup idea. Discovers "
    "sources (or uses the URLs you provide), indexes them into a session "
    "knowledge base, runs the x402 payment gate (stub mode by default), and "
    "generates a one-page business plan, validation report, and PRD with "
    "inline citations. Returns a ResearchResult JSON payload including the "
    "session_id needed for follow-up `gecko_ask` calls."
)

_ASK_DESCRIPTION = (
    "Ask a follow-up question grounded in an existing session's knowledge "
    "base. Cites the chunks used inline. Requires the session_id returned "
    "by a prior `gecko_research` call."
)

_SOURCES_DESCRIPTION = (
    "List every source indexed into a session's knowledge base (URL, type, "
    "chunk count, and indexed_at timestamp). Useful for transparency before "
    "running `gecko_ask`."
)

_CLASSIFY_DESCRIPTION = (
    "Classify a startup idea into Gecko's category taxonomy (crypto, defi, "
    "devtools, saas, regulated, hackathon-team) using embedding nearest-"
    "neighbor cosine similarity. Returns the selected categories (top-2 "
    "above threshold) plus the full score map so callers can see why. "
    "Free — no x402 payment required."
)

_PRECEDENTS_DESCRIPTION = (
    "Look up prior Gecko verdicts on similar ideas (the flywheel). Embeds "
    "the idea, runs an internal cosine search over `gecko_precedent`, and "
    "returns the top-K precedent rows with verdict + key_comparables. Free "
    "— no x402 payment required."
)

_AVAILABLE_SOURCES_DESCRIPTION = (
    "List the catalog of signal sources Gecko queries (Tavily, HN, Reddit, "
    "twit.sh, Colosseum, gecko_precedent flywheel, …) with description, "
    "gating rule, and per-call cost. Distinct from `gecko_sources`, which "
    "lists indexed sources for a specific session. Free."
)

_ROUTE_DESCRIPTION = (
    "Route an LLM call through Gecko's cost-aware router. Pays via x402 "
    "wallet. Use task_hint to bias model selection (reasoning, code, "
    "extraction, summary, default). Returns response + cost breakdown "
    "including savings_vs_premium so subagents can show 'you saved $X by "
    "routing through Gecko'."
)

_SCAFFOLD_DESCRIPTION = (
    "Generate a 3-file project starter bundle (PRD.md, business-plan.md, "
    "BUILDING.md) from a completed Pro tier debate. Refuses on verdict=kill. "
    "Files land under <output_dir>/.gecko/scaffolds/<session_id>/. The "
    "BUILDING.md file is a ready-to-use Claude Code prompt for V1. Free — "
    "the user already paid for the Pro debate."
)

_PROJECT_ECONOMICS_DESCRIPTION = (
    "Per-project economics snapshot (S2-09): privy wallet address, live USDC "
    "balance, budget cap + spend, and the 5 most recent paid sessions. Use "
    "this to answer 'how much have I spent on project X?' and 'does my "
    "project wallet have enough balance for the next run?'. Distinct from "
    "`session_id`-scoped economics — pass a project UUID."
)


@server.list_tools()  # type: ignore[no-untyped-call,untyped-decorator]
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="gecko_research",
            description=_RESEARCH_DESCRIPTION,
            inputSchema={
                "type": "object",
                "properties": {
                    "idea": {
                        "type": "string",
                        "description": "Plain-language startup idea (1-2 sentences).",
                    },
                    "tier": {
                        "type": "string",
                        "enum": ["basic", "pro"],
                        "default": "basic",
                        "description": (
                            "'basic' = single-pass generation. 'pro' = multi-agent "
                            "AutoGen GroupChat (slower, deeper)."
                        ),
                    },
                    "urls": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Optional seed URLs (web articles or YouTube). When "
                            "omitted, sources are auto-discovered via Tavily."
                        ),
                    },
                    "auto_approve": {
                        "type": "boolean",
                        "default": True,
                        "description": (
                            "If True, skip the source-approval prompt and proceed "
                            "directly to the payment gate. MCP clients should "
                            "leave this True — there is no interactive prompt."
                        ),
                    },
                    "project_id": {
                        "type": "string",
                        "description": (
                            "Optional project UUID to attach this session to. "
                            "Phase B5 v1: enables client-side budget enforcement "
                            "and audit-trail (paid_from_wallet_address)."
                        ),
                    },
                    "tier_preset": {
                        "type": "string",
                        "enum": ["quality", "balanced", "budget", "free"],
                        "default": "balanced",
                        "description": (
                            "User-facing cost/quality preset (S4-MATRIX-01). Maps "
                            "to per-agent model selection via the curated catalog. "
                            "Default 'balanced' picks Kimi K2.6 / DeepSeek for the "
                            "sweet spot. Orthogonal to 'tier' (basic/pro)."
                        ),
                    },
                },
                "required": ["idea"],
            },
        ),
        Tool(
            name="gecko_ask",
            description=_ASK_DESCRIPTION,
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "Session UUID returned by `gecko_research`.",
                    },
                    "question": {
                        "type": "string",
                        "description": "Plain-language follow-up question.",
                    },
                },
                "required": ["session_id", "question"],
            },
        ),
        Tool(
            name="gecko_sources",
            description=_SOURCES_DESCRIPTION,
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "Session UUID returned by `gecko_research`.",
                    },
                },
                "required": ["session_id"],
            },
        ),
        Tool(
            name="gecko_classify",
            description=_CLASSIFY_DESCRIPTION,
            inputSchema={
                "type": "object",
                "properties": {
                    "idea": {
                        "type": "string",
                        "description": "Plain-language startup idea (1-2 sentences).",
                    },
                },
                "required": ["idea"],
            },
        ),
        Tool(
            name="gecko_precedents",
            description=_PRECEDENTS_DESCRIPTION,
            inputSchema={
                "type": "object",
                "properties": {
                    "idea": {
                        "type": "string",
                        "description": "Plain-language startup idea to look up.",
                    },
                    "top_k": {
                        "type": "integer",
                        "default": 5,
                        "minimum": 1,
                        "maximum": 25,
                        "description": "Max number of precedent rows to return.",
                    },
                },
                "required": ["idea"],
            },
        ),
        Tool(
            name="gecko_available_sources",
            description=_AVAILABLE_SOURCES_DESCRIPTION,
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="gecko_route",
            description=_ROUTE_DESCRIPTION,
            inputSchema={
                "type": "object",
                "properties": {
                    "prompt": {"type": "string"},
                    "task_hint": {
                        "type": "string",
                        "enum": [
                            "reasoning",
                            "code",
                            "extraction",
                            "summary",
                            "default",
                        ],
                    },
                    "max_cost_usd": {"type": "number"},
                    "prefer_premium": {"type": "boolean"},
                    "tier_preset": {
                        "type": "string",
                        "enum": ["quality", "balanced", "budget", "free"],
                        "default": "balanced",
                    },
                },
                "required": ["prompt"],
            },
        ),
        Tool(
            name="gecko_scaffold",
            description=_SCAFFOLD_DESCRIPTION,
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": (
                            "Session UUID returned by `gecko_research` (Pro tier). "
                            "Verdict must be 'ship' or 'pivot'."
                        ),
                    },
                    "output_dir": {
                        "type": "string",
                        "description": (
                            "Workspace root. Files land under "
                            "<output_dir>/.gecko/scaffolds/<session_id>/. "
                            "Defaults to the server's current working directory."
                        ),
                    },
                },
                "required": ["session_id"],
            },
        ),
        Tool(
            name="gecko_project_economics",
            description=_PROJECT_ECONOMICS_DESCRIPTION,
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": (
                            "Project UUID. Get one from `gecko project list` "
                            "or the V2 web app at app.geckovision.tech."
                        ),
                    },
                },
                "required": ["project_id"],
            },
        ),
    ]


@server.call_tool()  # type: ignore[untyped-decorator]
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    client = _get_client()

    if name == "gecko_research":
        idea = str(arguments["idea"])
        tier_raw = arguments.get("tier", "basic")
        if tier_raw not in ("basic", "pro"):
            raise ValueError(f"tier must be 'basic' or 'pro', got {tier_raw!r}")
        urls_raw = arguments.get("urls")
        urls: list[str] | None = [str(u) for u in urls_raw] if isinstance(urls_raw, list) else None
        # `auto_approve` is accepted in the schema for forward-compat but
        # the API always runs auto-approved; there is no MCP prompt surface.
        project_id_raw = arguments.get("project_id")
        project_id = str(project_id_raw) if project_id_raw else None
        tier_preset_raw = arguments.get("tier_preset", "balanced")
        if tier_preset_raw not in ("quality", "balanced", "budget", "free"):
            raise ValueError(
                f"tier_preset must be quality|balanced|budget|free, got {tier_preset_raw!r}"
            )

        result = await client.research(
            idea,
            tier=tier_raw,
            urls=urls,
            project_id=project_id,
            tier_preset=str(tier_preset_raw),
        )
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    if name == "gecko_ask":
        result = await client.ask(
            session_id=str(arguments["session_id"]),
            question=str(arguments["question"]),
        )
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    if name == "gecko_sources":
        sources = await client.list_sources(session_id=str(arguments["session_id"]))
        return [TextContent(type="text", text=json.dumps(sources, indent=2))]

    if name == "gecko_classify":
        result = await _run_classify(idea=str(arguments["idea"]))
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    if name == "gecko_precedents":
        top_k_raw = arguments.get("top_k", 5)
        top_k = int(top_k_raw) if top_k_raw is not None else 5
        result_list = await _run_precedents(idea=str(arguments["idea"]), top_k=top_k)
        return [TextContent(type="text", text=json.dumps(result_list, indent=2))]

    if name == "gecko_available_sources":
        result_list = _run_available_sources()
        return [TextContent(type="text", text=json.dumps(result_list, indent=2))]

    if name == "gecko_route":
        result = await _run_route(
            client=client,
            prompt=str(arguments["prompt"]),
            task_hint=str(arguments.get("task_hint", "default")),
            max_cost_usd=float(arguments.get("max_cost_usd", 0.05)),
            prefer_premium=bool(arguments.get("prefer_premium", False)),
            tier_preset=str(arguments.get("tier_preset", "balanced")),
        )
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    if name == "gecko_scaffold":
        output_dir_raw = arguments.get("output_dir")
        result = await _run_scaffold(
            session_id=str(arguments["session_id"]),
            output_dir=str(output_dir_raw) if output_dir_raw else None,
        )
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    if name == "gecko_project_economics":
        result = await client.get_project_economics(project_id=str(arguments["project_id"]))
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    raise ValueError(f"unknown tool: {name}")


async def _run_classify(*, idea: str) -> dict[str, Any]:
    """Call `gecko_core.classify.classify_idea_with_scores`.

    Free path — bypasses GeckoAPIClient / x402. We import lazily so the
    embedder + numpy aren't pulled into the MCP startup path for users
    who never invoke the classifier.
    """
    from gecko_core.classify import classify_idea_with_scores

    selected, scores = await classify_idea_with_scores(idea)
    return {"categories": selected, "scores": scores}


async def _run_precedents(*, idea: str, top_k: int) -> list[dict[str, Any]]:
    """Embed `idea` and retrieve top-K Gecko flywheel precedents."""
    from gecko_core.ingestion.embedder import embed
    from gecko_core.sessions.store import SessionStore

    vecs, _tokens = await embed([idea])
    if not vecs:
        return []
    store = SessionStore.from_env()
    rows = await store.retrieve_gecko_precedent(embedding=vecs[0], limit=top_k)
    return [r.model_dump(mode="json") for r in rows]


def _route_uses_local_fallback(api_url: str | None) -> bool:
    """True when the MCP should bypass the API and call gecko_core directly.

    Localhost / 127.0.0.1 / unset → local-dev mode (call core directly so a
    developer without a running gecko-api still gets answers). Anything else
    forwards through the API so production gets x402-paid routing.
    """
    if not api_url:
        return True
    lowered = api_url.lower()
    return "localhost" in lowered or "127.0.0.1" in lowered


async def _run_route(
    *,
    client: GeckoAPIClient,
    prompt: str,
    task_hint: str,
    max_cost_usd: float,
    prefer_premium: bool,
    tier_preset: str = "balanced",
) -> dict[str, Any]:
    """Forward to gecko-api `/route`, or call the core directly in local dev.

    S4-ROUTE-02: production MCP forwards to gecko-api so x402 payment goes
    through frames.ag wallet. Local dev (no GECKO_API_URL or pointed at
    localhost) falls back to a direct `gecko_core.routing.route` call so a
    developer can iterate without booting the whole API.

    Validates the task_hint against the matrix's enum so we surface a clean
    ValueError instead of an upstream KeyError or a network round-trip.
    """
    import os

    from gecko_core.routing.matrix import ROUTING_MATRIX

    if task_hint not in ROUTING_MATRIX:
        raise ValueError(f"task_hint must be one of {sorted(ROUTING_MATRIX)}; got {task_hint!r}")

    api_url = os.environ.get("GECKO_API_URL")
    if _route_uses_local_fallback(api_url):
        from gecko_core.routing import route

        result = await route(
            prompt,
            task_hint=task_hint,
            max_cost_usd=max_cost_usd,
            prefer_premium=prefer_premium,
        )
        return result.model_dump(mode="json")

    return await client.route(
        prompt,
        task_hint=task_hint,
        max_cost_usd=max_cost_usd,
        prefer_premium=prefer_premium,
        tier_preset=tier_preset,
    )


async def _run_scaffold(*, session_id: str, output_dir: str | None) -> dict[str, Any]:
    """Generate a 3-file scaffold bundle from a Pro tier session.

    Free path — bypasses GeckoAPIClient / x402 (the user already paid for
    the Pro debate). Lazy import keeps OpenAI / supabase out of the MCP
    startup path for users who never invoke this tool.
    """
    from pathlib import Path
    from uuid import UUID

    from gecko_core.orchestration.scaffold import (
        KillVerdictError,
        ScaffoldError,
        SessionNotFoundError,
        SessionNotReadyError,
        generate_scaffold,
    )

    out_dir = Path(output_dir) if output_dir else Path.cwd()
    try:
        result = await generate_scaffold(UUID(session_id), out_dir)
    except KillVerdictError as exc:
        return {"error": "kill_verdict", "message": str(exc)}
    except SessionNotFoundError as exc:
        return {"error": "session_not_found", "message": str(exc)}
    except SessionNotReadyError as exc:
        return {"error": "session_not_ready", "message": str(exc)}
    except ScaffoldError as exc:
        return {"error": "scaffold_failed", "message": str(exc)}

    return {
        "session_id": str(result.session_id),
        "paths": [str(p) for p in result.paths],
        "tokens_used": result.tokens_used,
        "summary": result.summary,
    }


def _run_available_sources() -> list[dict[str, Any]]:
    """Return the static source catalog as JSON-safe dicts."""
    from dataclasses import asdict

    from gecko_core.sources import available_sources

    return [asdict(e) for e in available_sources()]


async def serve() -> None:
    """Run the MCP server over stdio.

    Self-warming: brings up ClawRouter on demand if it isn't already
    reachable (and the user didn't override GECKO_LLM_ENDPOINT). The proxy
    is torn down when stdio closes.
    """
    async with warm_clawrouter(), stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())
