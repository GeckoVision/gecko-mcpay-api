# Gecko Context Strategy Checklist — Agentic Context Engineering (2026-06-14)

Consolidated from three specialist passes (data-engineer = semantic model/dataset, ai-ml-engineer = context-to-model, software-engineer = data-access layer). This is the plan to give `gecko_trade_research` a reliable, auditable, live-aware context layer — the substrate the decision-integrity / Information-MEV wedge runs on.

> **For agentic workers:** use superpowers:subagent-driven-development to execute, task-by-task. Each box is a self-contained change. Boundaries: PAPER + `X402_MODE=stub`; no merge to main / no prod deploy without founder OK; `private/` stays gitignored; Pattern A (shared Literals), Pattern E (reachability tests), Pattern F (session_id never gates permanent corpus) apply throughout.

---

## 🚨 Headline: the wedge is currently DARK in prod — three convergent findings

The safety / Information-MEV read is our differentiator. All three lanes independently found it is **not actually functioning end-to-end** right now:

1. **Not configured (SE).** `QUICKNODE_RPC_URL` is read at `safety_check.py:~98` but is **NOT in the SSM param map** (`infra/push-ssm-params.sh`). In prod `_rpc_url()` returns `None` → **every contract-safety read returns `safety_check_unavailable`.** The rug/honeypot/concentration signal is dark in production today.
2. **Dead endpoint (already fixed this session).** The market/liquidity read pointed at CoinGecko's on-chain endpoint, which was **gated to paid keys in 2026** (401 keyless) → silently broke the manipulation read. Fixed → GeckoTerminal free API (PR #136 branch).
3. **Never reaches the model (AI/ML).** Even when computed, the live safety/Information-MEV read runs **after** the panel and is attached post-hoc (`_attach_safety`). The 7 voices and the grounding gate never see it — so the gate **redacts live on-chain numbers as ungrounded** (the BrCA redaction). "Grounded but stale" beats "current but uncited."

**Net:** the Information-MEV wedge must be (a) configured, (b) pointed at a live source, AND (c) injected into the model's context — all three — before it actually works. This is also the **Functionality (20%)** gap in the Colosseum rubric: the wedge has to *demonstrably fire on mainnet*, not just exist in code.

---

## The architecture in one picture

Two data planes meet in `run_trade_panel_with_retrieval` (`trade_panel/__init__.py:2154`):

- **Plane A — precomputed chunks** (Atlas `$vectorSearch`, two-leg protocol + canon-floor, Voyage rerank). Mature, self-caching. Feeds the LLM prompt.
- **Plane B — live reads at request time.** Today only ONE: `evaluate_contract_safety` (`safety_check.py`), fired *post-panel*, mutating only the envelope. No shared transport, cache, rate-limiter, or abstraction. Four ad-hoc injection seams (`safety_client`, `safety_market_client`, `news_provider`, `history_source`) with no common interface.

The gaps: Plane B (1) isn't configured in prod, (2) doesn't reach the model, (3) is uncached/unthrottled (every mint-resolving run hits GeckoTerminal cold → ~30/min cap → cascade to silent `unavailable`), and (4) has no semantic model — voices read flat text; `provider_kind`/`freshness_tier` are used only for routing, never exposed as structured facts.

---

## Phase 0 — make the wedge actually fire (P0 correctness)

