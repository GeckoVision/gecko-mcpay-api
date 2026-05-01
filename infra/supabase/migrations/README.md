# Supabase migrations

Forward-only SQL migrations applied by both CI (`.github/workflows/e2e-smoke.yml`,
which uses `ls *.sql | sort -V`) and production (Supabase CLI).

## Filename scheme — date-prefixed only

Every migration uses `YYYYMMDDHHMMSS_<description>.sql`. Generate via:

```bash
DATE=$(date -u +%Y%m%d%H%M%S)
touch infra/supabase/migrations/${DATE}_<description>.sql
```

Under `sort -V` the timestamp prefix produces correct chronological order.
**Do not introduce a second naming scheme** (e.g. `NNN_*` legacy numbers) —
that's what caused Bug F19.

## Bug F19 — what happened and the fix (2026-04-30)

Earlier, this directory contained two filename schemes side by side:

- Date-prefixed: `20260425000000_init.sql` (the bootstrap)
- Legacy numeric: `009_session_costs_agent.sql` … `019_pulse_runs.sql`

Under `sort -V`, `009` sorts **before** `20260425`, so the numeric migrations
ran first and failed with `relation "sessions" does not exist` — `sessions` is
created by `20260425000000_init.sql`.

**Fix applied:** rename the legacy numeric files to date-prefixed slots that
sort into their correct dependency position. Mapping:

| Old name | New name |
|---|---|
| `009_session_costs_agent.sql` | `20260427000300_session_costs_agent.sql` |
| `010_pro_events.sql` | `20260427000400_pro_events.sql` |
| `011_waitlist.sql` | `20260428000100_waitlist.sql` |
| `012_x402_settlements_network.sql` | `20260428000200_x402_settlements_network.sql` |
| `013_project_wallets.sql` | `20260428000300_project_wallets.sql` |
| `015_gecko_precedent.sql` | `20260428000400_gecko_precedent.sql` |
| `017_v1_source_telemetry.sql` | `20260429000000_v1_source_telemetry.sql` |
| `018_memory.sql` | `20260429000100_memory.sql` |
| `019_pulse_runs.sql` | `20260429000200_pulse_runs.sql` |

The new timestamps respect each file's **actual** dependency order. For example
`20260428000200_x402_settlements_network.sql` (legacy `012`) needs the
`x402_tx_signature` column added in `20260426000000_x402_tx_signature.sql`, and
its new slot is correctly after that file under `sort -V`.

### Why renaming was safe

Supabase CLI tracks applied migrations by filename in
`supabase_migrations.schema_migrations`. Renaming a migration causes the CLI to
treat it as new and re-apply it. To make that re-application a no-op in
production, every renamed file was made strictly idempotent:

- `CREATE TABLE` → `CREATE TABLE IF NOT EXISTS`
- `CREATE INDEX` → `CREATE INDEX IF NOT EXISTS`
- `CREATE POLICY` → wrapped in `DO $$ ... IF NOT EXISTS (SELECT 1 FROM pg_policies ...) ...`
- `GRANT ... TO <role>` → wrapped in `DO $$ ... IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = ...) ...`

So in production, every renamed migration re-applies as a sequence of
no-op-because-already-exists statements. In a fresh DB (CI / local), they
create fresh objects.

### Why a bootstrap-roles migration was added

`20260424999999_bootstrap_roles.sql` runs before every other migration and
creates the Supabase-managed roles (`anon`, `authenticated`, `service_role`)
if they don't exist. Production already has these roles, so the migration is
a no-op there. CI / local raw Postgres needs them so the GRANT statements
later in the chain succeed.

### Why a non-CLI-numbered prefix is OK

`20260424999999` is one second before midnight on 2026-04-24, which is before
the init suite (`20260425000000_*`). On a Supabase project where the init
suite has already been applied, the CLI will see this "earlier" migration as
new on the next sync and apply it once — that's the desired behavior.

## Constraints to remember when writing new migrations

1. Date-prefixed filenames only. No legacy numeric prefixes ever again.
2. Use `IF NOT EXISTS` / `IF EXISTS` guards. Migrations should be safe to
   re-apply (Supabase CLI tracking aside).
3. RLS `CREATE POLICY` lacks `IF NOT EXISTS` — wrap in a `DO` block that
   checks `pg_policies`.
4. `GRANT` statements that target Supabase-managed roles should still work
   today because of the bootstrap migration; for new roles, follow the same
   `IF EXISTS (SELECT 1 FROM pg_roles ...)` pattern.
5. Header comment is mandatory:

   ```sql
   -- 20260501120000_<description>.sql
   -- Purpose: <one line — what this enables>.
   -- Reversible: yes/no (and what the rollback would touch).
   -- Touches: <tables, RPCs, extensions>.
   ```

## Local apply

CI uses `ls *.sql | sort -V` and applies each file with `psql -v ON_ERROR_STOP=1`.
For local dev, prefer `supabase db reset` / `supabase migration up` (Supabase
CLI handles tracking). To replicate the CI flow exactly:

```bash
PGHOST=localhost PGUSER=postgres PGPASSWORD=postgres PGDATABASE=postgres \
  bash -c 'for f in $(ls infra/supabase/migrations/*.sql | sort -V); do \
    psql -v ON_ERROR_STOP=1 -f "$f"; done'
```
