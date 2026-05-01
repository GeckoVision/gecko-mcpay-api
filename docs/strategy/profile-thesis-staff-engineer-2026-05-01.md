# Profile Thesis — Staff Engineer Lens

**Verdict:** Thesis holds, with one refinement: the "unified index" framing is wrong. Keep `SourceProvider` (S12 Track F) plural; add `ContributorRegistry` as an orthogonal axis, not a replacement.

## 1. Where the profile registry lives

New first-party module: `packages/gecko-core/src/gecko_core/contributors/` — siblings to `classify/`, `sources/`, `payments/`. Pure SDK, no transport. Web app (`gecko-mcpay-app`) renders profile chips by calling `gecko-api`; it does **not** own the registry. Skills repo stays markdown-only.

Why a new module, not an extension of `SourceProvider`: a contributor is a *principal* (0x address + reputation), a source is an *artifact* (URL + content). They have different lifecycles (reputation accrues; sources are immutable once chunked) and different identity primitives. Folding them confuses both.

## 2. Does X402Client generalize to ContributorClient?

**No.** Same Protocol *shape* (pluggable backend, mode enum, stub/live), different *semantics*:

- `X402Client` is request-scoped, idempotent-ish, returns receipts. Failure = retry.
- `ContributorClient` (Lens / Farcaster / EAS / publish.new-native) is read-mostly, eventually-consistent, returns identity + attestation graphs. Failure = stale cache OK.

Copy the **pattern** from S13-PAY-01 (`b77b636`): Protocol + `ContributorMode = stub|live|cached`, factory in `gecko_core.contributors.factory`. Do **not** share a base class. Identity != payment; coupling them now creates a refactor in Sprint 18.

## 3. Unified index vs SourceProvider Protocol — pick (a) hybrid leaning (a)

**(a) Unified index downstream of providers.** Providers stay plural and grow (Sprint 12 Track F is correct). The index is a *materialized view* keyed by `(profile_type, idea_signature, reputation_score)` that every provider's chunks feed into. Gecko owns the *index schema and ranking*; it does not own the *data ingestion surface*.

Rejecting (b): killing providers kills the Tavily/YouTube/Paragraph composability that makes Gecko a clerk rather than a walled garden. The thesis itself ("Gecko = clerk picking judges") requires multi-source heterogeneity.

The thesis line "everything indexes into one space" is true at the *retrieval* layer, false at the *ingestion* layer. Document that distinction.

## 4. Sprint 14 sequencing — ship as planned, profile-type the seam

**Ship Sprint 14 as planned.** Do not re-anchor. But: when wiring Paragraph + publish.new (Track B/C), require the ingest path to write a `contributor_address` column on chunks (nullable, default null for non-onchain sources). That's a one-line schema cost that unlocks Sprint 16+ profile work without rewriting Sprint 14.

Sprint 15 = `ContributorRegistry` Protocol stub + read-side only (resolve 0x → display name from Lens/Farcaster cache). Sprint 16 = reputation accrual + classifier extension. Sprint 17 = profile-typed routing in orchestrator.

Re-anchoring now risks slipping the demo and conflates two reversibility classes (Paragraph wiring is two-way; profile schema is one-way).

## 5. Sprint 15 ticket from my lane

**S15-ARCH-01 — ContributorRegistry Protocol + stub backend (3-4 days, one-way on schema, two-way on backend choice)**

- Add `packages/gecko-core/src/gecko_core/contributors/{protocol.py,stub.py,factory.py}` mirroring `gecko_core.payments` shape.
- Migration `infra/supabase/migrations/`: add `contributor_address text null` to chunks; index on `(contributor_address, profile_type)`.
- Stub backend: in-memory dict seeded from a fixture of 5 known publish.new authors with hand-classified `profile_type` ∈ {judge, investor, pm, designer, security, founder, operator}.
- Wire into `gecko-api` `/openapi.json`: read-only `GET /contributors/{address}` returning `{address, profile_type, citation_count, sources[]}`.

**Acceptance:**
- `uv run pytest packages/gecko-core/tests/contributors/` green.
- `gecko-mcp doctor` reports `contributor_mode=stub` cleanly.
- `bb research --idea "smoke test"` unchanged in output (registry is dormant until Sprint 16 routing).
- OpenAPI contract change posted to `frontend-engineer` in `gecko-mcpay-app`.
- No `X402Client` imports in `contributors/` (boundary check).
