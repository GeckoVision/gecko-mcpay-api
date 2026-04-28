# Phase B5 v2 — frames.ag bearer auth on /projects (shipped)

The CLI no longer needs Supabase credentials. End users with only a
frames.ag apiToken at `~/.agentwallet/config.json` can run
`gecko project init/list/show/delete` against production gecko-api.

## What landed

### gecko-api
- `packages/gecko-api/src/gecko_api/auth.py` — `verify_frames_token`
  FastAPI dependency. Verify-then-cache (sha256 token → username,
  10-min TTL via `cachetools.TTLCache`). On cache miss, GET
  `frames.ag/api/wallets/{username}/balances` with the bearer; 200 →
  cache + return; 4xx → 401; 5xx/timeout → 503 (no poison-cache).
  Never logs the apiToken or its hash; logs verified username only.
- `packages/gecko-api/src/gecko_api/main.py` — four new endpoints, all
  Depends(verify_frames_token), all `60/minute` slowapi-rate-limited
  per Authorization header (falls back to remote address):
  - `POST /projects` (201 ProjectOut)
  - `GET /projects` (list w/ total_spent_usd + sessions_count)
  - `GET /projects/{name}` (full record + spend + remaining + last 5 sessions)
  - `DELETE /projects/{name}` (204; soft-delete via deleted_at)
  Middleware order preserved: CORS → x402 PaymentMiddlewareASGI; bearer
  auth is per-route Depends, so /research's 402 flow is untouched.

### gecko-core
- `SessionStore.delete_project(username, name) -> bool` — soft-delete by
  setting `deleted_at`.

### gecko-mcp api_client
- `GeckoAPIClient(..., bearer=, frames_username=)` — new optional kwargs.
  Reads from `~/.agentwallet/config.json` lazily on first /projects call;
  raises `GeckoAPIError("no frames.ag credentials...")` if absent.
- New methods: `create_project`, `list_projects`, `get_project`,
  `delete_project`. All attach `Authorization: Bearer ...` and
  `X-Frames-Username: ...`.

### CLI
- `apps/cli/src/gecko_cli/commands/project.py` — rewritten as a thin
  wrapper over `GeckoAPIClient`. `SessionStore` import is gone. `init`,
  `list`, `show`, `delete` all hit HTTP. `_client()` is the test seam.

### Tests
- `tests/api/test_auth.py` — respx-mocked frames.ag round-trip; covers
  missing/malformed headers, 200 caches, 401 propagates, 5xx → 503 (no
  poison-cache), cached-username-mismatch → 401.
- `tests/api/test_projects.py` — 4 endpoints + auth-required negative.
- `tests/cli/test_project.py` — refactored; mocks the api_client seam.
- `tests/mcp/test_api_client.py` — extended with bearer-header-injection
  + project-method tests.

All 151 tests pass; mypy clean on changed files.

## Decisions

- **`/research` stays bearer-free.** frames.ag's `/x402/fetch` proxy
  may not preserve arbitrary headers. We don't add risk there for a
  marginal audit gain; the project_id body field already correlates.
- **`gecko project budget --set` and `gecko project policy` removed**
  from v2 surface (no PATCH /projects endpoint in the contract). To
  re-add: extend `SessionStore.set_project_budget` exposure via a
  `PATCH /projects/{name}` endpoint — out of scope for this slice.

## TODO

- Smoke-deploy via `./infra/deploy.sh` and run `gecko project init/list`
  from a clean dir without sourcing the dev `.env`. Deferred so the
  deploy doesn't ship half-baked code mid-implementation.
- PyPI publish of the user-facing CLI (separate repo plan).
- Re-add `project budget --set` once `PATCH /projects/{name}` is spec'd.
