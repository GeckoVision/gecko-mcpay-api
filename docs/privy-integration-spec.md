# Privy Direct Integration — V2 Spec

Status: planning. Implementation post-Shipathon.
Author: web3-engineer. Last updated: 2026-04-27.

## TL;DR

Frames.ag remains the user's main wallet (email OTP, Onramp/PIX, identity). Each Gecko project gets its own Privy wallet under Model 1 (agent-controlled, developer-owned), bounded by a per-project policy and funded once by the user via a frames.ag transfer. The user's blast-radius is exactly what they fund into a project; Gecko's blast-radius is the authorization key, which we treat as a top-tier secret with a path to key-quorum.

## Architecture

```
   user (human)                 Gecko backend                Privy
   -----------                  -------------                -----
   frames.ag wallet  --fund-->  project_wallet_addr   <----  created via
   (main, identity)             (Privy, owner=us)            REST + auth-key

                                gecko-api  ---signs--->   Privy /wallets/{id}/rpc
                                  |                            |
                                  v                            v
                                x402 facilitator <--- on-chain SPL transfer
                                (www.x402.org)                (Solana mainnet)
```

Per-project state lives in `.gecko/project.json` (local) and `projects` table (DB).

## Question-by-question

### 1. Python integration strategy

**Recommendation: (a) hand-rolled REST client.** Privy ships an official REST API at `https://api.privy.io/v1` covering wallet create, policy create, and `/wallets/{id}/rpc` for signing ([REST quickstart](https://docs.privy.io/basics/rest-api/quickstart.md), [create wallet](https://docs.privy.io/api-reference/wallets/create.md)). The Node SDK is a thin wrapper over the same endpoints. We already have `httpx` + secret-handling patterns from `FramesAGWallet`; a Python client is ~300 LoC.

Fall back to (b) Node sidecar **only if** x402 signing requires `wrapFetchWithPayment()` (Privy's `@x402/fetch` helper) and the underlying wire shape isn't reproducible from REST. Per the [x402 recipe](https://docs.privy.io/recipes/agent-integrations/x402), the helper "automatically handles 402 payments" but doesn't expose a Solana-specific `pay()` — likely we can replicate it from `signTransaction` calls, but **needs Privy team confirmation**.

### 2. Authorization key management

- **Storage:** SSM SecureString, one key per environment (`gecko/privy/auth_key/{prod,staging}`). Same pattern we use for `OPENAI_API_KEY`. Never logged; redacted in error paths.
- **Rotation:** Privy supports multiple authorization keys per app ([owners overview](https://docs.privy.io/controls/authorization-keys/owners/overview.md)). Rotation = add new key, rewrite SSM, deploy, remove old key. Quarterly cadence.
- **Leak survival:** From day 1, configure a **key quorum** for high-impact actions (policy edits, wallet ownership transfer) per [key-quorum quickstart](https://docs.privy.io/controls/key-quorum/create.md). Day-to-day signing stays single-key for latency. M1 ships single-key; M2 layers in 2-of-3 quorum for policy mutations.

### 3. x402 signing wire shape

Confirmed from Privy's x402 docs:

- **No native PAYMENT-header signer.** Integration is via `wrapFetchWithPayment({ walletAddress, fetch })` which intercepts a `402 Payment Required` response, builds the payment, signs via the wallet, and retries.
- **Solana is supported** ("USDC in Privy embedded wallet on Base, Base Sepolia, or Solana"; chain inferred from address).
- **No Privy-mandated facilitator.** The facilitator is whoever the API provider points to (`www.x402.org/facilitator` for us). Privy's example uses Coinbase's, but it is not coupled.
- **SPL transfer construction:** ambiguous from public docs. The helper appears to build the instruction from the `paymentRequirements` field returned in the 402 body. **Spike (M0) needed** to confirm whether we need to construct the SPL `TransferChecked` instruction ourselves before calling `solana_signTransaction`, or whether the helper does it.

→ Implementation plan: Python port of `wrapFetchWithPayment` calling `POST /v1/wallets/{id}/rpc` with `method: "solana_signTransaction"` for the per-tx signature. Open item: confirm the exact RPC method name on Solana wallets.

### 4. Wallet provisioning & race conditions

```
gecko project init my-hotel-guide
  -> writes .gecko/project.json {project_id: uuid, wallet_address: null, status: pending}
  -> DB insert into projects (project_id PRIMARY KEY)

first paid call:
  gecko-api -> SELECT FOR UPDATE projects WHERE project_id = ?
            -> if wallet_address null:
                 POST https://api.privy.io/v1/wallets
                   {chain_type: solana, owner: {public_key: <our-auth-pubkey>},
                    policy_ids: [<template-policy-id>]}
                 UPDATE projects SET wallet_address = ..., status = active
            -> proceed with x402 call
```

Privy's REST surface does not publicly document `Idempotency-Key` support for wallet creation. Use **DB-side dedup** via `SELECT FOR UPDATE` on `project_id` — simpler and provider-agnostic. Flag for Privy team: confirm or add idempotency.

### 5. Policy templates

Policy DSL per [policies overview](https://docs.privy.io/controls/policies/overview.md): `Policy → Rules → Conditions`, with `chain_type`, `field_source`, `operator`, `action: ALLOW|DENY`, default-deny.

Concrete `default` template (sketch — exact field names need verification against API reference):

```json
{
  "version": "1.0",
  "name": "gecko-default",
  "chain_type": "solana",
  "rules": [
    {
      "name": "cap-per-tx",
      "method": "solana_signTransaction",
      "conditions": [
        {"field_source": "solana_program_instruction",
         "field": "spl_token.transfer.amount_usd",
         "operator": "lte", "value": "0.50"}
      ],
      "action": "ALLOW"
    },
    {"name": "default-deny", "method": "*", "conditions": [], "action": "DENY"}
  ]
}
```

Templates: `frugal` ($1/day, $0.10/tx), `default` ($5/day, $0.50/tx, x402 facilitator only), `pro-research` ($25/day, $1/tx, Tavily+Deepgram+ClawRouter), `unbounded` ($1000/day, $50/tx — still bounded). Daily caps may need wallet-level config rather than policy rules; **verify with Privy**.

### 6. Funding flow

```
gecko project fund my-hotel-guide --amount 5
  reads .gecko/project.json -> wallet_address
  prompts: "Send 5 USDC on Solana to <addr>? [y/N]"
  POST frames.ag /api/wallets/{user}/actions/transfer-solana
       { destination, amountUsd: 5, asset: "USDC" }
  DB insert: fundings (project_id, tx_signature, amount_usd, ts)
```

**SOL for fees:** SPL token transfers cost ~5000 lamports. Privy wallets ship empty. Provisioning must seed the wallet with ~0.01 SOL (~50 transactions worth) from a Gecko-controlled treasury wallet, **not from the user's frames balance** (cleaner accounting). M1 can hand-fund; M2 automates a treasury sweeper.

### 7. Migration v1 → v2

**Recommendation: (a) v2 is opt-in for new projects only.** v1 projects keep the policy-bounded model on the user's main wallet. Reasons: migration requires new on-chain funding (UX friction), v1 users self-selected for "I trust Gecko with my main wallet's policy," and we get a clean A/B for COGS analysis. Add a `gecko project migrate` command in M2 if demand materializes.

### 8. Failure modes

- **Privy outage:** hard-fail with a clear error. Falling back to the main wallet violates the per-project blast-radius contract — never silently widen scope.
- **Auth key leak:** blast = all Gecko project wallets. Mitigations: per-env keys, key quorum on policy mutations (so an attacker with one key can't lift caps), monitoring on `/wallets/.../rpc` call rate, ability to rotate within minutes via SSM + redeploy.
- **User revocation:** Under Model 1 the user does **not** own the wallet — Gecko's auth key does. The user's revocation primitive is **stop funding** (and `gecko project drain` to sweep residual USDC back to their frames address via a normal x402-style transfer). Privy's "users can revoke agent access" applies to Model 2 (user-owned, agent-delegated), not Model 1. **Document this clearly in onboarding.**

### 9. Pricing

Per [Privy pricing](https://www.privy.io/pricing): free up to 499 MAUs, Core at $299/mo to 2,500 MAUs, usage-based above 10K MAUs / 50K signatures / $1M monthly volume. Server Wallets are included. **Per-wallet/per-tx fees at scale require sales contact.** This is a real COGS question once we cross 500 MAUs — flag for `business-manager`.

## Milestones

- **M0 (1 week, spike):** Python REST client; create one Privy wallet on devnet; sign one Solana tx via `/rpc`; confirm x402 wire shape end-to-end against `www.x402.org/facilitator`.
- **M1 (2 weeks, minimal):** `gecko project init/fund/status`; provisioning with DB-side dedup; one policy template (`default`); single auth key; hand-funded SOL.
- **M2 (3 weeks, production):** all 4 templates; key quorum on policy mutations; treasury SOL sweeper; `gecko project drain`; migration command (if needed); alerting on RPC call rate and auth-key usage.

## Open items — ping Privy team

1. Idempotency-Key support on `POST /v1/wallets`?
2. Exact RPC method name for Solana tx signing (`solana_signTransaction` vs `signTransaction`)?
3. Does Privy build the SPL `TransferChecked` instruction inside the x402 helper, or do we?
4. Daily-limit semantics — wallet-level config or expressible in the policy DSL?
5. Per-wallet / per-signature pricing above the Core tier.
