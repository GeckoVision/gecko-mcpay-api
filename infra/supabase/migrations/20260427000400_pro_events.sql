-- 20260427000400_pro_events.sql (renamed from 010_pro_events.sql, F19, 2026-04-30)
-- Purpose: append-only event log that the Pro-tier SSE endpoint tails.
--          Producers write turn_start/turn_end/final/error events with a
--          monotonic per-session `seq`; the SSE handler poll-tails by
--          (session_id, id > last_id).
-- Reversible: yes (drops the new table and its index).
-- Touches: pro_events (new), references sessions.
--
-- Notes:
-- - BIGSERIAL `id` because the event log will grow unboundedly across all
--   sessions; INT would wrap.
-- - UNIQUE (session_id, seq) enforces producer-side ordering invariants.
-- - Index on (session_id, id) is required for the tail-poll query
--     SELECT * FROM pro_events
--      WHERE session_id = $1 AND id > $last_id
--      ORDER BY id LIMIT 50;
--   The PK on `id` alone doesn't help that filter (no session_id prefix),
--   and the UNIQUE (session_id, seq) sorts by seq not id.
-- - ON DELETE CASCADE: deleting a session drops all its events; events have
--   no value without their parent session.
-- - RLS intentionally NOT enabled. gecko-api uses the service role key and
--   authorizes per-session via the existing bearer-auth dependency
--   (frames.ag apiToken -> session ownership check). When the web app gets
--   direct read access (post-V2), revisit and add RLS keyed on
--   sessions.frames_username = auth.jwt()->>'username'.

CREATE TABLE IF NOT EXISTS pro_events (
  id          BIGSERIAL PRIMARY KEY,
  session_id  UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  seq         INT  NOT NULL,
  event_type  TEXT NOT NULL CHECK (event_type IN ('turn_start','turn_end','final','error')),
  agent       TEXT,
  content     TEXT NOT NULL,
  tokens_in   INT  NOT NULL DEFAULT 0,
  tokens_out  INT  NOT NULL DEFAULT 0,
  ts          DOUBLE PRECISION NOT NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (session_id, seq)
);

CREATE INDEX IF NOT EXISTS idx_pro_events_tail ON pro_events (session_id, id);
