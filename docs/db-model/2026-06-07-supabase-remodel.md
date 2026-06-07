# Supabase schema remodel — grounded in the actually-running DB

**Date:** 2026-06-07
**Status:** DESIGN ONLY. Additive migration FILE written + ready to apply; destructive section is commented-out and founder-gated. NOT applied to remote, NOT pushed, NOT a PR.
**Owner lane:** data-engineer. Coordinates with software-engineer (gecko-api route enforcement) + web3-engineer (wallet seam).
**Supersedes:** PR #106 (`origin/sprint-61/supabase-session-schema`). Its 4 tables + RLS + helper fn are folded in here verbatim, reconciled against the real schema.
**Source of truth for "what's running":** `docs/db-model/old_db_schema.sql` (15 live tables) + a grep audit of `packages/` and `apps/` (every verdict below is backed by a code reference or its documented absence).

---

## TL;DR

- **15 tables running.** Verdict: **KEEP 9, ARCHIVE 3, DROP 3** (plus add **4 new** session-scoped-agent tables).
- The big nuance: the **research-product surface is frozen but still mounted** in gecko-api (`/research`, `/sessions/*`, `/projects`, `/pulse`, `/precedents`, `/memory/query`, `/advise`, `/scaffold`). Its core tables are therefore **KEEP** even though the product pivoted — a live route still reads/writes them. Dropping them breaks `/openapi.json` contract endpoints. **Do NOT drop research tables without first retiring the routes (software-engineer + frontend-engineer).**
- The genuine "stopped due to size" tables (`chunks`, `chunk_embedding_cache`, `chunks_write_audit`) were **already dropped** 2026-05-03 (migrations `20260503000000` + `20260503010000`) when chunks moved to Mongo Atlas. They are not in the live 15. The remaining pgvector tables (`gecko_precedent`, `memory`) are the next size risk and the next archive targets — research-only, untouched by the V1 oracle.
- The 3 true DROP candidates (`creators`, `session_outputs`, `tavily_extract_cache`) have **zero live-code references** and no V1 role. Each verified below.

---

## Store split: Supabase vs MongoDB (the load-bearing context)

| Concern | Store | Status |
|---|---|---|
| Identity / wallet bindings / agent grants (control plane) | **Supabase** (NEW: `app_users`, `wallet_links`, `agent_grants`, `user_agents`) | added here |
| Research sessions / sources / costs / events (frozen product) | **Supabase** (`sessions`, `sources`, `session_costs`, `pro_events`) | KEEP (routes live) |
| Projects / budgets / pulse credits / spend ledger | **Supabase** (`projects`, `pulse_purchases`, `bazaar_spend_ledger`) | KEEP (routes/x402 live) |
| Marketing waitlist | **Supabase** (`waitlist`) | KEEP (written by gecko-claude landing, service-role) |
| Top-of-funnel telemetry | **Supabase** (`telemetry_events`) | KEEP (`/events` route live) |
| RAG chunks + embeddings (the size-cap casualty) | **MongoDB Atlas** (`gecko_rag.*`) | already cut over; Supabase copies dropped |
| Precedent flywheel + memory (pgvector) | **Supabase** (`gecko_precedent`, `memory`) | ARCHIVE — research-only, next size risk |
| Agent **runtime** state (positions, journal, PnL, spec_version) | **MongoDB** (`agent_state` keyed by `GECKO_AGENT_ID`) | NOT in Supabase; `user_agents.agent_id` is the cross-store join |

`user_agents.agent_id` is the only path from a Supabase user to a Mongo `agent_state` doc, and it is owner-checked by RLS. There is no Mongo RLS — the Supabase binding IS the gate.

---

## Table-by-table verdict (with evidence)

### KEEP — 9 tables

