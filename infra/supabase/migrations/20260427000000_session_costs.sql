-- 20260427000000_session_costs.sql
-- Purpose: track real per-session unit economics — what we charged vs what we
--          actually spent on LLM, embeddings, Tavily, and Deepgram. Lets us
--          see margin (or lack of it) per run instead of guessing at pricing.
-- Reversible: yes (additive only; columns are nullable / default 0).
-- Touches: table `sessions`.
--
-- Notes:
-- - cost_total_usd and margin_usd are STORED generated columns so dashboards
--   can index/sort on them without recomputing.
-- - Currency is USD throughout. We do NOT store the on-chain USDC raw amount
--   here — that lives on the x402 transaction (see x402_tx_signature).
-- - NUMERIC(12,6) gives micro-cent precision (LLM tokens are fractional cents).

ALTER TABLE sessions
  ADD COLUMN IF NOT EXISTS price_usd          NUMERIC(12, 6),
  ADD COLUMN IF NOT EXISTS cost_llm_usd       NUMERIC(12, 6) NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS cost_embed_usd     NUMERIC(12, 6) NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS cost_tavily_usd    NUMERIC(12, 6) NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS cost_deepgram_usd  NUMERIC(12, 6) NOT NULL DEFAULT 0;

-- Drop and recreate generated columns idempotently. Postgres doesn't have
-- ADD COLUMN IF NOT EXISTS for GENERATED columns combined with the GENERATED
-- expression in all versions, so we wrap in DO blocks.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'sessions' AND column_name = 'cost_total_usd'
  ) THEN
    ALTER TABLE sessions
      ADD COLUMN cost_total_usd NUMERIC(12, 6)
      GENERATED ALWAYS AS (
        COALESCE(cost_llm_usd, 0)
        + COALESCE(cost_embed_usd, 0)
        + COALESCE(cost_tavily_usd, 0)
        + COALESCE(cost_deepgram_usd, 0)
      ) STORED;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'sessions' AND column_name = 'margin_usd'
  ) THEN
    ALTER TABLE sessions
      ADD COLUMN margin_usd NUMERIC(12, 6)
      GENERATED ALWAYS AS (
        COALESCE(price_usd, 0)
        - COALESCE(cost_llm_usd, 0)
        - COALESCE(cost_embed_usd, 0)
        - COALESCE(cost_tavily_usd, 0)
        - COALESCE(cost_deepgram_usd, 0)
      ) STORED;
  END IF;
END $$;

-- Atomic increment helper. Avoids read-modify-write races when multiple
-- ingestion adapters run in parallel and each adds its own cost line.
-- Use: SELECT gecko_add_session_cost('<uuid>', 'llm', 0.0042);
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
    ELSE
      RAISE EXCEPTION 'unknown cost kind: %', p_kind;
  END CASE;
END $$;

GRANT EXECUTE ON FUNCTION gecko_add_session_cost(UUID, TEXT, NUMERIC) TO service_role;
