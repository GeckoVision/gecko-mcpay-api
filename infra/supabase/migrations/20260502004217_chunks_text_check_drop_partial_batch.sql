-- 20260502004217_chunks_text_check_drop_partial_batch.sql
-- Purpose: S16-INGEST-02 — fix two of the failure modes called out in
--          docs/diagnostics/2026-05-01-chunk-write-failures.md.
--          (1) Add CHECK (length(text) > 0) on chunks.text so a
--              whitespace-only / empty chunk can never persist; today
--              `_filter_embeddable` is the only line of defense.
--          (2) Drop `partial_batch` from chunks_write_audit.error_kind:
--              once `insert_chunks` becomes transactional + ON CONFLICT,
--              FM-1 (silent partial-batch drop) is unreachable. Removing
--              the bucket from the SQL CHECK + the Python ErrorKind
--              keeps Pattern A clean (single source of truth).
-- Reversible: partially. The text CHECK is drop-only-if-needed; the
--             error_kind ALTER recreates the constraint with a tighter
--             value set. Old rows containing 'partial_batch' (legacy
--             FM-1 audit history pre-S16-INGEST-02) get rewritten to
--             'unknown' so the new CHECK accepts them.
-- Touches: chunks (new CHECK), chunks_write_audit (re-CHECK + data backfill).
--
-- error_kind canonical set (single source of truth — see Pattern A in CLAUDE.md):
--   gecko_core.ingestion.audit.ErrorKind
-- Adding/removing a value = touch exactly one Python file (audit.py) + one
-- migration (this file pattern). Schema-drift test in
-- packages/gecko-core/tests/test_audit_error_kind_consistency.py enforces
-- equality between the SQL CHECK and the Python Literal.

-- ---------------------------------------------------------------------------
-- (1) chunks.text — non-empty CHECK.
-- ---------------------------------------------------------------------------
-- Pre-flight validation lives in `gecko_core.ingestion.exceptions.ChunkValidationError`
-- so we never round-trip a doomed insert. The DB CHECK is the belt-and-braces
-- backstop in case the pre-flight ever regresses.
ALTER TABLE chunks
  ADD CONSTRAINT chunks_text_nonempty_check
    CHECK (length(text) > 0);

-- ---------------------------------------------------------------------------
-- (2) chunks_write_audit.error_kind — drop 'partial_batch'.
-- ---------------------------------------------------------------------------
-- Backfill any historical 'partial_batch' rows (pre-S16-INGEST-02 dogfood
-- runs) into 'unknown' so the new CHECK accepts them. We don't lose
-- forensic value: those rows were emitted *because* FM-1 just happened,
-- and the bucket they roll up into post-fix is "we couldn't classify it"
-- — which is exactly right for legacy data.
UPDATE chunks_write_audit
   SET error_kind = 'unknown'
 WHERE error_kind = 'partial_batch';

ALTER TABLE chunks_write_audit
  DROP CONSTRAINT chunks_write_audit_error_kind_check;

ALTER TABLE chunks_write_audit
  ADD CONSTRAINT chunks_write_audit_error_kind_check CHECK (
    error_kind IN (
      'none',
      'toast_limit',
      'pool_timeout',
      'rls_denied',
      'embedding_null',
      'dim_mismatch',
      'supabase_5xx',
      'unknown'
    )
  );
