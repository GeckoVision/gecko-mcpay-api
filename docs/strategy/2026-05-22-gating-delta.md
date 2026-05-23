# Phase V.0 — the fee × gating direction-falsifier

*2026-05-22, quant-analyst. The highest-value next measurement from the fee/venue package
(`docs/strategy/2026-05-22-fee-venue-decision.md`, committed `69325b8`): settle, for free on cached
data, whether the venue is the blocker or the wedge is.*

Script: `scripts/calibration/fee_sensitivity_gating_delta.py` (reuses the `exit_reconciliation.py`
real-exit stack + block bootstrap, and `chart_floor_calibration.py` candidate detection + proxies).
Raw output JSON: `/tmp/gating_delta.json`. Read-only w.r.t. the live bot (port 8265 — never touched).

## TL;DR (the direction the falsifier points)

**The venue is not the only blocker, and on this window it is not the binding one — the wedge is.**

1. **No reachable fee makes net-EV confidently positive.** Only one cell in the entire sweep clears
   zero on the +side — `gating=OFF` at a literal **0% fee** on W1 (`+0.171% [+0.012, +0.393]`) — and it
   evaporates in W2 and at any nonzero fee. The gross edge (`+0.09–0.17%`) is too thin to survive even
   free execution with a clean CI. **The edge, not the venue, is the first-order blocker.**
2. **The gating delta is negative and CI-clean-negative at break-even fee — the gate currently
   SUBTRACTS selection value.** It is not flat; it is **anti-predictive on this window.**
3. **This is a chop-window result (61–64% of candidates are direction-aware CHOP), but it is NOT a
   small-N artifact** — the negative sign holds across a 10-level floor robustness grid (N up to 64)
   and across a clean veto-pool/kept-pool decomposition. On *this* tape the local panel's
   confidence proxy is anti-correlated with realized outcome.

The headline `gating=ON` arm is the live policy's `N=2–3` trades, which on its own is fragile. But its
**sign is corroborated** by the robustness grid below at much larger N, so the directional read is solid;
the *magnitude* (`Δ ≈ −1.5 to −1.9%`) is not.

## The fee × gating table (real-exit stack, net-EV%, block-bootstrap 95% CI)

Block bootstrap: block=3, 5000 resamples, seed 1729. `N_eff = N / VIF` (Bartlett K=4). `excl0` =
does the 95% CI exclude zero (`+`/`-` = which side).

### Window W1 (`/tmp/cal_candles_d1.json`)

| fee% | arm | N | N_eff | net-EV% | block 95% CI | excl0 | payoff |
|---:|:--|---:|---:|---:|:--|:--:|---:|
| 0.75 | OFF | 175 | 135 | −0.579 | [−0.738, −0.357] | **YES(−)** | 0.66 |
| 0.75 | ON  |   3 |   3 | −2.093 | [−3.872, −1.187] | **YES(−)** | n/a |
| 0.50 | OFF | 175 | 135 | −0.329 | [−0.488, −0.107] | **YES(−)** | 1.02 |
| 0.50 | ON  |   3 |   3 | −1.843 | [−3.622, −0.937] | **YES(−)** | n/a |
| 0.20 | OFF | 175 | 135 | −0.029 | [−0.188, +0.193] | no | 1.39 |
| 0.20 | ON  |   3 |   3 | −1.543 | [−3.322, −0.637] | **YES(−)** | n/a |
| 0.10 | OFF | 175 | 135 | +0.071 | [−0.088, +0.293] | no | 1.58 |
| 0.10 | ON  |   3 |   3 | −1.443 | [−3.222, −0.537] | **YES(−)** | n/a |
| 0.04 | OFF | 175 | 135 | +0.131 | [−0.028, +0.353] | no | 1.63 |
| 0.04 | ON  |   3 |   3 | −1.383 | [−3.162, −0.477] | **YES(−)** | n/a |
| **0.00** | **OFF** | 175 | 135 | **+0.171** | **[+0.012, +0.393]** | **YES(+)** | 1.52 |
| 0.00 | ON  |   3 |   3 | −1.343 | [−3.122, −0.437] | **YES(−)** | n/a |

