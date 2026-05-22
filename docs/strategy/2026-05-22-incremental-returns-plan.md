# Incremental Returns Plan — the honest ladder to grow the account

*2026-05-22. Branch `s41/oracle-real-execution`. Author: quant-analyst.
Founder ask: a clear, honest, sustainable ladder to grow the account, anchored
on a daily-return target, balancing trading + yield. This doc answers six
questions with numbers, confidence intervals where the data supports them, and
an explicit "no data" flag everywhere it doesn't.*

**Live bot (PID 2198871, port 8265) is read-only and untouched by this doc.**

---

## TL;DR for the founder

- **Honest sustainable daily number: ~0.10–0.20%/day NET, blended.** Not 0.5%.
  **0.5%/day is aspirational, not a floor** — it would require an 80–84% win
  rate on our TP/SL process, which the calibration study shows we do **not**
  have (0% would-have-won in chop, CI [0%,0%]). 0.3%/day is the *proven grid
  benchmark ceiling* (= ~1.5%/week), reachable only after the levers below land
  and are validated. Today, with n=2 live trades, the trading bucket is
  **statistically silent** — we are reasoning from calibration + benchmarks,
  not from a measured live edge.
- **A "mean" is not a floor.** Even at a *true* 0.3%/day mean, a 21-day month
  has a 5th-percentile of **−8%** and a 23% chance of closing red. Variance
  dominates the daily number at our capital. Plan in months, judge in quarters.
- **The fee wall is the hidden enemy of the small-TP math.** A ~0.7% round-trip
  cost eats **35% of a +2% win**. TP2/SL3 needs a **74% net win-rate just to
  break even**. This is the single most important number in this plan.
- **Yield is the STABILIZER, not a peer to trading.** Kamino USDC lending
  (~6% APY, ρ≈0, program+depeg risk only) is far lower risk than directional
  meme trading. It does not "earn its keep" in dollars below ~$1k — it earns
  its keep in **Sharpe** (lifts blended Sharpe ~1.43 → ~1.6) and in **smoothing
  the equity curve**, which is what lets you stay in the game.
- **Time to +10% is a range, not a promise: ~1–3 months median**, but with a
  **31–44% chance −10% arrives first** at today's high vol. The yield base is
  what shifts that race in your favour.

---

## 1. The honest daily target

### Compounding math (computed)

| Daily NET mean | Annual (252 trading d) | Annual (365 cal d) |
|---|---|---|
| 0.10% | +28.6% | +44.0% |
| 0.20% | +65.4% | +107.4% |
| 0.30% | +112.7% | +198.4% |
| 0.40% | +173.5% | +329.3% |
| 0.50% | **+251.4%** | +517.5% |

0.5%/day compounds to ~250%/yr — a number that would put us at the very top of
the proven OKX grid-bot leaderboard *every year*. That alone should set the
prior: **0.5%/day is not a sustainable mean for our capital and maturity.**

### Where 0.5%/day sits vs the proven grid benchmark

The roadmap's north-star (proven OKX spot-grid bots, decoded):

| Bot | Real weekly avg | → daily-equiv (5d/wk) | Max weekly drawdown |
|---|---|---|---|
| SUI/USDT | ~2.4%/wk | **0.495%/day** | 8.08% |
| XRP/USDT | ~1.9%/wk | 0.397%/day | 7.50% |
| TRX/USDT | ~1.7%/wk | 0.298%/day | **0.75%** (gold standard) |

So 0.5%/day ≈ the **best** proven grid bot (SUI, ~2.5%/wk) — achieved over
**654 days** of runtime, by a *grid* strategy in a *favourable* pair, at **8%
max weekly drawdown**. It is a real number for a mature, validated, low-drawdown
grid — it is **not** a starting target for a 2-trade-old momentum bot in chop.

### The variance reality — a mean is not a floor (computed)

I simulated a 21-trading-day month as a TP2/SL3 process, tuning the win-rate to
hit each target mean (net win +1.3%, net loss −3.7% after ~0.7% fees):

| "True" daily mean | Required win-rate | Daily vol | 21-day median | 5th pctile | 95th pctile | P(month < 0) |
|---|---|---|---|---|---|---|
| 0.10% | 76% | 2.1% | +1.8% | **−12.5%** | +18.5% | **39%** |
| 0.30% | 80% | 2.0% | +7.1% | **−8.0%** | +24.7% | **23%** |
| 0.50% | 84% | 1.8% | +12.7% | −3.2% | +24.7% | 11% |