| Table | Verdict | Evidence (live read/write) |
|---|---|---|
| `sessions` | **KEEP** | `SessionStore.SESSIONS_TABLE` — ~20 `.table(SESSIONS_TABLE)` calls in `sessions/store.py`; routes `/research`, `/research/pro`, `/sessions/{id}/*`, `/trade_research/pro` all persist here. Central table; `result_json` holds verdicts. |
| `sources` | **KEEP** | `SessionStore.SOURCES_TABLE`; `store.py` lines 580/622/1376; route `GET /sessions/{id}/sources` (`SourceInfo` response model). Per-source provenance still written on every research run. |
| `session_costs` | **KEEP** | `SessionStore.SESSION_COSTS_TABLE` (store.py:1657); economics ledger; route `GET /sessions/{id}/economics`. |
| `pro_events` | **KEEP** | `SessionStore.PRO_EVENTS_TABLE` (store.py:1581); SSE buffer for `GET /research/pro/{id}/events`. |
| `projects` | **KEEP** | `SessionStore.PROJECTS_TABLE` (store.py:1034); `memory/store.py:231`; routes `POST/GET /projects`, `/projects/{id}/economics`, `/sessions/spent-by-project`. Budget cap + spent_usd RPC live. |
| `pulse_purchases` | **KEEP** | `payments/pulse_credits.py:210` `_PULSE_PURCHASES_TABLE`; consumed by `/pulse` credit gating. x402-adjacent — do not touch. |
| `bazaar_spend_ledger` | **KEEP** | `payments/spend_ledger.py:45` `TABLE_NAME`; x402 spend audit. Payment-touching — do not touch. |
| `waitlist` | **KEEP (cross-repo writer)** | **No reference in this repo** — but its migration (`20260428000100`) documents it as the service-role write sink for the **gecko-claude apex landing**. Marketing funnel data. Absence here is expected (writer is another repo). **Flagged: do NOT drop — verify with whoever owns gecko-claude before any action.** |
| `telemetry_events` | **KEEP** | `telemetry/store.py:27` `TELEMETRY_TABLE`; route `POST /events` (`record_telemetry_event`, main.py:3466) + `GET /metrics/telemetry`. Top-of-funnel, still wired. |

### ARCHIVE — 3 tables (research-only, pgvector size risk; export then defer-drop)

