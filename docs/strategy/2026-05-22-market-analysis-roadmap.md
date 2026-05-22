# Market-Analysis Roadmap — "See Clearly" (v0.3 foundation)

*2026-05-22. Synthesis of a 6-lens discovery (trading-strategist, data-analyst,
data-scientist, statistician, quant-analyst, ai-ml-engineer) into a phased
roadmap + implementation plan. The founder's frame: stop running, build the
foundation; math not intuition; "a calm sea doesn't make a good sailor" — have a
strategy for every sea, not a wait for the perfect one.*

## The diagnosis (what all 6 lenses agreed on)
**"The agent can't see clearly" is literally true at the data + architecture level — it is NOT a prompt/timidity problem.**
- It reads a **2-hour window of 5m candles** through a momentum lens. **There is no 4h timeframe anywhere. There is zero structure detection** (no swing highs/lows, no support/resistance, no HH/HL).
- It's **inverted**: the 5m trigger *originates* the thesis; higher TFs only veto. A pro runs **4h decides *if* → 1h decides *where* → 15m decides *when*.**
- `chart_analyst` is over-narrow (0 bullish / 2,712 polls) **because it's asked to eyeball structure it can't see** (S/R off 30 raw rows). It's a data problem wearing a prompt costume.
- And three **live data bugs** corrupt even what it does read (below).

## Three live data bugs (data-analyst — fix FIRST, they invalidate everything downstream)
1. **🔴 The Wave-2b CVD/net-flow gate is a silent NO-OP** — parses a USD field that doesn't exist in `token trades` → always `neutral` → blocks nothing.
2. **🔴 The signal bar is the *forming* candle** (`confirm=0`, high/close still moving) → premature breakout fires that mean-revert = the "enter at exhausted micro-tops" symptom.
3. **🔴 Quote-token unit inconsistency** (PYTH USDC-quoted, WIF SOL-quoted) → any USD math must read `changedTokenInfo` per-trade.
Plus: `volUsd` discarded; candle-order sort is a load-bearing single-point-of-failure; no order-book in onchainOS (DEX has no CLOB → OKX/Birdeye proxy); **4h+15m candles already work, just never called.**

## The quant reconciliation — ✅ RESOLVED 2026-05-22 (`db113f2`, `docs/strategy/2026-05-22-exit-reconciliation.md`)
The question was: binary **TP2/SL3 backtest says −EV** vs **live N=7 trailing exits show 3.6:1** — which exit model is truth? **Settled with a faithful replica of the live exit stack** (trail-activate +1% / give-back 1% / stall-green / flat-stall / close-based polling, not intrabar-touch). **Verdict — the edge is NOT in the exits, and the −EV is NOT an artifact of the wrong exit model:**
- Real-exit net-EV is **negative with the block-bootstrap CI excluding zero in EVERY regime** (ALL −0.58%, TREND −0.62%, TRANSITIONAL −0.48%, CHOP −0.63%); replicates across both windows (N≈175, N_eff≈135).
- The real stack improves the *shape* (payoff 1.5–2.0:1 vs binary 0.7:1 — trail/flat-stall cut the loss tail to −0.58% vs binary −2.2%) but **gross EV is only +0.17%/trade → break-even fee 0.17%, below any real DEX fee.**
- **The live N=7 (3.6:1 / +1.31%) was small-sample luck:** jackknife — dropping the single WIF +6.21% trade collapses the mean to +0.50%; 5 of 7 live exits fall outside the backtest window; the live entry gate itself backtests *negative* (−0.64%), so selection quality isn't the explanation.

**→ THE STRATEGY IS FEE-DOMINATED, not exit-limited or entry-floor-limited.** Both the exit mechanism and the entry floor move EV by *less than the fee*. Keep the exit stack (good risk management — it cuts the loss tail), but the gross edge isn't above costs. **This re-prioritizes the roadmap: the fee/venue lever is now the dominant Phase-1 move (see below), the structure/multi-TF analysis is the second lever.**

