# CDP Bazaar — listing conventions for gecko-api routes

**Status:** active (Sprint 12 Track B)
**Owner:** software-engineer
**Predecessor:** `docs/research/cdp-bazaar-2026-04-30.md`

CDP Bazaar (`api.cdp.coinbase.com/platform/v2/x402/discovery/*`) is the
discovery layer above x402. Sellers register routes by attaching a
`discoveryExtension` blob to their x402 metadata; the CDP Facilitator
catalogs the route the first time a payment **settles** through CDP.

This runbook locks the conventions every new paid route in `gecko-api`
must follow so that listings stay clean, discoverable, and don't get
collapsed by Bazaar's path-deduplication heuristic.

---

## 1. Where the metadata lives

`packages/gecko-api/src/gecko_api/bazaar.py` is the single source of
truth. Every paid route eligible for Bazaar listing has an entry in
`BAZAAR_EXTENSIONS` with:

- A semantic-search-friendly `description` (40+ chars).
- A short `tags` list — verbs/nouns an LLM would use in a query.
- A concrete `input` example.
- A `schema` with `properties.input` and `properties.output` JSON
  Schemas describing the request and response bodies.
- An optional `output_example` for buyer-side previews.

The `/.well-known/x402` endpoint surfaces the registry under
`bazaarExtension` per route so the CDP facilitator client (Sprint 12
Track A) can attach it at settle time.

## 2. Description rule — write for an LLM

Bazaar's `/discovery/search` endpoint ranks results by semantic
similarity. Descriptions optimized for human readability of the path
("Run /research") rank poorly. Write what the route *does* and what
makes it differentiated.

**Bad:**

> "/research — kicks off a research session"

**Good:**

> "Adversarial multi-agent product validation: emits a KILL/REFINE/BUILD
> verdict + cited evidence + 5-voice advisor panel. Best for founders
> who want a structured second opinion on a startup hypothesis before
> committing build effort."

The good version embeds the keywords an agent looking for "founder
validation" / "product research MCP" / "adversarial PRD" would query
for.

## 3. Path-segment rule — no bare UUIDs in paid routes

**Bazaar collapses paths with bare-UUID segments into a single catalog
entry.** A route like `POST /research/{session_id}` would consolidate
every research session into one Bazaar row, blowing up the metadata.

**Rule:** any paid route that takes an ID in the path must prefix the
parameter with a constant string. The `bazaar.has_bare_uuid_segment()`
helper enforces this; the test
`tests/api/test_route_consolidation.py` runs it against every entry in
`_routes_config`.

| Bad | Good |
|---|---|
| `POST /research/{session_id}/refine` | `POST /research/session-{session_id}/refine` |
| `POST /economics/{session_id}` | `POST /economics/session-{session_id}` |
| `POST /projects/{project_id}/audit` | `POST /projects/project-{project_id}/audit` |

Bare path segments matched as bare UUIDs:

- `{id}`, `{uuid}`, `{session_id}`, `{project_id}` — anything where the
  parameter name ends in `_id` or is in the `{"id", "uuid"}` set.
- Any segment that's the entire `{name}` placeholder (no constant
  prefix or suffix glued onto it).

Free / read-only routes (e.g. `GET /sessions/{session_id}/result`) are
**not** subject to the rule today — Bazaar only catalogs after settle,
and free routes never settle. Still, prefer the prefixed form on any
**new** session-keyed route so we don't have to rewrite client code if
we ever add a paid variant.

### Migrating an existing route

If you need to change a path that clients already call:

