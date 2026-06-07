# Design — Supabase schema for V1 non-custodial onboarding + session-scoped agent access

**Date:** 2026-06-07
**Status:** DESIGN ONLY — migration FILE written, NOT applied to remote. Founder-gated.
**Owner lane:** data-engineer (schema + RLS); coordinates with software-engineer (gecko-api enforcement), web3-engineer (wallet seam).
**Migration:** `infra/supabase/migrations/20260607000000_session_scoped_agents.sql`
**Builds on:** `docs/superpowers/specs/2026-06-07-phase-a-onboarding-noncustodial-design.md`, `memory/project_noncustodial_custody_decision_2026_06_07`.

## Hard requirement

> Only the user's own session can access their own bot session.

A user's deployed bot lives as a Mongo `agent_state` doc keyed by `GECKO_AGENT_ID`. The job of this Supabase layer is to make that doc reachable **only** by its owning user, by routing every access through an owner-checked binding row plus Row-Level Security.

## What is and is NOT in Supabase (the store split)

| Concern | Store | Why |
|---|---|---|
| Identity (user, email) | **Supabase** (`app_users`) | Control plane; RLS-native. |
| Wallet binding (public address) | **Supabase** (`wallet_links`) | Identity ↔ wallet; non-secret. |
| Revocable trade-only grant | **Supabase** (`agent_grants`) | Access-control state; owner-only. |
| `user_id → GECKO_AGENT_ID` binding | **Supabase** (`user_agents`) | The ownership gate into Mongo. |
| Agent **runtime** state (positions, journal, spec_version, PnL) | **MongoDB** `agent_state` | Written by the deployed bot (`GECKO_STATE_BACKEND=mongo`); high-write, document-shaped. Do NOT move to Supabase. |
| Research sessions / sources / chunks | **Supabase** (existing) / Mongo (chunks) | Pre-existing, different concept. Untouched by this migration. |

`user_agents.agent_id` is the cross-store join key. There is no path from a session to a Mongo `agent_state` doc that does not first pass an owner-checked `user_agents` lookup.

## ER overview

```
app_users (id = u_<sha256(wallet)[:16]>, email?, created_at, deleted_at)
   │  1
   ├──────────────< wallet_links (user_id FK, address, provider, custody='user-owned')
   │  1
   ├──────────────< agent_grants (user_id FK, allowed_actions[], withdraw_allowlist[], revoked)
   │  1
   └──────────────< user_agents  (user_id FK, agent_id ─────────────────┐ status)
                                                                          │
                                                       (cross-store join) ▼
                                              MongoDB  agent_state { _id: GECKO_AGENT_ID, ... }
```

