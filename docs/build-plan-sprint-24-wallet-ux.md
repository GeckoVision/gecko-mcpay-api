# Ticket: Wallet Management UX — self-custody + easy funding

**Track:** gecko-mcp (backend Python) + gecko-mcpay-app (frontend, coordinate separately)
**Priority:** P1 — blocks live-mode adoption
**Status:** ready to plan

## Problem

`gecko-mcp quickstart` hard-fails if `~/.agentwallet/config.json` is absent and redirects users to frames.ag's connect flow, which requires them to leave their terminal, navigate to a third-party site, and complete an OAuth-style setup Gecko does not control. The self-custody path (`wallet_self_custody.py`) already generates, encrypts, and stores a keypair at `~/.gecko/wallet.json` with a working `balance` command, but quickstart never routes to it — it is dead code from the user's perspective.

## Backend work (this repo)

- **`quickstart.py` — add self-custody fork.** In `_check_wallet`, detect `GECKO_WALLET_PROVIDER=self` (or absence of `~/.agentwallet/config.json`) and branch to the self-custody path: check `~/.gecko/wallet.json` exists, print address and balance, offer to run `gecko-mcp wallet new` inline if missing. The frames.ag path remains when the env var is absent and the frames config exists (no regression).
- **`wallet_self_custody.py` — add `fund_url()`.** Return a Phantom deep link pre-filled with the wallet's public key and a suggested USDC amount. Add `qr_code_ascii()` helper that wraps the address in a terminal-printable QR (use `qrcode` with `TerminalOutput`) so users on a phone can scan and fund without copy-paste.
- **`wallet.py` — expose provider selection.** Add `gecko-mcp wallet switch --provider [frames|self]` that writes `GECKO_WALLET_PROVIDER` to `~/.gecko/config.toml` and prints what changed. Quickstart and doctor both read this file so the preference survives shell restarts.
- **`wallet_self_custody.py` — passphrase UX.** `get_keypair_for_signing` falls back to the literal string `"default"` when `GECKO_WALLET_PASSPHRASE` is unset. Document this prominently in `wallet new` output and add a `--no-passphrase` flag so users opt in explicitly.
- **`doctor.py` — report wallet provider and balance.** `gecko-mcp doctor` should include a `payments:` line showing provider, public address, and USDC balance.

## Frontend work (gecko-mcpay-app — coordinate with frontend-engineer)

- **`/onramp` page** — `wallet new` already prints `https://app.geckovision.tech/onramp` as the funding URL; this page does not exist yet. Build a minimal page that accepts `?address=<pubkey>`, renders a Phantom/Solflare deep link button, and shows a Coinbase On-ramp widget for credit card → USDC.
- **`/wallet` dashboard** — display USDC balance, recent x402 charges from `sessions` table, copy-address button. Read-only; no signing in browser.
- **Phantom deep link flow** — use the SPL token URI scheme (`solana:${address}?amount=...&spl-token=...`) so mobile Phantom pre-fills the USDC transfer form.

## Wallet strategy options

**Option A — frames.ag (current):** frames.ag owns onboarding, spending policies, x402 dispatch. Pro: zero key management, battle-tested. Con: third-party signup required before Gecko works; any frames.ag outage blocks all payments; no UX control.

**Option B — Self-custody local keypair (`~/.gecko/wallet.json`):** already implemented in `wallet_self_custody.py`. Pro: zero external dependency, works offline for stub/devnet, user owns keys. Con: key backup is user's problem; passphrase UX rough today.

**Option C — Privy embedded wallet:** Pro: smooth OAuth-based wallet creation. Con: SDK is React/browser-first — no headless Python SDK. Requires browser popup or redirect, breaking headless developer context. Not suitable for CLI MCP server.

**Option D — Direct Phantom deep link:** funding-only path, not a full wallet solution for x402 signing.

**Recommendation: Option B (self-custody) as default, Option A as opt-in.** Target user is a developer running `gecko-mcp serve` headlessly. Self-custody requires no external account, works in CI, implementation already exists. frames.ag stays available via `gecko-mcp wallet switch --provider frames`. Option D is additive as the funding URL.

## Acceptance criteria

- `gecko-mcp quickstart` completes successfully with only `~/.gecko/wallet.json` present and no `~/.agentwallet/config.json`.
- `gecko-mcp wallet new` followed by `gecko-mcp wallet balance` on devnet returns a USDC amount without error.
- `gecko-mcp wallet new` output includes a Phantom deep link and a terminal QR code scannable on a phone.
- `gecko-mcp doctor` output includes `payments: self-custody | <address> | <balance> USDC` when `GECKO_WALLET_PROVIDER=self`.

## Out of scope

- Privy embedded wallet (browser-only; revisit in V2 web app)
- On-chain spending policy enforcement
- Key export / backup UX (document "back up `~/.gecko/wallet.json`" in README)
- Mainnet funding flow (devnet only for this sprint)
