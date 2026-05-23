# Oracle gating-delta — W2 replication + TRANSITIONAL fill

*2026-05-22/23, ai-ml-engineer. Replication of the W1 result
(`docs/strategy/2026-05-22-oracle-gating-delta.md`, commit `95879e1`): does the real
`gecko_trade_research` Oracle's positive, CI-clean gating delta hold on a second window, and is the
soft TRANSITIONAL cell genuinely positive or noise?*

Harness reused unchanged: `scripts/trading_oracle/oracle_gating_delta.py` (paired moving-block
bootstrap, block=3, 5000 resamples, seed 1729). Pooling + jackknife: `scripts/trading_oracle/pool_gating_delta.py`.
Raw: W1 `tests/eval/live_runs/2026-05-22-oracle-gating-delta-w1.json` (N=30, prior run),
W2 `tests/eval/live_runs/2026-05-22-oracle-gating-delta-w2.json` (N=48, this run).
Read-only w.r.t. the live bot (port 8265 — never touched). x402 stayed STUB. Gateway: OpenRouter
(`openai/gpt-4o-mini`), same byte-identical Oracle logic the W1 run proved; OpenAI-direct
cross-check still deferred (key out of quota).

## TL;DR — the verdict in one line

**The +1.1% is NOT locked. The SIGN is locked (positive on both windows, jackknife-robust, pooled
CI-clean at +0.65%), but the MAGNITUDE is not — W2 came in at +0.31% (CI straddles zero), roughly a
quarter of W1's +1.12%.** Honest read: the Oracle discriminates in the right direction on both
windows, but "+1.1%" was a high-end-of-the-range single-window draw, not a stable point estimate.
The defensible claim is now **"+0.6% pooled, sign-robust"**, not "+1.1% confirmed."

The one genuinely improved result: **TRANSITIONAL — the W1 soft cell — is now CI-clean positive
pooled** (+0.78% [+0.09, +1.74], N=22). That cell firmed up.

## Results

### Per-window

| window | scope | nSAFE | nOFF | mSAFE% | mOFF% | **Δ%** | paired 95% CI | CI-clean |
|---|:--|--:|--:|--:|--:|--:|:--|:--:|
| **W1 (N=30)** | ALL | 16 | 14 | +0.637 | −0.482 | **+1.119** | [+0.314, +1.935] | **YES(+)** |
| | TREND | 8 | 3 | +0.728 | −1.104 | +1.832 | [+0.561, +4.597] | YES(+) |
| | TRANSITIONAL | 5 | 4 | +0.599 | +0.173 | +0.425 | [−0.727, +1.503] | no |
| | CHOP | 3 | 7 | +0.461 | −0.589 | +1.050 | [+0.343, +1.966] | YES(+) |
| **W2 (N=48)** | ALL | 20 | 28 | +0.063 | −0.250 | **+0.313** | [−0.386, +0.701] | **no** |
| | TREND | 12 | 7 | −0.248 | −0.085 | −0.162 | [−1.060, +0.333] | no |
| | TRANSITIONAL | 4 | 9 | +0.791 | −0.209 | +1.000 | [−0.254, +2.216] | no |
| | CHOP | 4 | 12 | +0.268 | −0.376 | +0.644 | [−0.590, +3.251] | no |