Two things fall out of this table:

1. **Even a *true* 0.3%/day mean loses money 23% of months** and has a −8%
   bad-month tail. The daily target is a *long-run average*, never a floor. Any
   single day, week, or even month can be deeply red while the mean is positive.
2. **The required win-rates (76–84%) are exactly what the calibration study
   says we do NOT have.** The chart-floor study found a 0% would-have-won rate
   with a [0%,0%] bootstrap CI across *every* floor in a 61%-chop window. We
   cannot currently support even the 0.1%/day row's 76% win-rate from data.

### The honest sustainable number

| Horizon / state | Honest NET daily mean | Basis |
|---|---|---|
| **Today (n=2 live)** | **unmeasured — assume ~0.00–0.10%** | calibration says break-even-to-slightly-negative in chop; live sample is silent |
| **After Rung 1–2 levers, validated** | **~0.10–0.20%/day** | regime-routing + yield floor; ~0.7–1.0%/wk |
| **Mature, low-drawdown, multi-strategy** | **~0.30%/day (≈1.5%/wk)** | the TRX-grid gold-standard profile |
| **Aspiration / top of range** | 0.5%/day | the SUI-grid ceiling — celebrate if reached, never assume |

**Anchor target for the plan: 0.15%/day NET, blended, as the near-term goal;
0.30%/day as the validated-mature goal. 0.5% is the aspiration ceiling.**

---

## 2. The incremental ladder — 0.3 → 0.4 → 0.5 (the heart of the ask)

Honest framing first: we are **not at 0.3 yet** — the calibration study puts the
bare momentum bot at break-even in chop. So the ladder below is really
"break-even → 0.3 → 0.4 → 0.5", and **each rung's lift is a hypothesis with a
validation method, not a measured result.** One lever per rung, in priority
order. Do not bank any lift until its validation passes.

### Rung 0 → ~0.15% (net): the yield floor + regime gate (foundation)

| Field | Value |
|---|---|
| **Lever** | (a) Kamino USDC yield base on idle capital; (b) the CHOP gate — *stop trading the break-even-in-chop signal*. Don't add edge yet; **stop bleeding** the negative-EV chop trades the calibration study identified. |
| **Expected lift** | +0.01–0.02%/day from yield (at $1k+); the bigger effect is removing the −0.13 to −0.18%/trade chop drag. Net move from ~0.00 to ~0.10–0.15%/day. |
| **Prerequisite** | Yield-base sleeve (`docs/strategy/2026-05-22-yield-base-build-plan.md`); a deterministic CHOP detector (ADX≤18 / Choppiness Index) wired as an entry veto. |
| **Validate** | Re-run `scripts/calibration/chart_floor_calibration.py` partitioned by regime; confirm trading *only* in non-chop bars lifts per-trade EV CI above zero. Run the grid/cash/breakout kill-metric backtest. **Believe the lift only if the trend-only EV CI excludes zero with N≥30.** |

### Rung 1: 0.15 → 0.3% — regime → strategy routing (momentum in trend, grid in chop)

| Field | Value |
|---|---|
| **Lever** | Add a spot-grid sleeve gated on ADX. Momentum runs in trend; grid harvests oscillation in the chop where momentum stalls. This is the proven path to the 0.3%/day (1.5%/wk) benchmark — TRX-grid did exactly this. |
| **Expected lift** | +0.10–0.20%/day **IF** grid earns its benchmark in chop. Honest range wide because grid's edge in *our* meme pairs is unmeasured. |
| **Prerequisite** | Track B6 grid bot (paper), capital-allocator parent so the two bots don't collide on one balance, the CHOP detector from Rung 0. |
| **Validate** | Run grid in paper *alongside* the meme bot for ≥2 weeks spanning ≥1 real chop period; compare chop-day PnL head-to-head. **If grid does not out-earn meme's stalls with a positive PnL CI, the second bucket should be yield, not grid.** Bootstrap CI on the per-day PnL difference; require it to exclude zero. |

### Rung 2: 0.3 → 0.4% — better/added symbols + multi-timeframe confirmation

