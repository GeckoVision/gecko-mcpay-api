-- 20260425000000_init.sql
-- Purpose: bootstrap the core schema — sessions, sources, chunks — with pgvector.
-- Reversible: no (drops would lose data; soft-delete via deleted_at instead).
-- Touches: extension `vector`, tables `sessions`, `sources`, `chunks`.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS sessions (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  idea              TEXT NOT NULL,
  tier              TEXT NOT NULL CHECK (tier IN ('basic', 'pro')),
  status            TEXT NOT NULL DEFAULT 'pending'
                       CHECK (status IN ('pending', 'indexing', 'generating', 'complete', 'failed')),
  payment_intent_id TEXT UNIQUE,
  payment_mode      TEXT NOT NULL DEFAULT 'stub'
                       CHECK (payment_mode IN ('stub', 'live', 'frames')),
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at      TIMESTAMPTZ,
  deleted_at        TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS sources (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id   UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  url          TEXT NOT NULL,
  url_hash     TEXT NOT NULL,
  type         TEXT NOT NULL CHECK (type IN ('youtube', 'web')),
  chunk_count  INT NOT NULL DEFAULT 0,
  indexed_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (session_id, url_hash)
);

CREATE TABLE IF NOT EXISTS chunks (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id   UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  source_id    UUID NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  chunk_index  INT NOT NULL,
  text         TEXT NOT NULL,
  embedding    VECTOR(1536) NOT NULL,
  UNIQUE (source_id, chunk_index)
);