**Does the sign hold on W2?** Yes for ALL (+0.31), TRANSITIONAL (+1.00), CHOP (+0.64) — all positive.
**No for TREND** (−0.16): on W2 the Oracle's `act` calls in trend slightly *under*-performed its
defers. But every W2 per-regime CI straddles zero — W2 alone is directional-only, not significant in
any cell. The headline: **W2's ALL delta is +0.31%, same sign as W1 but ~4× smaller, and its CI
includes zero.** W2 was also more cautious (20 act / 28 off vs W1's 16/14) — a higher defer rate that
compresses the SAFE arm.

### Pooled (W1 + W2, N=78)

`Δ = netEV(SAFE='act') − netEV(DEFER∪REJECT)`. Same paired moving-block bootstrap, applied to the
combined per-symbol-ordered pool.

| scope | nSAFE | nOFF | mSAFE% | mOFF% | **Δ%** | paired 95% CI | CI-clean |
|:--|--:|--:|--:|--:|--:|:--|:--:|
| **ALL** | 36 | 42 | +0.318 | −0.327 | **+0.645** | [+0.208, +1.021] | **YES(+)** |
| TREND | 20 | 10 | +0.142 | −0.391 | +0.533 | [−0.206, +1.448] | no |
| **TRANSITIONAL** | 9 | 13 | +0.684 | −0.091 | **+0.775** | [+0.090, +1.742] | **YES(+)** |
| CHOP | 7 | 19 | +0.351 | −0.455 | +0.805 | [−0.155, +1.941] | no |

**Pooled jackknife (drop-one, N=78):** Δ stays in **[+0.564, +0.753] — always positive**. The most
influential single drop (removing the BOME trend `defer`, pnl −3.66, which *helps* the delta) only
lowers it to +0.564. **The positive pooled sign is not carried by any one entry.**

**N_eff = 78, VIF = 1.00** — as in W1, the stratified sample draws scattered, non-adjacent entries, so
within-symbol autocorrelation is broken by construction and the block bootstrap reduces to ~IID. The
CI is honest (not artificially narrow), but see the overlap caveat below — N_eff overstates *windows*
even if it's right about *entries*.

## Is the +1.1% LOCKED?

**No — and this is the honest, load-bearing finding.** Decompose "locked" into its parts:

| claim | status |
|---|---|
| **Sign positive, replicated across both windows** | ✅ YES (W1 +1.12, W2 +0.31, both +) |
| **Sign jackknife-robust (pooled)** | ✅ YES ([+0.56, +0.75], always +) |
| **Pooled CI-clean positive** | ✅ YES (+0.645 [+0.208, +1.021]) |
| **Magnitude ≈ +1.1% stable across windows** | ❌ NO (W2 = +0.31, ~¼ of W1) |
| **W2 CI-clean on its own** | ❌ NO (ALL CI [−0.39, +0.70] straddles 0) |
| **TREND cell robust** | ❌ NO (W2 TREND went −0.16) |

So: **the selection-value claim is locked at the SIGN level; the +1.1% MAGNITUDE is not.** W1's +1.12%
now reads as the optimistic end of a range whose pooled center is ≈ +0.65%. The product wedge claim
("the adversarial Oracle adds selection value where the cheap local gate subtracts it") survives — the
local proxy was CI-clean *negative* (−1.5%/−1.9%); the Oracle is CI-clean *positive* pooled. But the
roadmap-grade number to quote is **+0.6%, sign-robust**, not "+1.1% confirmed."

## TRANSITIONAL — is the soft cell now CI-clean?

**Yes, pooled.** W1 had it at +0.425 [−0.727, +1.503] (straddled zero, N=9). W2 added +1.000
[−0.254, +2.216] (also straddled, N=13, but same sign and larger). **Pooled: +0.775 [+0.090, +1.742],
CI-clean POSITIVE, N=22.** The cell that was the explicit "watch this" soft spot is now positive and
clean once the sample is large enough. Caveat: it's clean by a thin margin (lower bound +0.09 — one or
two entries from straddling), so call it "firmed up, not bulletproof." More TREND N is now the weaker
cell (pooled TREND straddles, dragged by W2's −0.16).

## Caveats (load-bearing)

- **W1 and W2 overlap ~90% — they are NOT independent windows.** Measured directly: the two cached
  candle windows share **Jaccard 0.90 on raw bar timestamps** (W1 `cal_candles_d1.json`
  2026-05-18 23:25 → 05-22 04:35; W2 `cal_candles.json` 2026-05-18 21:55 → 05-22 01:20 — offset ~90
  min, same tape). They differ at the *candidate* level (different bar indices fire breakout/vol-spike,
  different enrichment edges, different stratified draws → only partial entry overlap), so W2 is a
  *near*-replication, not a true second window. **Pooled N=78 overstates the effective independent
  information** — it's closer to "78 reads of one quiet week" than "two independent weeks." A genuinely
  independent window (a different calendar week, ideally a non-chop regime) is the real replication
  still owed. This is why "sign-robust" is the honest claim and "magnitude locked" is not.
- **One quiet, chop-heavy week.** Both windows are the same 2026-05-18..22 tape. Per-regime cells
  remain small (pooled TREND nSAFE=20/nOFF=10; CHOP 7/19 — the SAFE arm in chop is tiny because the
  Oracle is appropriately reluctant to enter in chop). Treat per-regime as directional.
- **OpenRouter gateway, not OpenAI-direct.** The OpenAI production key was still out of quota; both
  windows ran via OpenRouter `openai/gpt-4o-mini` (byte-identical Oracle logic, only the HTTP gateway
  differs — the W1 run established this). **The OpenAI-direct cross-check remains the ONE outstanding
  verification** — same model, rules out any gateway artifact. Deferred until the founder restores
  quota; do not block on it. OpenRouter was heavily rate-limited this run (per-call latency stretched
  to ~70–110 s with backoffs; AG2's per-voice timeout kept every call bounded — 0 transport errors, 0
  degraded panels across all 48).
- **Verdict mix shifted between windows.** W1: 16 act / 14 defer. W2: 20 act / 26 defer / 2 pass — a
  meaningfully higher defer rate. The Oracle is not deterministic across near-identical tapes (temp
  0.3); some of the magnitude difference is the Oracle drawing a more cautious verdict distribution on
  W2, which shrinks the SAFE arm and the delta. This is itself a finding: the +1.1% was partly a
  favorable verdict-mix draw.
- **This is basic tier (gpt-4o-mini), grounding is corpus-thin at these historical times** (dated
  evidence is DEX-protocol, not memecoin-specific — same as W1). Pro tier and a richer per-symbol
  corpus are separate, deferred measurements.

## Spend (actual)

Per-call ≈ $0.004 (tiktoken estimate over returned turns + seed). Cap was ~$1.00.

| item | calls | cost |
|---|--:|--:|
| W2 smoke (path confirmation) | 3 | ~$0.012 |
| W2 first run (killed by stale-task reap before JSON flush — work lost) | ~46 | ~$0.19 |
| W2 successful run (N=48) | 48 | $0.199 |
| **total NEW spend** | ~97 | **≈ $0.40** |

Well under the $1.00 cap. (The killed first run is the one waste — the original invocation piped
stderr through `tail`, which buffered all output and made the JSON depend on a clean process exit; a
background-task reap then killed it before completion. Re-launched under `nohup` with a logfile, which
survived subsequent reaps. Lesson: long LLM sweeps go to a logfile, never a `tail` pipe, and under
`nohup`.)

## Bottom line for the founder

- **Quote "+0.6% pooled, sign-robust," not "+1.1% confirmed."** The wedge (Oracle-as-selector beats
  the local gate) replicates at the sign level and survives jackknife; the +1.1% was a single-window
  high draw. W2 says +0.31%; pooled center ≈ +0.65%.
- **The TRANSITIONAL soft cell is resolved positive** (pooled CI-clean +0.78%). The new weakest cell
  is TREND (W2 dragged it to straddle zero).
- **Two checks still owed before this is roadmap-load-bearing:** (1) a *genuinely independent* window
  (different calendar week — the two we have overlap 90%), and (2) the OpenAI-direct production path
  once quota is restored. Both are cheap (~$0.25 each). Until then this is "strongly suggestive,
  sign-confirmed," not "locked magnitude."
- Unchanged from W1: this validates the *selection layer*, not the *strategy* — the absolute levels
  are still inside the fee-dominated regime; the Oracle improves which entries you take, it does not
  manufacture a gross edge the breakout primitive lacks.

---

*Reproduce:*
```bash
set -a && source .env && set +a
# W2 (N=48, OpenRouter) — run under nohup + logfile, NOT a tail pipe:
nohup uv run python scripts/trading_oracle/oracle_gating_delta.py --full 48 --gateway openrouter \
  --window /tmp/cal_candles.json \
  --json-out tests/eval/live_runs/2026-05-22-oracle-gating-delta-w2.json > /tmp/w2_run.log 2>&1 &
# pool + jackknife:
uv run python scripts/trading_oracle/pool_gating_delta.py \
  tests/eval/live_runs/2026-05-22-oracle-gating-delta-w1.json \
  tests/eval/live_runs/2026-05-22-oracle-gating-delta-w2.json
```
(Use `--gateway openai` once the OpenAI direct key has quota — identical model, the production path,
the one remaining cross-check.)