---

## The phased roadmap

### Phase 0 — Data Integrity (you can't read clearly through bad data) — *do first, ~days*
- **0.1** Fix the forming-candle bug: evaluate on the last *closed* bar (drop/handle `confirm=0`). [the −EV-entry mechanism]
- **0.2** Fix the CVD USD reconstruction (`net_flow._parse_usd` → read `changedTokenInfo` quote leg × quote-USD price; side from `type`). Make the Wave-2b gate actually work.
- **0.3** Capture `volUsd` from kline; add a guard/test on the newest-first→ascending candle sort.
- **0.4** Start a real **outcome ledger** (entry → realized exit reason + net PnL) so validation isn't 100% reliant on candle reconstruction.
- **0.5 (highest value) — ✅ DONE (`db113f2`):** Re-ran with a faithful replica of the live exit stack. **Verdict: edge NOT in the exits; strategy is fee-dominated (gross +0.17% < break-even fee 0.17%); live N=7 was luck.** See the resolved section above + `2026-05-22-exit-reconciliation.md`. *This result promotes the fee/venue lever to Phase 1.* (quant)

### Phase 1 — Two levers in priority order: (A) the FEE/VENUE lever [dominant, NEW], (B) the multi-TF read + structure
*Phase 0.5 proved the strategy is fee-dominated: gross edge +0.17% vs a ~0.5–0.75% DEX round-trip. Lowering the fee bar is the bigger, cheaper move; the structure work then has to clear a much lower bar. Do (A) first.*

- **1.0 — THE FEE/VENUE LEVER (dominant). ✅ DECIDED 2026-05-22 → `docs/strategy/2026-05-22-fee-venue-decision.md`.** The 3-lens package resolved it: **the DEX-vs-CEX fork was a false binary, and "CEX already wired" was wrong** (the wired path is a DEX taker-swap router, no maker/limit). **Decision: stay on-chain. Fix the fee with Jupiter RFQ (~0.04% RT, interim) → Phoenix CLOB maker (~0% maker, the real fix)** — both on-chain, self-custodial, *cheaper* than OKX CEX maker (~0.18%), and identity-true. **CEX rejected** for the house path (more expensive than the on-chain orderbook + breaks the non-custodial/x402 story the proof-artifact exists to prove); kept only as a user-selectable neutral adapter.
  - **The hard truth (quant EV-at-each-fee table):** even at ~0% fee, *today's* gross edge (+0.09–0.17%) is a coin-flip (CI straddles zero). The fee buys ~0.55%/trade and turns a guaranteed loser into break-even; a **~2.4–4× gross-edge lift** (the Phase-1 structure work) must carry it past. **Both levers required** — neither alone clears the 2×-fee gate.
  - **Lower frequency alone does NOT fix per-trade EV** — only helps combined with the edge work + a higher-R:R gate.
  - **Build order:** the §5 fee×gating sweep FIRST (Phase V, below) → confirm the fee path's depth on our 5 names (RFQ/Phoenix probe, web3) → Jupiter-limit/RFQ interim → Phoenix maker.
- **1.1** Add 4h + 15m candle fetch (zero-cost — `kline --bar 4H/15m` already works); probe 4h history depth first.
- **1.2** `features/structure.py` — swing-pivot detection → support/resistance level table → HH/HL market-structure classification → range boundaries. Pure functions (the `indicators.py` pattern). **P0 — decorrelated from momentum, the direct fakeout fix.** (data-scientist)
- **1.3** `features/patterns.py` (engulfing/pin/inside/outside — only `pattern@level`), `features/flow.py` (RVOL/VWAP/CVD-divergence, absorbing fixed `net_flow.py`), breakout/retest-quality features.
- **1.4** `features/mtf.py` — per-TF regime (4h bias / 1h structure / 15m setup / 5m trigger) → one **alignment score [−1,+1]** = the product (kills counter-context fakeouts).
- **1.5** Re-spec `chart_analyst` to grade **labeled structure** (level table, HH/HL, alignment score) instead of raw rows — fixes the over-narrowness at the source. (strategist + ai-ml)
- *Every feature passes the Phase-V validation gates before it's trusted.*

