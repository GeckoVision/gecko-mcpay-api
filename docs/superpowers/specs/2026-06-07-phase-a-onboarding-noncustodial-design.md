# Design — V1 Phase A: Onboarding & Non-Custodial Custody

**Date:** 2026-06-07
**Status:** approved decisions (founder, 2026-06-07); spec for review
**Owner lanes:** software-engineer (gecko-api auth/session/binding), web3-engineer (OKX link + scoped permission + withdraw), product-manager (user journey)

## Goal
The V1 onboarding spine: a user signs in with **email → OTP** (our session), **links their own OKX agentic wallet** (they keep custody), and Gecko receives a **scoped, trade-only permission** to run an agent on their behalf — with a **first-class withdrawal path** so money-out is never a trap.

## Decisions (locked, founder 2026-06-07)
1. **Non-custodial.** Each user owns their OKX agentic wallet (their email/keys in OKX's TEE). Gecko holds ONLY a scoped trade-only permission. Gecko never custodies funds. This is the only model consistent with the referee-not-player thesis (custody = the conflict-of-interest we sell against).
2. **Auth/session + binding live in gecko-api** (FastAPI), secrets server-side.
3. **Withdrawal is sacred.** The safety gate / kill-switch can HALT new risk (no new deposits/leverage) but must NEVER block a user's withdrawal.
4. **Withdraw path ships in V1** (functional); the polished one-click UX + external-send convenience is V1.x roadmap. Deposit and withdraw ship together.

## Two distinct "logins" (do not conflate)
- **(a) Our app session** — `email → OTP → session token`. Identifies the user to gecko-api. WE own this OTP. It is NOT wallet auth.
- **(b) The user's OKX wallet auth** — the user authenticates to OKX to own their wallet; OKX holds those keys in TEE. We never see them. We only record the resulting **public address** + obtain a **scoped permission**.
We persist the binding `{our user_id ↔ user's OKX wallet address + permission scope}`.

## Architecture (gecko-api)

### Auth router `gecko_api/routes/onboarding.py` (new APIRouter, mirrors routes/permissions.py)
- `POST /auth/request-otp {email}` → 6-digit OTP; store `sha256(code)` + `expires_at` (10 min) + `attempts=0`; send via email-provider seam (`EmailSender`: stub logs a masked line in dev; real provider behind founder config). Rate-limited per email (reuse `rate_limit.py`).
- `POST /auth/verify-otp {email, code}` → check hash + TTL + attempts (max 5); on success mint a session token (signed, expiry) → `{session_token, user_id}`. Wrong/expired → 401, increment attempts, never reveal which.
- `GET /auth/session` (Bearer) → `{user_id, email, wallet_linked: bool}`.

### Wallet link + scoped permission `gecko_api/routes/onboarding.py`
- `POST /wallet/link` (Bearer) → records `{user_id, okx_wallet_address}` and requests a **scoped trade-only permission** via `OkxAgentLink.request_scope(address)` (OKX policy: allowed = trade on Kamino/Jupiter/swap; **withdraw allowed only to the user's own address**; NO arbitrary external sends). Returns the scope summary.
- `GET /wallet` (Bearer) → `{address, custody: "user-owned-okx-tee", scope, balance}` (balance via the existing wallet-balance path).

### Withdrawal path (first-class) `gecko_api/routes/onboarding.py`
- `POST /vault/withdraw` (Bearer) → unwinds the user's vault position(s) back to USDC **in their own OKX wallet** (Kamino withdraw via the scoped permission; OKX TEE signs). **NEVER gated by the kill-switch** (explicit test). Paper V1: simulated unwind; live signing is the gated step.
- Money is then in the user's own wallet; sending it onward (to Phantom/exchange) is the user's own OKX `wallet send` — outside our scope by design.

### Provider seams (Pattern B — stub first, live later, gated)
- `OkxAgentLink`: `request_scope(address) -> scope`, `scope_for(user_id)`, `withdraw(user_id, amount) -> receipt`. Default = **stub** (deterministic, no network, $0). Live impl wraps the OKX OnchainOS scoped-permission/policy API + `wallet send`/Kamino withdraw — confirmed via a spike before going live.
- `EmailSender`: `send_otp(email, code)`. Default = **stub** (logs masked); live = founder-chosen provider.

### Storage (Mongo — the live store; Supabase deprecated for new data)
- `users`: `{user_id, email, okx_wallet_address?, permission_scope?, created_at}`.
- `auth_otps`: `{email, code_hash, expires_at, attempts, created_at}` (TTL index on expires_at).
- Both behind a collection seam with an in-memory fake for tests (mirror `mongo_credit_tokens.py`'s fake pattern).

### Deploy gating
- `/agents` deploy (control plane) becomes **session-auth-gated** and **bound to the user's linked wallet + scope**: a deployed agent trades via the user's TEE under the scoped permission. Paper V1: binding recorded; live signing gated.

## Security
- OTP: `sha256` only (never store/log plaintext); TTL + max-attempts + per-email rate-limit; constant-time compare.
- Session tokens: signed (HMAC) with expiry; secret via SSM.
- Scoped permission: trade-only; **withdraw allow-list = the user's own address only**; no arbitrary external send is ever in Gecko's scope.
- No private key material ever crosses the wire or is logged.
- Withdrawal endpoint is exempt from the kill-switch (sacred-withdrawal rule) — covered by an explicit test.
- Secrets (OKX creds, email-provider key, session HMAC secret) via env/SSM; sentinels keep the service booting before they're set.

## Scope — THIS build (non-gated, fully testable, $0)
gecko-api auth (otp/session) + wallet-link + binding + the withdraw-path **contract**, all against **stub** `OkxAgentLink` + `EmailSender` and the in-memory store. TestClient suite. Typed response models (`extra="allow"`), in `/openapi.json` for app codegen.

## NOT in scope (gates)
- Real email delivery (founder picks provider + key).
- Live OKX scoped-permission API + real link/withdraw (spike + founder OKX creds; the exact OnchainOS policy/permission call confirmed first).
- The app UI (separate frontend slice in gecko-mcpay-app).
- Real-money withdrawal/trade (founder-gated, paper-first).

## Verification
`request-otp → verify-otp → session → /wallet/link → GET /wallet → POST /vault/withdraw`, all via TestClient with stubs. Unit: OTP expiry, max-attempts, rate-limit, no-plaintext-in-logs, withdraw-not-blocked-by-kill-switch, unknown-session-401.

## Roadmap (post-Phase-A)
- V1.x: polished one-click "withdraw vault → my wallet" UX + external-send convenience; full OKX scoped-permission live wiring; multi-wallet per user; session refresh/logout.

## Boundaries
Paper + stub; non-custodial (Gecko never holds keys); withdrawal never gated; `private/` gitignored; branches + PRs (founder merges); no live flip / prod deploy without explicit OK.
