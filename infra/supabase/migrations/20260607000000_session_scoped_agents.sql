-- 20260607000000_session_scoped_agents.sql
-- Purpose: V1 non-custodial onboarding identity + session-scoped agent access.
--          Adds the IDENTITY / SESSIONS / BINDINGS / ACCESS-CONTROL layer for
--          the Phase A onboarding spine. This is the control plane only:
--            app_users     — who the user is (email and/or wallet-only).
--            wallet_links  — the user's OWN wallet bound to them (mirrors
--                            gecko_core.wallets.provider.WalletLink; we record
--                            the PUBLIC address only, never keys).
--            agent_grants  — the revocable trade-only scope the user gives Gecko
--                            (mirrors gecko_core.wallets.provider.Scope).
--            user_agents   — the binding {user_id -> Mongo GECKO_AGENT_ID} that
--                            makes a deployed bot's `agent_state` doc reachable
--                            ONLY by its owning user.
--          The hard requirement: "only the user session can access their bot
--          session." Enforced by RLS keyed on a per-request user_id claim that
--          gecko-api sets from the verified HMAC session token (see the RLS
--          section + the design doc).
-- Reversible: yes (drops the four new tables, the helper function, and the
--             grant on the function). NO existing rows touched. The research
--             `sessions` / `sources` / `chunks` tables are a DIFFERENT concept
--             and are NOT referenced here — this layer lives in its own
--             namespace and does not break research persistence.
-- Touches: NEW tables app_users, wallet_links, agent_grants, user_agents;
--           NEW function gecko_current_user_id().
-- Runtime split: agent RUNTIME state stays in MongoDB (collection `agent_state`,
--                keyed by GECKO_AGENT_ID, written by the deployed bot with
--                GECKO_STATE_BACKEND=mongo). Supabase here owns identity /
--                sessions / bindings / access-control ONLY. `user_agents.agent_id`
--                is the cross-store join key into Mongo; runtime state does NOT
--                move to Supabase.
-- Pattern A (shared Literals): the CHECK constraints below mirror canonical
--                Python Literals. Canonical home is
--                `gecko_core.wallets.provider`:
--                  - custody  -> Custody         (currently {"user-owned"})
--                  - provider -> WalletProviderKind (PROMOTE: today a free-text
--                                 field-comment in WalletLink.provider; this
--                                 migration is the trigger to make it a real
--                                 Literal + tuple, mirroring PaymentMode).
--                  - status   -> UserAgentStatus  (NEW Literal to add alongside).
--                Add a drift test `tests/test_user_agent_literal_consistency.py`
--                modelled on `test_payment_mode_consistency.py` that scans this
--                migration's CHECK values against those tuples.

-- ---------------------------------------------------------------------------
-- 0. RLS identity helper.
--    gecko-api authenticates the HMAC session token, resolves user_id, and
--    sets `request.jwt.claim.user_id` (a GUC) for the duration of the request
--    via `SELECT set_config('request.jwt.claim.user_id', $1, true)` (the
--    `true` = local to the transaction). Every RLS policy compares row
--    ownership against this helper. If the claim is absent (e.g. a raw
--    service-role connection that forgot to set it), this returns NULL and
--    every USING/ WITH CHECK predicate evaluates to FALSE -> deny by default.
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
  'the HMAC session token. NULL when unset -> RLS denies. This is the single '
  'identity anchor for every policy in the session-scoped-agents layer.';

-- ---------------------------------------------------------------------------
-- 1. app_users — identity root.
--    `id` is the Gecko user_id string `u_<sha256(wallet)[:16]>` minted by
--    gecko-api (onboarding._user_id_for). TEXT, not uuid, so it matches the
--    deterministic id the session token already carries and the RLS claim.
--    email is nullable (wallet-only users) and unique when present.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS app_users (
  id          TEXT NOT NULL PRIMARY KEY,
  email       TEXT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at  TIMESTAMPTZ
);

-- Case-insensitive uniqueness on email, ignoring soft-deleted rows. Partial
-- unique index (not a column UNIQUE) so multiple wallet-only users with NULL
-- email coexist and a soft-deleted user frees their email.
CREATE UNIQUE INDEX IF NOT EXISTS app_users_email_lower_uidx
  ON app_users (lower(email))
  WHERE email IS NOT NULL AND deleted_at IS NULL;

COMMENT ON TABLE app_users IS
  'Identity root. id = u_<sha256(wallet)[:16]> minted by gecko-api '
  '(onboarding._user_id_for). email nullable (wallet-only), unique when set. '
  'RLS: a user sees only their own row.';

-- ---------------------------------------------------------------------------
-- 2. wallet_links — the user's OWN wallet bound to them.
--    Mirrors gecko_core.wallets.provider.WalletLink. Records the PUBLIC
--    address only; NEVER key material (non-custodial invariant #1).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS wallet_links (
  id          UUID NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id     TEXT NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
  address     TEXT NOT NULL,
  -- Pattern A: mirrors WalletProviderKind in gecko_core.wallets.provider.
  provider    TEXT NOT NULL CHECK (provider IN ('privy', 'okx', 'magicblock', 'stub')),
  -- Pattern A: mirrors Custody in gecko_core.wallets.provider. V1 is
  -- non-custodial by construction; the only legal value is 'user-owned'.
  custody     TEXT NOT NULL DEFAULT 'user-owned' CHECK (custody IN ('user-owned')),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at  TIMESTAMPTZ
);

-- One live link per (user, address). A user may re-link after soft-delete.
CREATE UNIQUE INDEX IF NOT EXISTS wallet_links_user_address_uidx
  ON wallet_links (user_id, address)
  WHERE deleted_at IS NULL;

