-- 017_v1_source_telemetry.sql
-- Purpose: per-session telemetry for V1 source dispatcher (twit.sh, HN, Reddit,
--          gecko_precedent). twit.sh is the only paid V1 source today; we
--          carve a dedicated column out from cost_llm_usd so the dashboard
--          can isolate paid-source spend from inference spend, and a
--          rolled-up `cost_v1_sources_usd` for "all V1 source costs".
-- Reversible: yes (additive only; columns nullable / default 0).
-- Touches: table `sessions`; function `gecko_add_session_cost`.
--
-- Notes:
-- - cost_v1_sources_usd is the rollup. Today twit.sh is the only paid source;
--   when frames.ag-style sources (V1.5) start charging we add columns + sum
--   into the rollup the same way.
-- - Why a rollup *and* a per-source column? The rollup feeds the
--   "$0.10 per Pro session V1-sources cap" guard in workflows.py without a
--   trip back to the DB; the per-source column powers the per-source
--   attribution view in `gecko-mcp economics`.

ALTER TABLE sessions
  ADD COLUMN IF NOT EXISTS cost_twitsh_usd      NUMERIC(12, 6) NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS cost_v1_sources_usd  NUMERIC(12, 6) NOT NULL DEFAULT 0;

-- Extend the atomic increment helper with the new kinds. CREATE OR REPLACE
-- is safe — same signature, additive CASE branches.
CREATE OR REPLACE FUNCTION gecko_add_session_cost(
  p_session_id UUID,
  p_kind       TEXT,
  p_amount_usd NUMERIC
) RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
  IF p_amount_usd IS NULL OR p_amount_usd = 0 THEN
    RETURN;
  END IF;

  CASE p_kind
    WHEN 'llm' THEN
      UPDATE sessions
        SET cost_llm_usd = COALESCE(cost_llm_usd, 0) + p_amount_usd
        WHERE id = p_session_id;
    WHEN 'embed' THEN
      UPDATE sessions
        SET cost_embed_usd = COALESCE(cost_embed_usd, 0) + p_amount_usd
        WHERE id = p_session_id;
    WHEN 'tavily' THEN
      UPDATE sessions
        SET cost_tavily_usd = COALESCE(cost_tavily_usd, 0) + p_amount_usd
        WHERE id = p_session_id;
    WHEN 'deepgram' THEN
      UPDATE sessions
        SET cost_deepgram_usd = COALESCE(cost_deepgram_usd, 0) + p_amount_usd
        WHERE id = p_session_id;
    WHEN 'twitsh' THEN
      UPDATE sessions
        SET cost_twitsh_usd      = COALESCE(cost_twitsh_usd, 0) + p_amount_usd,
            cost_v1_sources_usd  = COALESCE(cost_v1_sources_usd, 0) + p_amount_usd
        WHERE id = p_session_id;
    WHEN 'v1_sources' THEN
      -- Generic V1-source bucket (HN/Reddit always 0; reserved for future
      -- paid V1 sources that don't deserve their own column yet).
      UPDATE sessions
        SET cost_v1_sources_usd = COALESCE(cost_v1_sources_usd, 0) + p_amount_usd
        WHERE id = p_session_id;
    ELSE
      RAISE EXCEPTION 'unknown cost kind: %', p_kind;
  END CASE;
END $$;

GRANT EXECUTE ON FUNCTION gecko_add_session_cost(UUID, TEXT, NUMERIC) TO service_role;
