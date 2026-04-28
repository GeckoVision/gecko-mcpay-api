-- 009_session_costs_agent.sql
-- Purpose: Pro tier per-agent cost attribution.
--          Basic tier continues using rolled-up columns on `sessions`
--          (cost_llm_usd, cost_embed_usd, cost_tavily_usd, cost_deepgram_usd).
--          Pro tier writes one row per LLM call per agent into this table.
-- Reversible: yes (drops the new table + indexes).
-- Touches: session_costs (new table — distinct from the legacy rolled-up
--          columns living on sessions; there was no prior table by this name).
--
-- Notes:
-- - No backfill: Basic-tier history stays in sessions.cost_* columns.
-- - No RLS: service-role-only access pattern, consistent with the rest of
--   the schema; gecko-api authorizes per-session via the bearer-auth dep.
-- - Partial index on (session_id, agent) WHERE agent IS NOT NULL is the
--   hot path for Pro UI's per-agent rollup:
--     SELECT agent, SUM(cost_usd) FROM session_costs
--      WHERE session_id = $1 AND agent IS NOT NULL GROUP BY agent;
CREATE TABLE session_costs (
  id          BIGSERIAL PRIMARY KEY,
  session_id  UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  line_item   TEXT NOT NULL CHECK (line_item IN ('llm','embed','tavily','deepgram')),
  agent       TEXT,                     -- analyst|critic|architect|scoper|judge for line_item='llm' on Pro tier; NULL otherwise
  cost_usd    NUMERIC(10,6) NOT NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_session_costs_session ON session_costs (session_id);
CREATE INDEX idx_session_costs_agent
  ON session_costs (session_id, agent)
  WHERE agent IS NOT NULL;

COMMENT ON TABLE session_costs IS
  'Per-call cost ledger for Pro tier (per-agent attribution). Basic tier uses rolled-up columns on sessions.';
COMMENT ON COLUMN session_costs.agent IS
  'AG2 agent attribution; populated on Pro tier llm rows, NULL elsewhere.';
