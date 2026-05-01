-- 20260424999999_bootstrap_roles.sql
-- Purpose: ensure the Supabase-managed roles (anon, authenticated, service_role)
--          exist before any subsequent migration GRANTs to them. Production
--          (Supabase) has these roles preinstalled; raw Postgres environments
--          (CI's pgvector/pgvector image, local dev with bare Postgres) do not.
-- Reversible: no (roles outlive migrations; do not drop in production).
-- Touches: roles only — no schema objects.
--
-- Bug F19 (2026-04-30): the legacy numeric migrations (009-019) were renamed
-- to date-prefixed names so `sort -V` orders them correctly. With ordering
-- fixed, CI now reaches the GRANT statements in 20260425000300_doctor_rpcs.sql
-- first; without the Supabase role set, those GRANTs fail. This migration
-- creates the roles idempotently as the FIRST applied migration so all
-- downstream GRANTs work in both production (no-ops, roles already exist)
-- and CI / fresh local dev.
--
-- Filename uses the 999999 suffix so it sorts strictly before the init suite
-- (20260425000000_init.sql) under any ASCII / -V sort.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
    CREATE ROLE anon NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
    CREATE ROLE authenticated NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
    CREATE ROLE service_role NOLOGIN BYPASSRLS;
  END IF;
END $$;
