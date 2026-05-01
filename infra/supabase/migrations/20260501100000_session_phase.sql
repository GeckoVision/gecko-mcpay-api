-- 20260501100000_session_phase.sql
-- Purpose: S13-PHASE-01 — introduce SessionPhase + parent_session_id on
--          sessions so the same persistence layer can carry pre-product
--          research, during-build pulses, and ongoing operational sessions.
--          parent_session_id is the linkage edge S14 gecko_pulse rides on
--          (a pulse session's parent is the pre_product research that
--          spawned it).
-- Reversible: yes (additive; new columns + check constraint + FK + index).
-- Touches: sessions table only. No data movement; existing rows default to
--          phase = 'pre_product' so legacy callers stay unchanged.
--
-- Notes:
--  - phase is TEXT + CHECK rather than a Postgres ENUM. Two reasons: enum
--    ALTERs are non-trivial when we add 'launching' / 'sunset' later; and
--    Supabase's PostgREST round-trips enums as strings anyway, so we lose
--    nothing on the wire.
--  - parent_session_id self-FKs sessions(id). NOT cascading on delete —
--    soft-delete is the contract; hard-deleting a parent that has children
--    should fail loudly so we notice.
--  - No index on parent_session_id yet. Add one when the pulse history
--    query (S14) lands and EXPLAIN shows we need it; "just in case"
--    indexes are forbidden per data-engineer charter.

ALTER TABLE sessions
  ADD COLUMN IF NOT EXISTS phase TEXT NOT NULL DEFAULT 'pre_product'
    CHECK (phase IN ('pre_product', 'during_build', 'ongoing')),
  ADD COLUMN IF NOT EXISTS parent_session_id UUID
    REFERENCES sessions(id);
