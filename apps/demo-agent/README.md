# gecko-demo-agent

The on-stage demo client. Calls `gecko-api`, handles 402, signs the x402
payment with the local Solana keypair, retries.

This is the canonical shape any third-party agent can copy.

## Quickstart (stage operator)

```bash
# 1. one-time: create a wallet and fund it on devnet
gecko-mcp wallet new
gecko-mcp wallet address     # send 25 USDC (devnet) here
gecko-mcp wallet balance     # confirm

# 2. start the API in another shell
uv run gecko-api

# 3. on stage — the live demo
gecko-demo-agent research "a hotel guide for Brazil"

# 4. follow-up (free, no 402)
gecko-demo-agent ask <session_id> "what's the strongest validation signal?"
```

## Backup path

If devnet flakes mid-demo, fall back to local stub mode without changing
the script:

```bash
X402_MODE=stub uv run gecko-api &
gecko-demo-agent research "a hotel guide for Brazil" --api-url http://localhost:8000
```

Same code path, same output, no on-chain explorer link.

## Env vars

| Var | Default | Purpose |
|---|---|---|
| `GECKO_WALLET_PASSPHRASE` | `default` | Decrypts `~/.gecko/wallet.json` |
| `X402_NETWORK` | `solana-devnet` | Used to build the explorer URL |
