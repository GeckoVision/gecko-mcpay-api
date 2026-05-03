# Sprint 8 — Demo readiness: ingestion, config, live x402

**Status:** ready to fire
**Predecessors:** Sprint 7 shipped (`8d032d9`, `7c688fe`, `2c9f5ea`) + hotfixes (`53fdb1c` source quality, `3425b74` --yes flag).
**Driver:** dogfood + integration audit (`docs/audits/integration-audit-2026-04-30.md`) surfaced 18 findings. This sprint closes the **demo blockers**.

**Done = the 5-idea Gecko stress matrix runs end-to-end on devnet without manual env overrides, with seeded memory readable by `bb sprint-review`.**

---

## Tracks (priority order)

### Track A — Ingestion reliability (S8-INGEST-01..03) **CRITICAL**

The pipeline crashes on every URL despite Tavily extract + OpenAI embeddings working in isolation. Without this, no live demo is possible.

- **S8-INGEST-01** — Root-cause the `APIError` in pipeline glue. Likely candidates: chunker output shape mismatch, embedder return-shape mismatch, Supabase upsert schema drift. Add structured logging at each stage. Verified components: `extract_via_tavily()` returns `(text, was_cached)`, `embed([text])` returns valid embeddings.
- **S8-INGEST-02** — Graceful degradation when `validation_report` cites a URL that wasn't successfully ingested. Today it raises `OrchestrationError` and crashes the session. Should drop the citation and continue (logged warning).
- **S8-INGEST-03** — Cross-session embedding dedup. Migration: `chunks` table keyed on `(url_hash, chunk_index)` so re-running a similar idea reuses embeddings. Stops re-spending OpenAI on identical content.

**Owner:** data-engineer
**Acceptance:** all 5 dogfood ideas ingest cleanly, sources show in research output with non-zero chunk counts.

### Track B — Config plane unification (S8-CONFIG-01..02) **CRITICAL**

- **S8-CONFIG-01** — Unify `LLM_ROUTER` (router.py — Pro debate) and `GECKO_LLM_ENDPOINT`/`GECKO_LLM_API_KEY` (advisor panel) into a single resolution path. Both should respect `LLM_ROUTER=openrouter` and pull keys/URLs from one settings module. Backward-compat shim for 1 release.
- **S8-CONFIG-02** — `bb doctor` command. Resolves Supabase URL + service role + LLM router + x402 mode + wallet config. Prints a Rich table with ✅/❌ for each. Catches the journal write/read split (F7) by writing a test entry and reading it back.

**Owner:** software-engineer
**Acceptance:** running `bb research` and `bb plan` requires only `OPENAI_API_KEY` (or `OPENROUTER_API_KEY`) — no `GECKO_LLM_ENDPOINT` override.

### Track C — Live x402 CLI (S8-X402-01) **CRITICAL**

- **S8-X402-01** — Implement `LiveX402Client.charge()` in `packages/gecko-core/src/gecko_core/payments/x402_client.py`. Bridge to frames.ag for signing:
  1. Receive 402 challenge from API
  2. POST to frames.ag `/sign` endpoint with apiToken auth
  3. Submit signed Solana tx
  4. Wait for confirmation (with timeout)
  5. Return `tx_signature` for the caller to include in next request

Devnet first; mainnet flag-gated. Must handle: network mismatch (server says mainnet, wallet on devnet), insufficient balance, signing timeout.

**Owner:** web3-engineer
**Acceptance:** `X402_MODE=live bb research --idea "..."` completes end-to-end on devnet, `tx_signature` is real (not `stub_`-prefixed), reconcile via `bb economics --verify` confirms.

### Track D — Polish (S8-CATALOG-01, S8-REVIEW-01, S8-API-01, S8-CI-01)

- **S8-CATALOG-01** — Run `scripts/check_catalog_drift.py --write` to swap the 5 delisted models. PR review the substitutions before merge.
- **S8-REVIEW-01** — `bb sprint-review` auto-discovers recent projects when no `--project-id`. Falls back to "list of last 5 projects" or git-only mode with a clear notice.
- **S8-API-01** — HTTP routes for `/scaffold` and `/pulse` to match MCP surface. OpenAPI contract for `gecko-mcpay-app` becomes complete.
- **S8-CI-01** — Fix `/health` → `/healthz` in `scripts/e2e_smoke.py` so CI smoke can wait-for-ready properly.

**Owner:** software-engineer

### Track E — Reliability hardening (S8-AUDIT-01..09)

Audit-driven. Lower priority than A/B/C but essential before any production traffic:

- **S8-AUDIT-01** — Tenacity retry + 30s timeout on Tavily search; typed `TavilyRateLimitError` so workflow degrades gracefully.
- **S8-AUDIT-02** — Circuit breaker (pybreaker, 5-fail/60s) around Tavily.
- **S8-AUDIT-03** — Distinguish `discovery_score` (Tavily) vs `retrieval_sim` (pgvector cosine) in UI/CLI/docs. They aren't comparable.
- **S8-AUDIT-05** — AG2 explicit `timeout: 60` + OpenRouter `X-Request-ID` logging for triage.
- **S8-AUDIT-06** — twit.sh structured cap-hit log + reconcile wiring.
- **S8-AUDIT-08** — uuid4 request-id propagation across all external clients (Tavily, OpenAI, OpenRouter, twit.sh).
- **S8-AUDIT-09** — Per-category `time_range` defaults on Tavily (crypto = "month", devtools = "year").

**Owner:** staff-engineer (architecture) + software-engineer (impl)

### Track F — Logging hygiene (S8-LOG-01) **SECURITY**

- **S8-LOG-01** — `DEBUG` log level dumps Supabase JWT + apikey + Bearer tokens to stdout via `httpcore`/`hpack`. Add a logging filter that redacts `authorization`, `apikey`, and any header containing `key`/`token`/`secret`. Verify against `LOG_LEVEL=DEBUG bb research ...`.

**Owner:** software-engineer

---

## Out of scope for Sprint 8

- Mainnet cutover (still gated on funding decision)
- Live-V1 eval gate — should run AFTER S8-INGEST lands so sources actually populate
- V3 dashboard (cross-repo to `gecko-mcpay-app`)
- Landing v2 implementation

## Acceptance (sprint-level)

- [ ] All 5 dogfood ideas run `bb research → bb plan → bb sprint-review` end-to-end with NO env overrides
- [ ] `bb doctor` returns all green
- [ ] `X402_MODE=live bb research` completes on devnet with real `tx_signature`
- [ ] `bb sprint-review` shows non-zero `memory_entry_count` after a session
- [ ] No `APIError` or `OrchestrationError` crashes on the dogfood ideas
- [ ] No JWT/apikey leaks in `LOG_LEVEL=DEBUG` output
- [ ] All audit findings either landed or explicitly deferred with a Sprint 9 ticket

## Test plan

After each track lands, re-run the 5-idea Gecko stress matrix from `docs/test-plan.md`. The dogfood IS the regression suite for this sprint.

## Reference

- `docs/audits/integration-audit-2026-04-30.md` — full audit
- Dogfood session ids (Sprint 7 stress run): `448e2f63`, `6fcda700`, `98880e53`, `efe30afa`, `8142bba8`
- Drift detector commit: `f153c4c`