### Window W2 (`/tmp/cal_candles.json`)

| fee% | arm | N | N_eff | net-EV% | block 95% CI | excl0 | payoff |
|---:|:--|---:|---:|---:|:--|:--:|---:|
| 0.75 | OFF | 176 | 130 | −0.658 | [−0.856, −0.435] | **YES(−)** | 0.60 |
| 0.75 | ON  |   2 |   2 | −2.529 | [−3.872, −1.187] | **YES(−)** | n/a |
| 0.50 | OFF | 176 | 130 | −0.408 | [−0.606, −0.185] | **YES(−)** | 0.93 |
| 0.50 | ON  |   2 |   2 | −2.279 | [−3.622, −0.937] | **YES(−)** | n/a |
| 0.20 | OFF | 176 | 130 | −0.108 | [−0.306, +0.115] | no | 1.17 |
| 0.20 | ON  |   2 |   2 | −1.979 | [−3.322, −0.637] | **YES(−)** | n/a |
| 0.10 | OFF | 176 | 130 | −0.008 | [−0.206, +0.215] | no | 1.42 |
| 0.10 | ON  |   2 |   2 | −1.879 | [−3.222, −0.537] | **YES(−)** | n/a |
| 0.04 | OFF | 176 | 130 | +0.052 | [−0.146, +0.275] | no | 1.54 |
| 0.04 | ON  |   2 |   2 | −1.819 | [−3.162, −0.477] | **YES(−)** | n/a |
| 0.00 | OFF | 176 | 130 | +0.092 | [−0.106, +0.315] | no | 1.48 |
| 0.00 | ON  |   2 |   2 | −1.779 | [−3.122, −0.437] | **YES(−)** | n/a |

The OFF arm reproduces the fee/venue doc's EV-at-each-fee table exactly (W1 ALL `+0.171%`, W2 `+0.092%`
gross; N≈175, N_eff≈130–135). This is the same baseline, sliced by the gate.

## The gating delta (the proof-artifact metric), paired block-bootstrap CI

`Δ = netEV(ON) − netEV(OFF)`. The two arms are **not independent** — `ON ⊂ OFF` — so the CI is a
**paired** moving-block bootstrap: each iteration resamples the underlying candidates once, recomputes
both arm means on the same resample, takes the difference. The fee cancels in the difference, so `Δ` is
**fee-invariant**; we report it at both break-even reads to show the absolute net level of each arm.

| window | fee | netEV(ON), N | netEV(OFF), N | **Δ** | paired 95% CI | CI-clean |
|:--|---:|:--|:--|---:|:--|:--:|
| W1 | 0.04% | −1.383% (N=3) | +0.131% (N=175) | **−1.514%** | [−3.362, −0.545] | **YES(−)** |
| W1 | 0.10% | −1.443% (N=3) | +0.071% (N=175) | **−1.514%** | [−3.362, −0.545] | **YES(−)** |
| W2 | 0.04% | −1.819% (N=2) | +0.052% (N=176) | **−1.872%** | [−3.357, −0.421] | **YES(−)** |
| W2 | 0.10% | −1.879% (N=2) | −0.008% (N=176) | **−1.872%** | [−3.357, −0.421] | **YES(−)** |

The point delta is negative and the CI excludes zero **on the wrong side** in both windows. The gate, as
the local deterministic proxy renders it, **removed value** on this tape.

## Why this is not an N=2–3 artifact — the robustness grid

The live policy keeps only 2–3 trades because the proxy confidence ladder caps at **0.885** (the 6/6
momentum-cell band midpoint) and the next band down is **0.825** (5/6 cells, *below* the 0.85 floor) — so
the 0.85 floor admits *only* the 6/6 band, and in this universe that's a handful of trades. To prove the
sign isn't an accident of those few trades, sweep the ON-arm confidence floor (de-discretizing the
knife-edge) and recompute the gross gating delta (`Δ = mean(ON) − mean(all)`, fee cancels):

