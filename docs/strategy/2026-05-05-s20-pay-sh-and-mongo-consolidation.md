# S20 Plan Seed — pay.sh integration + Mongo consolidation

**Window:** 2026-05-10 → 2026-05-17 (proposed)
**Predecessor:** S19 (Voyage/Mongo hardening — H1/H2/H4 shipped 2026-05-05)
**Author:** staff-engineer
**Theme:** Eliminate the dual-store complexity tax (Postgres precedents/memory + Mongo chunks) and start the pay.sh interop work.

**Status (2026-05-05 23:40):** This plan is OUT OF DATE — see brainstorm record in memory `project_knowledge_as_commodity_pivot`. Positioning shifted from "judgment as commodity" to "**knowledge as commodity**." pay.sh, twit.sh, Bazaar are now retrieval sources, not integration partners. The Mongo-consolidation Track A is still load-bearing; Track B (pay.sh interop) needs full rewrite as a retrieval-source adapter. New plan to be drafted after brainstorming round closes.

---

## Context

Two threads converged in the S19 wake-up:

1. **Dual-store tax** — S18 cut chunks over to Mongo + Voyage 1024, but `gecko_precedent`, `memory`, and a few internal flywheel writes still live on Supabase pgvector + OpenAI 1536 via `embed_for_postgres_vector`. Every retrieval site needs a `if get_chunk_store() == "mongo"` branch (`rag/query.py:248-252`, `pulse_engine.py:140-141`). This is the exact surface that produced the 1024/1536 inconsistency hardened in S19. Consolidating to one store + one embed model removes a whole class of future bugs.

2. **pay.sh exists and ships our distribution shape** — Solana Foundation's `pay` CLI + Pay MCP server (https://pay.sh, github.com/solana-foundation/pay) is community, not competition (per memory `project_solana_brasil_community`). It already ships:
   - `pay claude "..."` / `pay codex "..."` wrappers that inject the Pay MCP server + payment-safety prompts into agent sessions — the bootstrap UX gecko-mcp wants.
   - 75+ paid-API provider catalog with x402 + Stripe MPP wire protocols on Solana.
   - OS-keychain wallet storage (macOS Keychain, GNOME Keyring, Windows Hello, 1Password).
   - Workflow: `search_skills → get_skill_endpoints → curl`.

   We can either ignore it (and reinvent the catalog), compete (and split the small Solana-x402-agent audience), or **collaborate** (list Gecko as a provider, accept pay.sh wallet identity, honor receipts bidirectionally). The Solana-Brasil community memory says collaborator framing is the right default.

---

## Wedge — what S20 leads with

(a) + (b) fused — **"Gecko verdicts are tradeable judgments listed in the pay.sh catalog, settled on Solana, with a single Mongo+Voyage spine."**

The S19 wedge ("adversarial-debate verdict + grounded dissent, packaged as a tradeable judgment") gets a distribution layer. pay.sh provides the catalog and the wallet UX; Gecko provides the judgment artifact.

---

## Ticket list

Two tracks, run in parallel. Each is independently shippable.

### Track A — Mongo consolidation (S20-MONGO-FULL-*)

Spine of the sprint. Eliminates `embed_for_postgres_vector`. Owner: `data-engineer` lead, `software-engineer` pairs on call-site surgery.

| # | Ticket | Owner | Effort | Acceptance |
|---|---|---|---|---|
| A1 | **S20-MONGO-PRECEDENTS-01** | data-eng + sw-eng | M (1d) | New Mongo collection `precedents` with vector index `precedents_vector` (1024-d Voyage cosine). New module `gecko_core/db/mongo_precedents.py` mirroring `mongo_chunks.py` shape (`insert_precedent_mongo`, `match_precedents_mongo`). Schema validators mirror the Postgres `gecko_precedent` columns. Doctor extends to verify the new index dim (reuse `_extract_vector_index_dim` helper from S19-H1). |
| A2 | **S20-MONGO-MEMORY-01** | data-eng + sw-eng | M (1d) | New Mongo collection `memory` with `memory_vector` (1024-d Voyage cosine). Module `gecko_core/db/mongo_memory.py`. Existing `memory/embedder.py` wrapper switched from `embed_for_postgres_vector` → `embed`. Test stubs at `tests/memory/test_store.py` updated 1536 → 1024. |
| A3 | **S20-EMBED-CONSOLIDATE-01** | sw-eng | S (0.5d) | Delete `embed_for_postgres_vector` from `embedder.py`, `POSTGRES_VECTOR_DIM`, `POSTGRES_EMBED_MODEL` constants. Remove every `if get_chunk_store() == "mongo"` retrieval branch in `rag/query.py:248-252`, `pulse_engine.py:140-141`, `advisor/context.py:178-180`, `flywheel/__init__.py:326`, `workflows.py:1050,1131`. Single embed path: Voyage 1024 → Mongo. **Gated on A1 + A2 merging.** |
| A4 | **S20-EMBED-DOCTOR-CLEANUP-01** | sw-eng | XS | Remove `_is_server_stack` branching in `check_embed_provider` (`doctor.py:784-`). Remove the `OPENAI_API_KEY required for Postgres ANN paths` hint in `_OPTIONAL_HINTS`. Remove `check_voyage_api_key` Supabase-conditional logic. Doctor becomes simpler: Voyage required when chunks are written, full stop. |
| A5 | **S20-SUPABASE-CHUNK-DROP-01** | data-eng | S (0.5d) | Drop `gecko_precedent`, `memory`, `chunks`, `chunk_embedding_cache` tables from Supabase. Keep `sessions`, `sources` (small, no vector ops). Migration file `infra/supabase/migrations/20260510000000_drop_vector_tables.sql`. **Gated on doctor green for ≥3 days post-A1+A2+A3.** |