| Table | Verdict | Evidence + rationale |
|---|---|---|
| `gecko_precedent` | **ARCHIVE** | Live in code (`GECKO_PRECEDENT_TABLE`, store.py:1728; `/precedents` route) BUT it is the **research-era flywheel** (verdict='ship/kill/pivot' on startup ideas) and carries a **pgvector `embedding` column** — the same class of large vector data that already blew the storage cap. The V1 trade oracle (`orchestration/trade_panel/`, `trade_agent/`) does **not** read it (grep: zero hits). Recommendation: `pg_dump` the table, then drop in a later sprint once `/precedents` is retired with the rest of the research surface. Keep until the route is removed; archive-export now so the drop is safe later. |
| `memory` | **ARCHIVE** | Live (`memory/store.py`, `match_memory` RPC, `/memory/query` route) BUT research-era project/session/user memory with a pgvector `embedding` column. V1 oracle does not use `MemoryStore` (grep of `trade_panel`/`trade_agent`: zero hits). Same size profile + same archive plan as `gecko_precedent`. |
| `pulse_runs` | **ARCHIVE** | Live (`PULSE_RUNS_TABLE`, store.py:1856; written by advisor pulse). Research-era "pulse panel" output; large `panel_json`/`deltas_json` JSONB blobs. Not a payment table (that's `pulse_purchases`, which stays). Bound to the research advisor surface; archive-export now, drop when `/pulse` is retired. |

**Archive ≠ drop.** All three still have a live route, so they are export-then-keep until the research surface is formally retired. The archive verdict means: (1) they carry no V1 value, (2) they are the next size liability, (3) `pg_dump` them now so the eventual drop is a one-liner with a backup already in hand.

### DROP — 3 tables (zero live references, no V1 role; founder-gated, destructive)

| Table | Verdict | Evidence (proof of unused) |
|---|---|---|
| `creators` | **DROP** | **Zero references** in `packages/` + `apps/` (grep `creators`, `earnings_pending`, `CreatorStore`, `.table("creators")` → only an unrelated CLI pluralization string in `render.py:169`). **No migration in this repo creates it** — it was created out-of-band and never wired. This is the abandoned "Pioneer / creator-attribution" concept. Safe to drop. |
| `session_outputs` | **DROP** | **Zero references** anywhere (`grep session_outputs packages/ apps/ infra/` → nothing). Its `output_type` enum is `business_plan/validation/prd` — the old research-product output table. Research results are persisted in `sessions.result_json`, not here. The in-memory `ResearchResult.business_plan` field (`models.py:812`) is unrelated (never serialized to this table). Dead. |
| `tavily_extract_cache` | **DROP** | Referenced only by a single dead constant `_CACHE_TABLE = "tavily_extract_cache"` in `ingestion/web.py:130`. This is a **large raw-HTML cache** (`raw_content text` per URL) — a prime size offender of the same class as the dropped chunk tables. The ingestion pipeline is part of the frozen research surface and chunks already moved to Mongo. Confirm the `_CACHE_TABLE` read/write path is dead, then drop. **Flag: this is the one DROP that's borderline — it has a constant, not just absence. Founder should confirm the research ingestion pipeline is truly retired before dropping, since a `bb research` run could still try to write it.** |

---

## NEW — session-scoped agent layer (4 tables, folds in PR #106)

Reconciled with the real schema. Verdict on the reconciliation question from the brief ("can `sessions`/`creators`/`waitlist` serve identity?"):

- **No.** `sessions` is research-idea-keyed (`idea text NOT NULL`), not a user identity table; `creators` is being dropped; `waitlist` is a write-only marketing sink. None model a Gecko user with a deterministic id. A dedicated `app_users` is correct — **but** note `gecko_precedent.user_id uuid` and `memory.scope_id` already gesture at a user concept that was never normalized. `app_users` becomes the first real identity table; if the research surface is ever revived, those columns should FK to it.

Tables (full DDL in the migration):

| Table | Role |
|---|---|
| `app_users` | Identity root. `id TEXT` = `u_<sha256(wallet)[:16]>` minted by `onboarding._user_id_for` (matches the HMAC session token + RLS claim — no extra mapping). email nullable + unique-when-set. Soft-delete. |
| `wallet_links` | User-owned wallet (PUBLIC address only). Mirrors `gecko_core.wallets.provider.WalletLink`. `custody='user-owned'` only (non-custodial). Soft-delete. |
| `agent_grants` | Revocable trade-only scope. Mirrors `Scope`. `revoked` flag (never deleted → audit trail). `withdraw_allowlist` holds only the user's own address. |
| `user_agents` | `{user_id → Mongo GECKO_AGENT_ID}` binding. The single owner-gate into Mongo `agent_state`. Soft-delete. |

### RLS model (unchanged from #106, validated against the real DB)

- Helper `gecko_current_user_id()` reads `request.jwt.claim.user_id` (a GUC gecko-api sets per request from the verified HMAC token). NULL when unset → every predicate FALSE → **deny by default**.
- All four tables: `ENABLE` + `FORCE ROW LEVEL SECURITY`. Owner-only `USING`/`WITH CHECK` for `authenticated`; explicit deny-all for `anon` (web app never touches these directly — it goes through gecko-api with anon key + RLS).
- This satisfies the hard requirement: *only the user's own session can access their own bot session.*

### Pattern A — shared Literals

Canonical home: `gecko_core.wallets.provider`.

| SQL CHECK | Python Literal | Action |
|---|---|---|
| `wallet_links.custody IN ('user-owned')` | `Custody` | exists |
| `wallet_links.provider IN ('privy','okx','magicblock','stub')` | `WalletProviderKind` | **PROMOTE** to real Literal + tuple (today a field comment) |
| `user_agents.status IN ('deployed','stopped')` | `UserAgentStatus` | **NEW** |

Follow-up (software-engineer): add `tests/test_user_agent_literal_consistency.py` modelled on `test_payment_mode_consistency.py`, scanning this migration's CHECK values vs the tuples. The migration comments name these so the drift test has an anchor.

---

## Migration / cutover plan

**One file, two parts** (`infra/supabase/migrations/20260607010000_supabase_remodel.sql`):

1. **ADDITIVE (auto-apply, safe):** the 4 new tables + helper fn + RLS. `CREATE TABLE IF NOT EXISTS`, no existing rows touched. This is the only part the orchestrator applies. It is exactly PR #106's content, so #106 can be closed in favor of this file.

2. **DESTRUCTIVE (commented-out, founder runs deliberately):** the 3 DROPs, in safe order, each preceded by its `pg_dump` export command. **Not executed by `supabase migration up`** — it's inside a `/* ... */` block with a header that says so. The founder uncomments after backing up.

### Safe drop order + backup (destructive section)

```
# 0. BACKUP FIRST (run outside the migration, founder's shell):
pg_dump "$SUPABASE_DB_URL" -t public.creators            > backup_creators_$(date -u +%Y%m%d).sql
pg_dump "$SUPABASE_DB_URL" -t public.session_outputs     > backup_session_outputs_$(date -u +%Y%m%d).sql
pg_dump "$SUPABASE_DB_URL" -t public.tavily_extract_cache > backup_tavily_cache_$(date -u +%Y%m%d).sql

# 1. creators        — no FKs in/out, drop freely.
# 2. session_outputs — no FKs (session_id is unenforced), drop freely.
# 3. tavily_extract_cache — confirm research ingestion retired first.
```

`session_outputs.session_id` and `gecko_precedent.session_id` reference `sessions` logically but `session_outputs` has no FK constraint, so its drop is independent. None of the 3 DROP targets are referenced by FK from a KEEP table → no cascade risk.

### Archive (export-only, no drop yet)

```
pg_dump "$SUPABASE_DB_URL" -t public.gecko_precedent > archive_gecko_precedent_$(date -u +%Y%m%d).sql
pg_dump "$SUPABASE_DB_URL" -t public.memory          > archive_memory_$(date -u +%Y%m%d).sql
pg_dump "$SUPABASE_DB_URL" -t public.pulse_runs      > archive_pulse_runs_$(date -u +%Y%m%d).sql
```
Drop these only after software-engineer retires `/precedents`, `/memory/query`, `/pulse` from gecko-api (separate sprint). Until then they stay live.

---

## Founder decisions required (2)

1. **Retire the research surface?** The KEEP-but-frozen research tables (`sessions`, `sources`, `session_costs`, `pro_events`, `projects`, `pulse_*`, `bazaar_spend_ledger`, `gecko_precedent`, `memory`) exist only because gecko-api still mounts the research routes. If V1 is oracle-only, the clean path is: software-engineer retires the routes → then these collapse from KEEP/ARCHIVE to DROP. **Decision: keep the research surface live, or schedule its retirement?** This remodel does NOT drop them either way (they're load-bearing today).

2. **`tavily_extract_cache` drop go/no-go.** It's the one DROP with a (dead-looking) code constant. Confirm `bb research` ingestion is retired / will never write it again, then it's safe. If research ingestion might still run, downgrade it to ARCHIVE.

(Open question carried from #106: `app_users.id` is TEXT `u_<sha256(wallet)[:16]>` not uuid — deliberate, so the PK == session-token claim == RLS claim with zero extra lookups. Flag if a uuid PK is required.)

---

## Boundaries honored

Design + migration FILE only. No remote apply, no push, no PR, no secrets accessed, nothing destructive executed. The destructive section is inert (commented). Every DROP/ARCHIVE/KEEP verdict is backed by a grep of `packages/` + `apps/`.