- [ ] **0.1 Configure the RPC in prod.** Add `QUICKNODE_RPC_URL` (or `HELIUS_RPC_URL`) to `infra/push-ssm-params.sh` + ECS `secrets:`. Without it the safety read is dark. *(SE P0 — the single highest-priority correctness fix.)*
- [ ] **0.2 Inject the live safety read as a sourced chunk BEFORE the panel.** Move `evaluate_contract_safety` to fire pre-panel and merge an in-memory chunk (`provider_kind="onchain_live"`, `freshness_tier="hot"`, `as_of=now`) carrying mint/freeze, top_holder_pct, mcap, liquidity, liq/mcap ratio, IMEV score+reasons — using the existing injection pattern (`__init__.py:~2247`). Fixes risk_manager starvation, the gate redaction, and BrCA in one move. Keep `_attach_safety` as the post-hoc amplifier. *(AI/ML P0.)*
- [ ] **0.3 Per-source cache + per-key lock + rate limiter.** Wrap every Plane-B call in cache-then-charge (TTL: safety 60s / liquidity 120s / price 10s) + per-key `asyncio.Lock` stampede collapse + per-upstream token bucket (GeckoTerminal 30/min), all fail-OPEN. Model on `trade_agent/oracle.py:~550`. Stops the next outage. *(SE P0.)*
- [ ] **0.4 Reachability test (Pattern E).** A request whose expected citations include the `onchain_live` chunk; assert the risk_manager turn cites it AND a live number survives the grounding gate. *(AI/ML P0.)*
- [ ] **0.5 Add `COINGECKO_API_KEY` to SSM** + pass to `CoinGeckoClient` (support exists, `coingecko.py:~184`) to lift the rate ceiling / un-gate the mirror. *(SE P1, cheap.)*
- [ ] **0.6 Verify `GECKO_RERANKER=voyage` is ON in prod.** If off, the canon-floor quota reranks nothing — retrieval runs on raw cosine. *(AI/ML P0, cheap to check.)*

## Phase 1 — the semantic model (voices see facts, not flat text)

- [ ] **1.1 Entity registry.** Canonical join `mint ↔ protocol_slug ↔ coingecko_id ↔ symbol ↔ chunk.protocol[]`. The spine that lets the live read and the corpus reference the *same entity* and lets the panel cross-check a corpus claim against a live number. *(data P1.1.)*
- [ ] **1.2 Numeric-fact extraction.** Extract numbers from `quote`-kind chunks into `metadata.facts` ({metric, value, unit, as_of}) at ingest, so a voice gets "TVL = $X as of D" not prose. Hook `insert_chunks_mongo` `metadata_extra`. *(data P1.2.)*
- [ ] **1.3 Source-trust axis.** Add `source_trust` (canon/protocol_native=high, paysh=medium, web/social=low); surface per chunk so risk_manager discounts low-trust claims. Generalizes the "venue rated it Normal" defense. *(data P1.3.)*
- [ ] **1.4 Expose semantic axes to voices.** `_format_chunk` (`__init__.py:~137`) hands voices `source`+text only. Surface `provider_kind`, `freshness_tier`, `as_of_date`, `source_trust`, resolved entity. Structure already on the doc — just dropped at format time. *(data P1.4.)*
- [ ] **1.5 Typed facts block (ontology v0).** Prepend a structured, dated, sourced facts section (Token / Protocol / Venue / RiskSignal / PriceObservation) ahead of prose chunks AND include it in the gate's snippet corpus → facts ground by construction; "same-asset" becomes a key-match not an LLM inference (kills the fabricated-TVL failure mode). *(AI/ML P1 + data P1.)*
- [ ] **1.6 Enforce `content_kind` TTL at read time.** `quote=24h / mechanism=30d / governance=7d` is documentation-only today; nothing recomputes `is_stale`. Drop or hard-tag `[STALE as of D]` stale quotes in `retrieve_trade_corpus_chunks`. A stale number presented as current IS the manipulation we exist to price. *(data P0.2.)*

## Phase 2 — retrieval quality

- [ ] **2.1 Wire `news_provider` in prod** — sentiment_analyst defaults to constant `neutral` without it (`__init__.py:~2262`); adapter exists. Add a reachability assert. *(AI/ML P1.)*
- [ ] **2.2 BM25 / `$search` keyword leg** unioned with the vector legs for protocol/token/pool exact-match recall; rerank the union. Highest-leverage retrieval add. Validate on the retrieval eval, ≥2 runs. *(AI/ML P1.)*
- [ ] **2.3 A/B `voyage-finance-2` vs `voyage-context-3`** — gate the re-embed on measured `citation_relevance` + coverage lift, ≥2 runs. *(AI/ML P2.)*
- [ ] **2.4 Content-typed chunk sizing** — smaller number-dense chunks for protocol_native/market_data; keep 512 for canon. *(AI/ML P2 + data.)*
- [ ] **2.5 Promote `protocol`/`freshness_tier`/`as_of_date` to filterable Atlas index paths** when corpus growth makes post-`$match` filtering slow (document the EXPLAIN first). *(data P1.5.)*

## Phase 3 — new sources + the access abstraction