**Gate = chart_bullish AND not-adverse-regime AND proxy_conf ≥ floor:**

| floor | W1: N | W1 grossEV% | **W1 Δ vs OFF** | W2: N | W2 grossEV% | **W2 Δ vs OFF** |
|---:|---:|---:|---:|---:|---:|---:|
| 0.885 | 3 | −1.343 | **−1.514** | 2 | −1.779 | **−1.872** |
| 0.825 | 9 | −1.013 | **−1.183** | 8 | −1.107 | **−1.200** |
| 0.810 | 14 | −0.540 | **−0.711** | 14 | −0.602 | **−0.695** |
| 0.750 | 19 | −0.409 | **−0.580** | 18 | −0.550 | **−0.642** |
| 0.600 | 24 | −0.428 | **−0.599** | 23 | −0.539 | **−0.632** |
| 0.500 | 24 | −0.428 | **−0.599** | 23 | −0.539 | **−0.632** |

**Without** the direction filter (gate = chart_bullish AND proxy_conf ≥ floor), larger N, sign unchanged:

| floor | W1: N | **W1 Δ** | W2: N | **W2 Δ** |
|---:|---:|---:|---:|---:|
| 0.885 | 7 | **−0.815** | 5 | **−1.158** |
| 0.825 | 29 | **−0.287** | 24 | **−0.408** |
| 0.750 | 64 | **−0.163** | 56 | **−0.205** |

Two facts settle it:
- The delta is **negative at every floor from 0.50 to 0.92**, in both windows, with and without the
  direction filter — at N up to 64. The sign is not an N=2–3 fluke.
- The relationship is **monotone the wrong way**: the *more selective* the gate (higher floor), the
  *more negative* the delta. Higher chart-confidence breakouts did *worse* on this window. That is the
  signature of an **anti-predictive** confidence signal, not a noisy-but-neutral one.

### The decomposition that makes it concrete

| window | VETOED pool (gate filtered out) | KEPT pool (passed gate) |
|:--|:--|:--|
| W1 | N=172, mean gross **+0.197%**, 70 winners (>+0.2%) | N=3, mean gross **−1.343%** |
| W2 | N=174, mean gross **+0.114%**, 70 winners | N=2, mean gross **−1.779%** |

The gate vetoed a pool that on net **wins** and kept the pool that **loses**. And the clincher: of the
**8–10 TREND-UP winners** in each window, **0 cleared the 0.85 floor** — every directional winner sat at
proxy-confidence 0.825 or below. The strongest realized up-moves carried *middling* chart-confidence; the
top-confidence setups failed.

## The three questions, answered explicitly

**Q1 — Does any reachable fee make a net-EV CI exclude zero on the +side, for either arm?**
**Effectively no.** The *only* positive-side-clean cell in the entire 24-cell sweep is `gating=OFF` at a
**literal 0% fee on W1** (`+0.171% [+0.012, +0.393]`). It does not survive in W2 (`+0.092% [−0.106,
+0.315]`, straddles 0) and not at any fee above 0%. No realistically reachable fee (Jupiter RFQ ~0.04%,
Phoenix maker ~0%) produces a confident winner with margin. **The gross edge itself is the binding
constraint** — exactly the fee/venue doc's "necessary, not sufficient" warning, now sharpened: at the
gross edge measured here it isn't even sufficient at zero fee. **Structure work (lift gross to ~+0.4–0.6%)
is mandatory and first.**

**Q2 — Is the gating delta positive + CI-clean at break-even fee?**
**No — it is negative and CI-clean-negative.** At the break-even fee (0.10%), `Δ = −1.514%`
[−3.362, −0.545] (W1) and `−1.872%` [−3.357, −0.421] (W2). The gate did not add selection value on this
window; it **subtracted** it. This is the strategist's `−0.64%` entry-gate hint and the floor sweep's "too
conservative?" question, now resolved with a paired CI: **the gate, as the local proxy renders it, is
anti-predictive here, not merely flat.** Corroborated by the robustness grid (negative at all 10 floors)
and the veto/kept decomposition.

