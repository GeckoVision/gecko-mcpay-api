-- enable_rls_session_scoped.sql
-- Standalone, IDEMPOTENT re-runnable RLS for the session-scoped-agents tables
-- (app_users, wallet_links, agent_grants, user_agents). Safe to run any number
-- of times — every statement is CREATE OR REPLACE / IF EXISTS / ENABLE (no-op if
-- already on). Run it after the remodel migration's Part A tables exist.
--
-- Enforcement model: gecko-api verifies the HMAC session token, resolves the
-- Gecko user_id, and as the FIRST statement of each request transaction runs
--     SELECT set_config('request.jwt.claim.user_id', <user_id>, true);  -- tx-local
-- Then every owner-only policy below resolves to that user. If the claim is
-- unset, gecko_current_user_id() is NULL → every predicate is NULL → FALSE → deny.
-- IMPORTANT: RLS only bites if gecko-api connects under a NOBYPASSRLS role.
-- A BYPASSRLS / service-role connection ignores all of this (app-level WHERE
-- becomes the only gate). See docs/db-model/2026-06-07-supabase-remodel.md.

-- 0. Identity helper -----------------------------------------------------------
CREATE OR REPLACE FUNCTION gecko_current_user_id()
RETURNS text
LANGUAGE sql
STABLE
AS $$
  SELECT NULLIF(current_setting('request.jwt.claim.user_id', true), '')
$$;

-- 1. Enable + FORCE RLS (FORCE so even the table owner is subject) -------------
ALTER TABLE app_users    ENABLE ROW LEVEL SECURITY;
ALTER TABLE wallet_links ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_grants ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_agents  ENABLE ROW LEVEL SECURITY;

ALTER TABLE app_users    FORCE ROW LEVEL SECURITY;
ALTER TABLE wallet_links FORCE ROW LEVEL SECURITY;
ALTER TABLE agent_grants FORCE ROW LEVEL SECURITY;
ALTER TABLE user_agents  FORCE ROW LEVEL SECURITY;

-- 2. Owner-only policies (authenticated) + anon deny-all -----------------------
-- app_users: the row's own id IS the user_id.
DROP POLICY IF EXISTS app_users_owner_only ON app_users;
CREATE POLICY app_users_owner_only
  ON app_users FOR ALL TO authenticated
  USING (id = gecko_current_user_id())
  WITH CHECK (id = gecko_current_user_id());
DROP POLICY IF EXISTS app_users_no_anon ON app_users;
CREATE POLICY app_users_no_anon
  ON app_users FOR ALL TO anon USING (false) WITH CHECK (false);

-- wallet_links: scoped by user_id.
DROP POLICY IF EXISTS wallet_links_owner_only ON wallet_links;
CREATE POLICY wallet_links_owner_only
  ON wallet_links FOR ALL TO authenticated
  USING (user_id = gecko_current_user_id())
  WITH CHECK (user_id = gecko_current_user_id());
DROP POLICY IF EXISTS wallet_links_no_anon ON wallet_links;
CREATE POLICY wallet_links_no_anon
  ON wallet_links FOR ALL TO anon USING (false) WITH CHECK (false);

-- agent_grants: scoped by user_id.
DROP POLICY IF EXISTS agent_grants_owner_only ON agent_grants;
CREATE POLICY agent_grants_owner_only
  ON agent_grants FOR ALL TO authenticated
  USING (user_id = gecko_current_user_id())
  WITH CHECK (user_id = gecko_current_user_id());
DROP POLICY IF EXISTS agent_grants_no_anon ON agent_grants;
CREATE POLICY agent_grants_no_anon
  ON agent_grants FOR ALL TO anon USING (false) WITH CHECK (false);

-- user_agents: scoped by user_id — the ownership gate into Mongo agent_state.
DROP POLICY IF EXISTS user_agents_owner_only ON user_agents;
CREATE POLICY user_agents_owner_only
  ON user_agents FOR ALL TO authenticated
  USING (user_id = gecko_current_user_id())
  WITH CHECK (user_id = gecko_current_user_id());
DROP POLICY IF EXISTS user_agents_no_anon ON user_agents;
CREATE POLICY user_agents_no_anon
  ON user_agents FOR ALL TO anon USING (false) WITH CHECK (false);

-- 3. Verify (optional) — list policies + rls state -----------------------------
-- SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class
--   WHERE relname IN ('app_users','wallet_links','agent_grants','user_agents');
-- SELECT schemaname, tablename, policyname, roles, cmd FROM pg_policies
--   WHERE tablename IN ('app_users','wallet_links','agent_grants','user_agents')
--   ORDER BY tablename, policyname;
