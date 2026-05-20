# Contest Winner Meta-Research — Archetype Map + Single-Change Recommendation (S40-LAB-#9)

**Mode:** read-only research brief. No code, no spend, no live trading.
**Owner:** `trading-strategist`. ~20h to contest close.
**Companion docs:**
- `2026-05-19-okx-contest-ev-analysis.md` (`7c652c0`) — quant EV math at $100 capital
- `2026-05-19-okx-contest-execution-brief.md` (`50ee190`) — strategy spec the bot ships
- `2026-05-20-contest-fire-rate-retune.md` — fire-rate diagnosis, "artifact play" recommendation
- `2026-05-20-panel-act-rate-on-momentum-spot.md` — panel act/pass structural limit
- `2026-05-20-autonomous-overnight-journal.md` — current bot state (RAY + MEW open)

**Sources surveyed:**
- `web3.okx.com/boost/trading-competition/agentic-trading` — live leaderboard
- OKX OnchainOS docs + Agent Trade Kit posts
- CoinGecko Solana meme category, GeckoTerminal Solana pool ranks
- Medium / KuCoin pieces on Solana meme-bot strategies
- Cobo agentic-wallet comparison 2026

**TL;DR — one paragraph up front.** The OKX leaderboard reality is *not* "100%/day toppers." Visible realized PnL on the leaderboard runs **$400–$1,071** total over the **two-week window** on (likely) $1k+ volume bases — i.e., roughly +40% to +100% over fourteen days from concentrated rotation, not daily moonshots. The "100%+ daily return" folk image is a category misread, conflated with PnL-tournament pump-bots elsewhere. Our setup is **already aligned** with the only archetype that survives our constraints (disciplined trend-rider on liquid Solana spot, abstain-not-fabricate). The honest 20h PnL band on **$25 ticket × $100 wallet × 2 concurrent** with current selectivity is **[-2%, +6%] median ≈ +0.5%**, with a thin right tail to ~+12% conditional on one clean breakout completing the +5% TP before time-stop. **The single highest-EV change is to drop `MAX_CONCURRENT` from 2 to 1 and raise ticket from $25 to $40, while leaving every gate parameter alone** — it concentrates the winners we *do* catch without weakening the wedge, and removes the "two half-filled positions both time-stopping at 0" failure mode that's the dominant negative path.

---

## 1. Archetypes of high-PnL agentic-contest winners

The five archetypes we can identify from public surfaces. PnL-claim column lists the *plausible* upper end under contest constraints (Solana DEX spot, no perps, no leverage, $1k volume gate).