| Field | Value |
|---|---|
| **Lever** | Tighten the universe to the names with real amplitude + liquidity (§4), and add a multi-timeframe entry confirm (5m breakout must agree with 1h trend) to cut the "enter at exhausted micro-top" failure the calibration study diagnosed (high-confidence breakouts faded worst, −0.16%/trade). |
| **Expected lift** | +0.05–0.10%/day from higher per-trade EV (fewer fade-entries). Modest and uncertain — this improves *quality* of existing trades, it does not add a new earnings engine. |
| **Prerequisite** | Symbol study confirmed (done — §4); multi-timeframe data (OKX `market_get_candles` at 1h, Track D1). JUP/RAY/JTO admitted only after canon-coverage check (oracle must have citations for them). |
| **Validate** | A/B the entry filter on telemetry: replay candidates *with* vs *without* the 1h-agreement gate; paired comparison of per-trade EV, bootstrap CI on the delta. Require the gated set's win-rate to clear the **74% net break-even** (the fee wall). Confirm added symbols reach +amplitude in a fresh window before live sizing. |

### Rung 3: 0.4 → 0.5% — regime-conditional TP + capital above the slippage floor

| Field | Value |
|---|---|
| **Lever** | (a) Regime-conditional TP (§5) — let winners run to TP4–5 in confirmed trend on high-amplitude names, where the fee math flips favourable (TP4 breakeven = 53% vs TP2's 74%). (b) Size each trade well above the slippage floor so fixed costs are a smaller % of the win. |
| **Expected lift** | +0.05–0.10%/day. The TP lever is the cleanest +EV mechanical change (it directly attacks the 74%→53% breakeven wall), but only *conditionally* — applying TP4 in chop reintroduces the structurally-unreachable target. |
| **Prerequisite** | A reliable trend/amplitude classifier (ADX + per-symbol realized range); enough capital that $/trade ≥ ~$50–100 so fixed slippage is <0.5% one-way. |
| **Validate** | Calibration harness, *trend-window only*: sweep TP ∈ {2,3,4,5} conditioned on ADX≥25 and symbol amplitude; require TP4/5's EV CI to **exceed** TP2's with non-overlapping CIs and N≥30 winners. This is the exact pre-registered rule the chart-floor study used. **Do not raise TP globally on a single good week.** |

**Ladder caveat (load-bearing):** the rungs compound *multiplicatively* and each
lift is conditional on the prior validating. Realistic outcome: we reach a
durable **0.15–0.30%/day** within a quarter or two; 0.4–0.5% is a stretch that
depends on the grid sleeve actually earning its benchmark and TP-conditioning
proving out in trend windows we have not yet sampled.

---

## 3. Trading + yield balance

### Correcting the premise "if yield risk == trading risk"

**They are not equal — not close.**

| Dimension | Kamino USDC lending | Directional meme momentum |
|---|---|---|
| Return driver | Borrow-demand interest | Price direction (you must be *right*) |
| Risk type | Smart-contract + USDC depeg (tail) | Full price drawdown, every position |
| Daily vol | ~0% (deterministic accrual) | ~2%/day (TP2/SL3 process) |
| Correlation to trading | **ρ ≈ 0** | — |
| Expected loss in a bad month | ~0 (absent program failure/depeg) | −8% to −12% (5th pctile, §1) |

Yield is the **stabilizer**: ρ≈0 means its variance *adds in quadrature*, not
linearly, so a yield sleeve cuts blended vol far more than it cuts blended
return. It is the keel, not a second engine.

### Recommended split + blended Sharpe sketch (computed)

Trading bucket modeled at an **optimistic-but-plausible post-lever** 0.15%/day
mean, 2%/day vol (NOT measured — flagged). Yield at 6% APY, ~0 vol, ρ≈0.

| Capital | Trading | Yield | Blended daily mean | Blended daily vol | Ann. Sharpe | Ann. return |
|---|---|---|---|---|---|---|
| **$100** | 90% | 10% | 0.137% | 1.80% | **~1.45** | ~65% |
| **$1,000** | 60% | 40% | 0.096% | 1.20% | **~1.53** | ~42% |
| **$3–5k** | 45% | 55% | 0.076% | 0.90% | **~1.62** | ~32% |
| (ref) 100% trading | 100% | 0% | 0.150% | 2.00% | ~1.43 | ~65% |

Reading:
- **At $100, yield is plumbing, not return** — ~$0.02/day on $10 idle. Keep
  trading-weighted; build the yield rail now for the *capability* and discipline.
- **As capital grows, you trade return for Sharpe.** The $3–5k blend earns less
  in % terms but its **Sharpe rises (1.45 → 1.62)** and its daily vol *halves*
  (1.8% → 0.9%). Higher Sharpe + lower drawdown is what survives a bad quarter.
- **The yield floor smooths the equity curve:** at $3–5k, the −10%-first
  probability in the time-to-+10% race drops from 44% (current) to **12%**
  (§6) — the yield base is doing the smoothing, not a better trading edge.

**Recommendation:** $100 → ~90/10 (capability build). $1k → ~60/40. $3–5k →
~45/55. Note these are slightly more yield-weighted than the prior quant plan's
70/30 and 35/35 splits — that plan was written for a *quant-curriculum* goal;
this one is written for *sustainable returns*, which favours the keel. Both are
defensible; pick by goal. Trading carries the *return*; yield carries the
*Sharpe*. Never let yield's coupon convince you it's earning meaningfully below
~$3k — it isn't; it's buying smoothness.

---

## 4. Symbols — keep vs avoid (building on the symbol study)

The criterion for *sustainable* returns: **amplitude** (does it reach the TP
band?) + **liquidity** (can we enter/exit inside the slippage floor?) + **clean
structure** (does it trend, or just chop?).

| Symbol | Verdict | One-line reason |
|---|---|---|
| **WIF** | **KEEP (core)** | The only name that reached +4% intraday and the *only* source of the 4 calibration winners (all on WIF trend volume-spikes) — has the amplitude the strategy needs. |
| **PYTH** | KEEP | Trends cleanly (median ADX 25.2), liquid; peaked +1.53% — fits the TP2 band, candidate for TP-conditioning when it trends. |
| **POPCAT** | KEEP | Trend posture (ADX 26.8), liquid meme amplitude. |
| **BOME** | HOLD/WATCH | Chop-leaning (ADX 17.4, 141/299 chop bars) — only profitable under the grid sleeve, not momentum. Keep for grid, demote for momentum. |
| **DRIFT** | **AVOID** | Dropped — illiquid (75h to fill 299 bars), chop-dominated (ADX 17.0). Slippage floor eats any edge. |
| **TNSR** | **AVOID** | Dropped — most illiquid (75h/299 bars), no clean structure. |
| **JUP / RAY / JTO** | CANDIDATES (gated) | Add only after (a) amplitude check in a fresh window confirms they reach the TP band, and (b) the oracle has canon citations for them (avoid ungrounded gating). |

**Keep:** WIF (core), PYTH, POPCAT. **Grid-only:** BOME. **Avoid:** DRIFT, TNSR
(illiquid + chop). **Pending:** JUP/RAY/JTO (amplitude + canon-coverage gate).

---

## 5. When to go back to 4–5% TP — the regime-conditional rule

TP was lowered 4→2 as a **chop adaptation** (the universe oscillates ~2%; +4%
was structurally unreachable in chop — only WIF ever hit it). That was correct
*for chop*. But TP2 carries a brutal fee penalty:

| TP/SL (net of ~0.7% round-trip) | Net win | Net loss | Breakeven win-rate |
|---|---|---|---|
| **TP2 / SL3** | +1.3% | −3.7% | **74%** ← the fee wall |
| TP3 / SL3 | +2.3% | −3.7% | 62% |
| TP4 / SL3 | +3.3% | −3.7% | **53%** |
| TP5 / SL3 | +4.3% | −3.7% | 46% |

TP2 demands a 74% win-rate just to break even because the 0.7% fee eats 35% of
the win. TP4 only needs 53%. **The higher TP is mechanically more forgiving —
but only if the move is actually reachable, which depends on regime + amplitude.**

### The rule (regime + amplitude conditioned, not a fixed guess)

```
if regime == TREND (ADX >= 25)  and  symbol_realized_range_24h >= 4%:
        TP = 4-5%      # let winners run; fee math is forgiving; move is reachable
elif regime == TREND (ADX >= 25) and symbol_realized_range_24h in [2.5%, 4%):
        TP = 3%        # partial credit
else:  # CHOP / transitional / low-amplitude
        TP = 2%        # capture the oscillation; or hand the bar to the grid sleeve
```

- **`symbol_realized_range_24h`** = the max(high)−min(low)/price over the last
  24h, per symbol — the deterministic amplitude gate. WIF clears 4% in trend;
  BOME/DRIFT do not.
- **ADX≥25** is the trend gate already used by `regime_analyst`.

### Validation before flipping any TP up

Re-run `scripts/calibration/chart_floor_calibration.py` in a **trend-dominated
window** (median ADX≥25 across ≥4 of 6 names — the study explicitly flagged its
current window can't answer this). Sweep TP∈{2,3,4,5} *conditioned on* ADX≥25 +
amplitude≥4%. **Adopt TP4/5 only if its EV CI exceeds TP2's with non-overlapping
CIs and N≥30 winners.** Until that window is sampled and that bar is cleared,
**TP stays 2 and the higher TP lives only in the conditional branch above**, not
as a global flip. (Same pre-registered discipline that kept the chart floor at
0.85.)

---

## 6. "+10% on the account" — realistic path + timeframe

I ran a Monte-Carlo first-passage that tracks whether **+10% or −10% arrives
first** (the down-path matters — high vol reaches +10% fast, but reaches −10%
almost as fast):

| Scenario | P(+10% first) | P(−10% first) | Median days to +10% | ≈ months |
|---|---|---|---|---|
| Honest current (μ=0.05%/day, vol 2%) | **56%** | **44%** | 23 | ~0.8 |
| Post-lever (μ=0.15%/day, vol 2%) | 69% | 31% | 22 | ~0.7 |
| Blended $1k (μ=0.09%, vol 1.2%) | 80% | 20% | 51 | ~1.7 |
| Blended $3–5k (μ=0.076%, vol 0.9%) | **88%** | **12%** | 80 | ~2.6 |

The honest read:
- **Naively**, +10% has a ~0.8-month *median* time at current vol — but that is
  a coin-flip dressed as a plan: **44% of the time −10% comes first.** High vol
  makes +10% *fast* and *fragile* in equal measure.
- **The yield base is what shifts the race.** Going from 100%-trading to a $3–5k
  blend cuts P(−10%-first) from 44% → 12% — at the cost of a *longer* median
  time (0.8 → 2.6 months). That is the right trade: you give up speed for a
  ~7-in-8 chance of seeing +10% before −10%.

**Honest expected time-to-+10%: 1–3 months median** in the blended scenarios,
with the explicit caveat that **at high (unsmoothed) vol there is a 30–45%
chance of seeing −10% first.** Do not promise a date. The lever that most
improves the *odds* (not the speed) of +10% is the yield floor + the CHOP gate,
not chasing a bigger trading edge.

---

## Rigor notes — what is measured vs assumed

- **Measured / from data:** the calibration study (0% would-have-won, [0%,0%]
  CI, confidence inversion, −0.13 to −0.18%/trade chop drag); the proven grid
  benchmark (1.5–2.5%/wk over 650–770 days); the fee-wall breakeven win-rates
  (arithmetic on a 0.7% round-trip assumption); the symbol amplitude/liquidity
  findings.
- **Assumed (flagged everywhere):** the trading bucket's forward daily mean
  (0.05–0.15%/day) and vol (2%/day) — these are *reasoning from* calibration +
  benchmarks, **not a live measurement.** Live sample is n=2 (1 paper W earlier,
  0W/1L live, −$0.27) — **statistically silent**; no live edge is established.
- **The 0.7% round-trip fee** is a midpoint of the stated 0.5–1.0% range; the
  breakeven win-rates scale with it (at 0.5% RT, TP2 breakeven = 71%; at 1.0%,
  77%) — re-measure actual round-trip cost from live fills before trusting TP2.
- **Every lever lift in §2 has a named validation method;** none should be
  banked until its bootstrap CI / non-overlap test passes. Do not chase noise
  (per `feedback_prompt_iteration_plateau`).

---

## Reproduce the numbers

All figures in this doc were computed with numpy Monte-Carlo (seed 1729):
compounding table, the variance/required-win-rate simulation (§1), the blended
Sharpe sketch (§3), the fee-wall arithmetic (§5), and the +10%/−10% first-passage
race (§6). The calibration CIs come from
`scripts/calibration/chart_floor_calibration.py` (5,000 bootstrap resamples,
seed 1729) documented in `docs/strategy/2026-05-21-calibration-study.md`.
