# Wallet options — Gecko is wallet-neutral

**Date:** 2026-04-30
**Sprint:** 12 (S12-DOCS-01)
**Audience:** anyone running `bb research`, `bb plan`, or installing the Gecko Claude Code skill
**Status:** runbook (cross-linked from main `README.md` and from `gecko-mcpay-skills`)

---

## TL;DR

Gecko is **wallet-neutral by design.** Any x402-capable wallet works. We integrate with each as a partner, never depend exclusively on one. Pick the wallet that matches the network you want to settle on and the funding rail you already have.

| Wallet | Network(s) | Setup time | Best for |
|---|---|---|---|
| **frames.ag** | Solana mainnet | 2 min | Default for Claude Code skill installs; existing Solana balance |
| **TWITSH** | Base mainnet | 1 min (OTP) | Simplest spin-up; no extension; Base USDC |
| **Coinbase Agentic Wallet (`awal`)** | Base mainnet, Base Sepolia, Solana | 3 min | Users already on Coinbase; CDP Bazaar buyer side |
| **publish.new wallet** | Solana | auto-generated | Receiving artifact sales (Sprint 14 — sellers) |
| **custom (BYO)** | Any x402-capable | varies | Advanced; existing infrastructure |

You do not need more than one to start. `bb research` only requires a wallet that can pay the network the chosen route settles on.

---

## How Gecko picks a settlement path

`gecko-api` resolves the settlement facilitator from `X402_NETWORK`:

- `solana:mainnet` → frames.ag facilitator (Sprint 8/10 path)
- `eip155:8453` (Base mainnet) → CDP Facilitator (Sprint 12, Track A)
- `eip155:84532` (Base Sepolia) → CDP Facilitator (test)
- `solana:devnet` → frames.ag (test)

`bb doctor` shows which facilitator is active per network. `X402_MODE=stub` bypasses all of this for offline testing.

---

## frames.ag (Solana mainnet — default for Claude Code skill)

**Why default:** the public Gecko skill (`Read app.geckovision.tech/skill.md`) installs with frames.ag wallet bootstrapping. Solana fees are negligible; USDC settlement is fast.

**Setup**

```bash
# Install the frames.ag wallet via the skill flow
Read app.geckovision.tech/skill.md
# Follow the wallet-creation prompt; copy the generated apiToken
```

**Where the credential lives**

`~/.gecko/wallet.json` (created by the skill) or `FRAMES_API_TOKEN` in `.env` for headless / CI use.

**Funding paths**

- Cross-chain bridge USDC → Solana via any Solana-aware bridge
- Direct USDC purchase on Coinbase / Kraken → withdraw to the frames.ag deposit address
- Faucet (devnet only): `solana airdrop` against `solana:devnet`

**Network coverage:** Solana mainnet, Solana devnet.

---

## TWITSH (Base mainnet — fastest setup)

**Why pick it:** OTP-based setup, no browser extension, no seed phrase to manage. Best for a first paid run on Base.

**Setup**

```bash
# Sign in with phone or email OTP at twitsh.app
# Copy the generated wallet address + apiToken
export TWITSH_API_TOKEN=...
export X402_NETWORK=eip155:8453
```

**Where the credential lives**

`TWITSH_API_TOKEN` in `.env`. The wallet address is printed by `bb wallet show` once configured (see Sprint 13+ wallet panel spec).

**Funding paths**

- Coinbase Onramp directly to the Base address (USDC)
- Base bridge (`bridge.base.org`) for USDC from Ethereum mainnet
- Faucet (Sepolia only): Coinbase Base Sepolia faucet

**Network coverage:** Base mainnet, Base Sepolia.

---

## Coinbase Agentic Wallet (`awal`)

**Why pick it:** users already in the Coinbase ecosystem; tight integration with CDP Bazaar buyer-side flows; acts as both wallet and MCP surface.

**Setup**

```bash
npx awal init
# Follow the prompt; awal creates a wallet keyed against your CDP account
```

**Where the credential lives**

`~/.awal/config.json` by default, or `AWAL_API_KEY` for headless. Coinbase manages key custody at the platform level — you do not see a raw private key.

**Funding paths**

- Coinbase Onramp (fiat → USDC, native to the wallet)
- Direct transfer from any Coinbase account
- Base bridge for USDC from L1

**Network coverage:** Base mainnet, Base Sepolia, Solana mainnet (CDP's Solana facilitator).

**Note:** Gecko does not require `awal`. It is one wallet among several. We list it because users on Coinbase ask for it, not because we recommend it over the others.

---

## publish.new wallet (Sprint 14 — sellers receiving artifact sales)

**Why pick it:** auto-generated when a creator publishes an artifact via the publish.new flow. Receives micro-payments from buyers without the seller having to set up anything.

**Setup**

Auto-generated on first publish; the seller is shown the address + recovery key once. Not used for buying — receive only.

**Where the credential lives**

`~/.publish-new/wallet.json` after first publish, or shown in the web flow at publish time.

**Funding paths**

Receive-only by default. Sellers withdraw to any Solana wallet via standard transfer.

**Network coverage:** Solana mainnet.

**Status:** Not active in Sprint 12. Listed here for forward compatibility — Sprint 14 ships the publishing surface.

---

## Custom (bring your own)

**Why pick it:** existing wallet infrastructure, custodial setup at scale, or an x402-capable wallet not listed above.

**Requirements**

- x402 v1 protocol support (verify + settle round-trip)
- USDC balance on Solana mainnet or Base mainnet
- An apiToken / signer the gecko-api client can present

**Wiring**

Implement `PaymentClient` Protocol in `packages/gecko-core/payments/`. The frames.ag client (`x402_client.py`) and CDP client (`cdp_x402_client.py`, Sprint 12) are the two reference implementations. Choose your path with `X402_MODE=custom` and inject the client via the factory.

**Support level:** community / advanced. We do not validate custom wallet implementations against the live eval gate.

---

## Wallet neutrality — the positioning

Gecko's product is the validation engine: 5-agent debate, 6 sources, KILL/REFINE/BUILD verdict, three documents. The wallet is **how you pay**, not what you bought.

- **We integrate with each wallet as a partner.** frames.ag is our distribution path for the Claude Code skill. CDP Bazaar (and `awal`) is our distribution path for agent-to-agent commerce. TWITSH is the simplest entry point. publish.new is the seller-side primitive.
- **We never depend exclusively on one.** If frames.ag changed terms tomorrow, Gecko keeps working on Base via CDP. If Coinbase shut down `awal` tomorrow, Gecko keeps working on Solana via frames.ag.
- **We never assume one.** `bb doctor` checks each configured wallet independently. `bb wallet` (Sprint 13+) shows the full picture.

This is a structural commitment, not a marketing line. The factory in `packages/gecko-core/payments/__init__.py` resolves the facilitator at runtime — no path through the codebase hard-codes a single wallet vendor.

---

## See also

- `docs/runbooks/cdp-bazaar.md` — CDP Facilitator wiring for Base settlement
- `docs/runbooks/cdp-bazaar-listing.md` — listing Gecko routes in CDP Bazaar
- `docs/strategy/wallet-panel-spec-2026-04-30.md` — Sprint 13+ `bb wallet` panel
- Main `README.md` — quickstart with frames.ag default
- `gecko-mcpay-skills` repo `skill.md` — Claude Code skill install flow
