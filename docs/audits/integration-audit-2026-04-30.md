# Pre-Sprint-8 Integration Audit — 2026-04-30

Synthesized from staff-engineer audit + live dogfood of "Gecko: pay-per-use AI co-founder MCP for Claude Code, x402+USDC on Solana".

## Verdicts

| Integration | Demo-ready? | One-liner |
|---|---|---|
| Tavily search (discovery) | YES with caveats | Single shot, advanced depth, category-aware query, but no retry/circuit breaker. |
| Tavily extract (fallback) | YES | Verified live: returns `(text, was_cached)` tuple correctly. 7-day Supabase cache. |
| **Ingestion pipeline glue** | **NO** | **Hard crash — `APIError` on every ingested URL despite components working in isolation.** |
| **Validation_report URL check** | **NO** | **Hard crash when agent cites a URL that failed ingestion.** |
| twit.sh | YES (gated) | Crypto-only, $0.05 cap, 6h cache, x402 self-pay; correctly silent when unconfigured. |
| OpenAI embeddings | YES | Verified live. Module semaphore + 4-attempt RateLimit retry. |
| OpenRouter / OpenAI chat | NEEDS-WATCH | No explicit retry/timeout on AG2 path; relies on AG2 defaults. |
| Pro-debate agent tools | YES (no tools) | Agents consume pre-fetched RAG only. Predictable cost. No agent function-calling. |
| Helius (Solana) | N/A | No core code path — out of scope for this repo. |
| **Memory journal write/read parity** | **NO** | **CLI writes and MCP reads may target different Supabase environments.** |
| **`LiveX402Client.charge()`** | **NO** | **Raises NotImplementedError. Live CLI path can't sign.** |
| Config plane | NO | `LLM_ROUTER` (router.py) ignored by advisor (uses `GECKO_LLM_ENDPOINT`). |

## Critical findings (block live demo)

### F11: Ingestion pipeline crashes on ingest, despite components working
Live dogfood: Tavily returned 6 perfect URLs for the Gecko pitch:
```
solanacompass.com/skills/x402-payments
x402.org/ecosystem
solana.com/.../intro-to-x402
news.bitcoin.com/mcp-in-2026-...
mcp.so/explore
allium.so/blog/x402-explained-...
```
Every ingestion attempt failed: `APIError`. Isolated tests confirm:
- `extract_via_tavily('https://x402.org/ecosystem')` → returns valid `(text, False)` tuple
- `embed(['test'])` → returns valid embeddings
The bug is in **pipeline glue** between extract and persist. Likely candidates: chunker output shape mismatch, embedder return-shape mismatch, Supabase upsert schema drift.

### F12: Hard crash when validation_report references unknown URL
```
OrchestrationError: citation in validation_report references unknown URL:
https://allium.so/blog/x402-explained-...
```
Even when ingestion fails on N URLs, the agent generates citations referencing those URLs. The orchestrator then crashes the entire research session. **No graceful degradation.**

### F4: Config plane split (LLM_ROUTER vs GECKO_LLM_ENDPOINT)
Advisor panel uses `GECKO_LLM_ENDPOINT` (defaults to clawrouter `localhost:8402/v1`). It IGNORES `LLM_ROUTER=openrouter`. Required workaround:
```
GECKO_LLM_ENDPOINT="https://openrouter.ai/api/v1" \
GECKO_LLM_API_KEY="$OPENROUTER_API_KEY" \
bb plan ...
```

### F7: Memory journal write/read split
`bb plan` writes via `MemoryStore.from_env()` in CLI process. `gecko_memory_search` MCP tool reads from a (possibly different) Supabase. Returns empty even after journal hooks fire without warnings.

### F8: LiveX402Client.charge() not implemented
```
NotImplementedError: live mode wiring is post-demo: configure
X402_FACILITATOR_URL and X402_WALLET_SECRET, then implement
on-chain settlement here.
```
Blocks all live CLI calls. The API path (HTTP 402 challenge) is fine — only the CLI client is unimplemented.

## Important (degrades UX)

### F3: 5 truly-delisted models in catalog
`scripts/check_catalog_drift.py` confirms:
- deepseek/deepseek-v4-flash-max
- qwen/qwen3.5-plus
- poolside/poolside-laguna-m1
- nvidia/nemotron-3-super
- nvidia/nemotron-3-nano-omni

### F5: bb sprint-review needs --project-id
Without flag, queries no scope → always shows `memory_entry_count: 0`.

### F9: /scaffold and /pulse are MCP-only
Confirmed via `/openapi.json`. OpenAPI contract for `gecko-mcpay-app` is incomplete vs MCP surface.

### F10: /healthz vs /health smoke mismatch
Sprint 7 Track B's CI smoke calls `/health` but route is `/healthz`. CI would fail wait-for-ready.

## Audit recommendations

| Ticket | Description |
|---|---|
| S8-INGEST-01 | Root-cause `APIError` in pipeline glue; isolate chunker/embedder/upsert |
| S8-INGEST-02 | Graceful degradation when validation_report cites failed-ingest URLs |
| S8-INGEST-03 | Cross-session embedding dedup (sha256(url)+chunk_index) — stop re-embedding |
| S8-CONFIG-01 | Unify `LLM_ROUTER` and `GECKO_LLM_ENDPOINT` into single config plane |
| S8-CONFIG-02 | Single Supabase resolution path; add `bb doctor` to verify CLI/MCP parity |
| S8-X402-01 | Implement `LiveX402Client.charge()` via frames.ag bridge |
| S8-CATALOG-01 | Swap 5 delisted models via drift detector `--write` |
| S8-REVIEW-01 | `bb sprint-review` auto-discovers projects when no `--project-id` |
| S8-API-01 | HTTP routes for /scaffold and /pulse to match MCP surface |
| S8-CI-01 | Fix /health → /healthz in e2e smoke |
| S8-AUDIT-01 | Tenacity retry + 30s timeout on Tavily search; typed `TavilyRateLimitError` |
| S8-AUDIT-02 | Circuit breaker around Tavily (5-fail / 60s window) |
| S8-AUDIT-03 | Distinguish `discovery_score` vs `retrieval_sim` in UI/logs |
| S8-AUDIT-05 | AG2 explicit `timeout: 60` + OpenRouter X-Request-ID logging |
| S8-AUDIT-06 | twit.sh structured cap-hit log + reconcile wiring |
| S8-AUDIT-08 | uuid4 request-id propagation across all external clients |
| S8-AUDIT-09 | Per-category `time_range` defaults (crypto = "month") |
| S8-LOG-01 | **Logging hygiene**: DEBUG mode dumps Supabase JWT + apikey to stdout |

## Files referenced

- packages/gecko-core/src/gecko_core/ingestion/{discovery,web,embedder,chunker,pipeline}.py
- packages/gecko-core/src/gecko_core/sources/{twit_sh,dispatcher,_catalog}.py
- packages/gecko-core/src/gecko_core/orchestration/pro/{__init__,agents,router}.py
- packages/gecko-core/src/gecko_core/payments/x402_client.py
- packages/gecko-core/src/gecko_core/memory/auto_journal.py