- [ ] **3.1 `SourceProvider` protocol + `LiveSourceRegistry`** (capability → provider: `contract_safety`, `token_liquidity`, `holders`, `spot_price`, `news`). Panel asks for a *capability*, never a named client — repointing CoinGecko→GeckoTerminal (the change we just made by hand) becomes one registry line. `CachedSourceProvider` decorator implements 0.3 once for all providers. Escalate the panel-contract touch to `staff-engineer`. *(SE P1.)*
- [ ] **3.2 `HeliusProvider`** under `holders` (DAS `getTokenHolders` — better than `getTokenLargestAccounts`) + `contract_safety`; register QuickNode as fallback (provider neutrality). Add `HELIUS_RPC_URL` to SSM. *(SE P1 + data P2.1.)*
- [ ] **3.3 Wire Pegana** (`sources/pegana.py` is BUILT but DARK — zero refs in orchestration). Fold `DepegRisk` into the safety block for LST/stable targets. *(data P0.1.)*
- [ ] **3.4 `DuneProvider`** (query-execute + poll, long TTL, credit budget) for holder-velocity / LP concentration / wash-trade score — the Information-MEV deepening GeckoTerminal's single ratio can't give. Add `DUNE_API_KEY` to SSM at ship time, behind a per-source cost ceiling. *(SE P2 + data P2.3.)*
- [ ] **3.5 DEX pool depth + age (LIVE)** and **holder-velocity store** (Helius snapshots over a window — the deferred `safety_check.py:~61` follow-up). *(data P2.2/P2.1.)*
- [ ] **3.6 Social/sentiment trade-scoped source** (twit.sh exists but general-research); tag `source_trust=low`, `freshness_tier=daily`. *(data P2.5.)*

---

## Live-vs-chunk contract (the unified rule)

Dividing line = **volatility of the datum × cost of staleness**, NOT "is it on-chain."

| Datum | Plane | TTL / cadence |
|---|---|---|
| Investor canon | CHUNK static | — (Pattern F: never session-gated) |
| Protocol mechanics/docs | CHUNK static/daily | daily ingest |
| TVL / OHLC / macro candles | CHUNK hot | ~1h ingest (7× cost to go live) |
| Mint/freeze authority | **LIVE (RPC)** | request-time |
| Holder concentration | **LIVE (Helius)** | request-time, 60s cache |
| Liquidity / mcap / IMEV ratio | **LIVE (GeckoTerminal)** | 60–120s cache — the wedge |
| Peg state | **LIVE (Pegana)** | request-time |
| Spot price (Pyth/Jupiter) | **LIVE** | 5–15s cache, only if a voice needs entry grounding |
| Dune aggregates | CHUNK daily *or* LIVE long-TTL | 5–15 min |
| Social / news | LIVE→ephemeral chunks | per request / daily |

**Binding principle:** a stale `quote` presented as current is worse than absent — live for volatile facts, TTL-enforced chunks for everything else, never an unlabeled stale quote reaching a voice.

## RPC / keys / access (SSM SecureString under `/gecko-api/*`)

Add to `infra/push-ssm-params.sh` + ECS `secrets:`: **`QUICKNODE_RPC_URL` (missing — P0)**, `HELIUS_RPC_URL`, `COINGECKO_API_KEY`, later `DUNE_API_KEY`. Never log URLs/keys (current redaction discipline is correct). Recommendation: **Helius = primary Solana RPC** (DAS + holders + mint/freeze), QuickNode = registered fallback.

## Open questions for the founder

1. **Helius as primary RPC** (DAS for holders/velocity) — provision the key + add to SSM? It also un-darks the safety read (P0).
2. **Dune account** — needed for the Information-MEV deepening (holder velocity, wash-trade). Credit-metered; gate behind the registry + cost ceiling. Provision now or after Phase 0/1?
3. **CoinGecko Pro key** — lifts the GeckoTerminal/CoinGecko rate ceiling and un-gates the on-chain mirror. Cheap; worth it for scale?
4. **Finance-embeddings re-embed** — full corpus re-embed has a one-time cost; gate on measured lift?

---

*Sources: data-engineer + ai-ml-engineer + software-engineer passes, 2026-06-14, grounded in the live trade_panel / safety_check / sources / infra code.*