1. Add the new prefixed path as a parallel handler (same function body).
2. Keep the old path alive returning **308 Permanent Redirect** to the
   new path. (308 preserves method; 301 doesn't.)
3. Notify `frontend-engineer` in the `gecko-mcpay-app` repo and the
   `gecko-mcp` MCP client maintainers — `httpx.AsyncClient` defaults to
   `follow_redirects=False`, so callers must opt in or hard-update the
   path.
4. Plan a deprecation window (one full sprint minimum) before removing
   the old path.

## 4. JSON Schema rule — input example must validate

Bazaar's extension validator runs strict JSON Schema validation: if
`extension.input` doesn't validate against
`extension.schema.properties.input`, the listing is rejected on first
settle.

The CI harness `tests/api/test_bazaar_extensions.py` validates every
declared extension before deploy. **Always run `uv run pytest
packages/gecko-api/tests/api/`** when adding or editing entries in
`BAZAAR_EXTENSIONS` — a malformed extension would fail silently against
the live Bazaar API days later.

## 5. Settlement is the listing trigger

A route is *not* listed until a real settle goes through the CDP
Facilitator. Pure-verify dry-runs don't register. The end-to-end smoke
runbook for first-settle is `docs/runbooks/cdp-bazaar-listing.md`
(landed by Sprint 12 Track C — `S12-LIST-01`).

## 6. Adding a new paid route — checklist

1. [ ] Add the FastAPI handler + register the price in `_build_routes`.
2. [ ] Confirm the path has no bare-UUID segments (run the test).
3. [ ] Add an entry in `BAZAAR_EXTENSIONS` with description, tags,
       input example, and input/output schema.
4. [ ] Run `uv run pytest packages/gecko-api/tests/api/`.
5. [ ] After deploy, check `/.well-known/x402` and confirm the
       `bazaarExtension` blob appears under the new route.
6. [ ] After first CDP settle, query
       `https://api.cdp.coinbase.com/platform/v2/x402/discovery/search?query=<keyword>`
       and confirm the route shows up.

## 7. Inspect public verdicts (S12-HARDEN-03 / S12-HARDEN-05 audit trail)

Every successful `/research` and `/plan` call writes one judge transcript
record so any verdict that lands in Bazaar is auditable for compliance
and post-hoc review of misranked verdicts. Capture lives in
`packages/gecko-core/src/gecko_core/orchestration/transcripts.py`
(`capture()` is invoked from `workflows.py::research()` after the verdict
is finalized, before the auto-journal step). Schema mirrors the eval-side
capture in `tests/eval/runner.py::_archive_live_transcript`.

**Backend (S12-HARDEN-05):** `GECKO_TRANSCRIPT_STORE` selects one of:

| Mode         | When                                                              |
|--------------|-------------------------------------------------------------------|
| `mongo`      | Production default when `MONGODB_URI` is set. Writes to the       |
|              | `judge_transcripts` collection on the same Mongo instance the     |
|              | twit.sh cache uses. Indexes: `unique(session_id)` (upsert /       |
|              | last-write-wins on re-run) and compound `(actual_verdict_v2,      |
|              | created_at desc)` for "every BUILD verdict in last 30d".          |
| `filesystem` | Local dev / CI / Mongo fallback. One JSON file per session_id at  |
|              | `GECKO_TRANSCRIPT_DIR` → `/var/lib/gecko/judge_transcripts/` →    |
|              | `/tmp/gecko/transcripts/`.                                        |
| `noop`       | Drop on the floor. Rare; differs from `CAPTURE=false` in intent.  |

If `mongo` is selected and the write fails (network blip, auth fail) the
dispatcher logs a WARN and falls through to the filesystem store so a
verdict is never lost. The verdict path itself is never blocked.

**Toggle:** `GECKO_TRANSCRIPT_CAPTURE=false` disables capture entirely.
Default true in production; the test conftest flips it false so pytest
doesn't litter $TMP / hit Mongo.

**ECS Fargate note:** Fargate's ephemeral filesystem evaporates on task
restart, which is why prod defaults to Mongo. The filesystem fallback
keeps the API alive on a Mongo outage, but those records are lost on
the next container restart — investigate the Mongo outage promptly.

### mongosh queries (primary path)

Connect with the same `MONGODB_URI` the API uses, then:

```js
// Single verdict by session_id
db.judge_transcripts.find({ session_id: "<uuid>" })

// Every BUILD verdict in the last 20 records (uses the compound index)
db.judge_transcripts
  .find({ actual_verdict_v2: "BUILD" })
  .sort({ created_at: -1 })
  .limit(20)

// All KILL verdicts in the last 24h
db.judge_transcripts.find({
  actual_verdict_v2: "KILL",
  created_at: { $gte: new Date(Date.now() - 24*60*60*1000) },
})

// Verdict mix — judge said X, structured surface said Y
db.judge_transcripts.find({
  parsed_verdict: { $ne: "UNKNOWN" },
  $expr: { $ne: ["$parsed_verdict", "$actual_verdict_v2"] },
})

// Aggregate verdict distribution
db.judge_transcripts.aggregate([
  { $group: { _id: "$actual_verdict_v2", count: { $sum: 1 } } },
])
```

### jq one-liners (filesystem-fallback path)

When the active store is `filesystem` (or after a Mongo outage that fell
through to disk), the same queries against the JSON files:

```bash
# Single verdict by session_id
jq '.actual_verdict_v2, .judge_prose, .gap_classification, .gap_summary' \
  /var/lib/gecko/judge_transcripts/<session_id>.json

# All KILL verdicts in the last 24h
find /var/lib/gecko/judge_transcripts -mtime -1 -name '*.json' \
  -exec jq -r 'select(.actual_verdict_v2 == "KILL")
    | [.session_id, .idea_text, .gap_classification] | @tsv' {} \;

# Verdicts where the judge said one thing but the structured surface said another
find /var/lib/gecko/judge_transcripts -name '*.json' -exec jq -r '
  select(.parsed_verdict != "UNKNOWN" and .parsed_verdict != .actual_verdict_v2)
  | [.session_id, .parsed_verdict, .actual_verdict_v2, .gap_classification] | @tsv
' {} \;
```

### If we promote to Supabase later (S13 trigger)

The promotion path is additive: keep the file as the source of truth,
add a thin `judge_transcripts (id uuid pk, session_id uuid fk,
transcript_path text, parsed_verdict text, actual_verdict_v2 text,
gap_classification text, created_at timestamptz default now())` table,
RLS service-role-only. The file path stays the canonical store; the
table is the queryable index. SQL example for "all KILL verdicts where
the judge disagreed":

```sql
SELECT session_id, parsed_verdict, actual_verdict_v2, gap_classification
FROM judge_transcripts
WHERE parsed_verdict <> actual_verdict_v2
  AND actual_verdict_v2 = 'KILL'
ORDER BY created_at DESC
LIMIT 50;
```