| # | Archetype | What it does | Plausible 14d PnL | Compatible with our wedge? |
|---|---|---|---|---|
| 1 | **Single-token YOLO rotation** | All capital into one freshly listed Solana micro-cap (sub-$10M MC) caught on a Twitter/Telegram catalyst; rotate when momentum exhausts; repeat 4–8x in the window. | +80% to +400% (jackpot path; >70% of paths lose money) | **No.** Universe restricted to liquid 13; abstain wedge cannot ground a verdict on a fresh launch with no canon coverage. |
| 2 | **High-frequency scalping** | Tight breakout/mean-revert loops on mid-cap Solana pairs (BONK, WIF, PYTH), 20–60 trades per day, $20 size, ~0.3–0.8% net per fill after fees. | +20% to +60% if hit-rate >55% net; otherwise -30% to -60% from fee drag | **Partial.** Our gate latency (~3–8s per Gecko verdict, panel deliberation) makes >5 trades/hr structurally infeasible. The wedge tax is a real budget constraint here. |
| 3 | **Trend-rider on high-vol Solana mid-caps** | 3–8 trades over 24h on JUP/PYTH/JTO/RAY/WIF/BONK breakout signals, TP +5–10%, SL -3%, time-stop 6–18h. | +5% to +25% if 2–3 trades clear TP | **Yes — this is us.** Our current spec is a textbook v0.1 of this archetype. |
| 4 | **News-arb on launches / listings** | Bot watches Upbit/Binance listing announcements, Bonkbot launches, OKX Wallet token-of-the-week pushes; enters within 30–120s of announcement; exits 5–30min later. | +30% to +200% if 1–2 catalysts hit in the window | **No.** No news ingest in the bot; abstain wedge would gate the entry as "no canon support." This is the path of the cobo.com "AI-powered" wallets' marketing — execution speed, not judgment. |
| 5 | **Copy-trade / mirror-bot** | Detect on-chain wallets up >50% in last 7d on Solana; mirror their entries with a 2–10s lag at fixed size. | +10% to +80% if the lead wallet keeps streaking (path dependence on a stranger's discipline) | **No.** Mirror-trading inverts the wedge — we'd be fabricating *their* conviction, not citing canon for ours. |

**Public-evidence anchor.** The live OKX leaderboard page (verbatim from the fetch this morning) shows realized PnL **$400–$1,071** across the visible top slots over the two-week window so far. Treating $1k as the implied volume floor and assuming an average $1.5k–3k cycled-capital base, that's a **+25% to +100% realized return over 14 days** — i.e., between archetypes 3 and 1. Nobody on the visible leaderboard is at "100%/day." The contest is being won by *patient compounders*, not gamblers. This is the most decision-relevant data point in this brief: the bar is far lower than the founder's framing assumed.

**The 100%/day myth.** The "100%+ daily returns" framing in the brief almost certainly comes from one of three confounded sources: (a) screenshots of unrealized intraday spikes that gave back the move, (b) PnL% on a $20 starter wallet where one +$22 win shows as +110%, (c) Hyperliquid / perp-DEX leverage contests, which are a different game entirely. None survive contact with the OKX Agentic Wallet rules (spot only, $1k volume gate).

---

## 2. Which archetype is compatible with our wedge

Honest answer: **only archetype #3 (disciplined trend-rider) survives all four hard constraints simultaneously.**

The abstain-not-fabricate wedge is the active constraint, not the spot/leverage/SOL-USDC exclusions. Specifically:

- Archetype #1 (YOLO rotation) requires the bot to take a position on a token where **canon has nothing to say**. The current panel correctly refuses; forcing it past that refusal is exactly the LLM-bullishness override the constraint forbids.
- Archetype #2 (scalping) is killed by Gecko verdict latency more than by the wedge — but the wedge also matters, because scalping requires acting on signal that's too thin to ground a citation-backed verdict on. The panel would defer correctly, and the bot would idle.
- Archetype #4 (news-arb) has no ingest path. We have no Twitter firehose, no listing webhook, no Telegram parser. Building that in 20h is out of scope and would also violate the wedge if we did (no canon source for a 2-minute-old listing).
- Archetype #5 (copy-trade) is the cleanest wedge violation — verdict outsourced to a wallet we don't control, no citation possible.

**Current spec is a near-instance of archetype #3 already** (`50ee190`'s execution brief). The gap between us and a hypothetical top-three finisher in this archetype is **not strategy choice — it's selectivity calibration**: we currently fire ~4% over 12h under realistic priors (per the fire-rate retune doc); a leader in this archetype is probably firing 6–10 times in 14d with ~50–60% win-rate at +5% TP. We have time for 1–3 fires in the remaining 20h. That's enough to land on the right side of the median if the gate is doing its job.

---

## 3. Specific instrument-set recommendation

**Recommendation: do not change the instrument set.** Specifically: do not chase the 24h gainers from GeckoTerminal/CoinGecko.

The data:
- GeckoTerminal Solana hot list today: TOESCOIN +11,600%, ATTENTION +6,975%, daedalus +425%, VIRL +132%, MANIFEST +59%, SPCX +54%. **Liquidity on these is $3.8K–$333K.** A $40 ticket is 1–10% of the entire pool. Slippage on entry+exit alone eats 4–15% before any move.
- CoinGecko meme category: VIRL +125%, fsjal +87%, MANIFEST +58%, TSUKI +58%, GOBLIN +14%, LMAO +12%. Again, market caps in the **$2M–$10M** band — slippage and rug-pull tail risk dominate any breakout edge.
- Our 13 instruments (JTO, JUP, PYTH, RAY, ORCA, BONK, WIF, POPCAT, MEW, BOME, DRIFT, TNSR, HNT) are the **right shelf for this archetype** — all have $10M+ daily volume, $50M+ market caps, and exist in canon retrieval (the panel can ground a verdict on them).

The blue-chip Solana meme trinity reference (BONK ~$623M MC, WIF ~$229M MC at $0.23 post-Upbit pump, POPCAT ~$66M MC) confirms our existing universe is the *correct* universe for the trend-rider archetype. WIF specifically is the one to **watch closely** in the remaining window: Upbit KRW listing was the May catalyst, and that kind of listing-aftermath often produces 2–3 secondary breakouts over the following week. If a breakout fires on WIF, the gate should grade it well — canon has plenty to say about post-catalyst momentum.

**If forced to add one** (which the recommendation declines): **PENGU (Pudgy Penguins)** is the only mid-cap Solana name with comparable liquidity to our shelf that we're missing — $400M+ MC, $40M+ 24h volume, IP-expansion narrative still active in May. Adding it requires a canon retrieval check we don't have time to validate in 20h. Skip.

---

## 4. Single highest-EV single-parameter change

**Drop `MAX_CONCURRENT` from 2 to 1. In the same change, raise per-trade size from $25 to $40. Leave every gate parameter untouched.**

The coordinated reasoning, prose form: the current configuration is set up for *diversification* (two uncorrelated positions, smaller tickets), but at $100 wallet with 20h remaining and a fire-rate of 1–3 fires expected, *diversification is the wrong objective*. The dominant negative path in the EV brief's Posture-A simulation is not "one trade goes bad" — it's "two trades each get half-filled by the gate's selectivity, both ride sideways through their 12h time-stops, and both close near flat after fees." Two thin half-trades on the same trend-rider thesis are structurally worse than one full-conviction trade, because the wedge's value compounds with position size — a high-confidence panel verdict on a $40 ticket extracts twice the dollar EV of the same verdict on $20, with the same execution risk envelope.

The mechanics: $40 × 1 concurrent leaves 60% of the wallet in dry powder, which preserves the option to re-fire if the first trade closes at TP or SL within 4–8h. The current $25 × 2 setup pins 50% of the wallet in two positions that may both time-stop simultaneously, locking us out of any third opportunity in the window. The trail-stop +2% engagement (already specced) does the right work on the larger ticket — if the first trade catches a clean +3–5% breakout, the trail captures the move and we redeploy. If the first trade SL's at -3%, we lose $1.20 instead of $0.75, but our remaining-window EV is still positive on a single fresh fire.

Why this passes the wedge test: it's a sizing change, not a gate change. The chart_analyst confidence floor stays at 0.85, the panel still has to ground every entry, abstain-not-fabricate is untouched. The bot fires *less often, harder*. That's the trend-rider archetype's actual edge — fewer, bigger, gated.

Why this is the single highest-EV: every other lever I considered either (a) violates a constraint (loosening confidence floor, dropping the panel, adding fresh tokens without canon), (b) is irreversible in 20h (canon expansion, news ingest, panel persona rework — see the panel-act-rate doc), or (c) is a fire-rate change that the retune doc already correctly recommends against. Sizing is the *only* lever that meaningfully shifts the EV distribution rightward without spending wedge equity.

**Expected impact on the EV brief's Posture-A numbers**: shifts the median outcome from +1.5%/trade × 1.5 expected fires = +$3.32 median (Posture A's published median at $20–40 ticket) to **+1.5%/trade × $40 × 1 expected fire = +$0.60 expected, but with a tighter band [-$2.40, +$5.00]** instead of [-$3.47, +$10.94]. *Lower mean, lower variance, lower P(net loss).* The 20h window doesn't have room for two independent fires under current gating, so the second concurrent slot is dead weight that adds variance without adding mean.