**Q3 — Chop-window artifact, or a real "the wedge needs work" signal?**
**Both are true, and that is the honest read.** It IS a chop-heavy window — direction-aware regime mix is
**~19% TREND-UP / ~17% TREND-DOWN / ~64% CHOP** (W1) and **~23% / ~16% / ~61%** (W2); the breakout
primitive is structurally −EV in chop (prior backtest finding). So the *magnitude* is a chop artifact and
will likely soften on a trendier tape. **But the SIGN is not** a pure artifact: even restricted to the
favorable TREND-UP candidates, the gate's high-confidence picks underperformed, and 0 of the directional
winners cleared the floor. The momentum-acceleration confidence ladder (6/6 cells → 0.885) is, on this
data, **selecting for setups that mean-revert rather than continue**. That is a real "the wedge needs
work" signal for the local panel — distinct from the chop drag on absolute PnL. The honest framing: *on a
chop week the local gate doesn't just fail to help — its confidence ranking points the wrong way, and we
should not assume a trend week flips it positive without re-measuring.*

## What this does and does not measure (caveats — load-bearing)

- **This is the LOCAL deterministic gate proxy, NOT the live Gecko Oracle (`gecko_trade_research`).** The
  Oracle (adversarial panel + grounded citations) cannot be cheaply backtested on historical candles — it
  needs *recorded verdicts* at each historical bar. **The Oracle's true gating delta is a separate, later
  eval** and is the number that actually decides whether the wedge works. V.0 measures the local panel's
  chart-confidence discrimination as the **replayable proxy** — the cheapest available falsifier, not the
  verdict on the product.
- The ON arm omits the LLM risk-veto and memory-contradict rules (no deterministic proxy). Those rules
  only ever *add* declines, so this ON arm is a **strict superset** of the live ON arm — a
  conservative, gate-*friendly* proxy. The real live gate keeps ≤ what we measured, so the true live
  selection is no better than this read.
- **One quiet chop-heavy week, two OVERLAPPING windows** (W1/W2 share most bars; PYTH/DRIFT recur as the
  same kept trades). Per-regime N_eff is small. The result is **directional, not precise.** Treat the
  signs as load-bearing and the magnitudes as indicative.
- The break-even fee is read at 0.10% (conservative) and 0.04% (Jupiter RFQ optimistic); the delta is
  fee-invariant, so the choice does not affect the gating verdict.

## Implications for the roadmap

1. **Re-order the build.** The fee/venue doc said "need both levers (fee + structure)." V.0 sharpens the
   ordering: **structure first.** No fee — not even 0% — makes today's edge a confident winner, and the
   gate currently subtracts value. Cutting the fee to Jupiter RFQ / Phoenix is still correct (it un-masks
   the gating signal, per the doc), **but it cannot be the first move** — there is no positive gating
   signal to un-mask yet.
2. **The next eval is the Oracle gating delta, not the venue.** Stand up the recorded-verdict harness
   (log `gecko_trade_research` verdicts at each historical bar for a window) so the *real* wedge — the
   adversarial panel, not the local proxy — can be measured the same way. If the Oracle's gating delta is
   positive and CI-clean where the local proxy's is negative, that *is* the product's value, demonstrated.
   If it is also negative, the wedge needs work before any feature build — a far more important finding
   than the venue.
3. **Re-measure on a trend week before concluding the local gate is broken.** The sign here is real but
   confounded with the chop regime. A trend-tape replay separates "anti-predictive everywhere" from
   "anti-predictive in chop, additive in trend." That partition decides whether the local panel's
   confidence ladder needs a redesign or just a regime gate.

---

*Reproduce:* `python3 scripts/calibration/fee_sensitivity_gating_delta.py --w1 /tmp/cal_candles_d1.json
--w2 /tmp/cal_candles.json --json-out /tmp/gating_delta.json`
