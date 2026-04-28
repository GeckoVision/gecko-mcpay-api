# Auth: frames.ag bearer tokens for `/projects`

End users don't have Supabase creds. The CLI must call `gecko-api` over HTTP, authenticated by the frames.ag `apiToken` already cached at `~/.agentwallet/config.json`. This doc fixes the verification model and endpoint contract so `software-engineer` can implement directly.

## 1. Verification model — recommend (c) verify-then-cache

- **(a) Trust the bearer.** Free, but anyone who guesses or steals a `mf_...` can spoof a username. Reject — we'd be trusting clients to declare their own identity.
- **(b) Verify every request.** Hit `GET frames.ag/api/wallets/{username}/balances` with the bearer; 200 means the token belongs to that username. Adds 100-300ms per call and couples our uptime to frames'.
- **(c) Verify-then-cache.** Verify on cache miss, store `sha256(apiToken) -> username` with a 10-minute TTL. ~1 frames call per user per 10min, miss cost equal to (b).

**Pick (c). Use an in-process `cachetools.TTLCache` (maxsize=10_000, ttl=600).** No Redis. gecko-api runs as one container today; the worst case of a multi-replica deploy is each replica verifying once on cold cache. Adding Redis for a sub-megabyte token map is overkill until we have >3 replicas or need cross-process invalidation. Revisit when we do.

Cache key is `sha256(apiToken)` — never the raw token, so a memory dump or log accident doesn't leak it. Cache the *positive* mapping only; on 401/403 from frames, raise immediately and don't poison-cache.

## 2. Endpoint contract

```
POST   /projects           Bearer mf_...    body {name, budget_usd}     -> 201 ProjectOut
GET    /projects           Bearer mf_...                                -> [ProjectOut]
GET    /projects/{name}    Bearer mf_...                                -> ProjectOut + spend
DELETE /projects/{name}    Bearer mf_...                                -> 204 (sets deleted_at)
```

All four are scoped to the verified `username`. The DB query always includes `WHERE frames_username = :current_username AND deleted_at IS NULL`. The client never sends a username — it's derived server-side from the verified token. Anything else is broken-by-design.

## 3. FastAPI dependency sketch

```python
# gecko_api/auth.py
async def verify_frames_token(
    authorization: str = Header(...),
) -> str:
    """Returns the frames.ag username bound to the bearer token.

    Raises 401 on missing/malformed header, expired or revoked token, or
    frames.ag 4xx. Raises 503 on frames.ag 5xx/timeout (see lifecycle below).
    """
    token = _parse_bearer(authorization)              # 401 if not "Bearer mf_..."
    if (cached := _cache.get(_hash(token))) is not None:
        return cached
    username = await _verify_with_frames(token)       # GETs /wallets/me or similar
    _cache[_hash(token)] = username
    return username
```

Wired as `current_username: str = Depends(verify_frames_token)` on every `/projects` route. Middleware-level enforcement is tempting but FastAPI dependencies give us per-route opt-in (healthz stays public).

Open question for software-engineer: frames.ag exposes `GET /wallets/{username}/balances` but no `/wallets/me`. Verification needs the username up-front. Two options: (i) require client to send `X-Frames-Username` and verify by hitting `/balances/{username}` with the bearer — 200 confirms binding; (ii) ask frames to add `/wallets/me`. Use (i) for v1, file an ask with frames for (ii).

## 4. Token lifecycle

- **Revoked at frames.** Next cache miss returns 401 from frames -> we 401. Stale cache entries persist up to TTL (10min). Acceptable for v1; surface in the 401 doc string ("token may take up to 10min to revoke after frames.ag deletion").
- **Leaked.** We have no detection. Mitigation lives at frames (rotate apiToken) and via wallet-level spending policy. We document this in the README quickstart: treat `~/.agentwallet/config.json` like an SSH key.
- **frames.ag down.** Hard-fail with 503 on cache miss (don't grant access without verification). Cache hits keep working until TTL expires — 10min grace by accident, which is fine. Don't extend TTL on frames-down; that's how trust gets backdoored.

## 5. Rate limiting — defer beyond a coarse global limit

Per-token DDOS of `/projects` is annoying but doesn't drain wallets (creates/lists are free, only `/research` is x402-paid). Ship v1 with `slowapi` at a flat `60 req/min per Authorization header` for `/projects/*`. Per-user fine-grained limits, anomaly detection — v2.

## 6. MCP api_client change

```python
# gecko_mcp/api_client.py
class ApiClient:
    def __init__(self, base_url: str, *, bearer: str | None = None) -> None: ...
    async def create_project(self, name: str, budget_usd: float) -> ProjectOut: ...
    async def list_projects(self) -> list[ProjectOut]: ...
```

The bearer is read once from `_read_config()["apiToken"]` (reuse `wallet._read_config`) and attached as `Authorization: Bearer <token>` on every request. CLI commands construct `ApiClient(base_url=GECKO_API_URL, bearer=token)`. Existing `/research` calls stay unchanged — they go through frames' `/x402/fetch`, not directly to gecko-api.

## 7. Audit + abuse

Log `username` (not the token, not its hash) on every authenticated request at INFO. frames usernames are pseudonymous handles, not PII under GDPR; document in `docs/PRD.md` privacy section. Never log `Authorization` headers — add a uvicorn access-log filter that strips them.

## 8. Schema impact — none

The existing `projects.frames_username text` column is sufficient. We do **not** store the apiToken on gecko-api; it stays client-side at `~/.agentwallet/config.json`. The bearer is presented per-request and discarded. No new migration needed.

---

Relevant files: `/home/nan/PycharmProjects/Gecko/gecko-mcpay-api/packages/gecko-api/src/gecko_api/main.py` (middleware order), `/home/nan/PycharmProjects/Gecko/gecko-mcpay-api/packages/gecko-mcp/src/gecko_mcp/wallet.py` (`_read_config`, FRAMES_BASE), new file `/home/nan/PycharmProjects/Gecko/gecko-mcpay-api/packages/gecko-api/src/gecko_api/auth.py`.
