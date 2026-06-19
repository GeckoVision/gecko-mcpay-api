# Launch check — the issuer / Block-Zero read

The other side of the same coin. `quickstart.md` is for an **agent about to buy**;
this is for a **founder / launchpad checking a token's launch** — their own, or
one they're about to list — for bot manipulation in the first candles.

Same endpoint, same gate. The framing differs: you're not deciding "should I
trade this," you're deciding "is this launch real, or is it being botted?"

## When to use it

- A founder, minutes-to-hours into their own launch, asking *"is my volume real?"*
- A launchpad deciding whether to **feature / list** a new token.
- Diligence on a token before you put your name (or liquidity) next to it.

## The call (identical)

```bash
curl -s -X POST https://api.geckovision.tech/safety \
  -H "Content-Type: application/json" -d '{"mint":"<SPL_MINT>"}'
```

## What to look at, in order

1. **`gate`** — `block` means the market is manufactured; for an issuer that's a
   signal the launch is being attacked (or is a scam you shouldn't touch).
2. **`information_mev` / `wash_risk`** — *which* manipulation: fake mcap, one-sided
   bot buy-loop (`thin_pool_buy_loop`), price bait across satellite pools
   (`multi_pool_price_bait`), wash recirculation, sybil-funder cluster.
3. **`liquidity_to_mcap_pct`** — a very low ratio means the headline mcap is air;
   real holders can't exit at that price.
4. **`top_holder_pct`** — one wallet on the float = a dump waiting to happen.

## Launch timing caveat (read this)

A genuine fair launch is **naturally thin and concentrated in the first minutes**
— low liquidity, few holders, buy-heavy. The oracle's launch guard avoids
escalating a lone static signal to `block` that early; expect `caution` more than
`block` on a < 1h-old token unless **flow** signals (wash/bot buy-loop/sybil)
corroborate. So:

- `caution` on a brand-new token → often just "it's early," not "it's a scam."
  Re-check as it ages and liquidity builds.
- `block` on a brand-new token with fired wash/bot signals → the launch is being
  manipulated. Act (pause, investigate the buyer cluster, warn your community).

## Monitoring, not a one-shot

Manipulation evolves over a launch. Re-run on a cadence (every few minutes in
hour 0–1, then back off). A token that reads `ok` at mint can turn `manipulated`
once a bot cluster turns on — and vice-versa, an early `caution` clears as real
demand arrives. The verdict is a live read, not a certificate.

> The continuous version of this (a streaming firewall that pre-computes the
> verdict so it's already fresh when you ask) is what powers the `wash_risk`
> block as it rolls out. Until then, poll the endpoint.
