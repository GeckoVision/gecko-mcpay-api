-- 015_gecko_precedent.sql
-- Internal Gecko Flywheel — every Pro session writes a (idea_summary,
-- verdict, comparables) row. Retrieved on future sessions by cosine
-- similarity on idea_summary embedding. Privacy bound: idea_summary is
-- LLM-generated 1-sentence category abstraction; never verbatim user
-- text. CI guardrail (S2X-05) enforces <=30% character overlap.
--
-- RLS: every authenticated user can READ all rows (cross-user signal is
-- the value); can DELETE only their own (self-service privacy escape).

create table if not exists gecko_precedent (
  id uuid primary key default gen_random_uuid(),
  session_id uuid references sessions(id) on delete cascade,
  user_id uuid,                          -- nullable until frames.ag user provisioning lands
  idea_summary text not null,            -- LLM-generated 1-sentence category abstraction; NEVER verbatim
  idea_hash text not null,               -- sha256 of normalized idea (dedup key)
  category_tags text[] not null default '{}',
  verdict text not null check (verdict in ('ship','kill','pivot')),
  key_comparables jsonb not null default '[]',
  embedding vector(1536) not null,
  created_at timestamptz not null default now()
);

create index if not exists idx_gecko_precedent_embedding
  on gecko_precedent using ivfflat (embedding vector_cosine_ops)
  with (lists = 100);

create index if not exists idx_gecko_precedent_user
  on gecko_precedent (user_id) where user_id is not null;

create index if not exists idx_gecko_precedent_idea_hash
  on gecko_precedent (idea_hash);

alter table gecko_precedent enable row level security;

-- All authenticated reads allowed: the cross-session signal IS the value.
-- Anonymous reads also allowed for now since RLS upstream of /research is
-- bearer-auth at the API layer; revisit when we add Supabase auth integration.
create policy "read_all_gecko_precedent" on gecko_precedent for select using (true);

-- Users can delete only their own rows (self-service privacy escape).
create policy "delete_own_gecko_precedent" on gecko_precedent
  for delete using (auth.uid() = user_id);

comment on table gecko_precedent is
  'Internal Gecko Flywheel. Every Pro session persists a category abstraction + verdict + comparables. New sessions retrieve top-5 similar by cosine. Privacy: idea_summary is LLM-abstracted, never verbatim.';

comment on column gecko_precedent.idea_summary is
  '1-sentence LLM category abstraction. CI guardrail (test_precedent_privacy.py) asserts <=30% character overlap with original idea text.';

-- Retrieval RPC: cosine similarity = 1 - (embedding <=> query). Returns rows
-- with similarity >= threshold, ordered by similarity desc. Pre-filter on
-- threshold (not post-filter) so the ivfflat index does the heavy lifting.
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
    p.key_comparables,
    1 - (p.embedding <=> query_embedding) as similarity
  from gecko_precedent p
  where 1 - (p.embedding <=> query_embedding) >= similarity_threshold
  order by p.embedding <=> query_embedding asc
  limit match_limit;
$$;