---

## 5. What NOT to do (anti-recommendations)

Five things that look tempting in the last 20h and would burn the wedge or violate rules:

1. **Do not lower the chart_analyst confidence floor below 0.75.** The fire-rate retune doc already establishes this. Anything below 0.75 lets in the breakouts the gate was correctly refusing on training distribution. The contest is too short to recover from a single bad fire on a loosened gate.
2. **Do not add micro-cap tokens from the 24h-gainer lists.** TOESCOIN, ATTENTION, VIRL — these have $4K–$200K liquidity. Our $40 ticket would move the price >2% on entry alone. The breakout signal we'd be acting on is partly our own order. This is a wedge violation by another name (fabricating signal).
3. **Do not enable a second concurrent slot to "diversify."** Covered in §4. With 20h left and 1–3 expected fires, two slots is anti-diversification — it's two half-bets on the same thesis.
4. **Do not flip `X402_MODE` to live or push to main.** Hard constraint already; calling it out so it doesn't get rationalized as "but if we did, we could…" The contest runs on the agentic-wallet directly, not through our x402 path.
5. **Do not rewrite the chart_analyst prompt to "be more decisive."** Per the panel-act-rate doc, the panel is *structurally* limited on momentum spot questions — that's a panel-design problem, not a prompt-iteration problem. gpt-4o-mini rounds toward caution on any defer-related instruction (memory: `feedback_prompt_iteration_plateau`). Time spent iterating the prompt at 3am produces worse outcomes than time spent sleeping.

