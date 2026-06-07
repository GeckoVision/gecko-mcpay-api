-- 20260607010000_supabase_remodel.sql
-- Purpose: Consolidated Supabase remodel grounded in the ACTUAL running DB.
--          Supersedes PR #106 (20260607000000_session_scoped_agents.sql) by
--          folding its 4 session-scoped-agent tables + RLS + helper fn in
--          here, reconciled against the real 15-table schema.
--
--          This file has TWO parts:
--            PART A (ADDITIVE)    — runs on `supabase migration up`. Creates the
--                                   identity / wallet / grant / agent-binding
--                                   control plane + RLS. No existing rows touched.
--            PART B (DESTRUCTIVE) — COMMENTED OUT. The founder runs it BY HAND
--                                   after backing up. Drops 3 dead tables. It is
--                                   NOT executed by the migration runner.
--
-- Reversible: PART A yes (drops the 4 new tables + fn). PART B is NOT reversible
--             without the pg_dump backups it instructs you to take first.
-- Touches:
--   PART A creates: app_users, wallet_links, agent_grants, user_agents,
--                   function gecko_current_user_id().
--   PART B drops (manual): creators, session_outputs, tavily_extract_cache.
-- Store split: agent RUNTIME state stays in MongoDB (collection `agent_state`,
--              keyed by GECKO_AGENT_ID). RAG chunks/embeddings already live in
--              MongoDB Atlas (Supabase copies dropped 2026-05-03). Supabase
--              here owns identity / sessions / bindings / access-control ONLY.
--              `user_agents.agent_id` is the cross-store join key into Mongo.
-- Pattern A (shared Literals): CHECK constraints below mirror canonical Python
--              Literals. Canonical home is `gecko_core.wallets.provider`:
--                custody  -> Custody          ({"user-owned"})
--                provider -> WalletProviderKind (PROMOTE to real Literal+tuple)
--                status   -> UserAgentStatus  (NEW Literal to add alongside).
--              Add drift test tests/test_user_agent_literal_consistency.py
--              modelled on test_payment_mode_consistency.py.
-- Design doc: docs/db-model/2026-06-07-supabase-remodel.md (KEEP/DROP/ARCHIVE
--              table-by-table verdict + evidence + founder decisions).

-- ===========================================================================
-- PART A — ADDITIVE (auto-applied; safe; no existing rows touched)
-- ===========================================================================

-- ---------------------------------------------------------------------------
-- 0. RLS identity helper.
--    gecko-api authenticates the HMAC session token, resolves user_id, and as
--    the first statement of the request transaction runs
--      SELECT set_config('request.jwt.claim.user_id', $1, true);  -- tx-local
--    Every RLS policy compares row ownership against this helper. If the claim
--    is absent (raw service-role connection that forgot to set it) this returns
--    NULL and every USING / WITH CHECK predicate is NULL -> FALSE -> deny.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION gecko_current_user_id()
RETURNS text
LANGUAGE sql
STABLE
AS $$
  SELECT NULLIF(current_setting('request.jwt.claim.user_id', true), '')
$$;

COMMENT ON FUNCTION gecko_current_user_id() IS
  'Returns the per-request Gecko user_id that gecko-api set via '
  'set_config(''request.jwt.claim.user_id'', user_id, true) after verifying '
  'the HMAC session token. NULL when unset -> RLS denies. Single identity '
  'anchor for every policy in the session-scoped-agents layer.';

