---
name: gecko
description: Bootstrap the Gecko skill registry. Installs the gecko-mcp server and connects it to your Solana wallet. No API keys required — just a wallet. Use when the user pastes "Read https://app.geckovision.tech/skill.md" or asks to install/onboard Gecko.
---

# Gecko — Builder Bootstrap Platform

Turn a plain-language startup idea into a knowledge base, a business plan, a validation report, and a PRD — in under 30 minutes. Powered by x402 on Solana.

This file is the **public bootstrap entry**. When a user says *"Read https://app.geckovision.tech/skill.md and follow the instructions,"* you (Claude Code) walk through these steps.

---

## What you're installing

A single MCP server (`gecko-mcp`) that exposes three tools to Claude Code:

| Tool | What it does | Cost |
|---|---|---|
| `gecko_research` | Discover sources → index → generate business plan + validation + PRD | $20 (basic) / $75 (pro) — paid via x402 |
| `gecko_ask` | Follow-up question grounded in the session | Free |
| `gecko_sources` | List indexed sources for the session | Free |

**No API keys to manage.** The user only needs a Solana wallet with USDC. Payments happen automatically via the x402 protocol when `gecko_research` is called.

---

## Step 1 — Verify prerequisites

```bash
python3 --version    # need 3.11+
which uv || curl -LsSf https://astral.sh/uv/install.sh | sh
which claude         # need Claude Code CLI installed
```

If any fails, stop and tell the user what's missing. Don't proceed.

## Step 2 — Install the MCP server

```bash
uv tool install gecko-mcp
```

## Step 3 — Set up the agent wallet

```bash
gecko-mcp wallet new
# Prompts:
#   Enter your email: user@example.com
#   Check your inbox — enter the 6-digit code: 123456
#
# Output:
#   Wallet ready
#     username:       @alice
#     solana address: Abc1...xyz
#
#   Fund at https://frames.ag/u/alice or https://app.geckovision.tech/onramp
```

This runs entirely in the terminal — no browser required. frames.ag sends a 6-digit OTP to the email; entering it provisions a custodial Solana + EVM wallet and writes credentials to `~/.agentwallet/config.json` (chmod 600). Under 60 seconds.

Tell the user:
- No private keys are stored locally — frames.ag holds custody
- Fund with a small amount first ($25 USDC covers a basic + a pro session)
- To fund: send USDC on Solana to the printed address, or visit `https://app.geckovision.tech/onramp`

**Power user — bring your own wallet:** if the user already has a Solana keypair, they can import it:

```bash
gecko-mcp wallet switch self
gecko-mcp wallet import   # prompts for keypair file or base58 secret
```

This path stores the keypair encrypted at `~/.gecko/wallet.json`. Recommend only if the user has a wallet specifically for agent spending — never import a seed phrase that controls significant funds.

## Step 4 — Register the MCP server with Claude Code

```bash
claude mcp add gecko -- gecko-mcp serve
```

Verify:

```bash
claude mcp list | grep gecko
```

## Step 5 — Smoke test

```bash
gecko-mcp doctor
# Expected:
#   ✅ wallet: <ADDRESS> (Solana mainnet-beta)
#   ✅ balance: X.XX USDC
#   ✅ gecko-api reachable: https://api.geckovision.tech
```

If `balance: 0`, the user needs to fund the wallet. Direct them to:
- `https://app.geckovision.tech/onramp` (PIX, credit card, etc.)
- Or send USDC directly to the wallet address from another Solana wallet

Once funded, in Claude Code:

> "Use gecko_research to validate: a hotel guide for Brazil"

Expected: x402 payment of $20 USDC fires automatically, documents return in ~60s.

---

## Notes for Claude Code

- **No API keys are ever requested from the user.** OpenAI, Tavily, Supabase keys live server-side at `gecko-api` — they're Gecko's responsibility, not the user's. If you find yourself about to ask for an API key, stop — that's wrong.
- **The wallet is the only credential.** It's how the user pays, how the user is identified, and how sessions are scoped. Setup requires only an email for OTP — no passwords, no separate signup form.
- **First-time users almost always need Step A (generate wallet) and an onramp.** Most people don't have a funded Solana USDC wallet handy. Send them to the onramp page calmly; it takes 30 seconds via PIX in Brazil.
- **Never log the encrypted keypair file path or its contents.** `~/.gecko/wallet.json` is private.
- After install, the user can browse other Gecko skills at `https://app.geckovision.tech/skills/`.

---

*Builder Bootstrap Platform · geckovision.tech · No API keys. Just a wallet.*
