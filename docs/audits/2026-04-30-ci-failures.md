# CI failures triage — 2026-04-30

Two CI failures surfaced on commit `0cd2960` (Theme 2 expansion docs commit). Triaged below; one fixed inline, one needs data-engineer judgment before fixing.

---

## Bug F19 — Migration ordering broken: 009 runs before sessions exists

**Workflow:** `e2e-smoke` (commit `0cd2960`)

**Error:**
```
psql:infra/supabase/migrations/009_session_costs_agent.sql:25:
ERROR:  relation "sessions" does not exist
```

**Root cause:**
The migrations directory contains TWO naming schemes:
- Numeric: `009_session_costs_agent.sql` ... `019_pulse_runs.sql`
- Date-prefixed: `20260425000000_init.sql` ... `20260427000000_session_costs.sql`

`sort -V` lexicographically treats `009` as smaller than `20260425`, so applies in order:
```
009_session_costs_agent.sql       ← runs FIRST, references sessions
010_pro_events.sql
...
019_pulse_runs.sql
20260425000000_init.sql           ← creates sessions, runs LAST among inits
20260425000100_pgvector_index.sql
...
```

`sessions` is created by `20260425000000_init.sql`. So 009 fails with "relation sessions does not exist."

**Why this didn't fail before:**
- Numeric migrations 009-019 predate the date-prefixed init (per `git log --diff-filter=A`)
- Earlier numeric migrations 001-008 created `sessions` originally
- At some point those were deleted/replaced when `20260425000000_init.sql` was added in commit `cbc5cfb` ("ship: production-ready Gecko platform") — but the numeric 009-019 were left behind
- The date-prefixed init uses `CREATE TABLE IF NOT EXISTS`, suggesting it was meant to be a re-runnable bootstrap, but its sort position guarantees it can't precede 009 under `sort -V`

**Fix options (data-engineer must choose):**

(a) **Renumber: rename 009-019 to date-prefixed format that sorts after `20260425*`.**
Example: `009_session_costs_agent.sql` → `20260425100000_session_costs_agent.sql`. Risk: if any migration runner tracks applied filenames in a tracking table, this breaks tracking. Need to verify Supabase's apply mechanism.

(b) **Custom sort in CI script.** Replace `sort -V` with a sort that ranks date-prefixed migrations first, then numeric. Risk: drift between local dev and CI behavior.

(c) **Single ordering scheme.** Convert ALL migrations to date-prefixed (or all numeric). Cleanest long-term; biggest one-time refactor.

**Severity:** P0 — blocks every CI run. e2e-smoke fails on every PR until fixed.

**Owner:** data-engineer (with staff-engineer arbitration if production has applied state we'd disturb).

**Sprint slot:** **Sprint 12 hotfix** — must land before any other Sprint 12 track ships, because Track A (CDP listing) and Track B (Bazaar declarations) need a working CI to merge safely.

---

## Bug F20 — `dotenv` missing from root dev deps

**Workflow:** `Pro tier eval (mock) #3`

**Error:**
```
ERROR tests/eval/test_suite_no_leakage.py
ModuleNotFoundError: No module named 'dotenv'
```

**Root cause:**
- `tests/conftest.py:17` imports `from dotenv import load_dotenv` at collection time
- `python-dotenv` is declared in: `apps/cli/pyproject.toml`, `packages/gecko-api/pyproject.toml`, `packages/gecko-mcp/pyproject.toml`
- NOT declared in: root workspace `pyproject.toml [dependency-groups] dev`
- CI's `Pro tier eval (mock)` workflow installs only the dev group, NOT the per-package deps, so `dotenv` is missing for test collection

**Fix:** added `python-dotenv>=1.0` to root `pyproject.toml [dependency-groups] dev` with comment explaining why.

**Severity:** P0 — blocks Pro tier eval workflow on every run.

**Owner:** software-engineer (just fixed inline).

**Status:** ✅ FIXED in this commit.

---

## Bug card summary

| ID | Severity | Owner | Status | Sprint slot |
|---|---|---|---|---|
| F19 | P0 | data-engineer | OPEN | S12 hotfix (pre-fire) |
| F20 | P0 | software-engineer | ✅ FIXED | this commit |

F19 must land before Sprint 12 fires — otherwise Track A/B/C can't merge.
