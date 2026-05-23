# Phase 1 de-risk — does STRUCTURE beat momentum at the gate?

*2026-05-22, quant-analyst. The $0 follow-up to V.0 (`docs/strategy/2026-05-22-gating-delta.md`).
V.0 proved the bot's LOCAL gate (chart_analyst momentum-confidence ladder + regime + floor) is
**anti-predictive** on the cached tape — gating delta −1.5% / −1.9%, CI-clean on the WRONG side: it
selects exhausted tops that mean-revert. The Phase 1 bet is that **STRUCTURE features** (S/R room,
swing structure, multi-TF alignment) — a decorrelated axis from momentum-confidence (Pattern D) —
select better. This tests that bet **cheaply, deterministically, no LLM, no spend**, before we build
Phase 1.*

Script: `scripts/calibration/structure_gating_delta.py` (reuses V.0's `exit_reconciliation.py`
real-exit stack + Bartlett VIF, `chart_floor_calibration.py` candidate detection + enrich + regime,
and the V.0 paired-bootstrap gating-delta recipe — generalized to any gate predicate). Raw output:
`/tmp/structure_gating_delta.json`. Read-only w.r.t. the live bot (port 8265 — never touched).

## TL;DR — the answer

**No simple structure feature shows a positive, CI-clean gating delta on this data. The single
positive-LEANING arm (multi-TF alignment) is a one-symbol artifact and cannot be trusted to
generalize.** Structure does NOT, on this tape, demonstrably beat momentum at the gate. It does one
useful thing: it stops *subtracting* as hard. That partial good news, plus a sharp data-coverage
finding, **reshapes Phase 1** — it does not greenlight it as scoped.

Three load-bearing facts:

1. **Every structure arm beats the momentum baseline on magnitude** — the deltas are −0.06% to
   +0.29% vs momentum's −1.5% / −1.9%. So structure is *less anti-predictive* than the
   momentum-confidence ladder. That is real and directionally consistent with the Pattern-D thesis
   (the momentum axis is actively wrong; a different axis is at worst neutral).
2. **But "less negative" is not "positive."** The only arm with a positive point delta in BOTH windows
   is **multi-TF alignment** (`align`: +0.05% W1, +0.29% W2) — and **neither CI excludes zero**, and
   **every aligned trade is a single symbol (TNSR)**. It is a positive *lean* with N_eff ≈ 1 cluster,
   not a positive *signal*. Power: W1 would need ~741 independent trades to call its delta CI-clean.
3. **The `structure=UP` arm is CI-clean NEGATIVE in both windows** (−0.45% / −0.53%) — i.e. requiring
   a confirmed HH/HL uptrend *repeats* the momentum pathology: it over-selects extended trends that
   revert. The useful structural signal is the **inverse** — vetoing DOWN-structure breakouts is
   mildly positive (+0.04% / +0.06%); demanding UP-structure hurts.

## The structure gating-delta table (paired block-bootstrap, vs the momentum baseline)

