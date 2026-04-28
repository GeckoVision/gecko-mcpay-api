# gecko — Builder Bootstrap Platform (Python)

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![OpenAI](https://img.shields.io/badge/openai-gpt--4o--mini-412991.svg)](https://openai.com/)
[![Supabase](https://img.shields.io/badge/supabase-pgvector-3ECF8E.svg)](https://supabase.com/)
[![x402](https://img.shields.io/badge/x402-Solana-9945FF.svg)](https://x402.org/)

**Turn a plain-language startup idea into a knowledge base, business plan, validation report, and PRD — in under 30 minutes.**

This is the Python backend. The web frontend lives at [`gecko-web`](https://github.com/<owner>/gecko-web). The public skill registry lives at [`gecko-skills`](https://github.com/<owner>/gecko-skills) and is served at `app.geckovision.tech/skill.md`.

---

## What's in this repo

A `uv` workspace with four packages:

| Package | Purpose |
|---|---|
| `packages/gecko-core` | The SDK. Pure business logic. Everything else imports this. |
| `packages/gecko-mcp` | MCP server. The frames-style surface for Claude Code. |
| `packages/gecko-api` | FastAPI service. What the web app calls. |
| `apps/cli` | The `bb` / `gecko` command-line tool. |

## Stack

| Layer | Tool |
|---|---|
| Language | Python 3.11+ |
| Workspace | `uv` (workspaces) |
| LLM | OpenAI `gpt-4o-mini`, embedding `text-embedding-3-small` |
| Pro orchestration | AutoGen GroupChat (5 agents) |
| Database | Supabase Postgres + pgvector |
| Source discovery | Tavily |
| Payments | x402 on Solana — modes: `stub`, `live`, `frames` |
| CLI | Click + Rich |
| MCP | `mcp` package |
| API | FastAPI |

## Quickstart

```bash
git clone https://github.com/<owner>/gecko.git
cd gecko
uv sync                                      # installs all 4 packages
cp .env.example .env                         # fill in keys
uv run bb research --idea "hotel guide for Brazil"
```

Run the API service:

```bash
uv run gecko-api
# OpenAPI docs at http://localhost:8000/docs
```

Run the MCP server (for Claude Code via skills):

```bash
uv run gecko-mcp doctor                      # verify env
uv run gecko-mcp serve                       # start over stdio
```

## Projects (per-project budgets)

Group runs into named, budgeted envelopes. v1 ships a logical budget bucket: payments still flow from your frames.ag main wallet, but each project tracks its own spend with a client-side budget pre-flight before the paid call. `gecko project init <name> --budget 5.00` creates the project (server-side row + `.gecko/project.json` in your cwd); `gecko project list / show / budget / policy` round out the surface. `bb research` auto-attaches the cwd's project; pass `--project <uuid|name>` to override. v2 (post-Shipathon) replaces the wallet plumbing with per-project Privy wallets — the CLI surface stays the same. See `docs/phase-b5-v1-shipped.md`.

## Skill-based onboarding (for Claude Code users)

```
Read https://app.geckovision.tech/skill.md and follow the instructions.
```

That installs the MCP server, configures env, and registers the skills. The skill file lives in the `gecko-skills` repo.

## Environment variables

| Variable | Required | Default | Notes |
|---|---|---|---|
| `OPENAI_API_KEY` | yes | — | |
| `SUPABASE_URL` | yes | — | |
| `SUPABASE_SERVICE_ROLE_KEY` | yes | — | server-only; never expose to web |
| `TAVILY_API_KEY` | yes | — | |
| `X402_MODE` | no | `stub` | `stub` for dev, `live` for direct x402, `frames` for frames.ag |
| `X402_FACILITATOR_URL` | only if `X402_MODE=live` | — | |
| `FRAMES_API_KEY` | only if `X402_MODE=frames` | — | |
| `GECKO_DEFAULT_TIER` | no | `basic` | `basic` or `pro` |

## Implementation status

- ✅ V1 — CLI, MCP server, ingestion pipeline, basic + pro orchestration, x402 stub
- ⏳ V2 — `gecko-web` Next.js app, creator attribution graph, frames.ag integration
- 🔜 V3 — Creator marketplace, subscription Pro tier, public Knowledge API

## Documentation map

| File | Audience |
|---|---|
| `CLAUDE.md` | Claude Code working in this repo |
| `docs/PRD.md` | Product requirements (V1 / V2 / V3 scope) |
| `docs/product-story.md` | Why this product exists — the Gecko → Builder Bootstrap pivot |
| `docs/migration-plan.md` | How existing V1 code maps into the workspace |

## Sister repos

- [`gecko-web`](https://github.com/<owner>/gecko-web) — Next.js frontend, deploys to Vercel at `app.geckovision.tech`
- [`gecko-skills`](https://github.com/<owner>/gecko-skills) — public skill registry, served at `app.geckovision.tech/skill.md`

---

*Builder Bootstrap Platform · geckovision.tech*
