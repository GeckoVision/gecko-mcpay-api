-- Doctor RPCs used by `gecko-mcp doctor` for connectivity + schema introspection.
-- Both are SECURITY DEFINER and read-only.

CREATE OR REPLACE FUNCTION public.gecko_doctor_ping()
RETURNS jsonb
LANGUAGE sql
STABLE
AS $$
  SELECT jsonb_build_object('ok', true, 'now', now());
$$;

CREATE OR REPLACE FUNCTION public.gecko_doctor_manifest()
RETURNS jsonb
LANGUAGE sql
STABLE
AS $$
  SELECT jsonb_build_object(
    'extensions', (
      SELECT coalesce(jsonb_agg(extname ORDER BY extname), '[]'::jsonb)
      FROM pg_extension
      WHERE extname IN ('vector', 'pgcrypto')
    ),
    'tables', (
      SELECT coalesce(jsonb_agg(tablename ORDER BY tablename), '[]'::jsonb)
      FROM pg_tables
      WHERE schemaname = 'public'
        AND tablename IN ('sessions', 'sources', 'chunks')
    ),
    'functions', (
      SELECT coalesce(jsonb_agg(proname ORDER BY proname), '[]'::jsonb)
      FROM pg_proc p
      JOIN pg_namespace n ON n.oid = p.pronamespace
      WHERE n.nspname = 'public'
        AND proname IN ('match_chunks', 'gecko_doctor_ping', 'gecko_doctor_manifest')
    )
  );
$$;

GRANT EXECUTE ON FUNCTION public.gecko_doctor_ping() TO anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.gecko_doctor_manifest() TO anon, authenticated, service_role;
