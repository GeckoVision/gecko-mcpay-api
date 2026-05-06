# Runbook — S20-A3 legacy chunk revoke

**Sprint:** S20-A-LEGACY-REVOKE-01
**Owner:** data-engineer
**Last verified:** 2026-05-06

This runbook covers the one-shot script that stamps pre-A2 chunks with the reserved `legacy_uncategorized` bucket and excludes them from default RAG retrieval. Per `project_mongo_cutover_no_backfill`: no backfill, no re-classification — just revoke and exclude.

## What the script does

1. Finds chunks missing one or more of the new A2 fields (`category`, `vertical`, `source`).
2. Stamps each missing field with a legacy default:
   - `category` → `legacy_uncategorized`
   - `vertical` → `unknown`
   - `source` → `web`
3. Sets `metadata.deprecated = true` and `metadata.legacy_revoked_at = <UTC now>`.
4. Builds the `vertical_category_compound` index (`createIndex` is idempotent).

## Pre-flight

- [ ] You are running against the right Mongo Atlas cluster (`MONGODB_URI`).
- [ ] You took a snapshot or are confident a snapshot exists. The script does not delete; rollback is recovering metadata, not chunks.
- [ ] You ran `uv run pytest tests/scripts/test_s20_legacy_revoke.py` locally — green.

## Procedure

### 1. Dry run (default)

```bash
uv run python scripts/mongo/s20_legacy_revoke.py \
    --mongodb-uri "$MONGODB_URI" \
    --db gecko_rag \
    --collection chunks
```

Output:

```
s20_legacy_revoke summary: matched=<N> modified=0 dry_run=True index_built=False
```

Sanity-check `<N>`. If it's 0, the collection is already revoked or has no legacy chunks — stop.

### 2. Apply

```bash
uv run python scripts/mongo/s20_legacy_revoke.py \
    --apply \
    --mongodb-uri "$MONGODB_URI" \
    --db gecko_rag \
    --collection chunks
```

Output:

```
s20_legacy_revoke summary: matched=<N> modified=<N or more> dry_run=False index_built=True
```

`modified` may be greater than `matched` because the script issues one `update_many` per missing-field axis (category, vertical, source). A chunk missing all three will count once toward `matched` and three times toward `modified`.

### 3. Verify idempotency

Re-run the apply step. Expect:

```
matched=0 modified=0 dry_run=False index_built=True
```

If `matched` is non-zero on the second run, investigate before doing anything else.

### 4. Smoke RAG

Run a `bb research --idea "smoke"` cycle. Confirm chunks returned are not legacy (their `category` is one of the canonical 7).

## Rollback

The script is non-destructive. To un-mark chunks as deprecated (re-include them in retrieval):

```javascript
db.chunks.updateMany(
  { "metadata.deprecated": true },
  { $set: { "metadata.deprecated": false } }
)
```

This leaves the `legacy_uncategorized` stamps in place but re-includes the chunks in default RAG (the filter drops on either axis).

For full rollback (restore the original missing-field shape), restore from the pre-run Atlas snapshot.

## Debug — read legacy chunks

The Python entry point exposes an opt-in flag:

```python
from gecko_core.rag.query import rag_query

chunks = await rag_query(
    session_id,
    "what's in the legacy bucket?",
    top_k=10,
    include_legacy=True,
)
```

`include_legacy=True` drops the default `category != legacy_uncategorized` AND `metadata.deprecated != true` filter on the Mongo `$vectorSearch`. Operators only — production code paths must leave the default `False`.

## Drop legacy chunks (deferred to S21)

Deleting legacy chunks entirely is out of scope for this runbook. The plan:

- [ ] S21 ticket: validate that no operator workflow has needed `include_legacy=True` for two sprints.
- [ ] S21 ticket: drop chunks with `metadata.deprecated=true` after a final dry-run count + snapshot.

Until S21 lands, keep the legacy chunks — they cost storage but cost zero retrieval time (filtered out at the `$vectorSearch` stage).
