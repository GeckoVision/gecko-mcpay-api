# Regime-Partitioned Calibration Validation — TP-level + trend-edge settlement

**Date:** 2026-05-22
**Branch:** `s41/oracle-real-execution`
**Author:** quant-analyst
**Scripts:**
- `scripts/calibration/chart_floor_calibration.py` (base study, re-run)
- `scripts/calibration/tp_regime_validation.py` (this study — TP × regime × fee)

**Live bot (UNTOUCHED, read-only):** `contest_bot/jto_breakout_gecko_gated_contest_bot.py` (PID 2198871, port 8265)

**Data window:** 6 live mints (PYTH, WIF, POPCAT, BOME, DRIFT, TNSR), 5m candles,
299 bars each, fetched 2026-05-22 via the bot's own `onchainos` wrapper (byte-faithful).
Spans 25–77h depending on liquidity. **175 candidates** surfaced by the deterministic
breakout/volume-spike gate (full-horizon only).

---

## TL;DR — the two questions, settled

**Q1 (trend-edge): Is there ANY chart floor whose EV confidence interval excludes
zero in the TREND subset?**

**Yes — but on the WRONG side.** At every floor 0.50–0.85, the trend-subset net-EV
95% CI lies *entirely below zero* (e.g. floor 0.80, TP2: net EV **−0.89% [−1.49, −0.31]**;
floor 0.85, TP2: **−1.58% [−2.68, −0.92]**). The CI excludes zero, which means this is
**statistically significant evidence the momentum signal LOSES money net of fees in
trend**, not that it has an edge. The trend regime does not rescue the strategy in this
window. Gross-of-fees EV in trend is ≈ break-even (+0.03% at TP2, −0.05% at TP4); the
~0.75% round-trip fee is larger than the entire gross edge.

**Q2 (TP2 vs TP4, net of fees): did lowering TP 4→2 help or hurt?**

**It is a marginal wash — TP2 is very slightly less-bad than TP4, but neither is +EV.**
Across all 175 candidates, net EV (fee 0.75%): **TP2 −0.62% [−0.81, −0.44]**,
**TP3 −0.67%**, **TP4 −0.69% [−0.87, −0.51]**, TP5 −0.69%. The CIs overlap heavily —
the TP-level choice is **not statistically distinguishable**. TP2's edge is that it
*realizes more wins* (17.1% would-have-won vs 0.0% at TP4) — the universe genuinely
oscillates ~2% and rarely reaches +4%, exactly the founder's observation. But TP2's
break-even win-rate is **75%** and the realized rate is **17%**, so even the "more
reachable" target is far from profitable. **Lowering TP did not make it harder; it made
the wins reachable, but the wins are still too rare to cover the higher break-even bar.**

**The regime-conditional TP rule (TP4-5 when ADX≥25 AND 24h range≥4%, else TP2-3) is
NOT supported.** Applied to the same candidate set it gives net EV **−0.650%
[−0.836, −0.468]**, statistically indistinguishable from fixed-TP2 (−0.624%) and
fixed-TP4 (−0.688%). It routed 42/175 candidates to high-TP and changed nothing
that matters.

**Headline:** the momentum signal in this window has a real but *tiny* gross edge
(≈ +0.06% to +0.32%/trade) that is **dominated by transaction costs**. No TP target
and no chart floor turns it net-positive. This is not a tuning problem — it is a
**signal-strength-vs-fee problem.**

---

## Break-even win-rate vs realized win-rate (the core settle)

Break-even win-rate for a binary TP/SL outcome net of fees is
`p* = (SL + fee) / (TP + SL)`, with SL = 3%. The founder's prior figures
(TP2≈74%, TP4≈53%) are confirmed:

| TP target | BE win-rate @0.5% fee | @0.75% | @1.0% | **realized would-win (all regimes)** |
|----------:|----------------------:|-------:|------:|-------------------------------------:|
| TP2 | 70.0% | **75.0%** | 80.0% | **17.1%** |
| TP3 | 58.3% | 62.5% | 66.7% | 2.3% |
| TP4 | 50.0% | **53.6%** | 57.1% | **0.0%** |
| TP5 | 43.8% | 46.9% | 50.0% | 0.0% |

The realized rate is **3–4× below** the break-even bar at every TP. Lowering TP cuts
the break-even bar (TP4 needs 54%, TP2 needs 75%) but raises it relative to what's
*achievable* — TP2's reachable wins (17%) still fall an enormous distance short of its
75% requirement. There is no TP target where realized ≥ break-even.

---

## Per-regime TP settlement (net EV, fee 0.75% round-trip)

| Regime | N | TP2 net EV [95% CI] | TP4 net EV [95% CI] | TP2 would-win | gross EV (TP2) |
|--------|---:|--------------------:|--------------------:|--------------:|---------------:|
| **trend** | 63 | −0.72% [−1.08, −0.39] | −0.80% [−1.14, −0.46] | 15.9% | +0.03% |
| transitional | 51 | −0.43% [−0.74, −0.12] | −0.51% [−0.80, −0.22] | 21.6% | +0.32% |
| chop | 61 | −0.68% [−0.99, −0.38] | −0.73% [−1.04, −0.43] | 14.8% | +0.07% |
| ALL | 175 | −0.62% [−0.81, −0.44] | −0.69% [−0.87, −0.51] | 17.1% | +0.13% |

