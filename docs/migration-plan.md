# Migration plan: existing V1 code → workspace layout

Your V1 `bb` CLI ships today as a single Python package. This guide maps each existing area into the workspace layout.

## Order of operations (safe path, ~half a day)

1. **Carve `gecko_core`.** Move pure-logic modules first: ingestion, orchestration, rag, payments, sessions. Anything that reads CLI args or calls `rich.print` does NOT come along.
2. **Re-point the CLI.** `apps/cli` becomes a thin shim: parse args → `await gecko_core.research(...)` → render. Tests against the CLI still pass.
3. **Wire the MCP server.** `packages/gecko-mcp` imports `gecko_core` and exposes the three tools. `gecko-mcp doctor` works.
4. **Wire the API service** (V2 prep, optional for hackathon). `packages/gecko-api` imports `gecko_core` and exposes the same operations as HTTP endpoints. Useful for `gecko-web` later.
5. **Publish skills.** Push `skill.md` and the three SKILL.md files to the `gecko-skills` repo. Deploy to Vercel under `app.geckovision.tech`. Test the bootstrap flow on a clean machine.
6. **Demo dry-run.** End-to-end on the demo machine, in stub mode, with the demo idea.

## Where each existing area goes

| Existing V1 area | New home | Notes |
|---|---|---|
| Tavily source discovery | `packages/gecko-core/src/gecko_core/ingestion/discovery.py` | Pure: `idea -> list[URL]` |
| YouTube adapter | `packages/gecko-core/src/gecko_core/ingestion/youtube.py` | Pure: `URL -> str` |
| Web adapter | `packages/gecko-core/src/gecko_core/ingestion/web.py` | Same shape as YouTube |
| Chunker (512/50) | `packages/gecko-core/src/gecko_core/ingestion/chunker.py` | Pure: `str -> list[Chunk]` |
| Embedder | `packages/gecko-core/src/gecko_core/ingestion/embedder.py` | Batch up to 100 chunks/call |
| Ingestion orchestrator | `packages/gecko-core/src/gecko_core/ingestion/pipeline.py` | Orchestrates the four above |
| Supabase persistence | `packages/gecko-core/src/gecko_core/sessions/store.py` | Single `SessionStore` class |
| pgvector queries | `packages/gecko-core/src/gecko_core/rag/query.py` | `query(session_id, text, top_k)` |
| x402 client (stub + live) | `packages/gecko-core/src/gecko_core/payments/x402_client.py` | Protocol + impls per `web3-engineer.md` |
| Basic orchestration | `packages/gecko-core/src/gecko_core/orchestration/basic.py` | Returns `ResearchResult` |
| Pro orchestration | `packages/gecko-core/src/gecko_core/orchestration/pro.py` | Returns `ResearchResult` |
| `bb research` Click | `apps/cli/src/gecko_cli/main.py` | Already stubbed |
| `bb ask` Click | `apps/cli/src/gecko_cli/main.py` | Already stubbed |
| `bb sources` Click | `apps/cli/src/gecko_cli/main.py` | Already stubbed |
| Rich renderer | `apps/cli/src/gecko_cli/render.py` | Already stubbed |
| Supabase migrations | `infra/supabase/migrations/` | Number with UTC timestamps |

## What stays out of `gecko_core`

These never move into the SDK:

- `click` argument parsing — stays in `apps/cli`
- `rich.print` — stays in `apps/cli/render.py`
- MCP `Tool` and `Server` types — stays in `packages/gecko-mcp`
- FastAPI route definitions — stays in `packages/gecko-api`
- Anything Next.js — that's the `gecko-web` repo

If you find yourself importing `click`, `rich`, `mcp`, or `fastapi` from `gecko_core` — stop. The dependency arrow goes one way: transport → core, never back.

## Validation after migration

```bash
uv sync
uv run ruff check && uv run ruff format --check
uv run mypy packages/ apps/cli
uv run pytest

# end-to-end smoke (stub mode)
bb research --idea "hotel guide for Brazil"
```

If `bb research` produces all three documents end-to-end after the carve, the migration is correct.

## What the demo on Monday actually shows

Pick one — rehearse both:

**Flow A (CLI demo, safer):**
```bash
bb research --idea "hotel guide for Brazil"
# documents render
bb ask <session_id> "what's the strongest validation signal?"
```

**Flow B (Claude Code skill, frames-style):**
```
[in Claude Code]
Read https://app.geckovision.tech/skill.md and follow the instructions.
[Claude installs gecko-mcp, configures env in stub mode]
Use gecko_research to validate: a hotel guide for Brazil
[documents render in Claude Code]
```

Flow B is the frames-style story. Flow A is the safety net. **Demo Flow B if it's stable by Sunday night, fall back to A if it's not.**
