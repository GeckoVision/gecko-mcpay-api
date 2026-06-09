# V1 Sequence — App↔Agent State Read → Custody Adapter → Kamino Multiply Wiring

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Code-writing agents run **sequentially** (`feedback_parallel_code_agents`); **targeted pytest only** (`feedback_remove_freezing_tests`).

**Goal:** Connect the deployed hosted agent to the app (session-scoped state read), then make wallet custody real (Privy adapter behind the existing seam), then complete the Kamino Multiply pick→open→lock loop — in that order, each phase independently shippable.

**Architecture:** Three sequenced phases on the existing seams. Phase 1 adds a session-gated read path (HMAC token → `user_agents` ownership lookup in Supabase → `agent_state` read from Mongo) plus the missing binding-writer. Phase 2 implements `PrivyWalletAdapter(WalletProvider)` composing the already-built `PrivyClient`, wired via an env-gated factory. Phase 3 activates min-hold stamping and wires the catalog pick→open path (already-built economics + lock + stamping). All PAPER / `X402_MODE=stub`; real-money + mainnet stay founder-gated.

**Tech Stack:** FastAPI (gecko-api), pymongo (agent_state read), Supabase Postgres + RLS (user_agents), httpx (Privy), pytest (TDD, targeted).

---

## Pre-flight context (what already exists — do NOT rebuild)

| Asset | Location | State |
|---|---|---|
| Mongo `agent_state` store, keyed by `agent_id` | `contest_bot/agent_store.py` (`MongoBotStateStore`, `AgentStateStore.get_state`) | BUILT (pymongo, doc `{agent_id, state, updated_at}`) |
| `user_agents` table + RLS owner-only + `gecko_current_user_id()` | `infra/supabase/migrations/20260607000000_session_scoped_agents.sql` | BUILT (migration) — **but no code writes rows** |
| HMAC session token issue/verify | `packages/gecko-api/src/gecko_api/routes/onboarding.py` (`_issue`, `_verify`, `_user_id_for`) | BUILT |
| WalletProvider Protocol + Stub + `user_scope`/`scope_for` | `packages/gecko-core/src/gecko_core/wallets/provider.py` | BUILT |
| `PrivyClient` (create wallet, create_policy, attach_policy) | `packages/gecko-core/src/gecko_core/wallets/privy.py` | BUILT (HTTP wrapper) |
| `PermissionKey` grid (6 keys, Pattern A) | `packages/gecko-core/src/gecko_core/permissions/__init__.py` | BUILT |
| Kamino economics + selector + catalog + monitor + lock + lot stamping | `contest_bot/kamino/*.py`, `vault_orchestrator.py` (`_stamp_min_hold`, `round_trip_cost_pct`) | BUILT |
| `/vault` + `/vault/catalog` read APIs | `contest_bot/agent_api.py` | BUILT |
| TS klend sidecar (unsigned tx build) | `contest_bot/kamino/ts-sidecar/build_tx.ts`, `gecko_core/execution/kamino_devnet.py` | BUILT (mainnet build feasible; submit founder-gated) |

---

## Decisions to confirm before starting each phase

- **[Phase 1 — D1] RLS enforcement path.** gecko-api → Supabase `user_agents`. Two options:
  - **(A, recommended)** Service-role client + **explicit `user_id` filter in code** (`.eq("user_id", user_id)`). Simplest for V1; the HMAC token is the gate; RLS is belt-and-suspenders not relied on. Ship now.
  - (B) NOBYPASSRLS connection role + set `request.jwt.claim.user_id` GUC per request → RLS enforces. Stronger, but needs the role provisioned + a per-request connection wrapper. Defer to a hardening pass.
  - **Plan assumes (A).** If founder wants (B), Task 1.4 changes the client construction only; the route logic is identical.
