# Sprint 16 — Bazaar buyer + chunking reliability

**Status:** ready to fire (after Sprint 15 lands the registry seam)
**Predecessor:** Sprint 15 (ContributorRegistry + identity ledger + profile-aware RAG, dormant)
**Driver:**
- User-flagged ingestion flakiness on Supabase chunk writes (multiple 2026-04-30 live runs)
- Bazaar buyer thesis: "we sell to agents AND we should buy from the agentic economy from day 1" — TripAdvisor / arxiv as canonical examples
- CLAUDE.md Pattern B (no stubbed-but-shipped wire integrations) + Pattern C (recorded-fixture contract tests)

**Done = (1) chunk write failures bounded by structured retry + observability; zero silent drops on holdout-live re-run. (2) Gecko consumes at least one CDP-Bazaar-discovered x402 endpoint as a `SourceProvider`, with TripAdvisor as the proving case and arxiv as a non-paid control. Stub mode `bb research` byte-identical to pre-S16.**

---

## Why this sprint, why now

Two coupled pressures converge:

1. **Ingestion is the foundation under everything S15 built.** Profile-typed RAG (S15-AIML-01) is meaningless if chunks intermittently fail to land. The reliability gap surfaced in 2026-04-30 live runs (`tests/eval/live_runs/2026-04-30-*.json`) blocks the dogfood loop.
2. **Bazaar-buyer is the cleanest dogfood proof.** We list on `/.well-known/x402` (S12). We have an X402Client Protocol (S13-PAY-01) and a SourceProvider seam (S12 Track F). The missing piece is the **discovery + outbound-buyer** path. Shipping it unlocks bot-paywalled corpora (TripAdvisor for travel/hospitality) AND demonstrates the agentic-economy thesis is something we live, not just sell.

Both are blocking. Both compose: a flaky chunker corrupts a Bazaar-purchased corpus the same way it corrupts a Tavily corpus, and we don't want to debug both at once. **Land Track A before Track B's live smoke.**

---

## Architecture — where Bazaar-buyer fits

**Two new abstractions, one composition, no new top-level package.**

```
gecko_core/
  payments/
    x402_client.py         (existing — outbound charge() + inbound verify())
    bazaar_discovery.py    (NEW — read-only discovery client; no signing)
  sources/
    __init__.py            (existing dispatcher)
    bazaar/                (NEW)
      __init__.py
      provider.py          (BazaarSourceProvider — composes Discovery + X402Consumer)
      catalog.py           (cached resource list with TTL)
```

**Why two abstractions, not one:**
- `BazaarDiscoveryClient` is read-only HTTP against `api.cdp.coinbase.com/v2/x402/discovery/*`. Pure browse + search. **No payment surface.**
- Outbound payment: software-eng memo (`docs/strategy/2026-05-01-bazaar-consumer-design.md`) recommends a separate `X402Consumer` Protocol rather than extending `X402Client` (seller-side, inverse vocabulary). Adopt that recommendation: buyer/seller fail independently.
- `BazaarSourceProvider` is the composition. It conforms to the existing `Source` Protocol (`gecko_core/sources/__init__.py`) so the dispatcher doesn't change.

**Boundary defense:**
- `bazaar_discovery.py` MUST NOT import `Source` or anything in `gecko_core.sources`. Discovery is a payments-adjacent primitive; sources consume it.
- `BazaarSourceProvider` MUST NOT import `httpx` directly for payment. All settle goes through the `X402Consumer` resolver.
- TripAdvisor-specific knobs (auth headers, response shape) live in `sources/bazaar/adapters/tripadvisor.py`. Adapters are pluggable per resource type. This is the **arxiv extension point**: arxiv ships as a non-paid adapter under the same `BazaarSourceProvider` umbrella, once we prove the paid path works.

**Mode plumbing:** introduce `X402_CONSUMER_MODE` separate from `X402_MODE` (per software-eng memo). Buyer/seller decoupled.

