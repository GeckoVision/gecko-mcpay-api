"""Gecko MCP server.

Exposes three tools:
    gecko_research — full discover → index → pay → generate workflow
    gecko_ask      — follow-up question against a session
    gecko_sources  — list indexed sources for a session

Thin transport layer. All logic lives in `gecko_core`.
"""

from __future__ import annotations

import json

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

import gecko_core

server: Server = Server("gecko-mcp")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="gecko_research",
            description=(
                "Run the full Builder Bootstrap workflow for a startup idea. "
                "Discovers sources, indexes them into a knowledge base, runs the "
                "payment gate (stub mode by default), and generates a business plan, "
                "validation report, and PRD with citations."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "idea": {"type": "string", "description": "Plain-language startup idea."},
                    "tier": {"type": "string", "enum": ["basic", "pro"], "default": "basic"},
                    "urls": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional seed URLs. Auto-discovered via Tavily if omitted.",
                    },
                },
                "required": ["idea"],
            },
        ),
        Tool(
            name="gecko_ask",
            description="Ask a follow-up question grounded in an existing session's knowledge base.",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string"},
                    "question": {"type": "string"},
                },
                "required": ["session_id", "question"],
            },
        ),
        Tool(
            name="gecko_sources",
            description="List all indexed sources for a session (URL, type, chunk count, indexed timestamp).",
            inputSchema={
                "type": "object",
                "properties": {"session_id": {"type": "string"}},
                "required": ["session_id"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    match name:
        case "gecko_research":
            result = await gecko_core.research(
                idea=arguments["idea"],
                tier=arguments.get("tier", "basic"),
                urls=arguments.get("urls"),
            )
            return [TextContent(type="text", text=result.model_dump_json(indent=2))]

        case "gecko_ask":
            result = await gecko_core.ask(
                session_id=arguments["session_id"],
                question=arguments["question"],
            )
            return [TextContent(type="text", text=result.model_dump_json(indent=2))]

        case "gecko_sources":
            sources_list = await gecko_core.sources(session_id=arguments["session_id"])
            payload = [s.model_dump(mode="json") for s in sources_list]
            return [TextContent(type="text", text=json.dumps(payload, indent=2))]

        case _:
            raise ValueError(f"unknown tool: {name}")


async def serve() -> None:
    """Run the MCP server over stdio."""
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())