- **[Phase 1 — D2] Binding seed vs. provisioning.** Nothing writes `user_agents`. For the single deployed agent (`hosted-setupc-001`), Phase 1 ships a **bind-on-onboard** helper + a one-row **seed** for the founder's user. Full per-user provisioning is the separate "Multi-tenant" slice (not in this plan).
- **[Phase 2 — D3] Privy is the V1 vendor** (confirmed by selecting this slice). MagicBlock = fast-follow, OKX = alt; both implement the same Protocol later.
- **[Phase 2 — D4] `execute()`/`withdraw()` signing.** Privy session-signer / delegated-signing mechanics must be verified against live Privy docs before real signing ships. Phase 2 ships **link/grant/scope_for/revoke real** (wallet + policy lifecycle) and leaves **execute/withdraw raising `NotImplementedError` (or advisory-only)** until D4 is resolved — consistent with advisor-first V1. Real signing = its own gated task.
- **[Phase 3 — D5] Real-money/mainnet Multiply stays founder-gated** (rides #191/#192). Phase 3 is paper-mode pick→open→lock only.

---

## PHASE 1 — App↔Agent session-scoped state read

**Outcome:** The app, holding a user's HMAC session token, can `GET /v1/agent/state` and receive only *that user's* agent runtime state (positions, pnl, liveness), gated by a `user_agents` ownership row. Zero-inbound agent stays zero-inbound; the read goes app → gecko-api → (Supabase ownership) + (Mongo state).

**Files:**
- Create: `packages/gecko-core/src/gecko_core/agents/state_reader.py` (Mongo `agent_state` reader, no contest_bot import)
- Create: `packages/gecko-api/src/gecko_api/routes/agent_state.py` (the route + ownership lookup)
- Create: `packages/gecko-api/src/gecko_api/routes/_session.py` (shared token-verify dependency, extracted from onboarding)
- Modify: `packages/gecko-api/src/gecko_api/routes/onboarding.py` (bind-on-grant: write `user_agents` row; import shared verify)
- Modify: `packages/gecko-api/src/gecko_api/main.py` (mount the new router)
- Test: `packages/gecko-api/tests/test_agent_state.py`, `packages/gecko-core/tests/test_state_reader.py`

### Task 1.1: Mongo agent_state reader in gecko-core (no contest_bot dep)

- [ ] **Step 1 — failing test** `packages/gecko-core/tests/test_state_reader.py`:
```python
from gecko_core.agents.state_reader import read_agent_state, scope_state_for_user

def test_read_returns_none_when_no_doc(monkeypatch):
    monkeypatch.setattr("gecko_core.agents.state_reader._collection", lambda name: None)
    assert read_agent_state("missing-agent") is None

def test_scope_state_strips_config_fields():
    raw = {"positions": [{"symbol": "BTC"}], "realized_pnl_today": 1.2,
           "still_alive_at": "2026-06-07T00:00:00+00:00", "poll_count": 9,
           "spec": {"secret_params": 1}, "total_spent_usd": 100.0}
    out = scope_state_for_user(raw)
    assert "spec" not in out and "total_spent_usd" not in out
    assert out["realized_pnl_today"] == 1.2 and out["positions"][0]["symbol"] == "BTC"
```
- [ ] **Step 2** Run: `uv run pytest packages/gecko-core/tests/test_state_reader.py -v` → FAIL (module missing).
- [ ] **Step 3 — implement** `state_reader.py`. Reuse the `agent_store.py` Mongo pattern (pymongo, `MONGODB_URI`/`MONGO_URI`, `GECKO_MONGO_DB` default `gecko`, collection `agent_state`, 3s timeout, in-memory fallback returns None). `read_agent_state(agent_id) -> dict | None` returns the `state` sub-doc + `updated_at`. `scope_state_for_user(state) -> dict` whitelists only user-safe keys: `positions, realized_pnl_today, wins_today, losses_today, daily_trades, still_alive_at, poll_count` (+ `updated_at`); never `spec`, `total_spent_usd`, internal cohort/model fields.
- [ ] **Step 4** Run the test → PASS.
- [ ] **Step 5** Commit: `feat(core): session-safe agent_state Mongo reader + field scoper`.

### Task 1.2: Shared session-verify dependency

- [ ] **Step 1 — failing test** in `packages/gecko-api/tests/test_session_dep.py`: assert `verify_session_token(issue(...))` returns `(user_id, wallet)` and raises `HTTPException(401)` on tamper/expiry.
- [ ] **Step 2** Run → FAIL.
- [ ] **Step 3 — implement** `_session.py`: move `_issue`/`_verify`/`_user_id_for`/`_secret` constants out of onboarding into a shared module; expose a FastAPI dependency `require_session(authorization: str = Header(...)) -> SessionCtx` returning `{user_id, wallet}`. Re-export from onboarding for backward compat (its existing routes import from here). **No behavior change** to the token format.
- [ ] **Step 4** Run `uv run pytest packages/gecko-api/tests/test_session_dep.py packages/gecko-api/tests/test_onboarding.py -v` → PASS (onboarding still green).
- [ ] **Step 5** Commit: `refactor(api): extract shared session-verify dependency`.

### Task 1.3: bind-on-grant — write the `user_agents` row (the missing writer)

- [ ] **Step 1 — failing test** `test_onboarding.py::test_grant_binds_agent`: after `POST /v1/onboarding/grant`, a `user_agents` row exists for `(user_id, agent_id=hosted-setupc-001)`. Use a fake Supabase writer injected via module seam (mirror the `_provider` monkeypatch pattern).
- [ ] **Step 2** Run → FAIL.
- [ ] **Step 3 — implement** in onboarding `grant`: after the scope grant succeeds, upsert a `user_agents` row `{user_id, agent_id, strategy, profile, status:'deployed'}`. Agent id source for V1 = `GECKO_DEFAULT_AGENT_ID` env (default `hosted-setupc-001`). Writer = a thin `bind_user_agent(user_id, agent_id, ...)` in a new `gecko_api/routes/_bindings.py` using the service-role Supabase client (D1-A); idempotent upsert on the `user_agents_agent_id_uidx` unique index.
- [ ] **Step 4** Run `uv run pytest packages/gecko-api/tests/test_onboarding.py -v` → PASS.
- [ ] **Step 5** Commit: `feat(api): bind user→agent on grant (writes user_agents)`.

### Task 1.4: the read route `GET /v1/agent/state`

- [ ] **Step 1 — failing test** `test_agent_state.py`:
  - owner token + seeded binding + fake Mongo state → 200, body has scoped fields, no `spec`.
  - valid token but **no binding** → 404 (`no agent for this user`).
  - tampered/expired token → 401.
  - binding for a *different* user_id → 404 (never leaks another user's agent).
- [ ] **Step 2** Run → FAIL.
- [ ] **Step 3 — implement** `routes/agent_state.py`: `GET /v1/agent/state`, `Depends(require_session)` → `user_id` → `lookup_agent_for_user(user_id)` (Supabase `user_agents` `.select(agent_id,strategy,profile).eq("user_id",user_id).is_("deleted_at","null").maybe_single()`) → if none, 404 → `read_agent_state(agent_id)` → `scope_state_for_user` → return `{agent_id, strategy, profile, state, updated_at}`. Mount in `main.py` next to onboarding/permissions.
- [ ] **Step 4** Run `uv run pytest packages/gecko-api/tests/test_agent_state.py -v` → PASS.
- [ ] **Step 5 — local smoke** (per `feedback_local_api_over_pytest_sweep`): boot `gecko-api` locally, `POST /v1/onboarding/link` → `/grant` → `GET /v1/agent/state` with the token; confirm 200 + scoped body. (Mongo state may be empty locally → assert shape, not contents.)
- [ ] **Step 6** Commit: `feat(api): session-scoped GET /v1/agent/state`.

### Task 1.5: seed the founder binding + docs

- [ ] **Step 1** Add `infra/supabase/scripts/seed_founder_binding.sql` (idempotent upsert: founder's `user_id` → `hosted-setupc-001`). Founder runs it once against remote Supabase. Do NOT hardcode a real wallet in the repo — parameterize with a `\set` placeholder + comment.
- [ ] **Step 2** Update `docs/runbooks/2026-06-07-hosted-agent-deploy.md` with the "app watches the agent" read path + the seed step.
- [ ] **Step 3** Commit + open PR for Phase 1. **Founder merges + runs the seed + applies the migration if not yet applied.**

**Phase 1 verification:** with the seed applied, `GET /v1/agent/state` against the deployed gecko-api returns the live `hosted-setupc-001` state; a token for any other user gets 404; the agent stays zero-inbound.

**Phase 1 follow-ups (tracked, non-blocking for V1 single-agent paper):**
- **Partial-index `ON CONFLICT` mismatch (Task 1.3).** PostgREST `on_conflict="agent_id"` emits a bare `ON CONFLICT (agent_id)` which does NOT bind to the partial unique index `user_agents_agent_id_uidx WHERE deleted_at IS NULL` (Postgres `42P10`). First insert works; an idempotent **re-grant raises** (caught by the grant try/except → no 500, but a silent no-op + log line). Fix before any multi-agent / soft-delete-then-re-grant flow: either drop the partial predicate, or switch `bind_user_agent` to select-then-insert/update. Add a **live contract test** (Pattern C) against the real `user_agents` table — the fake-only unit test cannot catch this.
- **Per-call pymongo client (Task 1.1).** `read_agent_state` builds a fresh `MongoClient` per call; cache a module-level client before this sits behind a hot route.

---

## PHASE 2 — Privy custody adapter (real link/grant/scope/revoke)

> **GATE:** D3 (Privy = vendor) confirmed. D4 (signing) unresolved → `execute`/`withdraw` ship as `NotImplementedError` until a dedicated signing task; advisor-first V1 needs only the wallet+policy lifecycle.

**Outcome:** With `PRIVY_APP_ID`/`PRIVY_APP_SECRET` set, onboarding provisions a real Privy Solana wallet and attaches a scoped policy (trade-only, withdraw-allowlist = user address); revoke detaches it. Without creds, it transparently falls back to `StubWalletProvider` (tests + dev unchanged).

**Files:**
- Create: `packages/gecko-core/src/gecko_core/wallets/privy_adapter.py` (`PrivyWalletAdapter(WalletProvider)`)
- Create: `packages/gecko-core/src/gecko_core/wallets/privy_rules.py` (`Scope`/`PermissionKey` → Privy policy `rules[]`)
- Modify: `packages/gecko-api/src/gecko_api/routes/onboarding.py` (env-gated provider factory replacing the hardcoded `StubWalletProvider()` at line 51)
- Test: `packages/gecko-core/tests/test_privy_adapter.py`, `test_privy_rules.py` (respx-mocked Privy; no live calls)

### Task 2.1: Scope → Privy policy rule builder
- [ ] TDD: `scope_to_privy_rules(scope: Scope, user_address: str) -> list[dict]` — maps `TRADE_ONLY_ACTIONS` to Privy v2 policy rules; encodes the withdraw-allowlist so the only permitted transfer destination is `user_address`. Pure function, fully unit-testable (no network). Assert: trade actions allowed; transfer to a non-allowlisted address denied by the produced rules.

### Task 2.2: `PrivyWalletAdapter` lifecycle methods (respx-mocked)
- [ ] TDD each method against respx-mocked Privy endpoints:
  - `link(user_id, address)` → `create_solana_wallet` (idempotent per user_id via external_id) → `WalletLink(custody="user-owned")`.
  - `grant_scope(user_id, scope)` → `create_policy(rules=scope_to_privy_rules(...))` + `attach_policy_to_wallet`.
  - `scope_for(user_id)` → read persisted policy state → `Scope | None`.
  - `revoke(user_id)` → detach/disable policy → subsequent `scope_for` reflects revoked.
  - `execute`/`withdraw` → raise `NotImplementedError("privy signing — gated task D4")` for now.
- [ ] Persist the `user_id → (wallet_id, policy_id)` mapping (Supabase `wallet_links`/a small `privy_wallets` table, or reuse `wallet_links.provider='privy'` + a metadata column). Contract test the persistence.
- [ ] Enforce the non-custodial invariants from `StubWalletProvider` (custody always user-owned; revoked blocks; allowlist-only) — reuse the stub's invariant tests as a shared conformance suite parametrized over `[StubWalletProvider, PrivyWalletAdapter(mocked)]`.

### Task 2.3: env-gated factory + wire
- [ ] TDD `make_wallet_provider()`: returns `PrivyWalletAdapter` iff `is_privy_configured()` and `GECKO_WALLET_PROVIDER != "stub"`; else `StubWalletProvider`. Replace onboarding line 51 `_provider = StubWalletProvider()` with `_provider = make_wallet_provider()`. Existing onboarding tests must stay green (they monkeypatch `_provider`).
- [ ] Local smoke: with no creds → stub path identical to today. With sandbox creds (founder-supplied, never committed) → `link`+`grant` hit Privy sandbox.
- [ ] Commit + PR for Phase 2. **Founder merges + sets `PRIVY_APP_ID`/`PRIVY_APP_SECRET` in SSM when ready.** Real signing (`execute`/`withdraw`) = follow-up gated task once D4 resolved against live Privy docs (verify session-signer / delegated-signing flow via context7 or Privy docs).

**Phase 2 verification:** stub path byte-identical without creds; with sandbox creds, a real Privy wallet + scoped policy are created and revocable; conformance suite passes for both providers; `execute`/`withdraw` cleanly signal "gated".

---

## PHASE 3 — Kamino Multiply pick→open→lock (paper)

> **GATE:** D5 — paper only. Real mainnet open rides #191/#192 (founder-gated).

**Outcome:** A user picks a Multiply option from `/vault/catalog`; the orchestrator opens that specific lot in paper mode with `entry_ts` + `min_hold_until` stamped (round-trip-cost active); the monitor then defers optimization exits until break-even while always honoring safety exits. Everything below the economics is already built — this phase is the *activation + pick→open wire*.

**Files:**
- Modify: `contest_bot/kamino/vault_orchestrator.py` (open-specific-template-by-name path; ensure `round_trip_cost_pct` is configurable from env at runtime)
- Modify: `contest_bot/agent_api.py` (`POST /vault/open` — pick a catalog option by name → open lot)
- Modify: `docker-entrypoint-agent.sh` / `infra/ecs-agent-stack.yml` (set `GECKO_VAULT_ROUNDTRIP_COST_PCT` so stamping is active in the hosted agent; default still safe)
- Test: `contest_bot/tests/test_vault_open.py`

### Task 3.1: open-by-name in the orchestrator
- [ ] TDD `open_from_catalog(option_name, principal, *, now)` on `VaultOrchestrator`: resolves the named template from the profile-ranked catalog, calls the existing `_add_to_lot`/`_stamp_min_hold` path, returns the new `VaultLot` with `entry_ts`/`min_hold_until` populated (given `round_trip_cost_pct > 0`). Assert lock is set and `apply_actions` defers a ROTATE before break-even but a safety EXIT still fires.

### Task 3.2: `POST /vault/open` endpoint
- [ ] TDD: `POST /vault/open {option_name, principal_usd}` → 200 with the opened lot (paper). Reject names not in the current profile catalog (400). **Paper-only guard:** refuse unless `PAPER_TRADE=true` (defense-in-depth; never opens real money from this route in V1).

### Task 3.3: activate stamping in the hosted agent
- [ ] Add `GECKO_VAULT_ROUNDTRIP_COST_PCT` (e.g. `0.0027`) to the entrypoint + CFN env so the deployed orchestrator stamps locks. Keep the code default `0.0` (inert) so non-hosted runs are unchanged. Update the `test_agent_entrypoint.py` lock-style test to assert the var is present + paper-safe.
- [ ] Commit + PR for Phase 3. Re-deploy (founder) picks up stamping. **Mainnet open stays gated** (#191/#192).

**Phase 3 verification:** paper pick→open stamps a lock; monitor defers optimization until break-even, safety always overrides; hosted agent has stamping active; no real-money path reachable from `/vault/open`.

---

## PHASE 4 — paySH / external data-provider ingest (Birdeye · Nansen · CoinGecko · Perplexity · QuickNode)

> **GATE:** independent of Phases 1–3 (different files, different lane — `data-analyst` owns "are we bringing the right data", `web3-engineer` owns x402 + hotpath). Can run in parallel with Phase 2/3. `X402_MODE=stub` stays default; API keys land in SSM founder-side, never committed.

**Outcome:** Five new data providers reach the system through the *correct* seam for each — not all five are corpus chunks. The mapping (see `docs/superpowers/plans/notes/2026-06-07-provider-ingest-map.md` if extracted) establishes three seams: **(i) time-series tape** (OHLCV → JSON store → backtest, NO `provider_kind`, NO embeddings), **(ii) corpus chunks** (prose → Voyage embed → Mongo `chunks`, new `provider_kind` per Pattern A, reachable by the trade panel), **(iii) hotpath RPC** (live chain transport, no corpus). Each corpus provider ships with an end-to-end **reachability probe** (Pattern E) asserting ≥1 chunk reaches the panel under its new `provider_kind`.

### Decisions to confirm before starting (D6–D10)

- **[D6 — Birdeye] = time-series tape, not corpus.** OHLCV are candles, not text. The adapter already exists at `scripts/calibration/tape/birdeye_source.py` (parses `/defi/ohlcv`, paginated) and is only key-gated. **Recommendation:** founder sets `BIRDEYE_API_KEY` in SSM; we add a thin verification + the tape-collector registry wire (`scripts/calibration/tape/__init__.py`) + a contract test for the parser. **No `ProviderKind`, no migration.** Cheapest win.
- **[D7 — Nansen] = corpus chunks (narrative), v0.1.** Smart-money flow is structured (`wallet, action, protocol, amount, ts`) but its *value to the panel* is narrative grounding ("top tracked wallets net-deposited $X into Kamino in 24h"). **Recommendation:** v0.1 renders prose chunks under new `provider_kind="nansen_smart_money"` (Pattern A: `sources/types.py` + migration + drift test); a structured `nansen_signals` Mongo collection for the trade-agent hotpath is **deferred to v0.2**. Needs a Nansen API key (founder, SSM).
- **[D8 — CoinGecko] = two surfaces.** OHLCV already has a tape path (`scripts/calibration/ingest_coingecko_solana_universe.py`) — leave it. The *new* value the founder named ("where trading is happening, not just price") = **venue/pool inventory** → corpus chunks under new `provider_kind="coingecko_venues"` (Pattern A). **Recommendation:** build only the venues-corpus track; OHLCV stays as-is. CoinGecko is also already in the `paysh_manifest` x402 catalog — if founder prefers paid routing, it rides the paysh_live seam (D9 pattern) instead of a direct key.
- **[D9 — Perplexity] = x402 corpus via `paysh_live` reuse.** Already wired through pay.sh but the catalog endpoint rotted (404 as of 2026-05-08). **Recommendation:** v0.1 fixes the catalog URL override + reachability test on the existing `paysh_live` seam (`sources/paysh_live.py`, `PAYSH_LIVE_BUDGET_USD=5.0` cap, `x402.settle` cost telemetry) — **no new `ProviderKind`**, citations land under `paysh_live`. A dedicated `perplexity_research` kind + direct x402 call is a later option if volume justifies it. Stays `X402_MODE=stub` until founder flips (`project_x402_stub_then_live`).
- **[D10 — QuickNode] = hotpath RPC redundancy, not corpus.** Like Helius, QuickNode is *transport* (uptime/latency), not unique content. **Recommendation:** v0.1 adds QuickNode as an alternate RPC endpoint in the trade-agent hotpath (`gecko_core/trade_agent/hotpath/`, env-selected, Helius stays default) with a contract test. **No `ProviderKind`, no chunks.** A `quicknode_docs` corpus is explicitly out of scope (public docs duplicate Helius/Jupiter).

**Net new Pattern-A corpus builds = exactly two: `nansen_smart_money` (4c) and `coingecko_venues` (4d).** Birdeye (4a) and QuickNode (4e) are config + transport; Perplexity (4b) is a URL fix on an existing seam.

### Task 4a — Birdeye OHLCV tape wire (time-series, no ProviderKind)
- [ ] Read `scripts/calibration/tape/birdeye_source.py` + `scripts/calibration/tape/__init__.py`. Confirm the registry auto-picks the source when `BIRDEYE_API_KEY` is set.
- [ ] TDD a contract test (`scripts/calibration/tape/tests/test_birdeye_source.py`): feed a recorded `/defi/ohlcv` JSON fixture → assert parser yields **ascending** bars, drops the forming bar, and maps `{ts,o,h,l,c,v}` correctly. (Mirror the OnchainOS contract per `feedback`/Pattern.) No live API call in tests.
- [ ] Wire the registry entry so a set key activates collection with zero further code change; `log()` the universe + bar count on first collect.
- [ ] **Founder action:** add `BIRDEYE_API_KEY` to SSM. Then a live smoke collects N bars for the majors universe into `scripts/calibration/data/`. Commit + PR.

### Task 4b — Perplexity cited-research via paysh_live (fix rotted catalog URL)
- [ ] Read `packages/gecko-core/src/gecko_core/sources/paysh_live.py` + the paysh manifest catalog. Find the dead Perplexity entry (404 since 2026-05-08).
- [ ] TDD: with `X402_MODE=stub`, a stubbed `PaidRequester` returns a synthetic cited response → assert the source renders chunks with citations under `provider_kind="paysh_live"` and emits the `x402.settle` cost event (within `PAYSH_LIVE_BUDGET_USD`).
- [ ] **Reachability probe (Pattern E):** call the real `retrieve_trade_corpus_chunks(...)` with a question whose answer needs live research; assert ≥1 `paysh_live` chunk with a non-empty `citations[]` reaches the panel. (Per CLAUDE.md Patterns E/F — per-layer tests are not sufficient.)
- [ ] Fix the catalog URL/override only; do not flip `X402_MODE`. Commit + PR. **Founder:** confirm the live Perplexity x402 endpoint before any `live` smoke.

### Task 4c — Nansen smart-money corpus (Pattern A: new `nansen_smart_money`)
- [ ] **Pattern A touch-points (one commit):** add `"nansen_smart_money"` to `ProviderKind` in `packages/gecko-core/src/gecko_core/sources/types.py`; new migration `infra/supabase/migrations/<ts>_provider_kind_nansen.sql` extending the `chunks_provider_kind_check` CHECK; update `packages/gecko-core/tests/test_provider_kind_consistency.py` to lock the value. Run ONLY `uv run pytest packages/gecko-core/tests/test_provider_kind_consistency.py -v` → green.
- [ ] New source config `packages/gecko-core/src/gecko_core/sources/nansen.py` (endpoint catalog, frozen dataclass like `protocol_native.py`). Smart-money chunks carry **exact protocol tags** (`protocol=["kamino"]` etc.) — NOT `protocol=[]` (canon is `[]`; this is protocol-specific), `freshness_tier="hot"`.
- [ ] New ingest script `scripts/nansen/ingest_nansen_smartmoney.py` mirroring `scripts/protocol_native/ingest_protocol_native.py` (fetch → `render_chunk_pairs` prose → `chunk_text` → `embed(input_type="document")` → `insert_chunks_mongo`; pre-insert `delete_chunks_for_source_mongo` for idempotency). Narrative template: "Top tracked wallets net-{deposited,withdrew} $X into {protocol} over {window}."
- [ ] **Reachability probe (Pattern E)** `packages/gecko-core/tests/test_nansen_reachability.py`: call `retrieve_trade_corpus_chunks(idea=..., protocol="kamino")`; assert ≥1 chunk with `provider_kind=="nansen_smart_money"` reaches the panel. With a recorded fixture (no live Nansen call in CI).
- [ ] **Founder:** Nansen API key → SSM. Commit + PR. (v0.2 `nansen_signals` structured store is a separate plan.)

### Task 4d — CoinGecko venue/pool corpus (Pattern A: new `coingecko_venues`)
- [ ] Pattern A: add `"coingecko_venues"` to `ProviderKind` + migration + drift-test update (same shape as 4c). Targeted drift test green.
- [ ] Source config `packages/gecko-core/src/gecko_core/sources/coingecko_venues.py` + ingest `scripts/coingecko/ingest_venues.py`: fetch pool/venue inventory (where volume concentrates, fees, pool age) → prose chunks. Venue chunks are **cross-cutting** market structure → `protocol=[]` so they surface for all protocols (per CLAUDE.md canon rule), `freshness_tier="daily"`.
- [ ] Reachability probe asserting ≥1 `coingecko_venues` chunk reaches the panel for a generic "where is SOL trading" question.
- [ ] Decide key vs paysh routing per D8 (founder). Commit + PR. **Do NOT touch the existing CoinGecko OHLCV tape ingest.**

### Task 4e — QuickNode hotpath RPC redundancy (transport, no corpus)
- [ ] Read `packages/gecko-core/src/gecko_core/trade_agent/hotpath/` — find the Helius RPC client + how the endpoint is configured. Confirm hotpath depends only on `httpx`/`websockets`/`pydantic` (do not introduce `gecko_core.db`/`rag`/`orchestration` imports — Pattern: hotpath isolation).
- [ ] TDD an env-selected RPC endpoint: `GECKO_RPC_PROVIDER=quicknode` routes to `QUICKNODE_RPC_URL`; default stays Helius. Contract test with a mocked httpx transport (no live RPC) asserting the URL/headers switch and a parsed response shape parity with Helius.
- [ ] **Founder:** `QUICKNODE_RPC_URL` → SSM. Commit + PR.

**Phase 4 verification:** Birdeye collects bars into the tape store on a set key (no corpus pollution); Perplexity citations reach the panel via `paysh_live` (stub); `nansen_smart_money` + `coingecko_venues` each pass an end-to-end reachability probe (≥1 chunk to the panel) and the `test_provider_kind_consistency` drift test is green; QuickNode is a config-selectable RPC with Helius unchanged as default. No `X402_MODE` flip; all keys in SSM, none in the repo.

---

## Sequencing & hard boundaries

- **Order is strict:** Phase 1 → 2 → 3. Phase 1 is the highest-information, fully-buildable-now slice (connects what's already deployed). Phase 2 is gated on D3 (done) with D4 deferred. Phase 3 is paper-only activation of built code.
- Each phase = its own PR(s); **founder merges**; no prod deploy / no main push / no PR merge without explicit OK.
- `PAPER_TRADE=true` + `X402_MODE=stub` everywhere; **no real-money/mainnet flip without explicit founder go** (`project_x402_stub_then_live`).
- Non-custodial invariants are sacred (`project_noncustodial_custody_decision_2026_06_07`): custody always user-owned; withdrawal never kill-switch-gated; allowlist = user's own address only.
- Targeted pytest only (never bare `uv run pytest` — `feedback_remove_freezing_tests`); code-writing agents sequential (`feedback_parallel_code_agents`).
- Don't touch founder WIP files (recorder.py, swing_signal_logger.py, decision_store/, the modified test files); `private/` stays gitignored (`project_public_repo_private_docs`).
- OpenRouter not OpenAI for any new LLM call (`feedback_openrouter_not_openai_for_new_llm`).

## Self-review notes
- **Spec coverage:** all three founder-selected slices have phases; each lands a shippable PR. ✔
- **Gaps closed vs. discovery:** Phase 1 explicitly adds the missing `user_agents` *writer* (Task 1.3) and the missing gecko-api Mongo reader (Task 1.1) — the two real gaps found. ✔
- **Decisions surfaced, not guessed:** D1–D5 listed at top with recommendations; none silently assumed beyond what the founder selected. ✔
- **No new types referenced without definition:** reuses existing `WalletProvider`/`Scope`/`VaultLot`/`agent_state`; new symbols (`read_agent_state`, `scope_state_for_user`, `require_session`, `bind_user_agent`, `scope_to_privy_rules`, `make_wallet_provider`, `open_from_catalog`) are each defined in their task. ✔