### Phase 2 — Regime router + per-regime strategies (the "tool for every sea")
- **2.1** Extract `voices/regime_router.py` — regime tuple → `StrategyContext` (permitted strategies, chart floor, direction bias, rule label). Pull the inline modulators out of `coordinator_rules.py`. (ai-ml)
- **2.2** Top-down gate: 4h bias → 1h structure → **15m R:R-gated entry** (entry/stop/target/R:R from structure; reject R:R < ~1.5 after fee). The R:R gate is the −EV fix (target next 1h resistance ≈ 2–4% > fee). (strategist)
- **2.3** Per-regime strategy map: trend-pullback / breakout-retest / **range mean-reversion** / **stand-aside or short** in down-tide. (Confirm shorting availability via web3-engineer; else flat.)
- **2.4** Promote net-flow to a first-class `flow_voice` (a real decorrelated axis). (ai-ml)

### Phase 3 — Sizing/risk + model + voice tuning (fold in the prior 4 items)
- **3.1** Vol-targeted sizing (constant risk budget ~0.5–1%/trade, position = risk ÷ stop-distance); **quarter-Kelly cap**; bankroll-relative drawdown breaker; the Kamino yield floor as the stabilizer. (quant — fixes "win big / lose big / stop")
- **3.2** The replay harness → **DeepSeek V3 model A/B** for chart_analyst (vs gpt-4o-mini), replay-gated.
- **3.3** **chart floor relaxation** (0.85→~0.72) + EMA→contributor — *now safe* because the regime router (Phase 2) blocks the chop/downtrend longs the high floor was bluntly suppressing. Sequenced, one variable at a time, replay-gated.

### Phase V — The validation spine (runs THROUGHOUT, gates every phase)
- **V.0 — ⭐ THE DIRECTION-FALSIFIER (run FIRST, free, on cached data).** `scripts/calibration/fee_sensitivity_gating_delta.py`: replay the cached windows through the exit-reconciliation simulator, sweep **fee × `gating ∈ {on, off}`**, emit `netEV / block-CI / payoff` per cell. **The bot is a proof artifact; the bar is the GATING DELTA, not absolute PnL** — does `backtest(gating=on) − backtest(gating=off)` come out positive + CI-clean (do the trades Gecko *let through* beat the ones it would *veto*)? Two free answers before we build: (1) does ANY reachable fee make net-EV CI exclude zero — if not even at 0%, the *edge* not the venue is the blocker; (2) is the gating delta positive at break-even fee — if zero/negative (the live entry gate already backtests −0.64%), **the wedge itself needs work before any venue or feature build.** Note: at high fee the fee MASKS the gating signal (every gated trade loses ~0.5%), so the delta is only legible at break-even fee. (quant + strategist)
- **V.1** Extend `scripts/calibration/` → `feature_validation.py`: a `Feature` protocol (computed strictly on `candles[:i+1]`), **block-bootstrap CI** (replacing the IID `bootstrap_ci` — autocorrelation makes effective-N ≪ raw-N), **leakage traps** (shuffle + placebo-label), **per-regime partitioning**, **FDR multiple-comparisons** + a pre-registration ledger, **walk-forward** folds. (statistician)
- **V.2 Acceptance gates — a feature/strategy ships ONLY if (default REJECT):** leakage-clean; net-of-fee EV block-CI **excludes zero** in its declared regime; survives **BH-FDR** across the batch; **N_eff ≥ 30**; out-of-sample positive, same sign across folds; **incremental** over the existing panel (VIF); **economically meaningful** — **gross edge ≥ 2× round-trip fee** (≥~1.5% at 0.75%, ≥~1.0% at 0.5%). (statistician + quant)