Reading:
- **Every regime, every TP, net of fees: CI entirely below zero.** Significantly −EV.
- **Transitional is the least-bad** (net −0.43% TP2, gross +0.32%) — counter-intuitive,
  but it has the highest realized would-win (21.6%) and N=51 is non-trivial. This is the
  one cell worth re-watching with more data; it is still −EV net.
- **Trend is NOT better than chop** here. The momentum thesis ("edge appears when ADX is
  high") is *not* visible in this 2026-05-22 window. Gross trend EV at TP2 is +0.03% —
  indistinguishable from zero — and net it is −0.72%.

### The live entry set (chart_bullish & proxy ≥ 0.85), N=7

The 7 candidates the live floor would actually admit: **0% would-win at any TP**, gross
EV −0.71%, net EV −1.46% [−2.25, −0.99]. The current floor is admitting the *worst*
slice (the confidence-inversion from the 2026-05-21 study persists). **N=7 is too small
to act on**, but it is consistent with "the floor is not selecting winners."

---

## D1.a — trend-only floor sweep (does any floor exclude zero on the +side?)

| floor | N | would-win (TP2) | net EV TP2 [95% CI] | excludes 0? | direction |
|------:|---:|----------------:|--------------------:|:-----------:|:---------:|
| 0.50 | 35 | 6% | −1.13% [−1.58, −0.68] | YES | **negative** |
| 0.70 | 25 | 8% | −0.93% [−1.42, −0.46] | YES | **negative** |
| 0.80 | 18 | 11% | −0.89% [−1.49, −0.31] | YES | **negative** |
| 0.85 | 5 | 0% | −1.58% [−2.68, −0.92] | YES | **negative** |
| 0.90–0.95 | 0 | — | — | — | (no entries) |

**Verdict: no floor produces a positive-EV CI excluding zero. Every floor that has data
produces a NEGATIVE-EV CI excluding zero.** The pre-registered decision rule ("lower the
floor only if a lower floor's EV is higher with a CI excluding zero AND adequate N") is
**not triggered** — and in fact the data argues the *opposite*: lowering the floor admits
more significantly-losing trades.

---

## Sample-size honesty (where we CANNOT conclude)

- **Trend cell N=63** total, but only **5** survive the live 0.85 floor. The floor-gated
  trend cell (N=5) cannot estimate an edge — its CI is [−2.68, −0.92] purely from
  near-flat-to-loss realizations, and 5 observations cannot detect a rare-but-large
  winner. **The "is the floor too tight in a real trend" question remains genuinely
  underpowered.** To detect a true would-win rate of, say, 25% with ±10% at 95%
  confidence requires **N ≈ 72** trend entries *that pass the floor*. We have 5. That is
  a ~14× data shortfall. **Recommendation: collect more live trend-regime data before
  any floor change.**
- **Live entry set N=7** — directional only, not actionable.
- **This is one 25–77h snapshot.** Median ADX 17–30 across names; it is *not*
  regime-balanced and over-weights two illiquid chop names (DRIFT, TNSR) by wall-clock.
- **The gross edge is real but sub-fee.** Gross EV is positive in 3 of 4 regime cells.
  That means the signal isn't *noise* — it has a small directional tilt — but the tilt
  (≈ +0.1%/trade) is roughly **1/7th** of the round-trip cost. No amount of TP/floor
  tuning closes a 7× gap; only a *stronger entry signal* or *lower fees* (bigger,
  more-liquid names; fewer legs) can.

---

## What this means for the live bot (no change recommended without more data)

1. **Hold the floor.** Loosening it is significantly −EV here (D1.a). Confirmed for the
   2nd consecutive window.
2. **TP2 (live) is fine — it is the least-bad and the most-reachable.** Do not revert to
   TP4; reverting would not help (CIs overlap) and would make wins unreachable. But do
   not expect TP2 to be profitable on the current signal.
3. **The regime-conditional TP rule is not worth implementing.** No measurable benefit.
4. **The real lever is the entry signal and the fee base, not the exit.** The bot is
   correctly *declining* almost everything; the problem is that the few things it takes
   carry a gross edge smaller than fees. Higher-leverage work: (a) a stronger entry
   filter that lifts gross would-win materially above ~17%, (b) routing only the most
   liquid names to cut effective round-trip cost toward 0.5%, (c) the chop "sit in cash"
   gate (already partly in via the chop-modulator).
5. **Collect ≥ ~70 floor-passing trend entries before re-asking the trend-edge
   question.** Until then, "momentum has an edge in trend" is **unproven, and the
   current data leans against it.**

---

## Reproduce

```bash
# fetch live candles + base floor study
python3 scripts/calibration/chart_floor_calibration.py \
    --dump-candles /tmp/cal_candles_d1.json --json-out /tmp/cal_results_d1.json
# TP x regime x fee settlement (this study), deterministic replay from cache
python3 scripts/calibration/tp_regime_validation.py \
    --cached /tmp/cal_candles_d1.json --json-out /tmp/tp_results_d1.json
```

Fee model: round-trip band {0.5%, 0.75%, 1.0%}, central 0.75% (S40 grid plan cited
~0.6%/leg DEX on thin memes → ~1.2% round-trip worst case; we use 0.75% central as a
liquid-name optimistic-realistic figure and report the full band on break-even).
Bootstrap: 5,000 resamples, seed 1729. SL fixed at 3% throughout.
