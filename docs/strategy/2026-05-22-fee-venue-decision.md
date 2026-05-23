# Fee/Venue Decision — the lever the exit reconciliation pointed at

*2026-05-22. Synthesis of a 3-lens package (trading-strategist, quant-analyst, web3-engineer) on
the question Phase 0.5 surfaced: the strategy is fee-dominated — so what fee, on what venue?*

## Recommendation (one line)
**Stay on-chain. The "DEX-vs-CEX" fork was a false binary.** Cut the fee with **Jupiter RFQ
(~0.04% RT, interim) → Phoenix CLOB maker (~0% maker, the real fix)** — both on-chain, both
self-custodial, both *cheaper* than OKX CEX maker (~0.18%). **CEX is rejected** for the house path:
it costs more than the on-chain orderbook *and* breaks the non-custodial / on-chain / x402 identity
the product exists to prove. Keep a CEX adapter only as a user-selectable neutral option.

**But the fee is necessary, not sufficient:** even at ~0% fee the *current* edge is a coin-flip
(CI straddles zero). The fee gets us to the starting line (break-even); a ~2.4–4× gross-edge lift
(the Phase-1 structure work) has to carry it past. **Need both levers.**

## Correction to the roadmap's premise
The roadmap said *"CEX maker, OKX Agent Trade Kit, already wired."* **Both halves are wrong:**
- The wired path (`contest_bot/onchainos.py`) is a **DEX taker-swap router** — `swap_execute()` is
  quote→approve→swap→sign→broadcast with `slippage` + `--mev-protection`; **no `order_type`, no
  `limit`, no `post_only`.** It is itself a DEX execution layer at taker cost. Maker fills are NOT wired.
- Reaching CEX maker fills is a **new integration** (OKX CEX spot API / Agent Trade Kit MCP), not a flip.

## The real options (corrected)
| path | RT fee | on-chain? | identity | wired? | gross-edge lift needed (2× fee) |
|---|---|:--:|---|:--:|---|
| DEX taker swap (today) | ~0.5–0.75% | ✅ | true | yes | **6–9×** (≈unreachable) |
| OKX CEX maker | ~0.16–0.20% | ❌ | **breaks non-custodial** | no (new) | 2.4× |
| Jupiter limit order | ~0.4% (0.2% taker on fill) | ✅ | true | no | 2.4× — *a trap, worse than it sounds* |
| **Jupiter RFQ / JupiterZ** | **~0.04%** (2 bps, gasless, 0-slip) | ✅ | **true** | no (quote API, tractable) | **~1.2×** |
| **Phoenix CLOB maker** | **~0% maker / 0.02–0.06% taker** | ✅ | **true** | no (Python SDK, single-tx) | **~1.3×** |

Two on-chain venues (RFQ, Phoenix) reach CEX-grade-or-better fees with **zero identity cost.** That is
the option the binary fork dropped. Jupiter *limit orders* are a trap: 0.2% taker-on-fill (~0.4% RT),
worse than expected and beaten by both.

## The quant's EV-at-each-fee table (the decisive number)
Gross per-trade edge held fixed at the exit-reconciliation value (+0.171% W1 / +0.092% W2), fee swept.
Block-bootstrap 95% CI, N≈175, N_eff≈130–135. (Net-EV(f) = gross − f; a pure location shift, CI width
constant.)

| fee% | net-EV% (W1) | block 95% CI | verdict |
|---:|---:|---|---|
| 0.75 (DEX taker today) | **−0.579** | [−0.738, −0.357] | **confidently −EV** (CI excl 0 neg) — the venue you must leave |
| 0.50 | −0.329 | [−0.488, −0.107] | confidently −EV |
| 0.35 | −0.179 | [−0.338, +0.043] | stops being *confidently* −EV here (~0.32–0.39% across windows) |
| 0.20 (CEX maker) | −0.029 | [−0.188, +0.193] | **break-even-ish, CI straddles 0** — necessary, not sufficient |
| 0.10 | +0.071 | [−0.088, +0.293] | marginally +EV point estimate (W1 only), CI still straddles 0 |
| 0.04 (Jupiter RFQ) | +0.131 | ≈[−0.03, +0.35] | retains ~all the gross edge — still a coin-flip CI |

**Bottom line:** no fee in the realistic range makes *today's* edge a confident winner — even free
execution straddles zero, because the gross edge itself (+0.09–0.17%) is thin and fragile (it's measured
on an entry gate that backtests −0.64%). **The fee move buys ~0.55%/trade and converts a guaranteed loser
to a coin-flip. The edge work converts the coin-flip to a win.** The roadmap's 2×-fee gate clears only at
maker-class fees (≤0.20%) AND a Phase-1 lift to gross +0.4–0.6%. Neither lever alone suffices.

