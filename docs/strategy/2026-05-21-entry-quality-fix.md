# Entry-Quality Fix — the noise-trigger bug + the proper entry design

*2026-05-21. Founder observed entries kept stalling — we were buying at
"stable/exhausted" moments, not good entry points. Investigation confirmed
a shipped-test-config bug; the proper RSI/ADX/MFI/EMA entry is designed but
must be backtested before going live.*

---

## The bug (fixed — iter-3.10)

`ENTRY_PARAMS` shipped with **test-mode-loosened values** that were never
reverted before the live flip:

```
was (test):   lookback_bars=4,  confirm_pct=0.2   # 0.2% above 20-min high = NOISE
now (fixed):  lookback_bars=24, confirm_pct=1.5   # 1.5% above 2-hour high = real breakout
```

A 0.2% close above a 20-minute high is statistical noise — we were buying
micro-pops that immediately mean-reverted. **This is why every entry peaked
within minutes and then stalled** (BONK +1.6%→fade, BOME +0.58%→0%→-0.86%).
Reverting the trigger is the single biggest entry fix and is already live.

---

## Investigation findings (trading-strategist, honest about N)

**N is tiny: 4 live trades, 2 with logged closes, 1 (BOME) with full
per-poll telemetry.** Directional, not significant.

| Symbol | Result | Note |
|---|---|---|
| WIF | +6.21% TP | the only clean runner |
| PYTH | +2.08% stall_green | win, but exited on stall not strength |
| BONK | (peaked +1.6% → faded) | bought-the-pop |
| BOME | -0.86% | the documented failure — full telemetry |

**BOME (88 polls):** peaked +0.58% in the first hour, *never made a new
high for the next ~88 min*, bled to -0.86%. Tight ±0.5% band the whole
time — no trend, no volatility expansion. Textbook breakout-that-wasn't.

**Honest conclusion:** we have evidence the *bad* entries are bad. We do
NOT have evidence the *good* entries (WIF, PYTH) are repeatable — they may
be survivors. Do not over-conclude on N=4.

---

## The proper entry design (validate before shipping live)

Four **uncorrelated** gates (Pattern D — no redundant signals), via the OKX
indicator API (`market_get_indicator`: `adx`, `ema`, `rsi`, `mfi`):

```
# TREND GATE — is there a trend to ride?
trend_ok = adx_14 >= 22 AND price > ema_50

# Variant A — breakout-with-room
entry_A = trend_ok
          AND close >= prior_24bar_high * 1.015   # keep the stopgap
          AND rsi_14 < 68                          # NOT already exhausted/topped
          AND mfi_14 >= 55                         # money actually flowing in

# Variant B — pullback-in-uptrend (founder's dip idea, done right)
entry_B = adx_14 >= 22 AND price > ema_50
          AND ema_50*0.985 <= close <= ema_50*1.01 # near a RISING ema (anchor)
          AND 40 <= rsi_14 <= 60 AND rsi_rising     # bouncing off mid, not a <30 knife
          AND mfi_14 >= 50

ENTER = entry_A OR entry_B
```

**Why these:**
- `adx≥22 + price>ema50` would have vetoed BOME directly (it chopped, no trend).
- `rsi<68` is the anti-exhaustion check — a 1.5% breakout with RSI already 75 *is* the top of a pop.
- `mfi≥55` requires volume-weighted inflow, not a single price tick — the cheapest defense against thin-liquidity micro-pops.
- Variant B answers the founder's "-6% dip has no anchor": here the anchor is a *rising EMA50 in a confirmed uptrend*, not a fixed % drop. Not a falling knife.

**Gating vs telemetry-only:**
- GATE: `adx`, `ema50`, `rsi`, `mfi` (four uncorrelated dimensions: trend-exist, direction, exhaustion, flow)
- LOG-ONLY: `macd`, `supertrend` (redundant with adx+ema), `bbwidth`, `stoch-rsi` (correlated with rsi), `vwap`. Observe before promoting any.

---

## CRITICAL: validate before shipping live (do NOT overfit N=4)