-- ---------------------------------------------------------------------------
-- 1. app_users — identity root.
--    id = the Gecko user_id string u_<sha256(wallet)[:16]> minted by gecko-api
--    (onboarding._user_id_for). TEXT, not uuid, so PK == session-token claim ==
--    RLS claim with no extra mapping table. email nullable (wallet-only users),
--    unique when present (case-insensitive, ignoring soft-deleted rows).
--    Reconciliation note: this is the FIRST real identity table. The research
--    `sessions` table is idea-keyed (not a user), `creators` is being dropped,
--    `waitlist` is a write-only marketing sink — none can serve identity.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS app_users (
  id          TEXT NOT NULL PRIMARY KEY,
  email       TEXT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at  TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS app_users_email_lower_uidx
  ON app_users (lower(email))
  WHERE email IS NOT NULL AND deleted_at IS NULL;

COMMENT ON TABLE app_users IS
  'Identity root. id = u_<sha256(wallet)[:16]> minted by gecko-api '
  '(onboarding._user_id_for). email nullable (wallet-only), unique when set. '
  'RLS: a user sees only their own row.';

-- ---------------------------------------------------------------------------
-- 2. wallet_links — the user's OWN wallet bound to them.
--    Mirrors gecko_core.wallets.provider.WalletLink. PUBLIC address only;
--    NEVER key material (non-custodial invariant #1).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS wallet_links (
  id          UUID NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id     TEXT NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
  address     TEXT NOT NULL,
  -- Pattern A: mirrors WalletProviderKind in gecko_core.wallets.provider.
  provider    TEXT NOT NULL CHECK (provider IN ('privy', 'okx', 'magicblock', 'stub')),
  -- Pattern A: mirrors Custody. V1 is non-custodial; only legal value.
  custody     TEXT NOT NULL DEFAULT 'user-owned' CHECK (custody IN ('user-owned')),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at  TIMESTAMPTZ
);

-- One live link per (user, address); a user may re-link after soft-delete.
CREATE UNIQUE INDEX IF NOT EXISTS wallet_links_user_address_uidx
  ON wallet_links (user_id, address)
  WHERE deleted_at IS NULL;

-- Read pattern: "give me this user's linked wallet(s)" (/onboarding/me +
-- deploy-binding). user_id leading so RLS predicate + lookup share the index.
CREATE INDEX IF NOT EXISTS wallet_links_user_idx
  ON wallet_links (user_id)
  WHERE deleted_at IS NULL;

COMMENT ON TABLE wallet_links IS
  'User-owned wallet bound to a Gecko user. Mirrors '
  'gecko_core.wallets.provider.WalletLink. PUBLIC address only — never keys. '
  'custody always user-owned (non-custodial). RLS: owner-only.';

-- ---------------------------------------------------------------------------
-- 3. agent_grants — the revocable trade-only scope.
--    Mirrors gecko_core.wallets.provider.Scope. One live grant per user;
--    revoke flips `revoked` rather than deleting (audit trail).
--    withdraw_allowlist holds ONLY the user's own address (non-custodial #3).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS agent_grants (
  id                  UUID NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id             TEXT NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
  allowed_actions     TEXT[] NOT NULL DEFAULT '{}',
  withdraw_allowlist  TEXT[] NOT NULL DEFAULT '{}',
  revoked             BOOLEAN NOT NULL DEFAULT false,
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One live (non-revoked) grant per user; a revoked row coexists with a fresh
-- one (re-grant after revoke), preserving the revoked row as history.
CREATE UNIQUE INDEX IF NOT EXISTS agent_grants_user_live_uidx
  ON agent_grants (user_id)
  WHERE revoked = false;

COMMENT ON TABLE agent_grants IS
  'Revocable trade-only scope a user gives Gecko''s agent. Mirrors '
  'gecko_core.wallets.provider.Scope. withdraw_allowlist holds ONLY the '
  'user''s own address (non-custodial invariant #3). revoke flips revoked; '
  'rows are never deleted (audit). RLS: owner-only.';

-- ---------------------------------------------------------------------------
-- 4. user_agents — the binding that makes a Mongo agent_state doc owner-only.
--    agent_id is the Mongo GECKO_AGENT_ID. gecko-api resolves session ->
--    user_id, looks up the user's user_agents row(s), and ONLY then reads /
--    writes the matching `agent_state` doc in Mongo. No path from a session
--    to a Mongo doc bypasses an owner-checked row here. THIS is the "only your
--    own bot session" gate.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS user_agents (
  id          UUID NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id     TEXT NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
  agent_id    TEXT NOT NULL,            -- Mongo GECKO_AGENT_ID (cross-store key)
  strategy    TEXT,
  profile     TEXT,
  -- Pattern A: mirrors UserAgentStatus in gecko_core.wallets.provider.
  status      TEXT NOT NULL DEFAULT 'deployed' CHECK (status IN ('deployed', 'stopped')),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at  TIMESTAMPTZ
);

