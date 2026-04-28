-- 20260427000200_session_results.sql
-- Purpose: persist the ResearchResult JSON on the session row so the API can
--          return 202 immediately, run the workflow in the background, and
--          let clients poll GET /sessions/{id}/result until completion.
--          frames.ag's /x402/fetch upstream timeout (~30s) was killing
--          synchronous research calls; async pattern fixes that and is also
--          the right shape for production load.
-- Reversible: yes (additive, idempotent).
-- Touches: table `sessions`.

ALTER TABLE sessions
  ADD COLUMN IF NOT EXISTS result_json JSONB,
  ADD COLUMN IF NOT EXISTS error_message TEXT;

-- Convenience index for "show me failed sessions in the last hour" dashboards.
CREATE INDEX IF NOT EXISTS sessions_status_completed_idx
  ON sessions (status, completed_at DESC NULLS LAST)
  WHERE deleted_at IS NULL;
