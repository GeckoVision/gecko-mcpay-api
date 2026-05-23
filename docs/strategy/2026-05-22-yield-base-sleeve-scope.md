# Scope — Yield-Base Sleeve (the uncorrelated floor)

*2026-05-22. The Stage-0 strategic move from the self-hosted roadmap. Scoped per
the quant + defi team review. This is a design sketch, not a committed sprint.*

## Why this is the highest-EV next move (not another directional bot)

The quant review was unambiguous: **multi-wallet/more-momentum is NOT a returns win**
(two momentum sleeves ρ≈0.7–0.9 → ~1.05× Sharpe). The entire diversification prize
is an **uncorrelated** sleeve. A stablecoin yield sleeve is ρ≈0 to everything →
**~1.4–1.6× portfolio Sharpe**, and it doubles as the **passive-income floor** and
the **profit vault** in the roadmap. It is the cheapest, most certain edge available.

It also fixes a real inefficiency: today idle USDC (the part of the wallet not in a
trade) earns 0%. At $100 that's noise; at $3–5k + ~2k BRL/month contributions, idle
capital earning 0% is a real drag.

## What it is

**Park idle USDC in a low-risk lending venue; keep an active tranche liquid for trades.**

```
Wallet capital
├── ACTIVE tranche  (kept liquid; funds USD_PER_TRADE × MAX_CONCURRENT)
└── RESERVE tranche (swept to Kamino Lend USDC → earns yield)
        ↑ profits sweep here  ↓ withdraw-on-signal if active runs short
```

- **Venue (v1):** Kamino Lend USDC supply (single-sided, no IL, withdrawable). Realistic **~3–8% APY, variable** (utilization-driven).
- **Reserve-only rule:** only park capital NOT needed for an imminent trade. Momentum needs *instant* deployable capital; a Kamino withdraw adds a tx + latency that can miss a fast breakout. Gate: park only capital that passes a "not needed in the next poll cycle" test. Never park the active tranche.
- **Profit sweep:** realized profits flow to the reserve → the yield base compounds (this IS the "vault" the founder wants to grow with ~2k BRL/month).

## What it is NOT (team guardrails)
- **NOT JLP.** JLP is *not* safe stablecoin yield — it's a volatile basket where you're the counterparty to perp traders; "yield" can be erased in a trend. If we ever add JLP, it's a *separate gated directional strategy*, not the cash floor.
- **NOT Kamino-as-execution-venue.** Kamino is for *parking idle capital*, never for executing a trade (you swap to trade; you can't execute a momentum entry through a lending reserve).
- **NOT leverage / kTokens / Multiply** — those add liquidation + depeg surfaces a yield floor must not carry.
- **SOL idle** (gas reserve, future SOL holdings) → **Sanctum LST ~7–9%** (SOL-denominated, separate sleeve) — lowest contract risk, but carries SOL price exposure, so it's not a USD floor.

## Risks (be honest)
- **Kamino program risk** (smart-contract) — mitigated by it being the largest, most-audited Solana lender, but non-zero.
- **USDC depeg** — systemic, unhedgeable here.
- **Withdraw latency** — mitigated by the reserve-only rule (never park active capital).
- **Variable APY** — 3–8% is a range, not a promise; it can compress in low-demand markets.

## Implementation gate (Pattern B/C — non-negotiable)
`packages/gecko-core/src/gecko_core/execution/kamino_devnet.py` is **devnet-simulate
only and explicitly refuses mainnet custody.** A live deposit is a NEW mainnet path,
NOT a flip of the devnet adapter. Sequence:
1. **Free local simulation** of the deposit/withdraw flow (no money) that can falsify the integration.
2. **Recorded-fixture contract test** against Kamino's relevant calls (the `live_cdp`/vcr pattern).
3. **Small live smoke** ($5–10) as the FINAL verification, founder-authorized — never the primary debug tool.

## Capital-staged value (honest)
- **At $100 (now):** build the capability + dogfood it tiny. Returns are negligible (~$2–3/yr on $50 idle) — the point is the *plumbing + discipline*, not the yield.
- **At $3–5k:** material (~$150–400/yr on idle) and the real diversification Sharpe kicks in.
- **Recurring (2k BRL/mo → vault):** the reserve/Kamino position IS the profit vault; this is where the roadmap's vault-privacy (far-future, opt-in) eventually attaches.

## Architecture fit
- Today: a reserve allocation *within the single trading wallet* (one wallet, two tranches).
- At multi-wallet stage: the yield base becomes its **own wallet/sleeve** (one wallet = momentum, one wallet = yield/vault), per the self-hosted multi-wallet roadmap. The `WalletHandle` + strategy-instance abstraction covers it.

## Recommended sequencing
1. **Now:** keep it as scope (this doc). Don't build the mainnet Kamino path while the
   live momentum bot + bundle restart are the active focus.
2. **After** the bundle deploys (next clean restart) and a few live momentum trades give
   us data: build the Kamino mainnet path through the 3-step gate above, dogfood at $5–10.
3. **At $3–5k:** promote the yield base to its own wallet/sleeve; wire the profit sweep.

## Open questions
1. Reserve/active split ratio — fixed (e.g. 50/50) or dynamic (scale reserve up when the bot is declining everything in chop, since capital sits idle anyway)? The dynamic version is elegant: *in chop the bot doesn't trade → sweep more to yield → earn while waiting.*
2. Does OKX onchainOS expose Kamino, or do we go direct to Kamino's program (defi-engineer + solana-architect)? Affects the neutrality/adapter shape.