## The reframe that matters most: the bot is a proof artifact → the bar is the GATING DELTA
The bot is a **$0 proof artifact; the Oracle is the product** (positioning doc). So the proof metric is
**not absolute PnL — it's `backtest(gating=on) − backtest(gating=off)`:** do the trades Gecko *let
through* outperform the trades it would have *vetoed*, with a clean CI? A strategy can be break-even
overall and still be a perfect proof artifact if the gate cleanly separates winners from blocked losers.

**Two consequences:**
1. The artifact does NOT need to beat a fund. It needs (a) a fee low enough that net ≈ break-even (so
   fees don't drown the gating signal), and (b) a **positive, CI-clean gating delta.**
2. **At 0.75% fee the fee MASKS the gating signal** — every gated trade loses ~0.5%, so a skeptic just
   says "your gate let through losers." You can't prove the gate works until the fee is at break-even.

**⭐ The single highest-value next measurement** (strategist's §5, free, on cached data):
`fee_sensitivity_gating_delta.py` — replay the cached windows through the exit-reconciliation simulator,
sweep fee × `gating ∈ {on, off}`, emit `netEV / block-CI / payoff` per cell. It answers, for free,
before we build anything:
- Does **any** reachable fee make net-EV CI exclude zero on the +side? (if not even at 0% → the edge,
  not the venue, is the blocker — structure work is mandatory first.)
- Is the **gating delta positive + significant at break-even fee?** (if zero/negative — and the live
  entry gate already backtests −0.64% — then *the wedge itself needs work before any venue or feature
  build*, which is a far more important finding than the venue.)

This is a Phase-V deliverable, run **first**, as the direction-falsifier.

## Open validation items (before committing the on-chain fee path)
1. **Jupiter RFQ depth** on PYTH/WIF/JUP/RAY/JTO at our size — JUP/WIF/PYTH near-certain; RAY/JTO need a
   read-only quote probe (MMs may not quote thin names → AMM fallback at normal cost).
2. **Phoenix book depth** on the 5 names — SOL/USDC + WIF confirmed; the other four unconfirmed.
3. **Maker-fill behavior:** a resting post-only bid may not fill the fast breakout — changes the strategy
   from "enter now" to "rest a bid, accept non-fills." A behavioral change for a momentum entry, not just
   a fee change. (Probe + the gating sweep inform this.)
4. **Pin the real DEX RT fee empirically** — one live `swap_quote` round-trip per symbol (roadmap open Q3).
5. `account_get_trade_fee` for the real OKX tier — only if the CEX *user-adapter* option is built.

## Sequence
Jupiter-limit/RFQ as the interim on-chain fee cut → Phoenix maker as the real fix → DEX-taker + CEX kept
as user-selectable neutral adapters, never the house path. **But first:** the fee×gating sweep — if the
gating delta doesn't survive at break-even fee, the venue isn't the problem and we'd be building the wrong
thing.

## UPDATE 2026-05-22 — Jupiter Ultra is THE execution path (from the Jupiter docs)
The cleaner answer than "RFQ vs Phoenix" is **Jupiter Ultra** (the meta-aggregator, `GET /swap/v2/order`
→ `POST /swap/v2/execute`): it routes every trade through **OKX, JupiterZ RFQ, Metis, and Dflow all
competing for best price.** That **subsumes both** the current path (onchainOS = OKX *alone*) and the RFQ
path — OKX has to *win* the price, and RFQ's ~0.04% kicks in when a market-maker quotes. One integration,
on-chain, self-custodial, identity intact, strictly ≥ the best of its sub-routes. Free tier (1 RPS) is
ample for the trigger-based bot; `x-api-key` from the Jupiter portal. **This replaces onchainOS as the
house execution layer once there's a proven edge to execute.**
- **Phoenix** (the founder's link) is **perpetual futures** — leverage/shorting/funding, a different
  instrument that conflicts with the long-only-spot "safety" positioning. Not a drop-in spot fee fix.
- **Backpack** (~0.16% RT) is a fine Solana-native exchange but **custodial** — same identity tradeoff as
  OKX CEX; keep as a user adapter only.
- **Data caveat:** Jupiter's Price API (`/price/v3`) is **real-time only — no historical candles.** Great
  for live price + token signals (organic score, holders, liquidity), but the data-coverage tape (deeper
  multi-regime history) still needs OKX market API / Birdeye klines or forward collection.
- **Sequencing:** execution is built *after* the edge is proven. The `jup-ag/agent-skills` "integrating-jupiter"
  skill is the build-time tool — install + use it when wiring execution, not before.
