# WalletProvider adapters — readiness & decision doc (V1 Phase A)

**Date:** 2026-06-07 · **Status:** decision-enabling (founder picks the V1 adapter)
**Seam:** `gecko_core/wallets/provider.py` (`WalletProvider` Protocol) — merged (#100).

The non-custodial decision is locked: user owns keys; Gecko holds a scoped,
revocable, trade-only grant; withdrawals only to the user's own address. Three
vendors implement that same `WalletProvider` contract. This doc maps each to the
seam's five methods and scores them, so picking one is a 5-minute decision.

## The contract every adapter must satisfy
`link(user_id, address)` · `grant_scope(user_id, scope)` · `revoke(user_id)` ·
`execute(user_id, action, amount)` · `withdraw(user_id, amount, to_address)`.
Invariants (enforced by the stub's contract tests): custody always `user-owned`;
never returns keys; `execute` in-scope only; `withdraw` only to the allow-list
(= user's own address); `revoke` blocks both.

---

## Option A — Privy (embedded wallet + delegated session signer)
- **Non-custodial mechanism:** Privy *embedded* wallets are user-owned (keys are
  user-controlled key-shares, not ours). The user grants a **session signer** /
  delegated action — a scoped, revocable key our server uses to sign trades.
- **Seam mapping:** `link` = verify Privy user token + record their embedded
  wallet address; `grant_scope` = register a session signer scoped to trade
  programs; `execute` = sign via the session signer; `withdraw` = sign a transfer
  to the user's address; `revoke` = revoke the session signer.
- **Solana:** yes (Privy supports Solana embedded wallets).
- **Build cost:** our `privy.py` today is *app-owned* (server-controlled) — needs
  extending to the user-owned embedded + session-signer flow; onboarding (email
  login) happens in the app via Privy's client SDK.
- **Pros:** turnkey email/passkey login + wallet creation; session signers are
  purpose-built for agentic non-custodial; great DX. **Cons:** another vendor in
  custody path; embedded-wallet onboarding lives in the app (client SDK), not
  pure-backend; Privy is the trust root for key-shares.

## Option B — OKX Agentic Wallet (user-owned + policy whitelist)
- **Non-custodial mechanism:** keys in OKX TEE ("never exposed to anyone,
  including your Agent"). The **owner sets a Policy** on the OKX web portal —
  **transfer whitelist** (only the user's own address) + per-tx/daily limits. The
  agent operates within that policy; it cannot send outside the whitelist.
- **Seam mapping:** `link` = user email-OTPs their own OKX wallet, we record the
  address; `grant_scope` ≈ the user's portal-set policy (whitelist = their addr);
  `execute` = `onchainos` trade within policy; `withdraw` = `wallet send` to the
  whitelisted (own) address; `revoke` = user tightens/clears policy or export.
- **Two login modes:** email-OTP (the human owner) and **AK / API-key** (server,
  no email). 50 sub-wallets per login.
- **Solana:** yes (EVM + Solana addresses on creation).
- **Build cost:** we proved the single-account flow in the contest. Multi-user
  needs either (i) each user email-OTPs their own account (true non-custodial,
  but hosted-server-operating-the-user's-session is awkward) or (ii) AK + 50
  sub-wallets under our key (operationally custodial — rejected). Honest gap:
  cross-account *delegated* agent access isn't a clean documented primitive; the
  policy-whitelist is the guarantee but is owner-set on the web portal.
- **Pros:** on-brand (OKX relationship, contest-proven), TEE custody, policy
  whitelist is a strong funds-safe guarantee. **Cons:** policy is web-portal-set
  (UX friction); multi-user delegation story is the weakest of the three.

## Option C — MagicBlock Session Keys (Solana-native scoped signing)
- **Non-custodial mechanism:** **Session Keys** — the user (owning their wallet)
  grants a temporary, scoped, **revocable** key the app uses to sign, *without*
  the app holding the main key. Solana-native, on-chain revocation.
- **Seam mapping:** `link` = user connects their Solana wallet, record address;
  `grant_scope` = create a Session Key scoped to the trade programs (Kamino/
  Jupiter) with limits; `execute` = sign with the session key; `withdraw` = a
  transfer to the user's own address (within scope); `revoke` = revoke the
  session key on-chain.
- **Solana:** native (this is its home turf).
- **Build cost:** integrate the Session Keys program + the React hooks (app) +
  server-side session-key signing. Newest of the three to us; needs a spike.
- **Pros:** purest non-custodial (on-chain scoped/revocable, no custody vendor in
  the path), Solana-native, conceptually clean (the grant IS an on-chain object).
  Ephemeral Rollups (their other product) are overkill for our cadence — skip.
  **Cons:** least battle-tested *for us*; no turnkey email login (need a separate
  auth/onboarding layer); ecosystem maturity vs Privy.

---

## Scorecard (V1 = hosted, multi-user, non-custodial, Solana)
| Criterion | Privy | OKX | MagicBlock |
|---|---|---|---|
| Non-custodial guarantee | strong (session signer) | strong (TEE + whitelist) | **strongest (on-chain scoped/revocable)** |
| Turnkey email onboarding | **yes** | yes (OTP) | no (bring your own auth) |
| Hosted multi-user fit | **good** | weak (delegation gap) | good (server signs w/ session key) |
| Solana support | yes | yes | **native** |
| Contest-proven for us | no | **yes** | no |
| Build cost (to live) | medium | low–medium | medium–high (spike) |
| Vendor in custody path | yes | yes (TEE) | **no** |

## Recommendation (for the founder to confirm)
- **Fastest to a working V1:** **Privy** — turnkey email login + wallet + session
  signers; the app-side SDK does onboarding, our backend verifies + signs within
  the grant. Best "deploy + execute starting from you" velocity.
- **Purest to the thesis (referee never near the chips):** **MagicBlock Session
  Keys** — the grant is an on-chain, revocable object; no custody vendor. Worth a
  short spike; strongest long-term story for "we literally cannot touch funds."
- **OKX** stays the execution/venue + the contest-proven path, and a fine custody
  option for users who already hold an OKX agentic wallet — but its multi-user
  *delegation* story is the weakest, so I'd not make it the default custody layer.

**Suggested call:** ship V1 on **Privy** (velocity), keep **MagicBlock** as the
fast-follow "maximal non-custody" upgrade, **OKX** as a supported alternative +
execution venue. All three are adapters of the same seam — no rewrite to switch.

## Next step once picked
Implement `gecko_core/wallets/adapters/<vendor>.py` conforming to `WalletProvider`
(the stub's contract tests become the adapter's tests), wire `onboarding._provider`
to it behind an env flag, and spike the live link/grant/execute/withdraw against
the vendor's sandbox (Pattern B: falsify locally before any real-money path).
