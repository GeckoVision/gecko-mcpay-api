-- 20260501120000_session_costs_commoditization.sql
-- Purpose: Sprint 13 Track E (S13-COMMO-01/02/03) — track per-session spend on
--          commoditization SKUs (advisor voices, ask follow-ups, classify).
--          Each gets its own column so `bb economics` can render line items.
-- Reversible: yes (additive only; columns nullable / default 0).
-- Touches: table `sessions`; function `gecko_add_session_cost`;
--          generated columns `cost_total_usd` + `margin_usd`.
--
-- Notes:
-- - Each new kind is its own column for clean line-item rendering. We do NOT
--   roll them into cost_llm_usd because the SKUs are *priced calls* (revenue
--   on the gecko side when the user paid us, OR external upstream cost when
--   another agent paid us — currently they're symmetric on devnet).
-- - Track E ships in stub mode only (S13 acceptance), but the columns work
--   identically once live x402 settles populate them via add_cost.

ALTER TABLE sessions
  ADD COLUMN IF NOT EXISTS cost_advisor_usd  NUMERIC(12, 6) NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS cost_ask_usd      NUMERIC(12, 6) NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS cost_classify_usd NUMERIC(12, 6) NOT NULL DEFAULT 0;

-- Counters: surface free-quota usage in /sessions/{id}/economics so the
-- client knows when the next /ask call will flip from free to paid.
ALTER TABLE sessions
  ADD COLUMN IF NOT EXISTS ask_calls_count   INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS advisor_calls_count INTEGER NOT NULL DEFAULT 0;

-- Recreate generated total + margin columns to include the new kinds.
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'sessions' AND column_name = 'cost_total_usd'
  ) THEN
    ALTER TABLE sessions DROP COLUMN cost_total_usd;
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'sessions' AND column_name = 'margin_usd'
  ) THEN
    ALTER TABLE sessions DROP COLUMN margin_usd;
  END IF;
END $$;

ALTER TABLE sessions
  ADD COLUMN cost_total_usd NUMERIC(12, 6)
  GENERATED ALWAYS AS (
    COALESCE(cost_llm_usd, 0)
    + COALESCE(cost_embed_usd, 0)
    + COALESCE(cost_tavily_usd, 0)
    + COALESCE(cost_deepgram_usd, 0)
    + COALESCE(cost_twitsh_usd, 0)
    + COALESCE(cost_v1_sources_usd, 0)
    + COALESCE(cost_advisor_usd, 0)
    + COALESCE(cost_ask_usd, 0)
    + COALESCE(cost_classify_usd, 0)
  ) STORED;

ALTER TABLE sessions
  ADD COLUMN margin_usd NUMERIC(12, 6)
  GENERATED ALWAYS AS (
    COALESCE(price_usd, 0)
    - COALESCE(cost_llm_usd, 0)
    - COALESCE(cost_embed_usd, 0)
    - COALESCE(cost_tavily_usd, 0)
    - COALESCE(cost_deepgram_usd, 0)
    - COALESCE(cost_twitsh_usd, 0)
    - COALESCE(cost_v1_sources_usd, 0)
    - COALESCE(cost_advisor_usd, 0)
    - COALESCE(cost_ask_usd, 0)
    - COALESCE(cost_classify_usd, 0)
  ) STORED;

-- Extend the atomic increment helper. Same signature; additive CASE branches.
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
      UPDATE sessions
        SET cost_v1_sources_usd = COALESCE(cost_v1_sources_usd, 0) + p_amount_usd
        WHERE id = p_session_id;
    WHEN 'advisor' THEN
      UPDATE sessions
        SET cost_advisor_usd     = COALESCE(cost_advisor_usd, 0) + p_amount_usd,
            advisor_calls_count  = COALESCE(advisor_calls_count, 0) + 1
        WHERE id = p_session_id;
    WHEN 'ask' THEN
      UPDATE sessions
        SET cost_ask_usd      = COALESCE(cost_ask_usd, 0) + p_amount_usd,
            ask_calls_count   = COALESCE(ask_calls_count, 0) + 1
        WHERE id = p_session_id;
    WHEN 'classify' THEN
      UPDATE sessions
        SET cost_classify_usd = COALESCE(cost_classify_usd, 0) + p_amount_usd
        WHERE id = p_session_id;
    ELSE
      RAISE EXCEPTION 'unknown cost kind: %', p_kind;
  END CASE;
END $$;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
    GRANT EXECUTE ON FUNCTION gecko_add_session_cost(UUID, TEXT, NUMERIC) TO service_role;
  END IF;
END $$;
