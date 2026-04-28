# Per-project vaults: v1 → v2 schema transition

## v1 (Shipathon)

Migration: `infra/supabase/migrations/20260428000000_projects.sql`.

A `projects` row is a named, budgeted grouping of sessions owned by one
frames.ag user. Budget enforcement is **client-side**: the gecko-mcp
api_client calls `gecko_project_budget_remaining(project_id)` before issuing
a paid run and refuses if the result is `<= 0`. The DB does not block paid
inserts that overrun budget — keeps the schema simple and lets us evolve
enforcement without another migration.

Wallet isolation in v1 is **policy-bounded, not cryptographic**. All
sessions across all of a user's projects pay from the same frames.ag wallet;
a frames.ag policy key caps total spend at the user level. `wallet_address`
is `NULL` and `wallet_provider` is `'frames-policy'`. Trust model: we trust
frames.ag to enforce the user-level ceiling, and we trust ourselves to honor
each project's `budget_usd` in api_client. Adequate for hackathon; not
adequate for a paying B2B customer who wants project A's overrun to never
touch project B's budget.

## v2 (post-Shipathon)

The big change is **one Privy wallet per project**. Each project gets its
own Solana keypair held by Privy and signed by a Gecko-owned authorization
key. A runaway project can drain its own wallet but can't touch any other
project's funds. `wallet_address` becomes the Privy-provisioned address,
`wallet_provider` flips to `'privy-direct'`.

Sketch (do not migrate yet):

```sql
-- Gecko-owned authorization keys. Rotated; old keys retire (not delete).
CREATE TABLE privy_authorization_keys (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  key_id       TEXT NOT NULL UNIQUE,        -- Privy's identifier
  public_key   TEXT NOT NULL,
  scope        TEXT NOT NULL CHECK (scope IN ('production', 'staging')),
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  retired_at   TIMESTAMPTZ
);

-- Named policy templates we attach to projects ('frugal', 'default',
-- 'pro-research', 'unbounded'). Hand-curated; one row per template.
CREATE TABLE privy_policy_templates (
  id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name                 TEXT NOT NULL UNIQUE,
  privy_policy_id      TEXT NOT NULL,
  description          TEXT,
  max_per_tx_usd       NUMERIC(12, 6),
  daily_limit_usd      NUMERIC(12, 6),
  allowed_facilitators TEXT[] NOT NULL DEFAULT '{}',
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Join: which template + which auth key currently govern a project.
-- Historical rows kept for audit; `active` flag picks the live one.
CREATE TABLE project_policy_assignments (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id          UUID NOT NULL REFERENCES projects(id),
  template_id         UUID NOT NULL REFERENCES privy_policy_templates(id),
  auth_key_id         UUID NOT NULL REFERENCES privy_authorization_keys(id),
  active              BOOLEAN NOT NULL DEFAULT TRUE,
  assigned_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  superseded_at       TIMESTAMPTZ
);
```

## Backfill policy

**Don't backfill v1 projects.** When v2 ships, existing projects keep
`wallet_provider = 'frames-policy'` and continue working as-is. Only
projects created after the v2 cutover get Privy wallets. Reasoning: the
v1 → v2 jump requires a wallet provisioning step that costs real SOL for
rent; we'd rather have users opt in by creating a new project than pay to
migrate dormant ones. The api_client branches on `wallet_provider` so both
modes coexist forever.

## Per-step cost table

**Defer to Phase B.1.** Adding a `project_steps` table now (one row per
LLM/embed/Tavily call with timestamp + cost) would let us draw nice
per-project burn-down charts, but the existing `cost_*_usd` columns on
sessions plus structured logs already cover every billing question we can
answer at hackathon scale. Revisit when a user actually asks "show me where
my $40 went on this project."