`Δ = netEV(structure-gated) − netEV(ungated)`. Ungated arm = ALL breakout/volume-spike candidates
(the raw tape — identical to V.0's gating=OFF). Paired moving-block bootstrap (block=3, 5000
resamples, seed 1729) because gated ⊂ ungated; the fee cancels in the difference (fee-invariant),
read at break-even 0.10%. Real close-based exit stack (V.0's `simulate_exit_real_close`). `CI-clean` =
the 95% CI excludes zero (and on which side).

### Window W1 (`/tmp/cal_candles_d1.json`, N=175)

| arm | N_on | symbols | netEV(on)% | netEV(off)% | **Δ%** | paired 95% CI | CI-clean |
|:--|---:|---:|---:|---:|---:|:--|:--:|
| room (room≥1.5% OR open-sky) | 12 | 6 | +0.006 | +0.071 | **−0.064** | [−0.866, +0.661] | no |
| structure (= UP, HH+HL) | 27 | 5 | −0.377 | +0.071 | **−0.447** | [−1.102, −0.136] | **YES(−)** |
| **align (5m long ∥ 1h TREND-UP)** | 11 | **1** | +0.118 | +0.071 | **+0.048** | [−0.543, +0.491] | no |
| combined (room AND aligned) | 1 | 1 | −0.391 | +0.071 | **−0.462** | [−0.679, −0.302] | YES(−)† |
| **— momentum baseline (V.0) —** | 3 | — | −1.343 | +0.071 | **−1.514** | [−3.362, −0.545] | **YES(−)** |

### Window W2 (`/tmp/cal_candles.json`, N=176)

| arm | N_on | symbols | netEV(on)% | netEV(off)% | **Δ%** | paired 95% CI | CI-clean |
|:--|---:|---:|---:|---:|---:|:--|:--:|
| room (room≥1.5% OR open-sky) | 13 | 6 | +0.026 | −0.008 | **+0.034** | [−0.579, +0.754] | no |
| structure (= UP, HH+HL) | 23 | 6 | −0.535 | −0.008 | **−0.527** | [−1.082, −0.077] | **YES(−)** |
| **align (5m long ∥ 1h TREND-UP)** | 9 | **1** | +0.278 | −0.008 | **+0.285** | [−0.220, +0.793] | no |
| combined (room AND aligned) | 1 | 1 | −0.391 | −0.008 | **−0.384** | [−0.603, −0.183] | YES(−)† |
| **— momentum baseline (V.0) —** | 2 | — | −1.779 | −0.008 | **−1.872** | [−3.357, −0.421] | **YES(−)** |

The momentum-baseline rows reproduce V.0 exactly (Δ −1.514% / −1.872%) — computed via the V.0 module
on the same enriched windows, so the comparison is apples-to-apples.

† **The `combined` CI-clean(−) is meaningless: N_on = 1.** A single trade has no sampling
distribution; the bootstrap just resamples that one value. Listed for completeness, **not** evidence.

## Why the one positive arm doesn't count — the single-symbol trap

The `align` arm is the only one with a positive point delta in both windows, so it deserves the
hardest look. It fails three independent checks:

- **It spans exactly ONE symbol (TNSR) in both windows.** All 11 (W1) / 9 (W2) aligned trades are TNSR.
  The block bootstrap resamples *within* symbol, so with one symbol the effective independent N is **≈ 1
  cluster**, not 9–11. The CI is genuinely uninformative about whether this holds on any *other* name.
- **Power says it's noise.** Treating the trades as independent (generous), the W1 delta (+0.05%) needs
  **~741 trades** to be CI-clean; W2 (+0.29%) needs **~20** — and both pools are one symbol, so even
  ~20 is unreachable from one name's one trend. The sign is real for TNSR-that-week; the *effect* is not
  estimable.
- **The multi-TF axis has no contrast on this tape.** `COUNTER` (5m breakout fired during a 1h
  TREND-DOWN) count = **0** in both windows. Relaxing the gate to "1h not-TREND-DOWN" is a literal
  **no-op** (Δ = +0.000%, N = all). The quiet week simply doesn't contain the counter-trend breakouts
  the MTF filter exists to veto. So the filter can't be evaluated here — there's nothing for it to cut.

## What each gate actually selects (gross shape, pre-fee)

| window | ungated | room | structure(UP) | align(TNSR) |
|:--|:--|:--|:--|:--|
| W1 | +0.171%, 51% win, N=175 | +0.106%, 33% win, N=12 | **−0.277%**, 44% win, N=27 | +0.218%, 45% win, N=11 |
| W2 | +0.092%, 46% win, N=176 | +0.126%, 31% win, N=13 | **−0.435%**, 35% win, N=23 | +0.378%, 56% win, N=9 |

`structure=UP` selects a pool whose gross mean is *negative* and *below* the ungated tape — the same
"high-conviction-trend setups revert" pathology V.0 found for the momentum ladder. The room arm tightens
win-rate downward without lifting mean — it isn't picking winners, it's picking lower-variance flats.

## Per-regime (5m ADX partition) — where any signal lives

The only CI-clean *positive* per-regime cell is **TRANSITIONAL + room** (W1 Δ=+1.328 [+0.717, +2.280],
W2 Δ=+1.451 [+0.838, +2.520]). **Do not headline it: it is N_on = 2, the SAME two trades (BOME idx≈127,
DRIFT idx≈107) in both overlapping windows.** Two observations, two symbols, one each — the CI excludes
zero only because those two happened to be clean +2.2% / +1.0% wins with tiny within-pair spread. It is a
small-N + low-variance artifact, not a transitional-regime edge. Every other positive per-regime cell
(`align` in CHOP, `structure` in W2-CHOP) straddles zero. The CI-clean *negative* per-regime cells
(`structure` in CHOP, `combined` in CHOP) just re-state the overall anti-predictivity at smaller N.

## Robustness — threshold + definition sweeps (guarding against a false negative)

- **Room threshold sweep (overall point delta):** non-monotone, with a small consistent bump at exactly
  **room ≥ 1.0%** (W1 +0.153% N=18 / W2 +0.210% N=20, all 6 symbols) that decays on both sides
  (≥1.5% → flat; ≥3% → −0.5 to −0.7%). This 1.0% bump is the *most diversified* positive structure
  signal in the study (6 symbols, ~20 trades) — but it is small, untested for CI here, and
  threshold-fragile. It is the one thread worth pulling in Phase 1, not a result.
- **Structure relaxed:** "not-DOWN" (UP or RANGE) is mildly positive (+0.044% / +0.056%); **DOWN-only is
  negative** (−0.140% / −0.179%). The usable structural information is *avoid* down-structure breakouts —
  the opposite of the "require confirmed uptrend" gate, which is the part that's anti-predictive.
- **Multi-TF relaxed:** no-op (COUNTER = 0), as above.

## Leakage — checked, clean

The whole point of computing on `candles[:i+1]`. Verified two ways:

- **Unit tests (synthetic, 14/14 pass)** — `--self-test`. T2 asserts a k-bar fractal pivot at bar j is
  *invisible* until exactly bar j+k (no look-ahead); T3 asserts room-to-run direction + open-sky; T4
  asserts HH/HL→UP, LH/LL→DOWN, mixed→RANGE; T5 asserts the 1h resample **drops the still-forming hour**
  (the entry bar's own hour never leaks into its regime read).
- **Real-data spot-check** — across all 175 W1 candidates: **0** pivot indices later than `i−k`, **0**
  1h-resample bars in or after the entry hour. The point-in-time discipline holds on the live tape.

## Caveats (load-bearing — this is directional, not a verdict)

- **One quiet, chop-heavy week; two OVERLAPPING windows** (W1/W2 share most bars; the TNSR aligned
  cluster and the BOME/DRIFT transitional-room pair recur as the *same* trades). The two windows are not
  independent replications — they are a stability check, not N≈350.
- **A deterministic SUBSET of the eventual Phase 1 feature set** — 3 simple proxies (k=2 fractal S/R, a
  2-pivot HH/HL rule, a resampled-1h regime), not the full S/R + swing-structure + MTF engine Phase 1
  would build. A richer encoding could carry signal these proxies miss. This *bounds* the bet downward on
  this data; it does not prove the rich version fails.
- **Small per-regime N_eff** — most per-regime/per-arm cells are single digits; treat per-regime signs as
  hints, not estimates. The gates are sparse by construction (room 7%, aligned ~6%, combined 1%).
- **This is the LOCAL deterministic proxy, NOT the live Gecko Oracle** (`gecko_trade_research`). Same
  caveat as V.0: the Oracle's true gating delta is a separate, recorded-verdict eval and is the number
  that actually decides the wedge.

## What this means for Phase 1

**Phase 1 as "build S/R + swing-structure + multi-TF and gate on them" is NOT justified by this data.**
On this tape those three axes, in simple form, range from flat to CI-clean-negative; the one positive
lean is a single symbol. Building the full engine on the expectation that it flips the gate positive
would be building on a result that isn't here.

But three findings *reshape* (not kill) Phase 1:

1. **Structure is less wrong than momentum — pursue the decorrelation, drop the direction-confirmation
   framing.** The Pattern-D instinct (momentum-confidence is the wrong axis) is corroborated: structure
   arms beat the momentum baseline by ~1.5pp of delta. But the *useful* structural signal is
   **subtractive** (veto DOWN-structure / no-overhead-room breakouts), not **additive** (require a
   confirmed uptrend — that re-creates the anti-predictivity). Reframe Phase 1 around vetoes, not
   confirmations.
2. **The most diversified positive thread is room ≥ ~1.0%** (6 symbols, ~20 trades, +0.15–0.21%). It is
   small and fragile but it is the only structure signal that is both positive and cross-sectional. If
   Phase 1 ships, lead with room-to-run, CI-test it on a fresh tape, and treat the threshold as a
   hyperparameter to validate, not assume.
3. **This tape cannot evaluate multi-TF at all** (zero counter-trend candidates). Multi-TF alignment is
   not falsified here — it is *untested* for lack of contrast. Re-measure it on a tape that contains
   1h-TREND-DOWN breakouts before spending on it, and require the aligned pool to span ≥3 symbols before
   trusting any positive delta.

**Decision input:** before committing Phase 1 build cost, get (a) a trendier / multi-symbol tape with
real counter-trend cases, and (b) the room-to-run thread CI-tested with ≥3-symbol coverage. If room
survives that, Phase 1 has a foothold. If it doesn't, structure won't save the gate and the effort
belongs on the Oracle's recorded-verdict eval (V.0's recommendation #2) instead.

---

*Reproduce:* `python3 scripts/calibration/structure_gating_delta.py --w1 /tmp/cal_candles_d1.json
--w2 /tmp/cal_candles.json --json-out /tmp/structure_gating_delta.json`
*Unit tests only:* `python3 scripts/calibration/structure_gating_delta.py --self-test`