-- agent_id globally unique among live rows (one Mongo doc = one owner).
CREATE UNIQUE INDEX IF NOT EXISTS user_agents_agent_id_uidx
  ON user_agents (agent_id)
  WHERE deleted_at IS NULL;

-- Read pattern: "list this user's agents" (dashboard) + the per-request
-- ownership check before any Mongo agent_state access.
CREATE INDEX IF NOT EXISTS user_agents_user_idx
  ON user_agents (user_id)
  WHERE deleted_at IS NULL;

COMMENT ON TABLE user_agents IS
  'Binding {user_id -> Mongo GECKO_AGENT_ID}. The single gate that makes a '
  'deployed bot''s agent_state doc reachable ONLY by its owner. agent_id is '
  'the cross-store join key into Mongo (runtime state lives there, NOT here). '
  'RLS: owner-only.';

-- ---------------------------------------------------------------------------
-- 5. Row-Level Security — owner-only on every new table.
--    For RLS to bite, gecko-api must connect under a role that does NOT bypass
--    RLS (service_role is BYPASSRLS). See design doc "Enforcement path" +
--    founder decision on the connection role. Policies target authenticated
--    (owner-only) and anon (deny-all). FORCE so even the table owner is subject.
-- ---------------------------------------------------------------------------
ALTER TABLE app_users    ENABLE ROW LEVEL SECURITY;
ALTER TABLE wallet_links ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_grants ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_agents  ENABLE ROW LEVEL SECURITY;

ALTER TABLE app_users    FORCE ROW LEVEL SECURITY;
ALTER TABLE wallet_links FORCE ROW LEVEL SECURITY;
ALTER TABLE agent_grants FORCE ROW LEVEL SECURITY;
ALTER TABLE user_agents  FORCE ROW LEVEL SECURITY;

-- ---- app_users ----
DROP POLICY IF EXISTS app_users_owner_only ON app_users;
CREATE POLICY app_users_owner_only
  ON app_users FOR ALL TO authenticated
  USING (id = gecko_current_user_id())
  WITH CHECK (id = gecko_current_user_id());

DROP POLICY IF EXISTS app_users_no_anon ON app_users;
CREATE POLICY app_users_no_anon
  ON app_users FOR ALL TO anon USING (false) WITH CHECK (false);

-- ---- wallet_links ----
DROP POLICY IF EXISTS wallet_links_owner_only ON wallet_links;
CREATE POLICY wallet_links_owner_only
  ON wallet_links FOR ALL TO authenticated
  USING (user_id = gecko_current_user_id())
  WITH CHECK (user_id = gecko_current_user_id());

DROP POLICY IF EXISTS wallet_links_no_anon ON wallet_links;
CREATE POLICY wallet_links_no_anon
  ON wallet_links FOR ALL TO anon USING (false) WITH CHECK (false);

-- ---- agent_grants ----
DROP POLICY IF EXISTS agent_grants_owner_only ON agent_grants;
CREATE POLICY agent_grants_owner_only
  ON agent_grants FOR ALL TO authenticated
  USING (user_id = gecko_current_user_id())
  WITH CHECK (user_id = gecko_current_user_id());

DROP POLICY IF EXISTS agent_grants_no_anon ON agent_grants;
CREATE POLICY agent_grants_no_anon
  ON agent_grants FOR ALL TO anon USING (false) WITH CHECK (false);

-- ---- user_agents ----
DROP POLICY IF EXISTS user_agents_owner_only ON user_agents;
CREATE POLICY user_agents_owner_only
  ON user_agents FOR ALL TO authenticated
  USING (user_id = gecko_current_user_id())
  WITH CHECK (user_id = gecko_current_user_id());