The mechanism is sound a priori (it would veto BOME/BONK on first
principles). The *thresholds* (22/68/55) are standard defaults, NOT
validated on our symbols. Picking them to fit 4 trades = overfit.

**Validation path (in order, per CLAUDE.md capital staging + Pattern B):**

1. **Backtest first, live never-first.** Pull 30-60d of 5m candles per
   symbol (`market_get_candles`), recompute adx/ema/rsi/mfi per bar, replay
   OLD (0.2%/20-min) vs NEW rule, emit PnL-delta CSV. *(The OKX indicator
   MCP tools work in the main session — the harness is buildable now.)*
2. **Forward counterfactual logger:** keep the live bot on the 1.5%/24-bar
   stopgap, but LOG the proposed gate's pass/fail + all 4 indicators every
   poll. After ~20-30 would-be entries, check: did the gate's rejections
   underperform its accepts? Zero capital risk.
3. **Threshold sweep on the backtest:** adx∈{18,22,26}, rsi_cap∈{65,68,72},
   mfi∈{50,55,60}. Flat across the grid = robust; one cell shines = overfit.

Only promote the new entry as the sole gate once the backtest shows a
positive PnL delta across the threshold sweep.

---

## Status

- ✅ iter-3.10 noise-trigger bug FIXED + live (1.5% / 24-bar)
- 📐 Proper RSI/ADX/MFI/EMA entry DESIGNED (above)
- ⏳ Backtest harness — next build (OKX indicator tools available)
- ⏳ Counterfactual logger — extends the existing telemetry
- ⏳ Promote new entry only after positive backtest delta

This is roadmap **Track D (D1) + B5** converging: OKX indicators wired into
entry, validated on data, not vibes.

---

## UPDATE — backtest harness built + run (iter-3.11)

`contest_bot/backtest_entry.py` — pulls 299×5m candles/symbol, pure-Python
indicators, replays OLD/NEW/PROPOSED entries through the live exit stack.

### CRITICAL BUG #2 found by the harness: candle ordering

`get_candles` returned candles **newest-first (descending)**, but every
consumer (`evaluate_breakout` `recent=candles[-1]`, `btc_overlay`
`current_close=candles[-1]`, volume_spike `volumes[-1]`) assumed the LAST
element is the most-recent bar. With descending order, `candles[-1]` was the
**oldest** bar — so **breakout detection compared ancient candles and never
fired on current price action.** Most entries came from volume_spike by
accident. Fixed in `onchainos.get_candles` (iter-3.11): `result.sort(key=ts)`
→ ascending, fixing breakout + BTC overlay + volume_spike + the harness at
once. This is a bigger root cause than the threshold bug.

### Backtest finding — breakout is REGIME-dependent (overturns "raise the threshold")

Sweep of lookback × confirm_pct over a 25h chop window, through the exit stack:

```
Every cell with confirm >= 0.5% is NEGATIVE.
0.8-1.5% breakouts: every signal hit the -3% SL (0% win) — fakeouts.
Only the loosest 0.2% scrapes positive (+2-4%) — by scalping noise,
  and at 36-57 trades it can't run under MAX_DAILY_TRADES=3 anyway.
NEW (1.5%/24-bar) + PROPOSED: 0 trades in chop — correctly ABSTAINING.
```

**Conclusion: in a chop regime, breakout entries are -EV at any threshold.**
Strong breakouts in chop are bull traps that reverse to SL. This is not a
threshold problem — it's a regime problem. We've been running a momentum
strategy in a market with no momentum.

**Implications:**
1. The strict NEW config firing 0 trades in chop is CORRECT — abstain when
   the strategy doesn't fit the regime. Do NOT loosen to force trades.
2. Validates the strategist's `adx>=22` gate: it keeps us out of chop.
3. Validates **Track B6 grid strategy**: grid profits from the chop that
   kills breakouts. The two strategies are regime-complementary
   (momentum when adx high, grid when adx low).

### Honest limits

- 25h / single regime (chop). The result "breakout loses in chop" is robust;
  "what threshold wins in a trend" is unanswerable without trend-regime data.
- Deeper history (pagination) + a trend-window sample are needed before
  promoting any breakout threshold. The harness is ready to re-run.
