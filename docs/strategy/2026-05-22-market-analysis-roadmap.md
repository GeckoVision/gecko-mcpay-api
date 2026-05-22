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

## The quant reconciliation (highest-value single measurement)
The binary **TP2/SL3 backtest says −EV** (demands 75% win-rate; gross edge ~1/7 of the fee). But the **live trailing-stop exits (N=7) show a 3.6:1 payoff** (avg win +2.9% vs loss −0.81%, break-even ~22%, realized 57%). **They measure different exit regimes and disagree on sign.** → **Re-run the calibration with the ACTUAL trailing-stop exit logic, not the TP2/SL3 binary.** The edge may already live in the *exit* mechanism, understated by the binary backtest. This is the cheapest, highest-value thing on the roadmap.

---

## The phased roadmap

### Phase 0 — Data Integrity (you can't read clearly through bad data) — *do first, ~days*
- **0.1** Fix the forming-candle bug: evaluate on the last *closed* bar (drop/handle `confirm=0`). [the −EV-entry mechanism]
- **0.2** Fix the CVD USD reconstruction (`net_flow._parse_usd` → read `changedTokenInfo` quote leg × quote-USD price; side from `type`). Make the Wave-2b gate actually work.
- **0.3** Capture `volUsd` from kline; add a guard/test on the newest-first→ascending candle sort.
- **0.4** Start a real **outcome ledger** (entry → realized exit reason + net PnL) so validation isn't 100% reliant on candle reconstruction.
- **0.5 (highest value)** Re-run `tp_regime_validation.py` / `chart_floor_calibration.py` with the **actual trailing-stop exit logic** — settle whether the edge is in the exits. (quant)

### Phase 1 — The multi-TF read + structure (see clearly) — *the core build*
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
Discovery complete (6 lenses). This doc = the design + roadmap. **Next: the granular, TDD-style implementation plan for Phase 0** (the data-integrity fixes + the exit reconciliation — the immediate, highest-value, real-bug work), then execute phase-by-phase behind the validation gates.
