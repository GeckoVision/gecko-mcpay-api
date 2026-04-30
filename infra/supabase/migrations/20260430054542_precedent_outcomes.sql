-- 20260430054542_precedent_outcomes.sql
-- Purpose: tag each gecko_precedent row with a ship/kill/unknown outcome and
--          add a sidecar table for append-only outcome labels (Sprint 10 will
--          populate them; Sprint 9 ships only the schema + grouping logic).
-- Reversible: yes (drops new column + sidecar table).
-- Touches: gecko_precedent (new column + index), new precedent_outcomes table.
--
-- Design notes:
-- * `outcome` is a denormalized "current best label" on the precedent itself
--   so the retrieval RPC stays a single SELECT. Heavy provenance (who, when,
--   from which URL) lives in the sidecar so we can append labels over time
--   without rewriting the precedent.
-- * Default 'unknown' so existing rows backfill safely.
-- * RLS: read-all (matches gecko_precedent), writes via service role only.

-- 1. Add outcome column with check constraint + default 'unknown'.
alter table gecko_precedent
  add column if not exists outcome text not null default 'unknown'
    check (outcome in ('shipped', 'killed', 'unknown'));

-- Backfill is implicit via the default — existing rows land on 'unknown'.

-- Index supports cheap grouping at retrieval time. Tiny corpus today, but the
-- ivfflat search returns candidates we then split by outcome — a btree on
-- the column keeps the post-RPC group-by O(retrieved rows) regardless of
-- corpus growth.
create index if not exists idx_gecko_precedent_outcome
  on gecko_precedent (outcome);

comment on column gecko_precedent.outcome is
  'Ship/kill outcome label for the idea this precedent represents. Default unknown; auto-labeling lands in Sprint 10. Retrieval groups by this column for the critic agent context block.';

-- 2. Sidecar table for append-only outcome labels.
create table if not exists precedent_outcomes (
  id uuid primary key default gen_random_uuid(),
  precedent_id uuid not null references gecko_precedent(id) on delete cascade,
  outcome text not null check (outcome in ('shipped', 'killed', 'unknown')),
  source_url text,                              -- evidence URL (TechCrunch, founder tweet, etc.)
  labeled_at timestamptz not null default now(),
  labeled_by text                               -- 'auto:gpt-4o', 'manual:ernani', etc.
);

create index if not exists idx_precedent_outcomes_precedent
  on precedent_outcomes (precedent_id);

create index if not exists idx_precedent_outcomes_labeled_at
  on precedent_outcomes (labeled_at desc);

comment on table precedent_outcomes is
  'Append-only label history for gecko_precedent rows. The denormalized current label lives on gecko_precedent.outcome; this table is the audit trail (who/when/from-where).';

alter table precedent_outcomes enable row level security;

-- Read-all matches the gecko_precedent policy: cross-session label signal
-- IS the value. Writes are service-role-only (the API and labeling job both
-- use the service-role key; no end-user write path exists).
create policy "read_all_precedent_outcomes" on precedent_outcomes
  for select using (true);

-- 3. Update the retrieval RPC to project the new column. Drop+create because
-- Postgres will not let us add a return column to an existing function.
drop function if exists gecko_precedent_match(vector, float, int);

create or replace function gecko_precedent_match(
  query_embedding vector(1536),
  similarity_threshold float,
  match_limit int
)
returns table (
  id uuid,
  session_id uuid,
  user_id uuid,
  idea_summary text,
  verdict text,
  outcome text,
  key_comparables jsonb,
  similarity float
)
language sql stable as $$
  select
    p.id,
    p.session_id,
    p.user_id,
    p.idea_summary,
    p.verdict,
    p.outcome,
    p.key_comparables,
    1 - (p.embedding <=> query_embedding) as similarity
  from gecko_precedent p
  where 1 - (p.embedding <=> query_embedding) >= similarity_threshold
  order by p.embedding <=> query_embedding asc
  limit match_limit;
$$;
