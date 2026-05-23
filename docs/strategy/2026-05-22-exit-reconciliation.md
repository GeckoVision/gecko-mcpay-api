# Exit Reconciliation — Phase 0.5 of the market-analysis roadmap

**Date:** 2026-05-22
**Author:** quant-analyst
**Harness:** `scripts/calibration/exit_reconciliation.py` (read-only w.r.t. the live bot, PID 3318350)
**Data:** two cached 5m-candle windows for the live 6-symbol universe — `/tmp/cal_candles_d1.json` (ends 2026-05-22 ~01:35 UTC) and `/tmp/cal_candles.json` (ends 2026-05-22 ~00:35 UTC), 299 bars/symbol.

---

## The question

The binary **TP2/SL3** calibration concludes the strategy is **net −EV** (needs ~75% win-rate; gross edge ~1/7 of a round-trip fee). The **live realized exits (N=7)** show a **3.6:1 payoff** (avg win +2.9% vs avg loss −0.81%, break-even ~22%, win-rate 57%). These disagree on sign. Hypothesis posed by the roadmap: *the binary TP/SL exit model does not match the bot's actual exit stack, and the real (trailing/stall) exits already carry a small edge the binary backtest hides.*

**Settled with numbers. The hypothesis is rejected.** The edge does NOT live in the exit mechanism. The −EV conclusion is NOT an artifact of the wrong exit model — it survives a faithful replica of the live exit stack. The live N=7's apparent 3.6:1 payoff is a small-sample artifact (one outlier carries 62% of it; 5 of 7 trades are outside the backtest window) and is not reproduced by the backtest at the same entry gate.

---

## 1. The live exit stack (transcribed from the bot)

Source: `contest_bot/jto_breakout_gecko_gated_contest_bot.py`, constants lines 96–114, poll loop `monitor_positions()` lines 1575–1631.

The bot polls every 30s and evaluates exits **on the CLOSE / spot price** (`current_price`), in this order:

| # | Exit | Rule (live params, s41 2026-05-22) |
|---|------|------|
| 1 | **Trailing stop** | if `peak_pct >= TRAIL_ACTIVATE_AFTER_PCT (+1%)` and `(peak−cur)/peak*100 >= TRAIL_STOP_PCT (1%)` → close |
| 2 | **Stop loss** | `pnl_pct <= −STOP_LOSS_PCT (−3%)` → close |
| 3 | **Take profit** | `pnl_pct >= TAKE_PROFIT_PCT (+2%)` → close |
| 4 | **Stall-green** | `age >= 60min` and `pnl >= +1.0%` → close |
| 5 | **Flat-stall** | `age >= 90min` and `−0.5% <= pnl <= +2.0%` and `no-new-high >= 30min` → close |
| — | ~~Time-stop~~ | **No 12h time-stop fires in the poll loop.** Line 530's `timedelta(hours=12)` only computes a dashboard ETA; nothing closes the position on age alone. |

Two facts that turn out to dominate the reconciliation:
- **The bot only ever sees the CLOSE price.** It cannot stop out on an intrabar wick. A −3% wick that recovers by the next poll does not trigger SL.
- **No fee is deducted in PAPER mode.** `close_position` books `(cur−ep)/ep*100`. In LIVE mode the fee is implicit in the real swap fill (slippage + spread).

## 2. Audit of the prior harness — the actual gap

The claim that the calibration uses "binary TP/SL only" is **false** — `chart_floor_calibration.simulate_exit` and `tp_regime_validation.simulate_exit_tp` already implement the full stack (trail, stall-green, flat-stall, time-stop). The real gaps are subtler and all push the same way:

1. **Stale parameters.** The base harness hardcodes `TRAIL_ACTIVATE_PCT=2`, `STALL_GREEN_MIN_PCT=2`, default `TP=4` — the *previous* iteration, not the live `TP=2 / trail-activate 1 / stall 1`. Stale trail/stall let positions run longer and bleed more downside before booking.
2. **Intrabar SL/TP.** The harness fires SL/TP on intrabar `high`/`low` touch. The live bot fires on close. The intrabar SL is the single biggest fidelity gap: **15 of 175 candidates (8.6%) hit the full −3% SL on a wick** in the harness, dragging avg loss to −0.76%; the live bot, polling on close with trail/flat-stall catching the −0.5..+2% band first, exits losers at −0.4 to −1.06%.
3. **Phantom time-stop.** The harness applies `TIME_STOP_BARS=144`; the live bot does not. (Low impact — flat-stall at 90min usually fires first.)
4. **The −EV headline is read off the wrong metric.** `tp_regime_validation` reports `wouldWin = 17.1%` for TP2 and a `breakeven_winrate = (SL+fee)/(tp+SL) = 75%`. That formula is only valid for a **clean binary** ±(2,3) outcome. The realized series under the full stack is a continuous distribution (wins avg +0.87%, losses avg −0.76%), so 75% is answering a question the strategy doesn't ask. The 17.1% "wouldWin" is itself an artifact: it counts `realized_pnl >= +2%` under the *stale TP4/trail2/stall2* exit, which books most positions via trail/stall **before** +2% is cleanly reached.