- `app_users.id` is **TEXT**, not a generated uuid — it is the deterministic `u_<sha256(wallet)[:16]>` that `onboarding._user_id_for` already mints and that the HMAC session token already carries. Using it directly means the RLS claim, the session token, and the PK are the same string with no extra mapping table. (The task brief said "uuid pk"; I deviated deliberately because a synthetic uuid would force a second lookup `session.user_id → app_users.id` on every request and a uuid↔text claim cast in RLS. Flag for founder if a uuid PK is preferred — see open questions.)
- `wallet_links` / `agent_grants` mirror `WalletLink` / `Scope` in `gecko_core.wallets.provider` field-for-field (text[] for the frozensets).
- Soft-delete (`deleted_at`) on user-facing tables per the soft-delete-by-default principle. `agent_grants` uses `revoked` instead (the seam's own concept) and never deletes — preserving the revoke audit trail.

## RLS model

Single identity anchor: `gecko_current_user_id()` returns `current_setting('request.jwt.claim.user_id', true)` (NULL when unset). Every policy predicate is `row.user_id = gecko_current_user_id()` (and `id = ...` on `app_users`). With the claim unset the predicate is NULL → FALSE → **deny by default**.

- RLS `ENABLE` + `FORCE` on all four tables (FORCE so even the table owner / migration role is subject to it — a misconfigured connection cannot silently bypass).
- `authenticated` role: owner-only `USING` + `WITH CHECK`.
- `anon` role: explicit deny-all (the web app never touches these tables directly; it goes through gecko-api).

### The exact enforcement path through gecko-api ("session → user → only-your-own")

1. Web app calls gecko-api with the HMAC `Bearer` session token (the OUR-app session from onboarding, not wallet auth).
2. gecko-api verifies the token (`onboarding._verify`) → extracts `user_id`.
3. gecko-api opens / checks out its Supabase connection and, **as the first statement of the request transaction**, runs:
   ```sql
   SELECT set_config('request.jwt.claim.user_id', :user_id, true);  -- true = tx-local
   ```
4. All subsequent queries in that transaction see RLS scoped to that user. A query for someone else's `user_agents` row returns zero rows — no 403 leak, same as "not found".
5. Only after an owner-checked `user_agents` row confirms ownership of `agent_id` does gecko-api read/write the matching Mongo `agent_state` doc. Mongo has no RLS; the Supabase binding IS the gate, so this ordering is mandatory.

**Which key / which role (the load-bearing decision):** RLS does **not** apply to the Postgres superuser, and the Supabase `service_role` key is `BYPASSRLS`. So gecko-api must connect under a role that is subject to RLS for these policies to bite. Two viable options:

- **(A) Dedicated non-bypass role** (recommended). Create a `gecko_api` Postgres role with `NOBYPASSRLS`, grant it DML on these four tables, and have gecko-api connect with that role's credentials (kept server-side in SSM, same secret-handling as the service-role key). It sets the `request.jwt.claim.user_id` GUC per request. This keeps RLS authoritative as defense-in-depth even though gecko-api is trusted.
- **(B) Keep using `service_role` and rely on gecko-api filtering.** RLS is then advisory (bypassed); the `WHERE user_id = ...` filter in application code is the only real gate. Simpler, but loses the DB-level guarantee — one missing `WHERE` clause leaks cross-user data. **Not recommended** for the "only your own bot" requirement.

The migration is written for option (A): policies target `authenticated`/`anon` and `FORCE ROW LEVEL SECURITY` is set. If the founder picks (B), the policies are harmless (bypassed) but the guarantee weakens — call it out.

> Note: `request.jwt.claim.user_id` is just a GUC name; we are NOT using Supabase Auth JWTs here (gecko-api mints its own HMAC sessions). The name is chosen to be familiar and to keep the door open to a future Supabase-Auth migration where the same GUC is populated by a verified JWT instead of `set_config`.

## Pattern A — shared Literals

Canonical home: **`gecko_core.wallets.provider`**.

| SQL CHECK | Canonical Python Literal | Status |
|---|---|---|
| `wallet_links.custody IN ('user-owned')` | `Custody` (exists) | already canonical |
| `wallet_links.provider IN ('privy','okx','magicblock','stub')` | `WalletProviderKind` | **PROMOTE** — today only a field-comment on `WalletLink.provider`; make it a real `Literal` + `WALLET_PROVIDER_KINDS` tuple, mirroring `PaymentMode`/`PAYMENT_MODES`. |
| `user_agents.status IN ('deployed','stopped')` | `UserAgentStatus` | **NEW** — add alongside. |

Follow-up (software-engineer / data-engineer): add `tests/test_user_agent_literal_consistency.py` modelled on `test_payment_mode_consistency.py` — scan this migration's CHECK values vs the tuples. Adding a provider/status value then = one Python file + one migration + the test updates. The migration comments already name these so the drift test has an anchor.

## Idempotency / indexes (intentional)

- `app_users_email_lower_uidx` — case-insensitive unique email, partial on `email IS NOT NULL AND deleted_at IS NULL` (wallet-only users with NULL email coexist; soft-delete frees the email).
- `wallet_links_user_address_uidx` — one live link per (user, address).
- `agent_grants_user_live_uidx` — one live (non-revoked) grant per user; a revoked row coexists with a fresh one (re-grant keeps history).
- `user_agents_agent_id_uidx` — `agent_id` globally unique among live rows (one Mongo doc = one owner).
- `wallet_links_user_idx` / `user_agents_user_idx` — leading `user_id` so RLS predicate + lookup share the index.

No "just in case" indexes; each is justified by a read pattern in the comments.

## Open questions for the founder

1. **Auth provider.** Supabase Auth, or gecko-api-minted HMAC sessions + the `request.jwt.claim.user_id` GUC (this design)? The Phase A spec already mints HMAC sessions, so this design extends that. If we adopt Supabase Auth later, `app_users.id` would need to align with `auth.uid()` (uuid) — see Q3.
2. **Connection role.** Option (A) dedicated `NOBYPASSRLS` `gecko_api` role (RLS authoritative) vs (B) keep `service_role` + app-level filtering (RLS advisory). (A) recommended for the "only your own bot" guarantee. Requires creating the role + SSM secret (devops-engineer).
3. **PK type.** `app_users.id` as TEXT `u_<sha256(wallet)[:16]>` (this design; zero extra mapping) vs synthetic `uuid` (task brief's literal ask; needs a `session.user_id → uuid` lookup + a claim cast). I chose TEXT for directness; flag if uuid is required.
4. **Store-of-record tension.** The Phase A onboarding spec lists `users` / `auth_otps` in **Mongo**; this task scopes identity to **Supabase**. Both can't be the source of truth for `users`. Decide: (a) Supabase owns identity/bindings (this design) and Mongo owns only OTP + runtime, or (b) Mongo owns everything and Supabase is dropped from V1 onboarding. This migration assumes (a). Needs a one-line founder ruling before either is implemented.

## Boundaries honored

Design + migration FILE only. No `apply_migration` against remote, no push, no PR, no secrets accessed, no deploy. Commits left in the worktree for the orchestrator to integrate.
