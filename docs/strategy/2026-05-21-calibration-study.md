# Chart-Floor Calibration Study — is the live bot too conservative?

**Date:** 2026-05-21
**Branch:** `s41/oracle-real-execution`
**Author:** quant-analyst
**Script:** `scripts/calibration/chart_floor_calibration.py`
**Live bot (untouched):** `contest_bot/jto_breakout_gecko_gated_contest_bot.py` (PID 1702780)

---

## Question

Is the live Solana DEX-momentum bot **too conservative** (declining candidates
that would have won) or **well-calibrated**? This gates whether we loosen the
chart-confidence entry floor (currently **0.85**, raised to **0.92** in a
confirmed-chop regime).

## TL;DR verdict

**WELL-CALIBRATED — do NOT loosen the floor. Hold at 0.85 / 0.92.**

Of 176 candidates the deterministic gate surfaced, **only 4 (2.3%) would have
hit TP (+4%) before SL (-3%)** in a realistic window — and all 4 had
sub-floor confidence AND a non-bullish chart posture, so **no chart floor at
any level selects them.** The would-have-won rate of the entry set is
**0% with a [0%, 0%] bootstrap CI at every swept floor from 0.50 to 0.95.**
Lowering the floor admits **more losers, not winners**: EV is mildly negative
at low floors (-0.13% to -0.18%/trade) and the high-confidence tail (>=0.80,
n=36) has **zero wins and the worst average PnL (-0.16%/trade).** Confidence is
flat-to-inverted against outcome in this window.

**Caveat (load-bearing):** the 24-75h window is **chop-dominated (61% of bars
are chop/transitional)** and the breakout/volume_spike signal is barely
break-even here for ANY floor. The N of *winners* (4) is far too small to
estimate the floor's upside. So the precise statement is: there is **no evidence
the floor is too conservative**, and **strong evidence loosening it would lose
money in this regime.** Re-run in a trend-dominated window before any change.

---

## Methodology

### Data (faithful to what the bot sees)
- Fetched 5m candles via the bot's **own** `onchainos` wrapper (`OnchainOS.get_candles`)
  — same ascending sort (iter-3.11 fix), same float coercion, same live-bar
  inclusion. Read-only; the running bot module is never imported or mutated.
- Universe = the live 6 mints: PYTH, WIF, POPCAT, BOME, DRIFT, TNSR (BONK removed).
- 299 bars/instrument (the onchainos cap) ≈ **24-75h** depending on liquidity
  (illiquid names like TNSR span more wall-clock per 299 bars).

### The deterministic gate replay
Candidate fires (OR-semantics, mirrors `poll_instruments`):
- **breakout**: `close >= prior 24-bar high * (1 + 1.5%)` (`ENTRY_PARAMS`)
- **volume_spike**: `vol[-1] >= 1.5 * median(last 24 vols)` (`VOL_SPIKE_*`)

### Chart-confidence proxy (the swept parameter)
`chart_analyst` is an LLM — non-deterministic, unreplayable. **But its prompt
anchors confidence to a falsifiable, fully-deterministic ladder** (see
`contest_bot/voices/chart_analyst.py` lines 87-138):
- **Momentum-acceleration**: 6 boolean cells. 6/6 → 0.85-0.92, 5/6 → 0.80-0.85,
  ≤4/6 → standard anchors.
- **Standard anchors**: count of {trend, flow, room, breakout-posture,
  vol-confirm} aligned → 0.50…>0.80.
- **Abstain protocol**: thin-liq / <24 bars / tight-chop → confidence 0.

We compute exactly those cells from candles and take each licensed band's
**midpoint** as the point estimate. This makes the floor sweep a faithful model
of "what confidence chart_analyst would license", not a guess. The artifact-log
audit confirms this is the right knob: **1,544 of 1,559 logged panel decisions
(99.0%) declined via `chart_below_threshold`** — the chart floor does
essentially all the gating; risk-veto/memory-contradict are negligible.

### Regime (deterministic)
ADX(14) ≥ 25 = trend, ≤ 18 = chop, between = transitional (mirrors
`regime_analyst`). The chop-modulator raises the floor to 0.92 only when
`regime_analyst` would be bearish & conf≥0.6, which (per its conf formula)
means **ADX ≤ 16.0** — modeled exactly.

