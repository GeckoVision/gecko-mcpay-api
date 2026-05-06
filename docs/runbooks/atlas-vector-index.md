# Atlas Vector Index Runbook

Owned by `data-engineer`. Procedure for managing the `chunks_vector` and
`chunks_text` Atlas Search indexes on the `gecko_rag.chunks` collection.

## Why filterable beats post-filter

Atlas Search's `vectorSearch` index accepts filter fields declared at
build time. A `$vectorSearch.filter` clause then pushes the filter
**before** the ANN graph traversal — Atlas only walks vectors that
match the filter, instead of running ANN over the whole collection
and dropping non-matches afterward.

Without filterable fields, the only way to scope retrieval by
`(vertical, category, source, deprecated)` is a `$match` AFTER
`$vectorSearch`. That post-filter wastes ANN budget: `$vectorSearch`
returns `limit` rows total across all tenants; if you want top-K
within `neobank` but 90% of the collection is `dex`, you get a
near-empty slate. Increasing `numCandidates` doesn't help — it scales
superlinearly and still doesn't guarantee survival of enough matches.

Pre-filter is the multi-tenant performance fix.

## Procedure: dry-run → review → apply

The script `scripts/mongo/s20_rag02_filterable_index.py` defaults to
**dry-run**. No Atlas mutations happen unless `--apply` is passed.

### 1. Dry-run

```bash
uv run python -m scripts.mongo.s20_rag02_filterable_index --dry-run
```

Prints the intended index definition (vector + text) as JSON. No
network calls.

### 2. Apply (creation case — no existing index)

```bash
uv run python -m scripts.mongo.s20_rag02_filterable_index --apply
```

If `chunks_vector` is missing, creates it. If it's already up-to-date,
exits cleanly (idempotent — re-runs are safe).

### 3. Apply with drift (rebuild case)

If the live index exists but is missing one or more expected filter
paths, the script REJECTS the apply with:

```
REJECTED: chunks_vector: drift detected ([...] missing) — pass --rebuild to drop + re-create
```

To proceed:

```bash
uv run python -m scripts.mongo.s20_rag02_filterable_index --apply --rebuild
```

**Operational risk of `--rebuild`:**

- Atlas drops the index, then re-creates it.
- Vector reads against `chunks_vector` will fail or fall back to
  exhaustive scan during the rebuild window (typically ~minutes for
  current collection size, longer at scale).
- Run during a low-traffic window. Demo-time rebuilds will visibly
  hang queries.

## Doctor check

`gecko-mcp doctor` surfaces two related rows:

- `chunk_store:mongo:index:chunks_vector:dim` — dimension matches
  `MONGO_VECTOR_DIM_EXPECTED` (1024 for Voyage). FAIL means the
  index was built at the wrong dim and Atlas rejects every insert.
- `chunk_store:mongo:index:chunks_vector:filters` — all
  `CHUNKS_VECTOR_FILTER_FIELDS` paths are declared filterable on the
  live index. FAIL means RAG queries can't pre-filter; either:
  - `no filter fields declared` → run the migration script with
    `--apply --rebuild`.
  - `missing filter: <path>` → one or more new filter fields haven't
    been built yet; same fix.

## Source of truth (Pattern A)

Filter-field paths are declared in exactly one place:
`gecko_core.db.mongo.CHUNKS_VECTOR_FILTER_FIELDS` (plus the legacy
filter list `CHUNKS_VECTOR_LEGACY_FILTER_FIELDS`). The migration
script, the read path, the doctor probe, and the tests all import
from there. Adding a new filter is a single edit:

1. Append the path to `CHUNKS_VECTOR_FILTER_FIELDS`.
2. Re-run the migration script with `--apply --rebuild` against the
   target environment.
3. Doctor will pass once Atlas finishes building.

## Rollback

The previous (unfiltered or partially-filtered) definition is
recoverable from Atlas's index history view. To roll back manually:

1. Drop `chunks_vector`.
2. Re-create with the prior definition shape from git history.
3. Optionally pin `CHUNKS_VECTOR_FILTER_FIELDS` to the rolled-back
   subset to keep the doctor green during the bisect.
