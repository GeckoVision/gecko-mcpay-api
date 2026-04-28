-- 20260428000000_projects.sql
-- Purpose: introduce per-project "vaults" so a frames.ag user can group
--          sessions under a named budget. v1 is policy-bounded (frames.ag
--          policy keys cap spend at the wallet level) and budget enforcement
--          is client-side: the gecko-mcp api_client sums cost_total_usd
--          for the project before issuing a paid call. v2 (post-Shipathon)
--          will swap in Privy direct wallets per project for cryptographic
--          isolation; the wallet_address / wallet_provider columns are
--          forward-compat seats for that work.
-- Reversible: yes (additive; new table + nullable session columns).
-- Touches: new table `projects`; ALTER `sessions` (additive); new RPC
--          `gecko_project_budget_remaining`.
--
-- Deferred to v2 (do NOT add here — see docs/schema-v1-v2-projects.md):
--   - privy_authorization_keys
--   - privy_policy_templates
--   - per-project policy assignments
--   - project_steps per-step cost table
--
-- Notes:
-- - frames_username is plain TEXT, not a FK. frames.ag is the source of truth
--   for users; we only mirror the handle. Lower-cased on insert by callers.
-- - budget_usd is a soft cap. The DB does not block inserts that would push
--   spend over budget; the api_client is responsible for refusing the call.
--   Keeps the DB simple and lets us evolve enforcement without a migration.
-- - NUMERIC(12, 6) matches the cost_*_usd columns on sessions for clean math.

CREATE TABLE IF NOT EXISTS projects (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  frames_username  TEXT NOT NULL,
  name             TEXT NOT NULL,
  budget_usd       NUMERIC(12, 6),
  -- v1: NULL. v2: the Privy-provisioned wallet for this project.
  wallet_address   TEXT,
  -- v1: 'frames-policy' (no isolation; relies on frames.ag policy ceilings).
  -- v2: 'privy-direct' (cryptographic isolation; one keypair per project).
  wallet_provider  TEXT NOT NULL DEFAULT 'frames-policy'
                   CHECK (wallet_provider IN ('frames-policy', 'privy-direct')),
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at       TIMESTAMPTZ,
  CONSTRAINT projects_frames_username_name_key UNIQUE (frames_username, name)
);

-- Lookup by owner. Filtering on deleted_at lets `list_projects` skip the
-- soft-deleted rows without a seq scan once a user accumulates archives.
CREATE INDEX IF NOT EXISTS projects_frames_username_idx
  ON projects (frames_username)
  WHERE deleted_at IS NULL;

-- Sessions get an optional project pointer. Nullable: pre-v1 sessions and
-- any "free probe" sessions that don't belong to a vault stay project-less.
ALTER TABLE sessions
  ADD COLUMN IF NOT EXISTS project_id UUID REFERENCES projects(id),
  -- Denormalized audit trail: snapshot of which wallet actually paid for
  -- this session at the moment it ran. v1 = the user's frames.ag wallet,
  -- v2 = the project's Privy wallet. Captured here so the truth survives
  -- even if the project's wallet later rotates.
  ADD COLUMN IF NOT EXISTS paid_from_wallet_address TEXT;

-- The hot query for budget enforcement is:
--   SELECT SUM(cost_total_usd) FROM sessions
--    WHERE project_id = $1 AND deleted_at IS NULL;
-- This partial index keeps it fast at 10k sessions / project. Including
-- cost_total_usd makes it an index-only scan on Postgres.
CREATE INDEX IF NOT EXISTS sessions_project_id_cost_idx
  ON sessions (project_id) INCLUDE (cost_total_usd)
  WHERE deleted_at IS NULL AND project_id IS NOT NULL;

-- Budget-remaining helper. Returns:
--   NULL if the project has no budget set (unlimited).
--   budget_usd - SUM(cost_total_usd) otherwise (can go negative on overrun).
-- SECURITY DEFINER so the anon role can call it via PostgREST without being
-- granted SELECT on sessions directly. The function only exposes a single
-- aggregate scalar, never row-level data.
CREATE OR REPLACE FUNCTION gecko_project_budget_remaining(
  p_project_id UUID
) RETURNS NUMERIC
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_budget NUMERIC;
  v_spent  NUMERIC;
BEGIN
  SELECT budget_usd INTO v_budget
    FROM projects
    WHERE id = p_project_id AND deleted_at IS NULL;

  IF NOT FOUND THEN
    RETURN NULL;
  END IF;

  IF v_budget IS NULL THEN
    RETURN NULL;
  END IF;

  SELECT COALESCE(SUM(cost_total_usd), 0) INTO v_spent
    FROM sessions
    WHERE project_id = p_project_id AND deleted_at IS NULL;

  RETURN v_budget - v_spent;
END $$;

GRANT EXECUTE ON FUNCTION gecko_project_budget_remaining(UUID) TO service_role;
GRANT EXECUTE ON FUNCTION gecko_project_budget_remaining(UUID) TO anon;
GRANT EXECUTE ON FUNCTION gecko_project_budget_remaining(UUID) TO authenticated;

-- Service role gets full table access; the API uses anon + RLS (RLS policies
-- ship in a follow-up migration once the gecko-api auth shape settles).
GRANT ALL ON TABLE projects TO service_role;
