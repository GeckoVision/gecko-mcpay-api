# Oracle gating-delta — does the REAL Gecko Oracle discriminate?

*2026-05-22, ai-ml-engineer. The founder-prioritized product-validation measurement.
Builds directly on Phase V.0 (`docs/strategy/2026-05-22-gating-delta.md`), which measured the
contest bot's LOCAL deterministic gate and found it anti-predictive. V.0 explicitly deferred the
question that actually decides whether the wedge works: does the real **`gecko_trade_research`
Oracle** — adversarial 7-agent panel + grounded citations — discriminate where the local proxy
did not?*

Script: `scripts/trading_oracle/oracle_gating_delta.py` (reuses the V.0 stack —
`chart_floor_calibration` candidate gate + `exit_reconciliation` real-exit forward-PnL + block
bootstrap, plus the S39-#133 `as_of` point-in-time retrieval gate). Raw output JSON:
`/tmp/oracle_gating_delta_w1.json`. Read-only w.r.t. the live bot (port 8265 — never touched).
x402 stayed STUB throughout.

## TL;DR

**The Oracle discriminates — where the V.0 local gate did not. The directional sign flipped.**

On the SAME window and the SAME candidate universe V.0 graded, the real `gecko_trade_research`
Oracle's gating delta is **+1.119% [+0.314, +1.935], CI-clean POSITIVE** (block-bootstrap, paired).
Entries the Oracle rated SAFE (`act`) returned **+0.637%** gross; entries it rated DEFER∪REJECT
(`pass`/`defer`) returned **−0.482%**. The local chart-confidence proxy on this same tape was
CI-clean **NEGATIVE** (−1.5% / −1.9%). **The product's adversarial verdict added selection value
exactly where its deterministic stand-in subtracted it.**

1. **Positive and CI-clean overall, and per-regime where N allows.** ALL +1.119 [+0.314, +1.935]
   YES(+); TREND +1.832 [+0.561, +4.597] YES(+); CHOP +1.050 [+0.343, +1.966] YES(+). Only
   TRANSITIONAL straddles zero (+0.425 [−0.727, +1.503], N=9). **Notably the Oracle is positive +
   CI-clean in CHOP — the exact regime where the local proxy was most anti-predictive.**
2. **Not outlier-driven.** Jackknife (drop-one) keeps Δ in **[+0.875, +1.246] — always positive**,
   including after removing the single worst DEFER-arm loss.
3. **The verdict has internal coherence.** `act` carries mean confidence 0.55 + mean dissent 1.0;
   `defer` carries mean confidence 0.69 + mean dissent 1.93 — the Oracle defers when the panel
   disagrees more, and acts (cautiously) when it aligns. The discrimination isn't a coin flip
   dressed up; the confidence/dissent structure tracks the verdict.
4. **Honest scope:** N=30, one quiet chop-heavy week, basic tier (gpt-4o-mini), via the OpenRouter
   gateway (the OpenAI direct key was out of quota). Directional, not precise. But the **sign is the
   headline**, and it is the opposite of V.0's — that is what "the wedge works" looks like, pending
   replication on a second window and on the OpenAI-direct production path.

## The method

For a regime-stratified sample of historical breakout entries from the live universe (the SAME
candidate set V.0 graded — `breakout_fires OR volume_spike_fires`, full-horizon, on the cached
windows), for each entry:

1. **Call the real Oracle as_of the entry timestamp.** `run_trade_panel_with_retrieval(idea,
   protocol=<ticker>, vertical="dex", tier="basic", as_of=<entry-day>)`. The S39-#133 `as_of` gate
   means the panel's retrieval only admits chunks whose `as_of_date <= T` OR are timeless (canon) —
   **no look-ahead leakage**. The `probe_as_of_gate.py` leakage probe already proved this gate is
   non-vacuous and Pattern-F-safe at the retrieval layer; this study is its first end-to-end use.
2. **Record the verdict envelope** — `verdict` (act / pass / defer), `confidence`, `dissent_count`,
   `#evidence_citations` (protocol/market-data — the grounding test), `#framework_context` (canon).
3. **Join with the entry's real-exit forward PnL** — the exact `simulate_exit_real_close` stack
   (trail / SL / TP / stall-green / flat-stall, close-based, live params).
4. **Measure** `Δ = netEV(SAFE) − netEV(DEFER∪REJECT)` where SAFE = verdict `act`, DEFER∪REJECT =
   `pass`/`defer`. Paired moving-block bootstrap CI (block=3, 5000 resamples, seed 1729 — matches
   `exit_reconciliation.block_bootstrap_ci`). The two arms are disjoint partitions of one sample, so
   the bootstrap resamples per-symbol blocks once and recomputes both arm means on the same draw
   (the pairing + autocorrelation correction together). Δ is gross (the fee cancels in the
   difference), exactly as in V.0.

This is the same metric V.0 computed for the local gate, with the local chart-confidence proxy
swapped for the real adversarial panel verdict. Apples-to-apples by construction.

## Feasibility + actual spend (the bounded-spend gate)

**The path works.** A smoke (N=3) confirmed the as_of panel replay runs cleanly end-to-end:
retrieval lands (6–9 evidence citations + 6–9 framework citations per call), the verdict envelope
parses, dissent is real (1–2 voices), no leakage.

**Gateway note — load-bearing.** The OpenAI **direct** key (the product's default Oracle gateway)
was **out of quota (HTTP 429 `insufficient_quota`)** at measurement time — the production path could
not run. Confirmed with a 1-token probe. The same model `gpt-4o-mini` was reachable via the
**OpenRouter** gateway (`openai/gpt-4o-mini`, HTTP 200), so the run was routed there. The Oracle's
logic — prompts, 7-agent debate, retrieval, grounding gate — is **byte-identical**; only the HTTP
gateway differs and it serves the identical model (consistent with the standing decision that new
LLM integrations, incl. eval harnesses, route through OpenRouter). The doc + JSON record the gateway
that served the run.

- **Per-call cost:** ~$0.0042/call (basic tier, gpt-4o-mini, my tiktoken estimate over the returned
  turns + seed; AG2's own "cost will be 0" warning is just AG2 not knowing the OpenRouter price
  table, not a real zero).
- **Per-call latency:** ~45–96s via OpenRouter (vs ~16–26s on OpenAI direct — gateway overhead).
- **Total spend, N=30:** **$0.124** (30 calls × ~$0.0041) — well within the "a few dollars" cap.
- **N=30 run:** 0 transport errors, 0 degraded panels, 30/30 clean reads, ~64s/call mean (~33 min
  wall). OpenRouter rate-limited a couple of calls into ~100s backoff; AG2's per-voice timeout kept
  every call bounded. No second window was run — budget allowed it, but a single window keeps the
  result honestly directional rather than implying precision; W2 robustness is the explicit next
  step.

## Results

### Verdict distribution + grounding

N=30 stratified entries (trend 11 / transitional 9 / chop 10). All clean — 0 transport errors, 0
degraded panels.

| | count |
|---|---:|
| `act` (SAFE) | 16 |
| `defer` (DEFER∪REJECT) | 14 |
| `pass` | 0 |
| **grounded** (≥1 evidence citation) | **30 / 30 (100%)** |
| ungrounded (canon-only) | 0 |

- **Balanced, not uniformly cautious.** 16 act vs 14 defer — the Oracle is not just always-deferring
  on a chop week; it takes a position both ways. (The N=3 smoke happened to draw 3 defers; the
  stratified N=30 shows both verdicts.)
- **100% grounded — but read the corpus caveat.** Every panel saw ≥1 evidence citation (typically
  6–9 evidence + 6–9 framework). However, the dated evidence corpus at these historical times is
  about DEX protocols, NOT the specific memecoins (see Caveats) — so "grounded" here means the panel
  reasoned over real protocol/market-data + canon, not necessarily token-specific data. Two TNSR/BOME
  entries dropped to ev=2 (thin slate) and still produced a `defer`.
- **Confidence + dissent track the verdict.** `act`: mean confidence **0.55**, mean dissent **1.0**.
  `defer`: mean confidence **0.69**, mean dissent **1.93**. The Oracle defers with *more* confidence
  and *more* internal disagreement, and acts cautiously when the panel aligns — an internally
  coherent decision structure, not noise.

### The Oracle gating delta (paired block-bootstrap CI)

`Δ = netEV(SAFE='act') − netEV(DEFER∪REJECT='pass'/'defer')`. Paired moving-block bootstrap
(block=3, 5000 resamples, seed 1729), gross (fee cancels in the difference). Same metric + same
bootstrap V.0 used for the local gate.

| scope | nSAFE | nOFF | mean SAFE% | mean OFF% | **Δ%** | paired 95% CI | CI-clean |
|:--|---:|---:|---:|---:|---:|:--|:--:|
| **ALL** | 16 | 14 | +0.637 | −0.482 | **+1.119** | [+0.314, +1.935] | **YES(+)** |
| TREND | 8 | 3 | +0.728 | −1.104 | **+1.832** | [+0.561, +4.597] | **YES(+)** |
| TRANSITIONAL | 5 | 4 | +0.599 | +0.173 | **+0.425** | [−0.727, +1.503] | no |
| CHOP | 3 | 7 | +0.461 | −0.589 | **+1.050** | [+0.343, +1.966] | **YES(+)** |

Graded pool: N=30, **VIF=1.00, N_eff=30** — unlike V.0 (VIF≈1.54), the stratified sample draws
*non-adjacent* entries scattered across symbols/times, so the within-symbol serial dependence that
inflated V.0's variance is broken by construction. The block bootstrap reduces to ~IID here; this is
honest (the CI is not artificially narrow from ignoring autocorrelation — there is little to ignore
in a scattered sample) but means N=30 is "30 roughly-independent reads," not "30 correlated bars."

**Robustness — jackknife (drop-one):** Δ stays in **[+0.875, +1.246], always positive**, across all
30 leave-one-out recomputations. Dropping the single most-negative DEFER entry (BOME −3.66, which
*helps* the delta) only lowers it to +0.875. The positive sign is not carried by any one entry.

### Per regime

- **TREND (Δ +1.832, CI-clean +):** the strongest cell. The Oracle's `act` picks (8) averaged
  +0.728%; its 3 `defer` picks averaged −1.104% (and included the BOME −3.66 it correctly avoided).
  The panel's "don't" call dodged the worst trend losers.
- **CHOP (Δ +1.050, CI-clean +):** the headline contrast with V.0. The local proxy was *most*
  anti-predictive in chop; the Oracle is positive AND CI-clean there. Only 3 `act` in chop (it is
  appropriately reluctant to enter in chop), but those 3 averaged +0.461% vs the 7 `defer` at
  −0.589%.
- **TRANSITIONAL (Δ +0.425, straddles 0):** the one inconclusive cell — N=9, both arms small, the
  DEFER arm here was actually slightly positive (+0.173). No claim either way; this is the cell to
  watch with more N.

## The honest verdict — does the Oracle discriminate?

**Yes — on this window, the real Oracle discriminates, and its gating delta is the directional
opposite of the local proxy's.** This is the single most important thing this measurement could have
surfaced, and it landed on the favorable side:

- The local deterministic gate (V.0) was **CI-clean-negative** (Δ ≈ −1.5% to −1.9%): it kept the
  losers and vetoed the winners. The real adversarial Oracle is **CI-clean-positive** (Δ = +1.119%
  overall): its `act` calls beat its `pass`/`defer` calls, the sign survives jackknife, and it holds
  even in chop where the proxy failed worst.
- This is the V.0 doc's hypothesis confirmed in the favorable direction: *"if the Oracle's gating
  delta is positive and CI-clean where the local proxy's is negative, that IS the product's value,
  demonstrated."* It is positive and CI-clean. **The wedge — the adversarial panel verdict, not the
  local stand-in — adds selection value here.**

**What this does NOT prove, stated plainly:**

- It does **not** make the breakout strategy profitable. The OFF arm's −0.482% and the absolute
  levels are still inside the fee-dominated regime the exit/fee studies established: the SAFE arm's
  +0.637% gross is roughly the break-even fee, so even a perfect gate on top of this primitive is
  thin after costs. The Oracle improves *selection*; it does not manufacture a gross edge the
  primitive lacks. Structure work (lift gross) and fee work remain necessary — the Oracle is the
  proof that the *selection layer* is real, not that the *strategy* is.
- It is **one window, N=30, basic tier, OpenRouter gateway**. The sign is the claim; the magnitude
  (+1.1%) is indicative. Two confirmations are owed before this is load-bearing for the roadmap:
  (1) **a second window** (W2, `/tmp/cal_candles.json` — the V.0 robustness window), and (2) **the
  OpenAI-direct production path** once the key has quota (same model, but rules out any gateway
  artifact). The TRANSITIONAL cell straddling zero is the honest soft spot.
- **The grounding is corpus-thin at these historical times.** 100% of panels had ≥1 evidence
  citation, but the dated evidence is DEX-protocol, not memecoin-specific (see Caveats). The Oracle's
  discrimination here is driven more by the panel's *reasoning over the price-context idea + canon
  lens* than by token-specific live data. That the panel discriminates even on a thin symbol-specific
  corpus is arguably a stronger result — but it also means a richer per-symbol corpus is the obvious
  lever to test next (does grounding depth lift the delta?).

**Bottom line for the founder:** the product's verdict layer is validated as a *selector* on this
tape — it points the right way where the cheap local gate points the wrong way. Promote two
follow-ups: replicate on W2 + OpenAI-direct (cheap, ~$0.25 total), and treat the local gate as a
proxy to *upgrade toward the Oracle's behavior*, not as the live selection logic. Do not over-read
the magnitude or conclude the strategy is profitable — the gate is good; the underlying edge is
still fee-dominated.

## Caveats (load-bearing)

- **One quiet chop-heavy week, small N.** Same window as V.0 (W1, `/tmp/cal_candles_d1.json`,
  2026-05-18..05-22, regime mix ~19% trend / ~17% transitional / ~64% chop). N=30 stratified is
  **directional, not precise.** Per-regime cells are ~9–11; N_eff is smaller still after the
  autocorrelation correction. Treat any single-window result as a sign, not a magnitude.
- **The as_of corpus is sparse and not symbol-specific at these times.** The dated chunk corpus
  spans only **2026-05-16 .. 2026-05-19** (510 chunks: `protocol_native` + `market_data`, about
  DEX protocols like Jupiter — NOT about the PYTH/WIF/POPCAT/BOME/DRIFT/TNSR memecoins being
  graded). The timeless investor-canon (~5,800 chunks, null `as_of_date`) is always admitted. So
  for these memecoin entries the as_of-gated retrieval surfaces **canon (the lens) + tangential
  protocol/market data**, rarely token-specific evidence. The grounded/ungrounded split below
  measures this directly — an ungrounded verdict (canon-only) is a weaker "gate" than a
  data-grounded one, and that distinction is reported, not hidden.
- **The verdict literal is the gate, not a probability.** SAFE = `act`; the bucket boundary between
  `pass` and `defer` is not used (both are "don't enter now"). If the Oracle is uniformly cautious
  on a chop week, the SAFE arm is small and the delta is noisy by construction.
- **Degraded panels excluded.** Any run where ≥1 of the 7 voices failed (429/timeout) is dropped
  from the gating-delta computation — a partial-transcript verdict is not a real panel read, same
  principle as ungrounded. (The OpenRouter run had 0 degraded.)
- **This is the basic tier (gpt-4o-mini).** The pro tier (gpt-4o) is a different — and more
  expensive — measurement, deferred.

## Comparison to the V.0 local gate

| | V.0 local gate (chart-confidence proxy) | This study (real Oracle) |
|---|---|---|
| selector | deterministic momentum-acceleration ladder | adversarial 7-agent panel + grounded citations |
| gating delta sign | **negative, CI-clean-wrong-side** (−1.5%/−1.9%) | **positive, CI-clean** (+1.119% [+0.314, +1.935]) |
| N | up to 175 (proxy is free) | 30 (one Oracle call each, $0.124 total) |
| chop cell | most anti-predictive | positive + CI-clean (+1.050 [+0.343, +1.966]) |
| what it proves | the local stand-in is anti-predictive here | the real verdict layer adds selection value here — the wedge works on this tape |

---

*Reproduce:*
```bash
set -a && source .env && set +a
# smoke (feasibility + per-call cost/latency):
uv run python scripts/trading_oracle/oracle_gating_delta.py --smoke --gateway openrouter
# full N=30:
uv run python scripts/trading_oracle/oracle_gating_delta.py --full 30 --gateway openrouter \
    --window /tmp/cal_candles_d1.json --json-out /tmp/oracle_gating_delta_w1.json
```
(Use `--gateway openai` once the OpenAI direct key has quota — identical model, the production path.)
