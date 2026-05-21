# Quant Investment Plan — the wallet as a learning lab

*2026-05-21. Founder goal: study + apply quant investing; diversify beyond
volatile trading into more stable strategies; grow $100 → $200 → ~$3,000
(funding more as trading succeeds); generate passive income + dogfood the
product, pre-customers/pre-grants. Synthesized from 3 parallel specialist
agents (defi-engineer, trading-strategist, quant-analyst).*

---

## The honest frame (all 3 agents converged)

**At $100-3,000, this is NOT passive income — it's cheap, real
product-validation + quant tuition.** $3,000 at 8% blended yield ≈ **$20/mo**.
One bad trading week erases a year of yield. The dollar income is irrelevant
below ~$50k capital.

**But that's exactly right for the stated goal.** The founder wants to *study
and apply quant investing*. A small real-money wallet is the ideal quant lab:
real stakes, real on-chain data, mistakes are cheap tuition not painful loss.
The capital buys **skills + a validated product + a track record**, not income.
Each strategy is a module in the quant curriculum, funded just enough to learn
it for real. Sell the income story only at ~$50k+.

## What's genuinely "stable" vs volatile-dressed-as-yield (defi-engineer)

| Strategy | APY | Honest risk | onchainOS today? |
|---|---|---|---|
| **Kamino USDC lending** ⭐ | ~5% (4-9%) | smart-contract + USDC depeg (low); no IL/liquidation | ✅ yes (OKX hosts Kamino Earn catalog) |
| JitoSOL/mSOL (LST) | ~6-8.5% | yield stable, **full SOL price** drawdown | swap-to-LST; partial |
| Stable LP (USDC-USDT) | ~3-8% | depeg tail risk | possible; skip <$1k |
| **JLP** ⚠️ | ~9.5-20% | **NOT stable** — long crypto basket, -18% in Aug-2024; you're the house vs traders | via Jupiter |
| Solana perps (Drift/Jup) | — | high risk / liquidation; delta-neutral funding-capture too heavy for <$3k | not native |

**The only genuinely stable income is Kamino USDC lending (~5%), executable
today.** Everything else trades stability for SOL-price exposure (LSTs) or
hidden crypto drawdown (JLP). "Phoenix" is a Solana SPOT DEX, not perps —
Solana perps = Drift / Jupiter Perps / Adrena.

## Allocation by capital tier (trading-strategist)

Below ~$1k, yield is irrelevant noise ($90 @ 10% = ~$0.02/day) — don't split
prematurely (Pattern-D trap). Allocate by what each tier can actually support:

| Tier | Momentum (meme) | Grid (chop) | Yield (Kamino USDC) | Delta-neutral / copy |
|---|---|---|---|---|
| **$200** | 70% | 30% | 0% | 0% |
| **$1,000** | 35% | 30% | 35% | 0% |
| **$3,000** | 25% | 25% | 35% | 15% |

- **$200:** skip yield; meme + a small **grid sleeve** (grid earns on the chop
  where meme stalls — the missing complement, Track B6).
- **$1,000:** yield becomes a real floor that smooths variance.
- **$3,000:** add delta-neutral funding capture / copy-trade *last*, after the
  others have a live track record.

## "Investment groups" — right abstraction, build the allocator first

The config-spec → bot pattern (starter-coach → validate_spec → runtime) is the
correct abstraction for multiple strategy bots. **But N bots on one shared
balance collide** (double-count budget, race the breaker). Build a
**capital-allocator parent FIRST**: one ledger owns the wallet, assigns each
child bot a fixed sub-budget (sub-account or virtual sleeve), each bot's
`budget_cap` = its sleeve only. The allocator is the prerequisite for "groups,"
not an afterthought.

**Open question (web3/defi-engineer):** does the OKX Agentic Wallet expose true
sub-accounts for sleeve isolation, or only one balance? Determines whether the
allocator is real isolation or virtual accounting.

## "Double to $200" — fund it, don't trade for it (quant-analyst)

- **Trading alone:** 88% chance within 2yr, median **33 weeks**, but ~4% near-ruin.
- **Blended 30/70:** 55% within 2yr, median **98 weeks**, 0% ruin — yield base
  buys safety by *halving* the doubling speed.

Doubling via trading is a coin-flip dressed as a plan. **Fund the $200**; let
trading compound it. Don't make doubling the trading KPI (cranks variance).

## The quant curriculum (the strategies ARE the syllabus)

1. **Momentum** (have it) — breakout entries, the regime-dependence finding
   (breakout is -EV in chop), real-fill PnL accounting.
2. **Mean-reversion / grid** (next) — profits from oscillation; ADX regime gate;
   the kill-metric backtest (grid vs cash vs breakout).
3. **Stable yield / lending** — Kamino USDC; the "risk-free-ish" floor; APY vs
   utilization; depeg tail.
4. **Portfolio construction** — Sharpe, max-drawdown, position sizing (Kelly),
   why the blend's Sharpe comes from the trading bucket not the yield.
5. **Delta-neutral / funding capture** (advanced, $3k+) — long spot + short perp,
   harvest funding; the operational cost.

The math to study alongside: Sharpe/Sortino, drawdown distributions,
first-passage (TP/SL hit probabilities), regime classification, sizing.

## Build sequence (gated — nothing skips the soak test)

1. **48h unattended soak** (Phase-1 gate, non-negotiable) — before any capital scale.
2. **Grid bot in paper, ADX-gated** (Track B6) — highest risk-adjusted add;
   monetizes the stalls. Falsify: run alongside the meme bot one week, compare
   chop-day PnL. If grid doesn't out-earn meme's stalls, the second bucket
   should be yield instead.
3. **Capital-allocator parent** — prerequisite for "groups."
4. **Kamino USDC yield sleeve** — at $1k.
5. **Delta-neutral / copy** — at $3k, last.

## Honest failure modes

- **Over-diversifying at $200** — 4 bot types on $200 = complexity tax for
  sub-cent yield. The #1 trap.
- **Shared-wallet collisions** — if "groups" ships before the allocator.
- **Treating doubling as a trading target** — cranks variance to hit a number.
- **Selling the income story too early** — it's tuition + validation until ~$50k.

## Bottom line

The plan is right *because* it's not really an income plan yet — it's a
**funded quant-learning curriculum** that simultaneously dogfoods the product
and builds a track record. Yield-first stable base (Kamino USDC) + grid as the
quant complement to momentum + fund (don't trade) the milestones + allocator
before groups. The income comes later, with real capital; right now the return
is the *learning* and the *proof*.