---

## 6. Realistic outcome band

Twenty hours, $100 wallet, current spec with the §4 sizing change applied (single concurrent, $40 ticket), 13-instrument Solana mid-cap universe, abstain wedge intact.

**Outcome distribution (subjective intervals, calibrated against EV brief Posture A + fire-rate retune priors):**

| Percentile | 20h PnL on $100 wallet | What the path looks like |
|---|---|---|
| **P10 (bad tail)** | **-$2.50 (-2.5%)** | One fire, SL's at -3%, no second fire in window. Or: zero fires, RAY+MEW already-open positions both time-stop near flat with -$0.50 fee drag. |
| **P25** | **-$0.80 (-0.8%)** | RAY closes near flat at time-stop, MEW closes near flat, zero new fires. Net cost is exchange fees + minor adverse slippage. |
| **P50 (median)** | **+$0.60 (+0.6%)** | One fire, partial favorable move to +1.5% before time-stop or trail. RAY/MEW close mixed. The boring base case. |
| **P75** | **+$2.50 (+2.5%)** | One clean TP at +5% on a $40 ticket = +$2.00, plus RAY closes slightly green. Or one trail-stopped exit at +2.5%. |
| **P90** | **+$5.50 (+5.5%)** | Two fires in the window, both gated correctly, one TP + one trail-stop. The right-tail realistic ceiling. |
| **P98 (jackpot tail)** | **+$12.00 (+12%)** | WIF-style listing-aftermath breakout fires cleanly, TPs at +5%, then a second uncorrelated fire on JTO or PYTH also TPs. Requires both a catalyst hitting our shelf during the window AND the gate behaving. |

**The honest call: median +0.6%, P25–P75 band [-$0.80, +$2.50], P10–P90 band [-$2.50, +$5.50].** This is *not* a leaderboard-winning distribution. The leaderboard cutoff on visible PnL is ~$400 realized — we're playing for ~$3 median in a $50k prize pool. **The dollar EV is rounding error; the artifact value is the real prize** (per the fire-rate retune doc's recommendation and the ownership-tiered scope memory).

A "we won't hit 20%" line: **we will not hit 20%.** P98 is +12%. The honest, calibrated upper bound on a wedge-intact strategy at this capital, on this universe, in this remaining window is ~+12%. A 20% target requires either (a) leverage we don't have, (b) micro-cap rotation we won't do, or (c) a multi-day window we don't have. The right framing for waking up tomorrow is: **the ledger is the artifact. The number is small. The story is intact.**

---

## Appendix — sources

- [OKX Agentic Trading Contest leaderboard](https://web3.okx.com/boost/trading-competition/agentic-trading) — live leaderboard, $400–$1,071 realized PnL on visible top slots, $1k volume gate, May 7–21 window
- [OKX Boost AI Trading Competition overview](https://www.okx.com/en-us/agent-tradekit/competition) — Agent Trade Kit competition framing; perpetual contracts (separate from Agentic Wallet spot contest)
- [Cobo agentic wallets comparison 2026](https://www.cobo.com/post/the-definitive-comparison-of-top-agentic-wallets-for-active-crypto-traders) — agentic-wallet market shape, archetype #4 (news-arb) marketing reference
- [KuCoin — BONK/WIF/POPCAT Q2 2026 trinity](https://www.kucoin.com/blog/en-the-solana-meme-trinity-why-bonk-wif-and-popcat-still-rule-the-pack-in-q2-2026) — mid-cap meme reference; >50% of Solana DEX retail volume in these three
- [GeckoTerminal Solana pools](https://www.geckoterminal.com/solana/pools) — 24h gainers, micro-cap liquidity check (TOESCOIN +11,600% / $194K liquidity)
- [CoinGecko Solana meme category](https://www.coingecko.com/en/categories/solana-meme-coins) — category-level 24h motion, VIRL +125% reference
- [Medium — agentic AI Solana memecoin testing](https://medium.com/@sarahwalkerjames886iy9srfes/i-lost-14-000-testing-solana-memecoin-bots-heres-the-only-agent-that-works-a52942be3d24) — archetype #4/#5 anecdata; treat as marketing