**Cutover sub-total:** 5 tickets, ~3.0 days. Pattern: same fresh-start cutover as S18 — no backfill (flywheel + memory are small and rebuild on next sessions). Pattern A applies (single source of truth for shared Literals); the chunk-store flag becomes vestigial after A3 and gets removed in A4.

**Risk:** flywheel "precedents" power the advisor's pattern-matching context. If A1's Mongo port has different recall behavior than Postgres, advisor verdicts shift subtly. Mitigation: contract-test A1 against a fixture set of 20 stored precedents and assert ranked output matches within ±1 position.

---

### Track B — pay.sh interop (S20-PAYSH-*)

Discovery + thin first integration. Owner: `web3-engineer` lead, `business-manager` arbitrates the catalog-listing decision.

| # | Ticket | Owner | Effort | Acceptance |
|---|---|---|---|---|
| B1 | **S20-PAYSH-DISCOVERY-01** | web3-eng | S (0.5d) | Read pay.sh provider-publishing docs (the `pay skills` subcommand surface). Document in `docs/web3/2026-05-pay-sh-interop.md`: (i) the JSON schema of a pay.sh skill manifest; (ii) which Gecko endpoints (`/research`, `/advise`, `/plan`, `/pulse`) would map to skills; (iii) what wire format pay.sh uses for x402 (HTTP 402 + facilitator dispatch — same as ours? CDP-compatible? frames-compatible?). |
| B2 | **S20-PAYSH-WALLET-COMPAT-01** | web3-eng | M (1d) | `gecko-mcp doctor` recognizes a pay.sh-provisioned wallet (OS keychain) as a valid `payments:provider` source, alongside frames.ag and self-custody. New `_pay_sh_wallet()` resolver in `gecko_mcp/wallet.py` reading from the appropriate keychain entry. Test under `tests/mcp/test_doctor_pay_sh_wallet.py`. **Does NOT** swap out the default frames.ag flow; just adds pay.sh as a third source. |
| B3 | **S20-PAYSH-CATALOG-LIST-01** | bus-mgr + web3-eng | S (0.5d) | Decision doc: do we list Gecko in pay.sh catalog (yes/no/wait)? Open question per memory `project_output_layer_positioning` — we publish insights, not a generic API. List the trade-offs: distribution vs commodity-framing risk. Recommendation in the doc; no implementation in S20. |
| B4 | **S20-PAYSH-RECEIPT-INTEROP-01** (OPTIONAL) | web3-eng | M (1d) | If B3 says "yes": x402 receipts produced by Gecko's facilitator are honored as proof-of-payment by pay.sh's verification (and vice versa). Requires reading pay.sh's `/verify` endpoint. Defer if B3 is "no" or "wait". |

**Interop sub-total:** 3 must-do (B1, B2, B3) + 1 optional (B4). ~2.0 days for the must-do core.

---

## Sprint total

10 tickets if both tracks ship in full; 8 tickets without A5 (deferred to S21 by design — Pattern C: drop only after green doctor for ≥3 days) and B4 (gated on B3 outcome).

**Effort mix:** 1×XS, 5×S, 4×M. Half-day slack for A1/A2 contract-test tuning.

**Recommended minimum critical path (3.5 days):** A1 + A2 + A3 + B1. Ship A4/A5 in S21. B2/B3 are nice-to-haves but not load-bearing for the dual-store tax.

---

## Risks

1. **Voyage 1024 dim is now the single point of failure for ALL ANN ops.** Memory + precedents lose their Postgres fallback. Mitigation: S19 H2 (`doctor --live`) already provides early warning. If Voyage outages happen, ALL retrieval halts — same as S19 risk, just expanded blast radius.

2. **pay.sh catalog framing.** Listing Gecko as "an API at $X per call" risks the commodity-framing slide that memory `project_output_layer_positioning` warned about. Recommendation: B3 should default to "wait until we have a credible price ladder per insight type" rather than "yes ship now."

3. **Wallet UX fragmentation.** With frames.ag (default) + self-custody (existing) + pay.sh (B2 adds), the wallet resolver becomes a 3-way switch. Pattern A applies: route through one canonical resolver, no parallel implementations.

4. **`@solana/pay` confusion.** The user mentioned `npx @solana/pay claude "buy some water with pay"` — that npm form does not exist (pay.sh ships via brew). If we want an `npx`-style entry point for Gecko (gecko-mcp via npx), that's an S21+ packaging ticket, not an S20 pay.sh task. Don't conflate.

---

## Out of scope (deferred to S21+)

- `npx`-based gecko-mcp distribution wrapper (`npx @gecko/mcp ...`).
- Live x402 settlement on the publisher side (pay.sh receipts → publish.new artifact unlock).
- Multi-currency support (USDC vs USDG) in the catalog price ladder.
- A pay.sh-style skill catalog UI in `app.geckovision.tech`.

---

## Verification

End-of-sprint smoke (after Track A merges):

```bash
# 1. Doctor — should still green with no embed_for_postgres_vector branch
uv run gecko-mcp doctor --live
# expect: voyage:embed:live PASS, no Postgres ANN rows

# 2. Mongo precedents/memory roundtrip
uv run pytest tests/memory/ tests/flywheel/ tests/orchestration/test_advisor.py -q

# 3. Real research run — confirms precedents come back from Mongo
uv run bb research --idea "S20 dogfood" --tier basic --tier-preset budget
# expect: ≥1 precedent in advisor context (logged), all embeds via Voyage

# 4. pay.sh wallet recognized (Track B2)
PAY_SH_WALLET_PRESENT=1 uv run gecko-mcp doctor
# expect: payments:provider INFO row mentions pay.sh as valid source
```
