-- 20260501140000_chunks_write_audit.sql
-- Purpose: per-source-batch audit row written by the ingestion pipeline so
--          we can classify chunk-write failure modes (FM-1/FM-2/FM-3 from
--          docs/diagnostics/2026-05-01-chunk-write-failures.md) without
--          grepping unstructured stdout. Sprint 16 Track A — observability
--          BEFORE fix; S16-INGEST-02/03 will use these counts to decide
--          which broken path to repair first.
-- Reversible: yes (drops the table — pure observability, no business data).
-- Touches: new table `chunks_write_audit`. No existing rows changed.
--
-- error_kind canonical set (single source of truth — see Pattern A in CLAUDE.md):
--   gecko_core.ingestion.audit.ErrorKind
-- Adding a value = touch exactly one Python file (audit.py) + one migration
-- (a new file that ALTERs the CHECK below). Never edit this file in place.

CREATE TABLE IF NOT EXISTS chunks_write_audit (
  id            UUID NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
  session_id    UUID NOT NULL,
  source_id     UUID,
  batch_size    INT  NOT NULL,
  succeeded     INT  NOT NULL,
  failed        INT  NOT NULL,
  error_kind    TEXT NOT NULL,
  embed_model   TEXT,
  captured_at   TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT chunks_write_audit_error_kind_check CHECK (
    error_kind IN (
      'none',
      'toast_limit',
      'pool_timeout',
      'rls_denied',
      'embedding_null',
      'dim_mismatch',
      'supabase_5xx',
      'partial_batch',
      'unknown'
    )
  ),
  CONSTRAINT chunks_write_audit_counts_nonneg CHECK (
    batch_size >= 0 AND succeeded >= 0 AND failed >= 0
  )
);

-- Read pattern A: bb doctor --recent rolls up last 7 days by error_kind.
--   SELECT error_kind, count(*) FROM chunks_write_audit
--   WHERE captured_at > now() - interval '7 days'
--   GROUP BY error_kind;
CREATE INDEX IF NOT EXISTS chunks_write_audit_error_kind_captured_at_idx
  ON chunks_write_audit (error_kind, captured_at DESC);

-- Read pattern B: per-session debug — list every batch this session emitted.
--   SELECT * FROM chunks_write_audit
--   WHERE session_id = $1 ORDER BY captured_at DESC;
CREATE INDEX IF NOT EXISTS chunks_write_audit_session_captured_at_idx
  ON chunks_write_audit (session_id, captured_at DESC);

COMMENT ON TABLE chunks_write_audit IS
  'S16-INGEST-01 — one row per ingestion source-batch exit. error_kind set '
  'mirrors gecko_core.ingestion.audit.ErrorKind. Service-role only; never '
  'expose to anon / web app. Acceptance: zero unknown rows on the 4 ideas '
  'in tests/eval/live_runs/2026-04-30-*.json.';