**Reversibility:**
- `BazaarDiscoveryClient` Protocol shape: **one-way** (it's a public seam other providers will compose against). Get it right; mirror the `X402Client` Protocol style.
- `X402Consumer` Protocol shape: **one-way**.
- `BazaarSourceProvider` internals: **two-way**.
- TripAdvisor adapter: **two-way**, but the cost-cap and SSRF defenses are one-way (security non-negotiable per CLAUDE.md).

---

## Chunking triage (Track A scope-setter)

**Symptom:** 2026-04-30 live runs show partial chunk writes. Some sessions complete with `chunks_written < expected`. No exception surfaces to the orchestrator.

**Confirmed root causes (from data-eng memo `docs/diagnostics/2026-05-01-chunk-write-failures.md`):**

1. **Partial-batch writes in `store.py:611-622`** — `insert_chunks` chunks at 500 rows with no transaction; mid-batch failure leaves orphan chunks while the source is marked `failed` and `chunk_count` stays 0. Tests don't exercise this (FakeStore at `tests/ingestion/test_pipeline.py:32-39` always succeeds — Pattern C from CLAUDE.md).
2. **Cache-hit dim drift** — `store.py:827-869` returns cached vectors without validating `len == 1536`. `chunk_embedding_cache` has no `embed_model` column (migration 20260430052216) — model change silently poisons the cache, trips Postgres `vector(1536)` mismatch on insert.
3. **RateLimit retry cliff** — `embedder.py:36-100` has 4 fixed backoffs, no jitter, no batch-shedding, synchronized across `MAX_CONCURRENT_SOURCES=5` × `_EMBED_CONCURRENCY=8`. Thundering herd, then hard fail.

**Schema gaps:** no `CHECK (length(text) > 0)` on `chunks.text`; pipeline never populates `captured_at` or `project_id` (relies on default and ignores the latter entirely); `chunk_embedding_cache` has no model fingerprint.

**Track A's first move is observability before fix.** Add `chunks_write_audit` table + structured logging classified at write time. Then fix the highest-frequency failure mode.

---

## Tracks

### Track A — Chunking reliability **CRITICAL — must ship**

- **S16-INGEST-01 — `chunks_write_audit` table + structured logging.**
  - New `chunks_write_audit` row per `_process_one` exit: `{session_id, source_id, batch_size, succeeded, failed, error_kind, embed_model, captured_at}`.
  - `error_kind` ∈ `{toast_limit, pool_timeout, rls_denied, embedding_null, dim_mismatch, supabase_5xx, partial_batch, unknown}` — classified at write time, not post-hoc.
  - structlog kwargs on existing log calls in `store.py` + `embedder.py` + `pipeline._process_one`.
  - Surface in `bb doctor --recent` as a 7-day rollup.
  **Owner:** data-engineer + software-engineer
  **Acceptance:** re-run of `tests/eval/live_runs/2026-04-30-*.json` produces a classification rollup with zero `unknown` rows.

- **S16-INGEST-02 — Transactional `insert_chunks` + cache dim-validate + `text` length CHECK.**
  - Wrap batched inserts in a single transaction with `ON CONFLICT (session_id, source_id, chunk_idx) DO NOTHING` for idempotency.
  - Validate cache hit `len(embedding) == 1536` before returning; on mismatch, evict and re-embed.
  - Add `CHECK (length(text) > 0)` constraint to `chunks.text`.
  - On `toast_limit` or `supabase_5xx`: retry with batch_size//2, twice, then surface.
  **Owner:** data-engineer
  **Acceptance:** synthetic fault-injection fixture (TOAST-sized payload, mocked 503, exhausted pool) succeeds on retry path; no duplicate rows; no null embeddings; cache-poison fixture self-heals.

- **S16-INGEST-03 — Embed retry jitter, batch shedding, `embed_model` column on cache PK.**
  - Migration: add `embed_model` column to `chunk_embedding_cache`; PK becomes `(text_hash, embed_model)`. Backfill with current model.
  - Replace fixed backoffs with full-jitter exponential; on persistent 429, halve `_EMBED_CONCURRENCY` per source (batch shedding).
  - Cap retries at 5; surface as `error_kind=embedding_null` to S16-INGEST-01 audit on exhaustion.
  **Owner:** data-engineer
  **Acceptance:** synthetic 429-storm fixture recovers without thundering herd; cache-with-model-change fixture re-embeds correctly.

- **S16-INGEST-SMOKE-01 — Re-fire 5-idea matrix on holdout-live.**
  - Re-run `tests/eval/live_runs/2026-04-30-*.json` ideas under stub + live; assert zero `chunks_written < expected`.
  - Land as the sprint-acceptance gate before Track B's live smoke fires.
  **Owner:** staff-engineer (one-shot dogfood)
  **Acceptance:** matrix completes; no `unknown` error_kinds; chunks-written delta vs pre-S16 captured in retro.

### Track B — Bazaar buyer + `BazaarSourceProvider` **CRITICAL — must ship MVP**

> **Reframe (2026-05-01, founder note):** Track B is **catalog-led**, not vendor-led.
> Gecko queries the *whole* Bazaar catalog at ingestion time (`agentic.market/v1/services/search?q=<idea>`) and pulls **whatever fits** — TripAdvisor for hotels, market-data services for finance ideas, scientific corpora for research ideas, etc. There is **one generic adapter** that consumes the discovered service contract; vendor-specific shims exist only when a response shape demands it. TripAdvisor is the **first proving smoke**, not a special architectural case.
>
> Reference: `docs/research/agentic-market-skill-2026-05-01.md` — engineers must read before touching this track.

- **S16-BAZAAR-DISCOVERY-01 — `BazaarDiscoveryClient` Protocol + dual backend (agentic.market primary, CDP fallback).**
  - Add `packages/gecko-core/src/gecko_core/payments/bazaar_discovery.py`.
  - Protocol: `name`, `mode: Literal["stub", "live"]`, `async list_resources(network=None, asset=None, max_usd_price=None, limit=20) -> list[BazaarResource]`, `async search(query, network=None, asset=None, max_usd_price=None) -> list[BazaarResource]`.
  - `BazaarResource` dataclass: `resource_url, resource_type, x402_version, accepts: list[PaymentRequirements], last_updated, metadata: dict, source_directory: Literal["agentic.market", "cdp"]`.
  - **Primary backend:** `GET https://agentic.market/v1/services` and `/v1/services/search?q={query}` (richer metadata, human-readable search, no auth).
  - **Fallback backend:** `api.cdp.coinbase.com/v2/x402/discovery/resources` + `/search` (CDP-native, cross-check).
  - Both read-only. Cache 5-minute TTL per (query, filters) tuple. On agentic.market 5xx/timeout, fall back to CDP.
  - **No `Source` import. No outbound payment. Discovery only.**
  **Owner:** web3-engineer + software-engineer
  **Acceptance:** unit test against recorded agentic.market + CDP discovery fixtures each return ≥3 resources; cache hit < 10ms; fallback path tested with mocked agentic.market 503.

- **S16-BAZAAR-CONSUMER-01 — `X402Consumer` Protocol (outbound buyer path).**
  - New file: `packages/gecko-core/src/gecko_core/payments/x402_consumer.py`.
  - Protocol: `name`, `mode: Literal["stub", "live", "cdp"]`, `async pay(requirements: PaymentRequirements, *, max_usd: Decimal) -> PaymentReceipt`.
  - `requirements` is the resource's `accepts[i]` from discovery; `max_usd` enforces caller-side cap (defense against advertised price drift).
  - Implementations: `StubX402Consumer.pay()` returns success with synthetic tx; `CDPX402Consumer.pay()` settles via CDP facilitator on Base; `FramesX402Consumer.pay()` settles via frames.ag on Solana.
  - Driven by `X402_CONSUMER_MODE` (separate from seller-side `X402_MODE`).
  **Owner:** web3-engineer
  **Acceptance:** stub-mode `pay()` returns synthetic receipt; CDP and frames clients have a recorded-fixture test (Pattern C) before any live smoke.

- **S16-BAZAAR-CONSUMER-02 — Daily + per-session spend caps for outbound payments.**
  - New env: `GECKO_BAZAAR_DAILY_USD_CAP` (default $5), `GECKO_BAZAAR_SESSION_USD_CAP` (default $0.50).
  - Cap enforcement at `BazaarSourceProvider.fetch()` level — refuse + degrade if exceeded.
  - Aggregate across sessions via the same ledger pattern as S14-TWITSH-05.
  - **Hard requirement** before live smoke fires. No "we'll add caps later."
  **Owner:** web3-engineer + software-engineer
  **Acceptance:** synthetic load past daily cap surfaces breaker in `degraded_sources`; pipeline continues without the Bazaar source; UTC reset works.

- **S16-BAZAAR-CONSUMER-03 — `BazaarSourceProvider` (catalog-led composition).**
  - `packages/gecko-core/src/gecko_core/sources/bazaar/provider.py`.
  - Conforms to `Source` Protocol. `applies_to(categories)` → **always True** (the catalog is universal; relevance is decided per-query at fetch time).
  - `fetch(idea, categories)`:
    1. Build search query from `idea` + `categories` (e.g. "Lisbon hotel digital nomads" + ["travel", "hospitality"]).
    2. `BazaarDiscoveryClient.search(query=…, max_usd_price=GECKO_BAZAAR_SESSION_USD_CAP)` → ranked list of candidate services from the **full catalog**.
    3. Apply rank + budget filter; pick top-K (V1: K=1, S17: K≤3 fan-out).
    4. For each pick: route through **GenericBazaarAdapter** (default) or a registered shim if the resource_type matches a known shape; settle x402 via `X402Consumer.pay()`; map response → chunks.
    5. Return `SourceResult` with `cost_usd`, `provider_kind="bazaar:<resource_type>"`, source-directory provenance.
  - **GenericBazaarAdapter** lives in `sources/bazaar/adapters/generic.py`. It expects the listed service to return JSON or text; normalizes via heuristics (top-level array → per-item chunk; top-level text → split into chunks). Vendor shims under `adapters/<name>.py` override only when the heuristic fails.
  - **SSRF defense:** discovered URLs validated against private IP ranges, file://, etc. (CLAUDE.md security non-negotiable).
  **Owner:** software-engineer
  **Acceptance:** stub-mode `bb research --idea "Lisbon hotel for digital nomads"` picks a hospitality service from the recorded catalog and produces ≥3 chunks via GenericBazaarAdapter; payment stubbed; SSRF unit test passes; second test on a finance idea picks a different (market-data) service with no code change.

- **S16-BAZAAR-CONSUMER-04 — Recorded-fixture contract test (Pattern C gate).** **GATE — blocks all other tickets in Track B from merging until green.**
  - VCR cassettes for: CDP discovery `/resources` + `/search`; one $0.01-class real x402 endpoint's `/verify` and `/settle` (record once on a smoke run, replay forever).
  - Test mirrors `tests/payments/test_cdp_live_verify.py` shape; runs on the `live_bazaar` marker.
  - Asserts: discovery returns parseable schema, `pay()` settles, receipt's `tx_hash` is on-chain.
  **Owner:** web3-engineer + ai-ml-engineer (eval policy)
  **Acceptance:** recorded cassette committed; CI runs in replay mode by default; `GECKO_BAZAAR_LIVE=1` toggles live record. CI-fail without the cassette.

- **S16-BAZAAR-TRIP-01 — TripAdvisor smoke (proves the generic path, not a vendor architecture).**
  - **No bespoke adapter unless `GenericBazaarAdapter` provably can't normalize TripAdvisor's response.** First attempt: stub fixture → generic adapter → chunks. Only if response shape defeats the heuristic do we land a `tripadvisor.py` shim — and the shim is one normalization function, not a class hierarchy.
  - Per-call cost cap: $0.10 (defensive against advertised price drift).
  - `provider_kind="bazaar:<resource_type>"` populated from discovery metadata; no hard-coded `bazaar:tripadvisor` string in code unless a shim exists.
  **Owner:** software-engineer
  **Acceptance:** stub-mode "Lisbon hotel" run lands a TripAdvisor citation via the generic path OR via a ≤30-line shim if the heuristic fails; live-mode smoke (~$0.05) produces a real citation in a real research run.

- **S16-BAZAAR-ARXIV-01 — arxiv as a non-paid `BazaarSourceProvider` adapter (model citizen).** **NICE-TO-HAVE — slipstream if Track A finishes early.**
  - Existing arxiv ingestion gets reframed under the BazaarSourceProvider umbrella with `accepts=[]` (free).
  - Validates the adapter shape generalizes to non-paid resources.
  - **No live cost.** Pure refactor.
  **Owner:** software-engineer
  **Acceptance:** existing arxiv-cited research runs byte-identical post-refactor; new adapter registered; `bb sources --catalog` shows arxiv under `bazaar` provider family.

### Track C — Observability + dogfood **MED**

- **S16-OBS-01 — `bb doctor` Bazaar row.**
  - New row: Bazaar discovery reachability, last-known-good search latency, daily spend / cap remaining, current session spend / cap remaining.
  - Mirrors Paragraph row from S14-PARA-03.
  **Owner:** software-engineer
  **Acceptance:** green/yellow/red on Bazaar; matches actual discovery reachability.

- **S16-DOGFOOD-01 — Bazaar-buyer dogfood across 5 unrelated verticals.**
  - Re-fire `bb research` on 5 ideas spanning **deliberately different categories** (travel, finance/market-data, science/research, local-services, e-commerce) under live mode.
  - **Goal:** prove the catalog-led path picks a *different* service per idea with **zero code changes between runs**. If we have to add a shim mid-dogfood, that's a finding to flag for S17.
  - Compare verdict quality + citation count against pre-S16 baseline (which couldn't reach any bot-paywalled corpus).
  - Capture in `docs/sprint-reviews/<date>-s16-retro.md`.
  **Owner:** staff-engineer (one-shot)
  **Acceptance:** retro doc lands; per-idea cost ≤ $0.30; ≥1 Bazaar-sourced citation per idea; ≥4 of 5 ideas served by the GenericBazaarAdapter without a shim.

---

## Out of scope (S16 explicitly defers)

- **Per-creator attribution on Bazaar resources.** TripAdvisor doesn't expose individual reviewer wallets. Defer to S17.
- **arxiv-paid (live x402) adapter.** S17 — once arxiv-free path proves the abstraction.
- **Subscription-style Bazaar resources.** All V1 buys are per-call.
- **Bazaar resource quality scoring.** Discovery's CDP-side "composite score" is sufficient for V1.
- **Multi-resource fan-out per fetch.** V1 buys at most one Bazaar resource per session per category.
- **Founder-owned Bazaar buyer wallets.** All buys go through Gecko's treasury for V1.

---

## Acceptance (sprint-level)

- [ ] Track A: chunk-write failure rollup shows zero `unknown` error kinds; 5-idea live matrix re-runs with no partial-chunk sessions
- [ ] Track B GATE: `S16-BAZAAR-CONSUMER-04` recorded-fixture contract test green before any other Track B ticket merges
- [ ] `BazaarDiscoveryClient` ships; CDP backend cached + read-only; no payment surface
- [ ] `X402Consumer` Protocol ships; all 3 conformers (Stub/Frames/CDP) implement; recorded-fixture tests pass
- [ ] Daily + per-session outbound spend caps enforced before any live smoke
- [ ] `BazaarSourceProvider` lands; conforms to existing `Source` Protocol; SSRF defense in place
- [ ] TripAdvisor adapter produces ≥1 citation in a travel-vertical research run (live)
- [ ] `bb doctor` Bazaar row exists; reflects real reachability + spend
- [ ] Stub-mode `bb research` byte-identical to pre-S16 (smoke regression)
- [ ] No regression on holdout-live ≥ 0.80
- [ ] S16 retro published; Bazaar-dogfood vs pre-S16 baseline captured

---

## Risks (Pattern B/C focused)

**#1 risk — stubbed Bazaar buyer that "works on /verify" but breaks on real outbound payment.** This is exactly Sprint 12 Track A redux. Outbound payment is a *different* code path from inbound charge — verify is a signature check that doesn't exercise dispatch.

**Gate (already ticketed):** `S16-BAZAAR-CONSUMER-04` recorded-fixture contract test must pass against (a) CDP discovery, AND (b) a real $0.01-class x402 endpoint's verify+settle, before TripAdvisor live smoke fires. No live ingestion code lands without a recorded VCR cassette.

**#2 risk — chunking fixes mask the real issue.** If we add retry without classification, we hide the root cause. **Mitigation:** S16-INGEST-01 ships *before* S16-INGEST-02/03.

**#3 risk — TripAdvisor's x402 pricing drifts mid-sprint.** **Mitigation:** `max_usd` cap on every `pay()` call.

**#4 risk — SSRF via discovered URLs.** Bazaar resources are user-controlled URLs from CDP's discovery index. Treat as untrusted. **Mitigation:** existing SSRF defense in source-fetch path applies; explicit unit test in S16-BAZAAR-CONSUMER-03 acceptance.

---

## Cross-lane handoffs

| Lane | Owns |
|---|---|
| **staff-engineer (this doc)** | Architecture decisions, Track A vs B sequencing, sprint acceptance gate, dogfood retro |
| **data-engineer** | Track A in full (INGEST-01/02/03); pool/embedding race analysis |
| **software-engineer** | `BazaarSourceProvider`, TripAdvisor adapter, arxiv refactor, doctor row, CLI surfaces |
| **web3-engineer** | `BazaarDiscoveryClient` CDP backend, `X402Consumer` Protocol, spend caps, recorded-fixture contract test (the gate) |
| **ai-ml-engineer** | Eval policy on the contract test; holdout-live regression check; whether TripAdvisor citations actually improve travel-vertical verdict quality (sub-eval, 10 fixtures) |
| **product-designer** | Citation rendering for `provider_kind="bazaar:tripadvisor"` |
| **business-manager** | None for S16 — TripAdvisor adapter is engineering-led; pricing/GTM implications captured in S17 retro |

---

## Spend / cost notes

- Stub mode: $0
- Track B contract test (S16-BAZAAR-CONSUMER-04): one-time recording ~$0.05
- TripAdvisor live smoke (S16-BAZAAR-TRIP-01): ~$0.10
- S16-DOGFOOD-01 (5 ideas): ~$1.50
- **Total Sprint 16 live-validation budget: ≤ $3 USDC**

---

## Reference

- `docs/build-plan-sprint-15.md` — predecessor sprint (registry seam dormant)
- `docs/build-plan-sprint-14.md` — sprint format template + Pattern C contract test pattern (S14-TEST-POLICY-01)
- `docs/diagnostics/2026-05-01-chunk-write-failures.md` — Track A root-cause memo (data-eng)
- `docs/strategy/2026-05-01-bazaar-consumer-design.md` — Track B design memo (software-eng)
- `packages/gecko-core/src/gecko_core/sources/__init__.py` — Source Protocol that `BazaarSourceProvider` conforms to
- `packages/gecko-core/src/gecko_core/payments/protocol.py` — X402Client (seller-side); X402Consumer is the buyer-side counterpart
- `tests/payments/test_cdp_live_verify.py` — Pattern C template (gated `live_cdp` marker)
- `tests/eval/live_runs/2026-04-30-*.json` — chunking-flakiness baseline for Track A re-run
- `docs/research/agentic-market-skill-2026-05-01.md` — agentic.market skill reference (REQUIRED reading before Track B)
- CLAUDE.md Patterns A–D — especially B (no stubbed-but-shipped) and C (recorded-fixture contract tests)
- agentic.market discovery API: `https://agentic.market/v1/services` + `/v1/services/search?q={query}` (primary)
- CDP Bazaar discovery API: `api.cdp.coinbase.com/v2/x402/discovery/{resources,search}` (fallback)
