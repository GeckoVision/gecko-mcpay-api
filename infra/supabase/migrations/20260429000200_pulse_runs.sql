-- 20260429000200_pulse_runs.sql (renamed from 019_pulse_runs.sql, F19, 2026-04-30)
-- Persist every Advisor Panel pulse run so subsequent pulses can compare
-- against the most recent prior panel for delta detection (S4-ADVISOR-05
-- handed off this work; S5-API-02 lands the schema).
--
-- A pulse is project-scoped when possible (so a project's "what changed"
-- view walks across sessions) but session-scoped is also valid (tests +
-- one-shot pulses against a single research session).
--
-- Reversible: yes (additive; new table + new indexes).
-- Touches: new table `pulse_runs`. No RPC.
-- RLS pattern follows `gecko_precedent`: read-all (cross-session signal
-- IS the value), write-service-role only.

CREATE TABLE IF NOT EXISTS pulse_runs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  -- Nullable in v1 because session-only pulses don't yet attach a project.
  -- The walk logic falls back to session_id when project_id is NULL.
  project_id UUID,
  session_id UUID NOT NULL,
  -- Full AdvisorPanel JSON — frozen voice list, total_cost_usd, generated_at.
  -- jsonb so we can query individual voices' closing_line in a follow-up
  -- migration if embedding-based delta detection wants pre-filtering.
  panel_json JSONB NOT NULL,
  -- Per-voice deltas vs the immediately-prior pulse_runs row in scope.
  -- Empty array on the first pulse for a project/session (no prior).
  deltas_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Hot path: walk the most recent pulse for a project, descending. The
-- partial index on project_id IS NOT NULL keeps it small for v1 where many
-- pulses are session-only.
CREATE INDEX IF NOT EXISTS idx_pulse_runs_project
  ON pulse_runs (project_id, created_at DESC)
  WHERE project_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_pulse_runs_session
  ON pulse_runs (session_id, created_at DESC);

-- RLS: same as gecko_precedent. Reads are open (cross-session signal is
-- the value); writes go through the service role only.
ALTER TABLE pulse_runs ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE schemaname = 'public'
      AND tablename = 'pulse_runs'
      AND policyname = 'read_all_pulse_runs'
  ) THEN
    EXECUTE 'CREATE POLICY "read_all_pulse_runs" ON pulse_runs FOR SELECT USING (true)';
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
    GRANT ALL ON TABLE pulse_runs TO service_role;
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
    GRANT SELECT ON TABLE pulse_runs TO anon;
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
    GRANT SELECT ON TABLE pulse_runs TO authenticated;
  END IF;
END $$;

COMMENT ON TABLE pulse_runs IS
  'Advisor Panel pulse history. Each row is one panel run with per-voice deltas vs the immediately-prior run for the same project (or session, when project_id is NULL).';
