-- restore_dropped_tables.sql
-- Re-create the 3 tables dropped in the 2026-06-07 remodel, IF you need any back.
-- DDL is verbatim from docs/db-model/old_db_schema.sql (the pre-drop schema).
--
-- ⚠️ SCHEMA ONLY — this restores the empty table structure, NOT the data.
--    The rows are gone unless you took the pg_dump backup the remodel migration
--    instructed before dropping. To restore DATA, run instead:
--        psql "$DATABASE_URL" < backup_<table>_YYYYMMDD.sql
--    (the dump includes both DDL and COPY data). Use THIS file only when you
--    just want the empty table back (e.g. to re-point code at it).
--
-- Each is independent — run only the block(s) you need. IF NOT EXISTS so it's
-- safe to run when the table already exists.

-- creators — abandoned Pioneer/creator-attribution (zero live refs).
CREATE TABLE IF NOT EXISTS public.creators (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  handle text NOT NULL,
  platform text NOT NULL,
  wallet_addr text,
  earnings_pending numeric NOT NULL DEFAULT 0,
  claimed_at timestamp with time zone,
  CONSTRAINT creators_pkey PRIMARY KEY (id)
);

-- session_outputs — old research outputs (business_plan/validation/prd),
-- superseded by sessions.result_json (zero live refs).
CREATE TABLE IF NOT EXISTS public.session_outputs (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  session_id uuid NOT NULL,
  output_type text NOT NULL CHECK (output_type = ANY (ARRAY['business_plan'::text, 'validation'::text, 'prd'::text])),
  content_md text,
  content_json jsonb,
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT session_outputs_pkey PRIMARY KEY (id)
);
-- NOTE: the original had no FK on session_id; if you want referential integrity
-- back, add:  ALTER TABLE public.session_outputs
--   ADD CONSTRAINT session_outputs_session_fk FOREIGN KEY (session_id)
--   REFERENCES public.sessions(id) ON DELETE CASCADE;  -- (was NOT present originally)

-- tavily_extract_cache — large raw-HTML extract cache for the bb research
-- ingestion pipeline (only a dead constant referenced it).
CREATE TABLE IF NOT EXISTS public.tavily_extract_cache (
  url_hash text NOT NULL,
  url text NOT NULL,
  raw_content text NOT NULL,
  fetched_at timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT tavily_extract_cache_pkey PRIMARY KEY (url_hash)
);
