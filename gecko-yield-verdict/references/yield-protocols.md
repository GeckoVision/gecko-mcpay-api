# Yield Protocol Map — what onchainOS reaches, and the Kamino wedge

This file maps yield-deposit questions to onchainOS `defi` discovery
calls. Load it in Step 1 to resolve a user's protocol/token mention into a
search call. Use natural-language matching, not literal string compare.

## How discovery works

onchainOS `defi` discovery is **platform + token + chain** filtered, not a
fixed pair table. The user names a protocol and/or a token; you build a
`onchainos defi search` call from it. There is no need to hard-code pool
IDs — `search` returns candidate `investment_id`s, then `detail` resolves
APY/TVL for the chosen one.

```bash
onchainos defi search --token <TOKEN> --platform <PLATFORM> \
  --chain <CHAIN> --product-group <GROUP>
```

At least one of `--token` or `--platform` is required. `--product-group`:
`SINGLE_EARN` (default — single-asset earn/lending), `DEX_POOL` (LP
positions), `LENDING` (money-market supply).

## The wedge — Kamino

**Kamino is the v0.1 wedge protocol.** It is the protocol named verbatim in
the canonical Class-D question ("should I deposit USDC into Kamino?"), it
is onchainOS-reachable via `okx-dapp-discovery`, and the investor-canon
corpus (Marks on yield/risk, Damodaran on risk premia, Berkshire on
durable franchises) reasons densely about exactly this kind of
single-asset stablecoin yield decision.

| Field | Value |
|---|---|
| Chain | `solana` |
| Typical product groups | `SINGLE_EARN` (lend), `DEX_POOL` (CLMM LP) |
| Canonical question | "should I deposit USDC into Kamino" |
| Discovery call | `onchainos defi search --token USDC --platform Kamino --chain solana --product-group SINGLE_EARN` |
| Verdict `protocol` tag | `kamino` |

Lead demos and the A/B run on Kamino — it is where the corpus is deepest
and the abstain-vs-fabricate differential is most visible.

## Other protocols onchainOS reaches

onchainOS `defi` discovery routes across hundreds of protocols and many
chains (`--chain ethereum | solana | base | bsc | polygon | arbitrum |
avalanche | sui …`). The skill is **venue-agnostic by construction** — it
grades the pool, not the venue, and never hard-codes one protocol. The
table below is orientation only; always confirm reach with a live
`defi search` rather than assuming.

| Protocol | Chains (typical) | Product groups | Verdict `protocol` tag |
|---|---|---|---|
| **Kamino** (wedge) | solana | SINGLE_EARN, DEX_POOL | `kamino` |
| Aave | ethereum, base, arbitrum, polygon | LENDING | `aave` |
| Lido | ethereum | SINGLE_EARN | `lido` |
| Compound | ethereum, base | LENDING | `compound` |
| Marinade | solana | SINGLE_EARN | `marinade` |
| Jito | solana | SINGLE_EARN | `jito` |
| Raydium | solana | DEX_POOL | `raydium` |
| Meteora | solana | DEX_POOL | `meteora` |
| Drift | solana | SINGLE_EARN, LENDING | `drift` |
| MarginFi | solana | LENDING | `marginfi` |
| Curve | ethereum, arbitrum | DEX_POOL | `curve` |
| Pendle | ethereum, arbitrum | SINGLE_EARN | `pendle` |

Notes:

- The exact protocol set onchainOS exposes can change — `defi
  support-platforms` returns the live list. Run it if a user names a
  protocol not in this table; do not refuse without checking.
- Set the verdict `protocol` tag to the normalized lowercase name. Canon
  literature is cross-cutting and carries `protocol=[]`, so general
  investor-canon citations reach the panel for *every* protocol; a
  protocol-specific tag additionally surfaces any protocol-tagged chunks.
- If `defi search` returns nothing for a protocol/token/chain combination,
  tell the user the pool was not found on onchainOS — do not fabricate one
  or fall back to a stale figure.

## Reading the discovery output for the verdict

From `defi detail` + `rate-chart` + `tvl-chart`, assemble the fact set the
verdict step consumes:

- `current_apy` — from `defi detail`.
- `tvl` — from `defi detail`.
- `apy_30d_trend` — derive from `rate-chart --time-range MONTH`: rising /
  flat / falling.
- `tvl_30d_trend` — derive from `tvl-chart --time-range MONTH`.
- `pair` / `pool` name, `chain`, `investment_id`, `product_group`.

These facts — all onchainOS-sourced — are what the Gecko verdict reasons
over. The oracle never fetches pool data itself; onchainOS is the sole
data feed, in both baseline and Gecko mode.