`exit_reconciliation.py` fixes all four: a faithful **close-based** simulator at **live params**, no phantom time-stop, and reports the realized **net-EV with CI** (not a binary break-even adjective). It keeps a pure binary TP2/SL3 (intrabar) model alongside for the side-by-side.

## 3. Method — block bootstrap

Adjacent breakout candidates within a symbol share momentum, so they are not IID. Measured **lag-1 autocorrelation of realized pnl = +0.29 to +0.46 per symbol (pooled +0.36)**, decaying to ~0 by lag-3. The IID `bootstrap_ci` therefore understates variance.

- **Variance-inflation factor** (Bartlett, K=4): VIF ≈ 1.54 → **N_eff ≈ 114 of 175** for the all-regime pool (per-regime cells smaller).
- **Moving-block bootstrap**, block length **3** (covers lag-1/2 dependence; autocorr dead by lag-3). Blocks sampled proportional to symbol length so the resample's symbol mix matches the data.
- **Confirmed empirically:** the block CI is **1.21–1.26× wider** than IID across both windows — exactly the autocorrelation correction the roadmap asked for.

---

## 4. Result — binary vs real-exit EV, per regime, with block-bootstrap CIs

Net of central **0.75% round-trip fee**. Window 1 (`cal_candles_d1.json`, N=175):

| regime | N | N_eff | **BIN netEV%** | BIN 95% CI (block) | excl 0 | **REAL netEV%** | REAL 95% CI (block) | excl 0 |
|---|---:|---:|---:|---|:---:|---:|---|:---:|
| ALL | 175 | 135 | +0.050 | [−0.238, +0.436] | no | **−0.579** | [−0.738, −0.357] | **YES (neg)** |
| TREND | 63 | 63 | +0.057 | [−0.461, +0.614] | no | **−0.619** | [−0.836, −0.309] | **YES (neg)** |
| TRANSITIONAL | 51 | 51 | +0.515 | [+0.032, +0.849] | YES (pos) | **−0.477** | [−0.904, −0.198] | **YES (neg)** |
| CHOP | 61 | 59 | −0.346 | [−1.067, +0.273] | no | **−0.625** | [−0.926, −0.253] | **YES (neg)** |

Window 2 (`cal_candles.json`, N=176) — robustness:

| regime | N | N_eff | BIN netEV% | BIN 95% CI | excl 0 | REAL netEV% | REAL 95% CI | excl 0 |
|---|---:|---:|---:|---|:---:|---:|---|:---:|
| ALL | 176 | 130 | −0.489 | [−0.903, −0.048] | YES (neg) | **−0.658** | [−0.856, −0.435] | **YES (neg)** |
| TREND | 69 | 69 | −0.327 | [−0.941, +0.350] | no | **−0.687** | [−0.931, −0.399] | **YES (neg)** |
| TRANSITIONAL | 47 | 47 | −0.298 | [−1.167, +0.357] | no | **−0.600** | [−1.174, −0.282] | **YES (neg)** |
| CHOP | 60 | 50 | −0.824 | [−1.665, −0.153] | YES (neg) | **−0.669** | [−1.008, −0.296] | **YES (neg)** |

**Gross (pre-fee) shape**, window 1 — the distribution the binary read collapses:

| regime | model | grossEV% | win% | avgWin% | avgLoss% | payoff |
|---|---|---:|---:|---:|---:|---:|
| ALL | BIN | +0.800 | 81% | +1.52 | −2.16 | 0.70 |
| ALL | **REAL** | **+0.171** | 51% | +0.88 | −0.58 | **1.52** |
| TREND | REAL | +0.131 | 57% | +0.71 | −0.64 | 1.11 |
| TRANS | REAL | +0.273 | 51% | +1.02 | −0.51 | 2.02 |
| CHOP | REAL | +0.125 | 46% | +0.95 | −0.57 | 1.65 |

The real-exit stack **does** produce an asymmetric payoff (1.1–2.0:1 by regime, because trail/flat-stall cut losers to −0.5..−0.6% vs the binary −2.2%). **But the gross mean is only +0.17%/trade.** The break-even round-trip fee is **0.17%**. Any realistic DEX fee (0.5–1.0% RT) makes it confidently −EV.

## 5. Reconciliation with the live N=7

| metric | LIVE (N=7) | BACKTEST real-exit (ALL, gross) |
|---|---:|---:|
| win-rate | 57.1% | 51.4% |
| avg win % | +2.90 | +0.88 |
| avg loss % | −0.81 | −0.58 |
| **payoff ratio** | **3.58** | **1.52** |
| mean gross % | +1.311 | +0.171 |

The backtest under the real exits **does not reproduce** the live 3.6:1 payoff or the +1.31% mean. Why the live N=7 looks so much better:

1. **One outlier carries it.** Jackknife: dropping the single WIF +6.21% take-profit collapses the mean from +1.31% to **+0.50%** and payoff from 3.58 to 2.22. With N=7 a single fill dominates — the 3.6:1 is not a stable estimate.
2. **5 of 7 live exits are outside the backtest window.** The MEW/RAY/PYTH paper trades (05-20) and the WIF +6.21% (05-21 00:54) all precede the cached candle windows. The backtest and the live N=7 are **not measuring the same market** — they cannot be expected to agree, and these live trades are not reproducible from this candle cache at all.
3. **The live entry gate does not select better trades — in this data it selects worse ones.** Filtering the backtest to the live entry proxy (`chart_bullish & proxy>=0.85`) gives gross **−0.64%/trade** (payoff 0.53), worse than the all-candidate +0.17%. So selection quality is not the explanation for the live strength.
4. **Mix:** live is 5 paper + 2 live (DRIFT −0.40, BOME −1.06 — both real fills, both losers). The 4 wins are all paper, where no fee/slippage was charged. The two real-money trades were both small losses.

## Verdict

- **Edge-in-exits? No.** The real close-based exit stack improves the *shape* (payoff 1.5–2.0:1 vs the binary 0.7:1, because trail/flat-stall cut the loss tail) but the realized gross mean is **+0.17%/trade — below the lowest plausible fee.** The exit mechanism is well-designed for capital preservation; it is not a source of positive expectancy.
- **Was −EV an artifact of the wrong exit model? No.** The −EV conclusion **survives** a faithful replica of the live exit stack. In both windows, the REAL-exit net-EV CI **excludes zero on the negative side in every regime**. The original harness's specific framing (75% break-even, 17% wouldWin) was indeed mis-specified — but correcting it does not flip the sign, it only narrows the gross gap to the fee.
- **The live N=7 "3.6:1 payoff" is small-sample luck, not a structural edge.** One outlier = 62% of it; 5/7 trades are off-window; the entry gate that produced them backtests negative. **Do not infer a working strategy from N=7.** Break-even win-rate at the live payoff is ~22%, but that payoff is the unstable quantity.
- **Honest CI caveat:** the *only* CI that excluded zero on the **positive** side anywhere was BINARY TRANSITIONAL in window 1 (+0.52), and it **did not replicate** in window 2 (−0.30, CI straddles 0). Single positive cell across 8 regime×window binary cells = noise. The real-exit model has **zero** positive-excluding cells.
- **Single-window / N caveats:** ~25–77h per symbol, 175–176 candidates, N_eff ≈ 130–135, two overlapping windows from the same week. This is one market regime (a quiet, chop-heavy week — median ADX 17–30, mostly chop/transitional). A genuinely different regime could move these numbers; the result is "−EV in the data we have," not "−EV forever."

## Roadmap implication

**The exit is not the lever — and neither, alone, is the entry.** The gross edge before fees is ~+0.17%/trade; the fee is 0.5–1.0%. The strategy is fee-dominated: it needs either (a) a materially higher gross per-trade edge or (b) a structurally lower fee, not a better exit.

Concrete reprioritization for Phase 1/2:

1. **Demote "tune the exit" and "tune the entry floor."** Both move EV by less than the fee. The chart-floor sweep already showed 0% would-have-won lift; this study shows the exit stack is at most +0.17%/trade gross. Neither closes a 0.5–1.0% fee gap.
2. **Promote the fee/venue question to Phase 1.** Break-even RT fee is 0.17%. Unless execution cost can be driven near that (limit/maker fills, tighter venue, larger-cap universe with deeper books, lower-frequency entries that justify the round-trip), the strategy is structurally −EV regardless of entry/exit tuning. This is a `trading-strategist` + `web3-engineer` question, not a calibration-knob question.
3. **Stop reading EV off N=7.** The live realized series is too small and outlier-dominated to validate or refute the backtest. Gate any "it works live" claim on N large enough that one trade is <10% of the mean (≈ N≥30 at this payoff dispersion), and on the backtest and live measuring the **same window**.
4. **The exit stack is still worth keeping** — it does what it was built for (cuts the loss tail from −2.2% binary to −0.58% realized, payoff 0.7→1.5). It is good risk management layered on a thesis whose gross edge is not yet above costs. Fix the edge first; the exit is already fine.

---

### Reproduce

```bash
python3 scripts/calibration/exit_reconciliation.py --cached /tmp/cal_candles_d1.json --json-out /tmp/exit_recon_d1.json
python3 scripts/calibration/exit_reconciliation.py --cached /tmp/cal_candles.json   # robustness window
```

Live N=7 source rows: `kind=position_close` in `contest_bot/artifact_2026052*.jsonl` (PYTH +2.08 stall_green, MEW −0.97 trail, RAY +1.39 trail, PYTH +1.93 trail, WIF +6.21 take_profit, DRIFT −0.40 flat_stall, BOME −1.06 flat_stall).