DROP POLICY IF EXISTS user_agents_no_anon ON user_agents;
CREATE POLICY user_agents_no_anon
  ON user_agents FOR ALL TO anon USING (false) WITH CHECK (false);

-- ---------------------------------------------------------------------------
-- PART A down (manual; forward-only repo, kept for reviewer clarity):
--   DROP TABLE IF EXISTS user_agents, agent_grants, wallet_links, app_users CASCADE;
--   DROP FUNCTION IF EXISTS gecko_current_user_id();
-- ---------------------------------------------------------------------------


/* ===========================================================================
   PART B — DESTRUCTIVE CLEANUP (NOT auto-applied — FOUNDER RUNS BY HAND)
   ===========================================================================

   This block is intentionally inside a SQL comment so `supabase migration up`
   will NOT execute it. The founder runs these statements DELIBERATELY, AFTER
   taking the pg_dump backups, and ONLY after confirming the two founder
   decisions in docs/db-model/2026-06-07-supabase-remodel.md.

   Every DROP below is backed by a grep of packages/ + apps/ showing zero live
   references (see the design doc evidence table). None is referenced by an FK
   from a KEEP table, so there is no cascade risk to live data.

   ---- STEP 0: BACKUP FIRST (run in your shell, NOT here) -------------------
     pg_dump "$SUPABASE_DB_URL" -t public.creators \
       > backup_creators_$(date -u +%Y%m%d).sql
     pg_dump "$SUPABASE_DB_URL" -t public.session_outputs \
       > backup_session_outputs_$(date -u +%Y%m%d).sql
     pg_dump "$SUPABASE_DB_URL" -t public.tavily_extract_cache \
       > backup_tavily_cache_$(date -u +%Y%m%d).sql

   ---- STEP 1: creators ----------------------------------------------------
     Abandoned creator/Pioneer attribution. Zero code refs; not even created
     by an in-repo migration. No FKs in or out.

       DROP TABLE IF EXISTS public.creators;

   ---- STEP 2: session_outputs ---------------------------------------------
     Old research-product output table (business_plan/validation/prd). Research
     results now live in sessions.result_json. Zero code refs. session_id is
     unenforced (no FK), so drop is independent.

       DROP TABLE IF EXISTS public.session_outputs;

   ---- STEP 3: tavily_extract_cache  (FOUNDER DECISION #2 GATES THIS) -------
     Large raw-HTML cache; same size-offender class as the already-dropped
     chunk tables. Only a dead constant _CACHE_TABLE references it. DROP ONLY
     after confirming the `bb research` ingestion pipeline is retired / will
     not write it again. If ingestion may still run, leave this table and
     downgrade it to ARCHIVE.

       DROP TABLE IF EXISTS public.tavily_extract_cache;

   ===========================================================================
   PART C — ARCHIVE (export-only; DO NOT DROP YET)
   ===========================================================================

   These three are research-only + pgvector/JSONB size risks, but each still
   has a LIVE gecko-api route, so they must NOT be dropped until software-
   engineer retires those routes (/precedents, /memory/query, /pulse). Export
   them now so the eventual drop is a one-liner with a backup in hand.

     pg_dump "$SUPABASE_DB_URL" -t public.gecko_precedent \
       > archive_gecko_precedent_$(date -u +%Y%m%d).sql
     pg_dump "$SUPABASE_DB_URL" -t public.memory \
       > archive_memory_$(date -u +%Y%m%d).sql
     pg_dump "$SUPABASE_DB_URL" -t public.pulse_runs \
       > archive_pulse_runs_$(date -u +%Y%m%d).sql

   Drop (later sprint, after the routes are gone):
     -- DROP TABLE IF EXISTS public.gecko_precedent CASCADE;
     -- DROP TABLE IF EXISTS public.memory;
     -- DROP TABLE IF EXISTS public.pulse_runs;

   =========================================================================== */