### Exit simulation
Copied (NOT imported / NOT edited) from `contest_bot/backtest_entry.py`:
TP +4 / SL -3 / trail(activate +2, give 1) / stall_green(60m,+2) /
flat_stall(90m,-0.5..+2,no-new-high 30m) / time-stop 12h. Conservative:
SL checked before TP on a straddling bar. **Censoring guard:** candidates within
18 bars (90 min) of window-end are dropped so we never mark-to-last-close and
bias toward 0.

### Statistics
- Would-have-won = pnl ≥ +4% (hit TP before SL).
- EV = mean realized pnl% per entry; EV$ at `USD_PER_TRADE = $25`.
- **Bootstrap 95% CIs** (5,000 resamples, seed 1729) on both win-rate and EV,
  per floor per regime.

---

## Data window

| Sym | bars | span | median ADX | trend/chop/trans bars |
|-----|------|------|-----------|----------------------|
| PYTH | 299 | 25.1h | 25.2 | 140 / 56 / 77 |
| WIF | 299 | 25.1h | 41.3 | 209 / 32 / 32 |
| POPCAT | 299 | 25.1h | 26.8 | 142 / 78 / 53 |
| BOME | 299 | 30.1h | 17.4 | 58 / 141 / 74 |
| DRIFT | 299 | 42.9h | 17.0 | 46 / 164 / 63 |
| TNSR | 299 | 75.1h | 18.8 | 51 / 113 / 109 |

Aggregate: trend 646 / chop 584 / transitional 408 bars → **61% chop+transitional.**
WIF/PYTH/POPCAT trend; BOME/DRIFT/TNSR chop. **This is a mixed, chop-leaning
window — one snapshot, not a regime-balanced sample.**

## Candidate base rate (deterministic gate, full-horizon only)

| regime | N | raw would-win | avg pnl |
|--------|---|--------------|---------|
| chop | 60 | 0/60 (0%) | -0.03% |
| transitional | 47 | 0/47 (0%) | +0.10% |
| trend | 69 | 4/69 (6%) | +0.16% |
| **total** | **176** | **4 (2.3%)** | **+0.08%** |

PnL distribution of all 176 candidates: SL(-3) 14 · (-3,-1) 6 · **(-1,0) 74** ·
(0,1) 50 · (1,2) 10 · (2,4) 18 · TP(+4) 4. The dominant outcome is a small
loss clustered just below break-even — the "enter at an exhausted micro-top,
mean-revert, exit near flat via stall/trail" pattern the founder already
diagnosed (iter-3.10). The signal itself is barely break-even in this window.

## The 4 winners — none are floor-selectable

| sym | proxy_conf | chart_bullish | regime | pnl |
|-----|-----------|--------------|--------|-----|
| WIF | 0.75 | **False** | trend | +4.0% |
| WIF | 0.65 | **False** | trend | +4.0% |
| WIF | 0.65 | **False** | trend | +4.0% |
| WIF | 0.65 | **False** | trend | +4.0% |

All 4 fired on **volume_spike during a strong WIF trend**, all have
**confidence below 0.80** (so even a *lower* floor of 0.80 misses them), and all
have **`chart_bullish = False`** (price posture wasn't a clean bullish breakout,
so the chart-analyst direction gate declines them regardless of floor). **There
is no floor — high or low — that captures these.**

Confidence vs outcome (the inversion):

| proxy_conf bucket | N | wins | avg pnl |
|-------------------|---|------|---------|
| ≥ 0.80 | 36 | 0 (0%) | **-0.16%** |
| 0.70-0.80 | 42 | 1 (2%) | +0.41% |
| < 0.70 | 98 | 3 (3%) | +0.02% |

Higher deterministic confidence → **worse** outcomes in this window. The cleanest
"textbook" breakouts are exactly the exhausted tops that fade.

---

## Floor-EV sweep (95% bootstrap CI)

EV is per-trade realized pnl%; EV$ at $25/trade. Win-rate is 0% with a [0%,0%]
CI at **every** floor in **every** regime (omitted for brevity below — see the
script output / `cal_results.json`).

