-- Credits system — ledger tables (pre-prod Phase 2; replaces the bypass).
-- Plan: docs/superpowers/plans/2026-06-10-credits-system-and-solana-pay.md
--
-- The append-only credit_ledger is the source of truth; `credits` is a
-- materialized convenience row (balance = sum of ledger amounts).
-- The kind CHECK mirrors gecko_core.credits.CreditKind (Pattern A): adding a
-- kind = touch that Literal + this migration.

create table if not exists credits (
    user_id        text primary key,
    balance        numeric    not null default 0,
    granted_total  numeric    not null default 0,
    spent_total    numeric    not null default 0,
    tab_floor      numeric    not null default 0,
    updated_at     timestamptz not null default now()
);

create table if not exists credit_ledger (
    id          bigserial primary key,
    user_id     text        not null,
    kind        text        not null check (kind in ('grant', 'comp', 'debit', 'topup', 'settle')),
    amount      numeric     not null,   -- signed: debit negative, all others positive
    ref         text,                   -- tx signature / session_id / admin note
    created_at  timestamptz not null default now()
);

create index if not exists credit_ledger_user_idx on credit_ledger (user_id, created_at);

-- RLS: a user sees only their own rows; service-role writes the ledger.
alter table credits enable row level security;
alter table credit_ledger enable row level security;