-- Read pattern: "give me this user's linked wallet(s)" — the /onboarding/me +
-- deploy-binding path. user_id is the leading column so RLS + this index align.
CREATE INDEX IF NOT EXISTS wallet_links_user_idx
  ON wallet_links (user_id)
  WHERE deleted_at IS NULL;

COMMENT ON TABLE wallet_links IS
  'User-owned wallet bound to a Gecko user. Mirrors '
  'gecko_core.wallets.provider.WalletLink. PUBLIC address only — never keys. '
  'custody is always user-owned (non-custodial). RLS: owner-only.';

-- ---------------------------------------------------------------------------
-- 3. agent_grants — the revocable trade-only scope.
--    Mirrors gecko_core.wallets.provider.Scope. One live grant per user
--    (the canonical user_scope()); revoke flips `revoked` rather than
--    deleting, preserving the audit trail. allowed_actions /
--    withdraw_allowlist are text[] mirroring the frozensets.
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

-- One live (non-revoked) grant per user. A revoked grant can coexist with a
-- fresh one (re-grant after revoke), preserving the revoked row as history.
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
--    agent_id is the Mongo GECKO_AGENT_ID (e.g. 'hosted-setupc-001'). gecko-api
--    resolves session -> user_id, looks up the user's user_agents row(s), and
--    ONLY then reads/writes the matching `agent_state` doc in Mongo. There is
--    no path from a session to a Mongo doc that does not pass through an
--    owner-checked row here. THIS is the "only your own bot session" gate.
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

-- agent_id is globally unique across the platform (one Mongo doc = one owner).
-- Partial on deleted_at so a stopped+soft-deleted agent_id can be reused.
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
-- 5. Row-Level Security — owner-only on every table.
--    Model: gecko-api is the SOLE writer/reader. It connects with the
--    service-role key BUT sets `request.jwt.claim.user_id` per request, and
--    these policies apply to a NON-superuser role. To make RLS bite even on a
--    service-role connection, gecko-api must connect under a role that does
--    NOT bypass RLS (see design doc "Enforcement path"). Policies target the
--    `authenticated` and `anon` roles explicitly; `anon` is denied outright
--    (the web app never reaches these tables directly).
--
--    Predicate everywhere: row.user_id = gecko_current_user_id(). With the
--    claim unset (NULL) the comparison is NULL -> treated as FALSE -> deny.
-- ---------------------------------------------------------------------------

ALTER TABLE app_users    ENABLE ROW LEVEL SECURITY;
ALTER TABLE wallet_links ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_grants ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_agents  ENABLE ROW LEVEL SECURITY;

-- Force RLS so even the table owner is subject to it (defense in depth: a
-- migration role or a misconfigured connection cannot silently bypass).
ALTER TABLE app_users    FORCE ROW LEVEL SECURITY;
ALTER TABLE wallet_links FORCE ROW LEVEL SECURITY;
ALTER TABLE agent_grants FORCE ROW LEVEL SECURITY;
ALTER TABLE user_agents  FORCE ROW LEVEL SECURITY;

-- ---- app_users ----
DROP POLICY IF EXISTS app_users_owner_only ON app_users;
CREATE POLICY app_users_owner_only
  ON app_users
  FOR ALL
  TO authenticated
  USING (id = gecko_current_user_id())
  WITH CHECK (id = gecko_current_user_id());

DROP POLICY IF EXISTS app_users_no_anon ON app_users;
CREATE POLICY app_users_no_anon
  ON app_users FOR ALL TO anon USING (false) WITH CHECK (false);

-- ---- wallet_links ----
DROP POLICY IF EXISTS wallet_links_owner_only ON wallet_links;
CREATE POLICY wallet_links_owner_only
  ON wallet_links
  FOR ALL
  TO authenticated
  USING (user_id = gecko_current_user_id())
  WITH CHECK (user_id = gecko_current_user_id());

DROP POLICY IF EXISTS wallet_links_no_anon ON wallet_links;
CREATE POLICY wallet_links_no_anon
  ON wallet_links FOR ALL TO anon USING (false) WITH CHECK (false);

-- ---- agent_grants ----
DROP POLICY IF EXISTS agent_grants_owner_only ON agent_grants;
CREATE POLICY agent_grants_owner_only
  ON agent_grants
  FOR ALL
  TO authenticated
  USING (user_id = gecko_current_user_id())
  WITH CHECK (user_id = gecko_current_user_id());

DROP POLICY IF EXISTS agent_grants_no_anon ON agent_grants;
CREATE POLICY agent_grants_no_anon
  ON agent_grants FOR ALL TO anon USING (false) WITH CHECK (false);

-- ---- user_agents ----
DROP POLICY IF EXISTS user_agents_owner_only ON user_agents;
CREATE POLICY user_agents_owner_only
  ON user_agents
  FOR ALL
  TO authenticated
  USING (user_id = gecko_current_user_id())
  WITH CHECK (user_id = gecko_current_user_id());

DROP POLICY IF EXISTS user_agents_no_anon ON user_agents;
CREATE POLICY user_agents_no_anon
  ON user_agents FOR ALL TO anon USING (false) WITH CHECK (false);

-- ---------------------------------------------------------------------------
-- Down (manual; forward-only repo, kept here for reviewer clarity):
--   DROP TABLE IF EXISTS user_agents, agent_grants, wallet_links, app_users CASCADE;
--   DROP FUNCTION IF EXISTS gecko_current_user_id();
-- ---------------------------------------------------------------------------
