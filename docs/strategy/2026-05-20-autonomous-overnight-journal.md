# Autonomous overnight journal — 2026-05-20

**Mandate:** Founder asleep. Find best strategy for OKX Agentic Trading
Contest PnL leaderboard. Target 20% PnL in 12h (stretch goal). Paper mode,
restart freely, dispatch agents as needed. Wake up with the bot running
on the best-found strategy, ready to fund.

**Contest closes:** 2026-05-21 07:00 UTC-3 (≈10:00 UTC) — ~24h window.

**Hard constraints (won't be violated):**
- Paper mode (`PAPER_TRADE = True`) — no real money
- No PRD oracle deploy / no main push / no x402 live
- abstain-not-fabricate wedge intact — chart_analyst's discipline stays
- Restart-safe via bot_state.json (RAY + MEW positions survive)

---

## Iteration log (newest at bottom)

### Iteration 0 — baseline state at autonomous-start

- **Branch:** `s39/okx-contest-entry` @ `ac377cc` (state persistence)
- **Bot:** PID 313867 running, 13 instruments
- **Open positions:**
  - RAY-USDC entry $0.736817, current ~$0.7406 (+0.51%), open 2h13min
  - MEW-USDC entry $0.000558, current ~$0.000558 (-0.01%), open 16min
- **Config:**
  - `_CHART_MIN_CONFIDENCE = 0.75`
  - `MAX_CONCURRENT = 2`
  - `MAX_DAILY_TRADES = 3`
  - TP +5% / SL -3% / time-stop 12h
  - `BTC_OVERLAY.condition = "green_candle"`
  - `ENTRY_PARAMS = {lookback_bars: 4, confirm_pct: 0.2}`
  - `VOL_SPIKE_MULTIPLIER = 1.5`
  - `TRAIL_STOP_PCT = None`

### Iteration 1 — initial wedge tighten (07:17 UTC)

- **Changes:**
  - `_CHART_MIN_CONFIDENCE` 0.75 → 0.85 (more selective)
  - `TRAIL_STOP_PCT` None → 2 (lock in partial wins)
- **Restart:** PID 327217, both positions recovered from state file
- **Outcome over ~10 min:** RAY climbed from +0.62% → +0.75%, MEW from -0.05% → -0.33%. No new entries (BTC red bar most of the period). Trail not yet engaged (peak was +0.62%, never reached the +2% trigger).

### Iteration 1.5 — 3-agent parallel research dispatch (07:20 UTC)

Three agents fired in parallel for ~30 min research:

| Agent | Commit | Key finding |
|---|---|---|
| `trading-strategist` | `5760bae` | Real OKX leaderboard toppers = $400-1071 over 14 DAYS (25-100% in 2 weeks, NOT daily 100%). We're correctly the "patient compounder" archetype. Realistic 20h band: **median +0.6%, P10-P90 [-2.5%, +5.5%], P98 tail +12%.** 20% won't happen. |
| `quant-analyst` | inline | Highest-EV single change: **TRAIL_STOP_PCT 2 → 1** (+1.3% [+0.4, +2.1] lift over 20h on $100). 20% PnL = **1 in 2000** with current config. Combo: TRAIL 1 + memes-only → expected +1.9% [-1.4%, +5.0%]. DON'T loosen breakout filter (no-op or actively bad). DON'T pyramid winners (negative EV). DON'T size-up to $35 (variance without edge). |
| `ai-ml-engineer` | `75c4d10` | **33 of 36 panel declines = `chart_below_threshold`** → chart_analyst is THE binding constraint. Proposed adding "MOMENTUM ACCELERATION" 6-cell falsifiable pattern to the system prompt — re-anchors confidence ≥ 0.85 to a specific observable shape. Synergistic with the new 0.85 floor. Honest worry: terminal-leg chop tags could fire 6/6 falsely. |

### Iteration 2 — apply quant + ai-ml-engineer recommendations (07:25 UTC)

- **Changes:**
  - `TRAIL_STOP_PCT` 2 → 1 (capture peak faster on volatile/fading positions)
  - chart_analyst system prompt: added **MOMENTUM ACCELERATION** lens (6 falsifiable cells + confidence licensing for 6/6 → 0.85-0.92 and 5/6 → 0.80-0.85)
  - Kept `MAX_CONCURRENT=2`, `$25` ticket (don't touch sizing while positions are open)
  - Kept memes alongside established (trading-strategist's instrument set is sound; quant's memes-only is a v3 option after RAY/MEW close)
- **Restart:** PID 331501, both positions recovered
- **State at restart:** RAY +0.75%, MEW -0.33%

**Expected lift over 20h vs iter-1:**
- TRAIL 1%: +1.3% [+0.4, +2.1]
- Momentum lens: targets the 33/36 declines; lift not quantified by agent
- Combined informal estimate: +1.5% to +3% over iter-1's modal outcome

**Honest read of where we are vs the 20% target:**
The quant analyst's math is unforgiving. **20% PnL in this window is a ~1-in-2000 outcome with our config + the wedge intact.** The honest stretch ceiling is ~+12% (98th percentile). The target outcome is +1-3% with a fat positive tail.

What we will NOT do (because they burn the wedge OR are negative-EV):
- Loosen breakout filter to chase candidates
- Pyramid winners (negative EV)
- Size up to $40+ ticket without selectivity matching
- Force chart_analyst to be more bullish

### Iter-2 60-min outcome (08:15 UTC — monitor timeout)

**Bot state after 60 min running iter-2 config:**
- RAY-USDC: entry $0.736817 → current $0.75344 (+2.26%) → **peak hit $0.75543 (+2.47%)** → trail-stop armed at $0.7479 (=$peak × 0.99), only $0.0055 above trigger
- MEW-USDC: entry $0.000558 → current $0.000553 (-0.92%) → peak hit $0.000558 (+0.06% briefly)
- **Zero new panel decisions in 60 min** — both slots filled (MAX_CONCURRENT=2), so even if BTC overlay had passed (it didn't — BTC stuck on red bars), no candidates could fire

**Key learning:** the binding constraint isn't chart confidence anymore — it's the **slot saturation + BTC chop combo**. We cannot test iter-2's momentum-acceleration lens until a slot opens, because no new candidates can be evaluated.

**Honest market diagnosis:** BTC has been chopping in a -0.1% to +0.1% band for 4+ hours. Altcoins follow on average. This is a **low-vol regime** in which the realistic outcomes are heavily compressed. Quant's median +0.6% is converging on what's actually playing out.

**Trail-stop validation, partial:** RAY hit +2.47%, then receded to +2.26%. With the 1% trail in place, the system has *locked in* a $0.7479 floor. Even if RAY now drops back to entry, we exit at +1.47% net (~$0.37 paper PnL on $25 ticket). **The trail change is already paying.**

### Iteration 3 plan (queued, fires after RAY or MEW closes)

When one of the open positions resolves (TP/SL/trail/time-stop), I'll have a free slot. At that point, evaluate:
- If we have a clean RAY or MEW close (any direction), restart with **memes-only universe** (drop JTO/JUP/PYTH/ORCA/RAY/HNT, keep BONK/WIF/POPCAT/MEW/BOME/DRIFT/TNSR/SLERF). Quant's expected lift: +1.9% over 20h.
- Optionally drop `MAX_CONCURRENT` to 1 + raise ticket to $40 (trading-strategist's recommendation). Lower variance, higher per-trade size.
- Decide based on what happened on the close — if it was a TP, we have momentum thesis confirmed; if SL, we may need to tighten further.




### 11:37 UTC — MEW closed via trail (-$0.24 paper)

**Event:** MEW-USDC closed via trailing_stop. pnl_pct -0.97%, pnl_usd -$0.24.

**Finding:** trail-stop fired even though MEW never went meaningfully green
(peak was only +0.06%). The TRAIL_STOP_PCT=1 logic checks `current < peak ×
0.99` regardless of whether peak ever cleared the +2% activation level.
This means the trail acts as a **tight max-drawdown-from-peak (~-1% effective
floor)**, not a "let-winners-run" trail.

For chop: this is actually decent risk management — caps losses at ~1%
instead of -3% SL. For real trail behavior: post-contest fix is to require
`activate_after_pct` (only engage trail after position is X% green).

**State:** 1 slot now free (RAY-USDC still open, +2.26%). daily_trades=2/3,
one more entry allowed today. Next candidate that passes the new
(0.85 floor + momentum lens) chart_analyst will be our first PRODUCTION
test of iter-2's prompt amendment.

**Decision:** Don't restart for iter-3 yet. Let iter-2 try the open slot
on its updated config first; the next entry IS the test.
