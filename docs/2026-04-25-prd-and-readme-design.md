# Design Spec: PRD + README for Builder Bootstrap Platform
**Date:** 2026-04-25
**Author:** Ernani Britto
**Status:** Approved

---

## Scope

Two documents to produce:

1. `docs/PRD.md` — Product Requirements Document for the Builder Bootstrap Platform (Option A: standard linear PRD)
2. `README.md` — Full replacement using the existing Gecko README as a visual format template (badges, tables, mermaid, ASCII flow)

Option B (narrative style) is reserved for a separate Notion ideation + GTM document — not in scope here.

---

## PRD Structure (`docs/PRD.md`)

| Section | Content |
|---------|---------|
| Header | Title, version, date, author, status |
| Vision | One-sentence product definition |
| Problem | Builder research bottleneck — visceral, specific |
| User Personas | Technical Developer (V1 primary) + Non-Technical Founder (V2 primary) with goals and pain points |
| V1 — Hackathon | Requirements table: feature / description / acceptance criteria. Covers: CLI (`bb research`, `bb ask`, `bb sources`), Tavily source discovery, YouTube + Web adapters, ingestion pipeline (chunk → embed → store), Basic orchestration (GPT-4o-mini → JSON), Pro orchestration (AutoGen 5-agent GroupChat, 72h), x402 payment gate, Rich terminal output |
| V2 — Post-hackathon | Next.js web app, creator attribution graph, creator OAuth claim flow, creator earnings settlement |
| V3 — Marketplace | Creator marketplace, subscription Pro tier, public Knowledge API |
| Non-functional | Latency targets, per-session cost ceiling, data retention, security (no private keys, service-role server-only) |
| Success metrics | V1: hackathon placement + live sessions + demo quality; V2: MAU + creator claims; V3: marketplace GMV |
| Out of scope | Explicit — what is not being built |

---

## README Structure (`README.md`)

Mirrors the Gecko README format exactly:

| Section | Notes |
|---------|-------|
| Badges | Python 3.11, OpenAI, Supabase, x402/Solana |
| Bold tagline | One sentence |
| The problem | 20+ hour research wall; both builder types |
| The solution | Inversion table (Before / With Builder Bootstrap) |
| What this repo is | CLI + skill.yaml; what's not in scope |
| End-to-end flow | ASCII: describe → discover → approve → index → pay → generate → ask |
| Architecture | Mermaid flowchart: CLI → adapters/discovery → pipeline → DB/LLM → output |
| Stack table | Python, OpenAI, AutoGen, Supabase/pgvector, Tavily, x402, Click, Rich |
| Prerequisites | Python 3.11+, env vars |
| Quickstart | pip install, .env, `bb research` |
| Environment variables | Table of required + optional vars |
| Implementation status | V1 complete; V2/V3 roadmap items |
| Documentation map | Table: CLAUDE.md, product-story.md, PRD.md |
| Footer | Tagline line |

---

## Decisions

- PRD lives at `docs/PRD.md` (alongside `product-story.md`)
- README completely replaces the Gecko content — no Gecko references remain
- PRD uses requirements tables (feature / description / acceptance criteria) for V1; roadmap bullet lists for V2/V3
- Mermaid diagram in README follows the same `flowchart TB` style as the Gecko README