| floor | regime | N | EV% | EV% 95% CI | EV$ |
|------|--------|---|-----|-----------|-----|
| 0.50 | ALL | 83 | -0.18 | [-0.45, +0.10] | -0.04 |
| 0.50 | trend | 33 | -0.43 | [-0.88, -0.02] | -0.11 |
| 0.50 | chop | 31 | -0.01 | [-0.43, +0.43] | -0.00 |
| 0.60 | ALL | 74 | -0.13 | [-0.42, +0.16] | -0.03 |
| 0.60 | chop | 23 | +0.23 | [-0.25, +0.76] | +0.06 |
| 0.70 | ALL | 50 | -0.20 | [-0.51, +0.13] | -0.05 |
| 0.80 | ALL | 26 | -0.37 | [-0.79, +0.01] | -0.09 |
| 0.80 | chop | 5 | -0.74 | [-1.36, -0.12] | -0.18 |
| **0.85** | **ALL** | **4** | **-1.19** | **[-2.36, -0.25]** | **-0.30** |
| 0.85 | trend | 3 | -1.17 | [-3.00, -0.07] | -0.29 |
| 0.90 | ALL | 0 | — | — | — |
| 0.95 | ALL | 0 | — | — | — |

(Full 40-row table — every floor × {ALL, trend, chop, transitional} — is in the
script output and `cal_results.json`.)

### Reading the curve
- **Win-rate is identically 0% [0%,0%] everywhere.** No floor recovers a TP.
- **EV is negative at every floor.** It is *least* negative at the lowest floors
  (more candidates dilute toward the +0.08% base rate) and *most* negative at
  0.85 (n=4, all near-flat-to-down).
- **Every EV CI straddles or sits below zero.** No floor has a positive EV with
  a CI excluding zero.
- The current 0.85 floor admits only 4 trades from this 176-candidate, ~30h
  window — consistent with the live log (3 acts / 1,556 declines). That is the
  floor working as designed: it suppresses a break-even-to-negative signal in a
  chop-leaning tape.

---

## Decision rule applied

The pre-registered rule: **change the 0.85 floor ONLY if a different floor's EV
is higher with non-overlapping CIs AND N is adequate.**

- No floor has an EV CI that excludes the 0.85 floor's CI (all overlap; all
  straddle/below zero).
- No floor produces a positive would-have-won rate (all 0% [0%,0%]).
- Winner N = 4, all sub-floor and non-bullish → upside is unestimable.

→ **Recommendation: HOLD the floor at 0.85 / 0.92. Collect more data.**
Per `feedback_prompt_iteration_plateau` — do not chase noise.

## Caveats / limits

1. **Small, single-regime-leaning window.** 299-bar cap = 24-75h, 61%
   chop/transitional. This window cannot answer "is 0.85 too high **in a strong
   trend**." It only answers "is it too high **now**" → no.
2. **Proxy, not replay.** chart_analyst's LLM call is modeled by its own
   deterministic confidence ladder + a bullish-posture direction gate. Faithful
   to the prompt's licensing, but the live LLM has temperature 0 and may differ
   at the margin. The conclusion is robust because it holds across the *entire*
   floor range, not at a single threshold.
3. **No data-availability blockers.** onchainos returned 299 bars for all 6
   mints; no auth/network failures.
4. **Exit conservatism.** SL-before-TP on straddling bars slightly understates
   wins; even removing that, the winner count and confidence-inversion stand.

## What would change the verdict

Re-run this exact script in a **trend-dominated window** (median ADX ≥ 25 across
≥4 of 6 names) and with **deeper history** once pagination lands. If, in a real
trend regime, a floor below 0.85 shows a would-have-won rate > 0 with a
positive-EV CI excluding zero and N ≥ ~30 entries, *then* reconsider. Until
then, the floor is not the bottleneck — the **break-even entry signal in chop**
is. The higher-leverage fix is regime-conditioning the *signal* (already partly
done via the chop-modulator), not loosening the floor.

## Reproduce

```bash
# fetch live + run
python3 scripts/calibration/chart_floor_calibration.py \
    --dump-candles /tmp/cal_candles.json --json-out /tmp/cal_results.json
# replay from cached candles (deterministic)
python3 scripts/calibration/chart_floor_calibration.py \
    --cached /tmp/cal_candles.json
```