## The EV bar (quant — what the whole thing must beat)
- Net expectancy > 0 with a **95% bootstrap CI lower-bound excluding zero** — never a point estimate.
- **N ≈ 100 closed, regime-matched trades** to confirm a sub-1% edge (trend question is ~14× underpowered today). Bake outcome-labeling in from day one.
- Lever priority: **A) regime→strategy routing** (highest — tuning is exhausted, EV must come from running the right strategy per regime), **B) stronger entry signal that lifts would-win** (not the threshold — selectivity alone inverted the edge), **C) lower fees** (real but capped — 0.75→0.10 only moves break-even 75%→62%), **D) fewer trades** (only with B).
- **Paper-before-live**: go live only after the paper CI excludes zero + clears the 2×-fee gate; then a small-size vol-targeted live A/B.

## Sequencing + the honest framing
- **Order:** Phase 0 (data integrity + exit reconciliation) → Phase V harness → Phase 1 (multi-TF + structure) → Phase 2 (router + R:R + per-regime) → Phase 3 (sizing + model + relaxation). Validation gates every step.
- **Honest:** the EV bar is HIGH (gross ≥ 2× fee) and today's data is **one provisional window**. The exit-reconciliation (0.5) might reveal the edge is already in the trailing exits — *measure that before building features on a false −EV premise.* Nothing goes live until paper-validated. This is math, not intuition — exactly the founder's frame.
- **Local-lab discipline:** build + validate in `contest_bot/` first; transplant winners to the PRD oracle.

## Open questions to resolve early
1. Does onchainOS `kline 4H` return ≥120 bars for the 5 majors? (probe — strategist/data-analyst)
2. Is **shorting** available on the execution venue? (web3-engineer) — decides down-tide = short vs flat.
3. Confirm the **real round-trip fee** (web3-engineer) — the R:R floor + 2×-fee gate key off it.
4. Is the goal still capital-preservation (favor fewer, higher-R:R trades)?

## Status
Discovery complete (6 lenses). **Phase 0.5 (exit reconciliation) DONE** + **Phase 1.0 fee/venue package DONE.** Two settled findings reframed the roadmap:
1. **The strategy is fee-dominated, not analysis-limited** (0.5). The −EV is real, not a measurement artifact.
2. **The fee fix is on-chain** (1.0) — the DEX-vs-CEX fork was a false binary; CEX is rejected (more expensive than the on-chain orderbook + identity-breaking). Path: Jupiter RFQ → Phoenix maker. But even free execution is a coin-flip on today's edge — **both** the fee fix and a ~2.4–4× gross-edge lift are required.

**The deepest reframe:** the bot is a **proof artifact**, so the bar is the **gating delta** (gated > ungated, CI-clean), not absolute PnL. This makes **V.0 (the fee×gating sweep) the highest-value next measurement** — it falsifies the whole direction for free before we build, and may reveal the *wedge itself* needs work (the entry gate backtests −0.64%).

**Next, in order:**
1. **V.0 fee×gating sweep** — the direction-falsifier (free, cached data). Does the gate discriminate at break-even fee?
2. **Foundation L1 — Phase 0 data integrity** (forming-candle, CVD, volUsd+candle-guard, outcome ledger) + **Phase V spine** (block-bootstrap, leakage traps, per-regime, FDR, walk-forward, acceptance gates). Venue-agnostic; needed regardless.
3. **Foundation L2 — Phase 1 structure/multi-TF** (the gross-edge lift) → only meaningful once V.0 confirms the gate discriminates.
4. The on-chain fee path (RFQ depth probe → Phoenix adapter) as the execution-layer build.

Granular TDD plan for L1 (Phase 0 + Phase V incl. V.0) → execute via subagent-driven-development.
