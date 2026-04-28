# Runbook — twit.sh wallet refill

The twit.sh integration uses a Gecko-owned EVM wallet on Base mainnet to pay
$0.0025–$0.01 per X/Twitter read via x402. The wallet is server-managed: the
private key lives in AWS SSM (`/gecko-api/TWITSH_WALLET_PRIVATE_KEY`),
unreachable from any user device.

This runbook covers refills when the CloudWatch alarm
`gecko-twitsh-wallet-low` fires.

## Address

The funding address is committed in `.env.example` only as a placeholder.
The live mainnet address lives in SSM at
`/gecko-api/TWITSH_WALLET_ADDRESS` and is also surfaced (read-only) at
`GET /internal/twitsh/balance`. Pull it once and bookmark Basescan.

## Check current balance

- **Basescan:** `https://basescan.org/address/<TWITSH_WALLET_ADDRESS>`
  (look at the USDC token balance — contract `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913`).
- **API:** `curl https://api.geckovision.tech/internal/twitsh/balance`
  (returns the address + balance once the S2X-08 client lands).
- **CloudWatch:** metric `Gecko/Twitsh/WalletBalanceUSDC` (us-east-2).

## Refill from a personal wallet

1. Open Coinbase / Phantom / MetaMask, switch to **Base mainnet** (chain
   id 8453). Confirm you have USDC on Base, **not** Ethereum mainnet.
2. Send to the address above. **Recommended top-up: $5 USDC** — that's
   roughly 100 worst-case sessions at $0.05/session of twit.sh calls,
   well above the alarm threshold of $1.
3. Confirm the transaction lands on Basescan. The CloudWatch metric
   updates on the next 5-minute scrape; the alarm clears within ~10 min.

## What the alarm does

When `WalletBalanceUSDC < $1` for two consecutive 5-min periods:

- SNS topic `gecko-ops-alerts` publishes.
- Email goes to `ernanibmurtinho@gmail.com` (the confirmed subscription).
- Service keeps running — twit.sh calls are non-fatal: the upstream
  source-discovery layer drops X results and continues with web sources.

## Disabling twit.sh in an outage

If twit.sh is down or the wallet is drained and refill is delayed:

```bash
aws ssm put-parameter --name /gecko-api/TWITSH_ENABLED \
  --value 'false' --type SecureString --overwrite --region us-east-2
aws ecs update-service --cluster gecko-api --service gecko-api \
  --force-new-deployment --region us-east-2
```

`Settings.is_twitsh_configured()` returns False with `TWITSH_ENABLED=false`
regardless of wallet state, so the integration shuts off cleanly.

## Re-enabling

After funding + the S2X-08 client is live:

```bash
aws ssm put-parameter --name /gecko-api/TWITSH_ENABLED \
  --value 'true' --type SecureString --overwrite --region us-east-2
aws ecs update-service --cluster gecko-api --service gecko-api \
  --force-new-deployment --region us-east-2
```

Then verify: `curl https://api.geckovision.tech/internal/twitsh/balance`
shows `configured: true` with a non-null balance.
